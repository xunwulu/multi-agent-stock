"""
get_kline - K线数据工具

提供多周期K线数据，默认250个交易日（约1年），
足够计算 MA120/MA250 等长周期均线。

支持的周期:
  - period="daily"    日K线（默认，250天）
  - period="weekly"   周K线（100周）
  - period="monthly"  月K线（60月）

数据源: Tushare daily/weekly/monthly 接口
"""

import time
import logging
from datetime import datetime, timedelta

from src.tools.tushare_utils import get_tushare_client, normalize_code

logger = logging.getLogger(__name__)


def get_kline(
    code: str,
    start_date: str = "",
    end_date: str = "",
    period: str = "daily",
    days: int = 250,
    max_output: int = 60,
) -> dict:
    """
    获取股票K线数据

    Args:
        code: 股票代码（如 300033.SZ 或 300033）
        start_date: 开始日期（YYYYMMDD 或 YYYY-MM-DD），为空则自动计算
        end_date: 结束日期（YYYYMMDD 或 YYYY-MM-DD），为空则用今天
        period: 周期 daily/weekly/monthly
        days: 自动计算时的回溯天数（默认250个自然日，约1年交易日）

    Returns:
        {"ok": True, "data": [...], "count": N, "error": None}
    """
    start_ms = time.time()

    try:
        # 标准化股票代码
        ts_code = normalize_code(code)

        # 自动计算日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        # 标准化日期格式
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        service = get_tushare_client()

        # 根据周期选择方法
        if period == "daily":
            raw = service.get_stock_daily(ts_code, start, end)
        elif period == "weekly":
            raw = service.get_stock_weekly(ts_code, start, end)
        elif period == "monthly":
            raw = service.get_stock_monthly(ts_code, start, end)
        else:
            return {
                "ok": False,
                "data": None,
                "count": 0,
                "error": f"Unsupported period: {period}",
            }

        # 统一输出格式
        if hasattr(raw, "to_dict"):
            # Pandas DataFrame
            records = raw.to_dict("records")
        elif isinstance(raw, list):
            records = raw
        else:
            records = []

        # 按日期正序排列
        records.sort(key=lambda r: r.get("trade_date", ""))

        # 空数据警告（可能是API权限或停牌）
        if not records:
            logger.warning(f"[get_kline] {ts_code} {period}: API returned 0 records")
            # Fallback: weekly/monthly API may return empty due to permissions or
            # data gaps. Fetch daily data and resample to the requested period so
            # the analyst still gets weekly/monthly candles.
            if period in ("weekly", "monthly"):
                records = _fetch_and_resample(service, ts_code, start, end, period)
                if records:
                    logger.info(
                        f"[get_kline] {ts_code} {period}: fallback resampled "
                        f"{len(records)} candles from daily data"
                    )

        # 前复权处理（日线和周线）
        if period in ("daily", "weekly") and records:
            records = _apply_adj_factor(service, ts_code, start, end, records)

        # 截取最近N条返回给LLM（避免上下文溢出）
        # max_output=0 表示返回全部数据（供 calc_technical 内部计算用）
        # 周线/月线默认截短，避免传递过多数据
        effective_max = max_output
        if effective_max > 0:
            if period == "weekly" and effective_max > 15:
                effective_max = 15
            elif period == "monthly" and effective_max > 12:
                effective_max = 12

        total_count = len(records)
        if effective_max > 0 and total_count > effective_max:
            output_records = records[-effective_max:]
        else:
            output_records = records

        # 用全部数据构建摘要（不让模型自己算）
        summary = _build_kline_summary(records, period)

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[get_kline] {ts_code} {period} "
            f"{start}-{end}: {total_count} rows total, "
            f"{len(output_records)} rows output, {duration_ms}ms"
        )

        return {
            "ok": True,
            "data": output_records,
            "count": len(output_records),
            "total_available": total_count,
            "summary": summary,
            "duration_ms": duration_ms,
            "error": None,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_kline] Error: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
        }


def _apply_adj_factor(
    service, ts_code: str, start: str, end: str, records: list[dict]
) -> list[dict]:
    """
    对K线数据做前复权处理

    前复权算法:
      前复权价 = 原始价 x (当日复权因子 / 最新复权因子)

    这样除权除息造成的价格跳空会被自动填补，
    确保涨跌幅计算和技术分析（均线、MACD等）准确。
    """
    try:
        # 获取复权因子
        if hasattr(service, "get_adj_factor"):
            adj_raw = service.get_adj_factor(ts_code, start, end)
        elif hasattr(service, "_call"):
            adj_raw = service._call("adj_factor", {
                "ts_code": ts_code,
                "start_date": start,
                "end_date": end,
            })
        else:
            logger.warning("[adj_factor] Service has no adj_factor method, skip")
            return records

        if hasattr(adj_raw, "to_dict"):
            adj_list = adj_raw.to_dict("records")
        elif isinstance(adj_raw, list):
            adj_list = adj_raw
        else:
            return records

        if not adj_list:
            return records

        # 建立 日期 -> 复权因子 的映射
        adj_map = {}
        for item in adj_list:
            date = item.get("trade_date", "")
            factor = float(item.get("adj_factor", 1))
            adj_map[date] = factor

        # 最新复权因子（用于前复权基准）
        latest_factor = max(adj_map.values()) if adj_map else 1.0

        # 如果所有因子相同（没有除权），直接返回
        if len(set(adj_map.values())) == 1:
            return records

        # 应用前复权
        adj_records = []
        for r in records:
            date = r.get("trade_date", "")
            factor = adj_map.get(date)
            if factor and latest_factor > 0:
                ratio = factor / latest_factor
                new_r = dict(r)
                # 调整 OHLC 价格
                for price_key in ["open", "high", "low", "close", "pre_close"]:
                    if price_key in new_r and new_r[price_key] is not None:
                        new_r[price_key] = round(float(new_r[price_key]) * ratio, 2)
                # change 也要调整
                if "change" in new_r and new_r["change"] is not None:
                    new_r["change"] = round(float(new_r["change"]) * ratio, 2)
                # pct_chg 不需要调整（百分比不受复权影响）
                adj_records.append(new_r)
            else:
                adj_records.append(r)

        logger.info(
            f"[adj_factor] Applied forward adjustment for {ts_code}: "
            f"latest_factor={latest_factor}, "
            f"ratio range={min(adj_map.values())/latest_factor:.4f} - 1.0"
        )

        return adj_records

    except Exception as e:
        logger.warning(f"[adj_factor] Failed to apply adjustment: {e}, using raw data")
        return records


def _build_kline_summary(records: list[dict], period: str) -> dict:
    """
    从全部K线数据中提取摘要统计，避免模型自行计算出错。

    包含: 最新价、近5/20日涨跌幅、区间高低点、均量等。
    """
    if not records:
        return {}

    latest = records[-1]
    latest_close = latest.get("close")
    latest_date = latest.get("trade_date", "")

    summary = {
        "latest_close": latest_close,
        "latest_date": latest_date,
    }

    # 涨跌幅计算
    closes = [r.get("close") for r in records if r.get("close") is not None]
    if len(closes) >= 2:
        # 近5日涨跌幅
        if len(closes) >= 5:
            chg_5 = round((closes[-1] / closes[-6] - 1) * 100, 2)
            summary["change_pct_5d"] = chg_5
        else:
            chg_all = round((closes[-1] / closes[0] - 1) * 100, 2)
            summary["change_pct_5d"] = chg_all

        # 近20日涨跌幅
        if len(closes) >= 20:
            chg_20 = round((closes[-1] / closes[-21] - 1) * 100, 2)
            summary["change_pct_20d"] = chg_20
        elif len(closes) >= 6:
            chg_all = round((closes[-1] / closes[0] - 1) * 100, 2)
            summary["change_pct_20d"] = chg_all

    # 区间最高/最低价
    highs = [r.get("high") for r in records if r.get("high") is not None]
    lows = [r.get("low") for r in records if r.get("low") is not None]
    if highs:
        summary["period_high"] = max(highs)
    if lows:
        summary["period_low"] = min(lows)

    # 均量
    vols = [r.get("vol") for r in records if r.get("vol") is not None]
    if vols:
        if len(vols) >= 5:
            summary["avg_volume_5d"] = round(sum(vols[-5:]) / 5, 0)
        if len(vols) >= 20:
            summary["avg_volume_20d"] = round(sum(vols[-20:]) / 20, 0)

    # 总涨跌幅（全区间）
    if len(closes) >= 2:
        summary["change_pct_total"] = round(
            (closes[-1] / closes[0] - 1) * 100, 2
        )

    return summary


def _fetch_and_resample(service, ts_code: str, start: str, end: str, target_period: str) -> list:
    """
    Fetch daily K-line and resample to weekly/monthly.

    Used as a fallback when the native weekly/monthly Tushare API returns
    0 records (e.g. permission limits or data gaps for SZ stocks).
    """
    try:
        raw_daily = service.get_stock_daily(ts_code, start, end)
        if hasattr(raw_daily, "to_dict"):
            daily_records = raw_daily.to_dict("records")
        elif isinstance(raw_daily, list):
            daily_records = raw_daily
        else:
            daily_records = []
        if not daily_records:
            return []
        return _resample_kline(daily_records, target_period)
    except Exception as e:
        logger.warning(f"[get_kline] daily fallback fetch failed: {e}")
        return []


def _resample_kline(daily_records: list, target_period: str) -> list:
    """
    Resample daily K-line records to weekly or monthly using pandas.

    Aggregation rules (standard OHLC resampling):
      open      -> first (week/month opening price)
      high      -> max  (highest in period)
      low       -> min  (lowest in period)
      close     -> last (week/month closing price)
      pre_close -> last
      vol       -> sum  (total volume in period)
      amount    -> sum  (total turnover in period)

    Args:
        daily_records: list of daily candle dicts (must have trade_date + OHLC)
        target_period: "weekly" or "monthly"

    Returns:
        list of resampled candle dicts, sorted ascending by date.
    """
    if not daily_records:
        return []
    if target_period not in ("weekly", "monthly"):
        return daily_records
    try:
        import pandas as pd

        df = pd.DataFrame(daily_records)
        if "trade_date" not in df.columns or "close" not in df.columns:
            logger.warning("[get_kline] resample: missing trade_date/close columns")
            return []

        df["trade_date"] = pd.to_datetime(
            df["trade_date"], format="%Y%m%d", errors="coerce"
        )
        df = df.dropna(subset=["trade_date"]).sort_values("trade_date")
        df = df.set_index("trade_date")

        # Carry each row's trading day to label buckets by LAST trade day
        # (matches Tushare convention; keeps trade_date a real trading day so
        # forward-adjustment via adj_map works correctly).
        df["_last_trade_day"] = df.index

        # Grouping anchor only affects bucket boundaries; final label uses
        # _last_trade_day. W-FRI groups a Mon-Fri trading week.
        # 'M' deprecated in pandas 2.1 in favor of 'ME' (Month End).
        if target_period == "weekly":
            rule = "W-FRI"
        else:
            try:
                _v = tuple(int(x) for x in pd.__version__.split(".")[:2])
                rule = "ME" if _v >= (2, 1) else "M"
            except Exception:
                rule = "M"
        agg_rules = {}
        for col, how in (
            ("open", "first"),
            ("high", "max"),
            ("low", "min"),
            ("close", "last"),
            ("pre_close", "last"),
            ("vol", "sum"),
            ("amount", "sum"),
            ("ts_code", "last"),
            ("_last_trade_day", "last"),
        ):
            if col in df.columns:
                agg_rules[col] = how
        if "close" not in agg_rules:
            return []

        result = df.resample(rule).agg(agg_rules)
        result = result.dropna(subset=["close"]).reset_index(drop=True)

        # Label each candle by its last trading day (Tushare convention).
        if "_last_trade_day" in result.columns:
            result["trade_date"] = result["_last_trade_day"]
            result = result.drop(columns=["_last_trade_day"])

        # Recompute change/pct_chg close-to-close across candles (matches Tushare's
        # weekly/monthly convention). First candle has no prior -> None.
        if "close" in result.columns and len(result) >= 2:
            prev_close = result["close"].shift(1)
            result["change"] = (result["close"] - prev_close).round(2)
            result["pct_chg"] = ((result["close"] / prev_close - 1) * 100).round(2)
            result.loc[result.index[0], "change"] = None
            result.loc[result.index[0], "pct_chg"] = None

        records = result.to_dict("records")
        # Format trade_date back to YYYYMMDD string; convert NaN -> None.
        for r in records:
            td = r.get("trade_date")
            if hasattr(td, "strftime"):
                r["trade_date"] = td.strftime("%Y%m%d")
            for k in ("change", "pct_chg"):
                if k in r and r[k] != r[k]:  # NaN is not equal to itself
                    r[k] = None
        return records
    except ImportError:
        logger.warning("[get_kline] pandas not available for resampling")
        return []
    except Exception as e:
        logger.warning(f"[get_kline] resample error: {e}")
        return []
