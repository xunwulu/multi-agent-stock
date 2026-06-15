"""
get_index - 指数数据工具

获取大盘指数数据，用于个股与大盘的相对强弱对比。

支持的指数:
  - 000001.SH  上证指数
  - 399001.SZ  深证成指
  - 399006.SZ  创业板指
  - 000300.SH  沪深300
  - 000905.SH  中证500

数据源: Tushare index_daily 接口
"""

import time
import logging
from datetime import datetime, timedelta

from src.tools.tushare_utils import get_tushare_client, normalize_code

logger = logging.getLogger(__name__)

# 常用指数代码
COMMON_INDICES = {
    "sh": "000001.SH",       # 上证指数
    "sz": "399001.SZ",       # 深证成指
    "cyb": "399006.SZ",      # 创业板指
    "hs300": "000300.SH",    # 沪深300
    "zz500": "000905.SH",    # 中证500
}

# 申万行业分类 -> 行业指数代码映射
SW_INDUSTRY_MAP = {
    "农林牧渔": "801010.SI",
    "采掘": "801020.SI",
    "化工": "801030.SI",
    "钢铁": "801040.SI",
    "有色金属": "801050.SI",
    "电子": "801080.SI",
    "家用电器": "801110.SI",
    "食品饮料": "801120.SI",
    "纺织服装": "801130.SI",
    "轻工制造": "801140.SI",
    "医药生物": "801150.SI",
    "公用事业": "801160.SI",
    "交通运输": "801170.SI",
    "房地产": "801180.SI",
    "商业贸易": "801200.SI",
    "休闲服务": "801210.SI",
    "综合": "801230.SI",
    "建筑材料": "801710.SI",
    "建筑装饰": "801720.SI",
    "电气设备": "801730.SI",
    "国防军工": "801740.SI",
    "计算机": "801750.SI",
    "传媒": "801760.SI",
    "通信": "801770.SI",
    "银行": "801780.SI",
    "非银金融": "801790.SI",
    "汽车": "801880.SI",
    "机械设备": "801890.SI",
    # Tushare 行业分类 -> 申万行业指数（Tushare分类名称与申万不完全一致）
    "软件服务": "801750.SI",
    "互联网": "801760.SI",
    "半导体": "801080.SI",
    "元器件": "801080.SI",
    "IT设备": "801750.SI",
    "通信设备": "801770.SI",
    "证券": "801790.SI",
    "保险": "801790.SI",
    "多元金融": "801790.SI",
    "煤炭": "801020.SI",
    "石油": "801020.SI",
    "矿物制品": "801050.SI",
    "日用化工": "801140.SI",
    "造纸": "801140.SI",
    "酒店餐饮": "801210.SI",
    "旅游": "801210.SI",
    "航空": "801170.SI",
    "电力": "801160.SI",
    "水务": "801160.SI",
    "供气供热": "801160.SI",
    "环境保护": "801160.SI",
}



def _resolve_index_code(index_code: str) -> str:
    """
    解析指数代码，支持简称和完整代码

    "sh"     -> "000001.SH"
    "hs300"  -> "000300.SH"
    "000001.SH" -> "000001.SH"
    """
    if index_code in COMMON_INDICES:
        return COMMON_INDICES[index_code]
    # 已经是完整代码
    if "." in index_code:
        return index_code
    # 纯数字，默认加 .SH
    return f"{index_code}.SH"



def _get_stock_industry(ts_code: str) -> dict:
    """
    查询股票所属行业及对应的行业指数代码

    Returns:
        {"industry": "计算机", "industry_index": "801750.SI", "stock_name": "同花顺"}
        或 {"industry": None, "industry_index": None} (查询失败时)
    """
    try:
        service = get_tushare_client()
        if hasattr(service, "get_stock_basic"):
            raw = service.get_stock_basic(ts_code)
        else:
            raw = []

        if isinstance(raw, list) and raw:
            info = raw[0]
            industry = info.get("industry", "")
            name = info.get("name", "")
            index_code = SW_INDUSTRY_MAP.get(industry)
            return {
                "industry": industry,
                "industry_index": index_code,
                "stock_name": name,
            }
    except Exception as e:
        logger.warning(f"[get_stock_industry] Failed: {e}")

    return {"industry": None, "industry_index": None, "stock_name": None}


def get_index(
    index_code: str = "sh",
    start_date: str = "",
    end_date: str = "",
    stock_code: str = "",
) -> dict:
    """
    获取指数日线数据，支持行业指数对比

    Args:
        index_code: 指数代码或简称
            "sh"    - 上证指数（默认）
            "sz"    - 深证成指
            "cyb"   - 创业板指
            "hs300" - 沪深300
            "zz500" - 中证500
            也可传入完整代码如 "000001.SH"
        start_date: 开始日期（YYYYMMDD 或 YYYY-MM-DD）
        end_date: 结束日期（YYYYMMDD 或 YYYY-MM-DD）
        stock_code: 股票代码（如 300033.SZ）。传入后自动查询所属行业指数

    Returns:
        {"ok": True, "data": [...], "count": N, "error": None}

    每条记录包含: trade_date, open, high, low, close, vol, amount, pct_chg
    """
    start_ms = time.time()

    try:
        ts_code = _resolve_index_code(index_code)

        # 自动计算日期范围（默认250天，和 get_kline 对齐）
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=250)).strftime("%Y%m%d")

        start = start_date.replace("-", "") if start_date else ""
        end = end_date.replace("-", "") if end_date else ""

        service = get_tushare_client()

        # 行业指数查询（传入 stock_code 时自动识别行业）
        industry_info = None
        if stock_code:
            stock_ts = normalize_code(stock_code)
            industry_info = _get_stock_industry(stock_ts)
            if industry_info.get("industry_index"):
                logger.info(
                    f"[get_index] Stock {stock_ts} -> "
                    f"industry: {industry_info['industry']}, "
                    f"index: {industry_info['industry_index']}"
                )

        if hasattr(service, "get_index_daily"):
            raw = service.get_index_daily(ts_code, start, end)
        else:
            raw = []

        if hasattr(raw, "to_dict"):
            records = raw.to_dict("records")
        elif isinstance(raw, list):
            records = raw
        else:
            records = []

        # 按日期正序
        records.sort(key=lambda r: r.get("trade_date", ""))

        # 只保留关键字段
        trimmed = []
        for r in records:
            trimmed.append({
                "trade_date": r.get("trade_date"),
                "close": r.get("close"),
                "pct_chg": r.get("pct_chg"),
                "vol": r.get("vol"),
            })

        # 截取最近60条（避免上下文溢出）
        total_count = len(trimmed)
        output = trimmed[-60:] if total_count > 60 else trimmed

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[get_index] {ts_code} "
            f"{start}-{end}: {total_count} rows total, "
            f"{len(output)} rows output, {duration_ms}ms"
        )

        # 附带简单统计（基于全部数据）
        stats = _calc_stats(trimmed)

        result = {
            "ok": True,
            "data": output,
            "count": len(output),
            "total_available": total_count,
            "stats": stats,
            "index_name": _get_index_name(ts_code),
            "duration_ms": duration_ms,
            "error": None,
        }

        # 相对强弱预计算（传入 stock_code 时自动计算）
        if stock_code:
            rs = _calc_relative_strength(trimmed, stock_code)
            if rs:
                result["relative_strength"] = rs

                # vs大盘评分建议
                op_20 = rs.get("outperform_20d", 0)
                if op_20 > 5:
                    hint_score = 10
                elif op_20 > 0:
                    hint_score = 7
                elif op_20 > -5:
                    hint_score = 3
                else:
                    hint_score = 0
                result["scoring_hints"] = {
                    "relative_vs_index": {
                        "score": hint_score,
                        "reason": f"近20日超额{op_20:+.1f}%",
                    }
                }

        # 如果查到行业指数，额外返回行业信息+行业指数统计
        if industry_info and industry_info.get("industry_index"):
            ind_result = {
                "stock_name": industry_info["stock_name"],
                "industry": industry_info["industry"],
                "industry_index_code": industry_info["industry_index"],
                "industry_index_name": _get_index_name(
                    industry_info["industry_index"]
                ),
            }
            # 自动获取行业指数的统计数据（用 sw_daily 接口）
            try:
                ind_ts_code = industry_info["industry_index"]
                if hasattr(service, "get_sw_daily"):
                    ind_raw = service.get_sw_daily(ind_ts_code, start, end)
                elif hasattr(service, "get_index_daily"):
                    ind_raw = service.get_index_daily(ind_ts_code, start, end)
                else:
                    ind_raw = []
                if isinstance(ind_raw, list) and ind_raw:
                    ind_raw.sort(key=lambda r: r.get("trade_date", ""))
                    ind_closes = [
                        float(r["close"])
                        for r in ind_raw
                        if r.get("close")
                    ]
                    if len(ind_closes) >= 2:
                        ind_first = ind_closes[0]
                        ind_last = ind_closes[-1]
                        ind_result["industry_stats"] = {
                            "period_change_pct": round(
                                (ind_last - ind_first) / ind_first * 100, 2
                            ),
                            "latest_close": ind_last,
                            "period_high": max(ind_closes),
                            "period_low": min(ind_closes),
                        }
                        logger.info(
                            f"[get_index] Industry {ind_ts_code}: "
                            f"change={ind_result['industry_stats']['period_change_pct']}%"
                        )
            except Exception as e:
                logger.warning(f"[get_index] Failed to get industry stats: {e}")

            result["industry_info"] = ind_result

        return result

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_index] Error: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
        }


def _get_index_name(ts_code: str) -> str:
    """指数代码 -> 名称"""
    names = {
        "000001.SH": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000300.SH": "沪深300",
        "000905.SH": "中证500",
        # 申万行业指数
        "801010.SI": "SW农林牧渔",
        "801020.SI": "SW采掘",
        "801030.SI": "SW化工",
        "801040.SI": "SW钢铁",
        "801050.SI": "SW有色金属",
        "801080.SI": "SW电子",
        "801110.SI": "SW家用电器",
        "801120.SI": "SW食品饮料",
        "801130.SI": "SW纺织服装",
        "801140.SI": "SW轻工制造",
        "801150.SI": "SW医药生物",
        "801160.SI": "SW公用事业",
        "801170.SI": "SW交通运输",
        "801180.SI": "SW房地产",
        "801200.SI": "SW商业贸易",
        "801210.SI": "SW休闲服务",
        "801230.SI": "SW综合",
        "801710.SI": "SW建筑材料",
        "801720.SI": "SW建筑装饰",
        "801730.SI": "SW电气设备",
        "801740.SI": "SW国防军工",
        "801750.SI": "SW计算机",
        "801760.SI": "SW传媒",
        "801770.SI": "SW通信",
        "801780.SI": "SW银行",
        "801790.SI": "SW非银金融",
        "801880.SI": "SW汽车",
        "801890.SI": "SW机械设备",
    }
    return names.get(ts_code, ts_code)


def _calc_stats(records: list[dict]) -> dict:
    """计算指数简单统计"""
    if not records:
        return {}

    closes = [float(r["close"]) for r in records if r.get("close")]
    if not closes:
        return {}

    first = closes[0]
    last = closes[-1]
    highest = max(closes)
    lowest = min(closes)

    return {
        "period_change_pct": round((last - first) / first * 100, 2),
        "period_high": highest,
        "period_low": lowest,
        "period_amplitude_pct": round(
            (highest - lowest) / lowest * 100, 2
        ),
    }


def _calc_relative_strength(index_records: list[dict], stock_code: str) -> dict | None:
    """
    计算个股 vs 指数的相对强弱。

    从 get_kline 获取个股数据，与指数涨跌幅对比，
    直接输出"跑赢/跑输多少百分点"，避免模型自己算。
    """
    try:
        from src.tools.get_kline import get_kline

        stock_ts = normalize_code(stock_code)
        stock_result = get_kline(code=stock_ts, max_output=0)

        if not stock_result.get("ok") or not stock_result.get("data"):
            return None

        stock_data = stock_result["data"]
        stock_closes = [
            r["close"] for r in stock_data
            if r.get("close") is not None
        ]
        if len(stock_closes) < 2:
            return None

        # 指数涨跌幅（按交易日窗口）
        index_closes = [
            float(r["close"]) for r in index_records
            if r.get("close")
        ]

        rs = {}

        # 定义对比周期: (名称, 回溯天数)
        periods = [
            ("5d", 5),
            ("20d", 20),
            ("60d", 60),
        ]

        for name, days in periods:
            # 个股涨跌
            if len(stock_closes) > days:
                s_first = stock_closes[-(days + 1)]
                s_last = stock_closes[-1]
                s_chg = round((s_last / s_first - 1) * 100, 2)
            else:
                s_chg = round(
                    (stock_closes[-1] / stock_closes[0] - 1) * 100, 2
                )

            # 指数涨跌（用同期数据）
            if len(index_closes) > days:
                i_first = index_closes[-(days + 1)]
                i_last = index_closes[-1]
                i_chg = round((i_last / i_first - 1) * 100, 2)
            else:
                i_chg = round(
                    (index_closes[-1] / index_closes[0] - 1) * 100, 2
                )

            diff = round(s_chg - i_chg, 2)
            rs[f"stock_{name}_change"] = s_chg
            rs[f"index_{name}_change"] = i_chg
            rs[f"outperform_{name}"] = diff

        # 总判断
        op_20 = rs.get("outperform_20d", 0)
        if op_20 > 5:
            rs["verdict"] = "outperform"
        elif op_20 < -5:
            rs["verdict"] = "underperform"
        else:
            rs["verdict"] = "inline"

        return rs

    except Exception as e:
        logger.warning(f"[get_index] Relative strength calc failed: {e}")
        return None
