"""
get_daily_basic - 每日基本面指标工具

提供技术分析所需的辅助数据:
  - 换手率 (turnover_rate)
  - 量比 (volume_ratio)
  - PE / PB (市盈率/市净率)
  - 总市值 / 流通市值

数据源: Tushare daily_basic 接口
"""

import time
import logging
from datetime import datetime, timedelta

from src.tools.tushare_utils import get_tushare_client, normalize_code, TushareError

logger = logging.getLogger(__name__)


def get_daily_basic(
    code: str,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """
    获取股票每日基本面指标

    Args:
        code: 股票代码（如 300033.SZ 或 300033）
        start_date: 开始日期（YYYYMMDD 或 YYYY-MM-DD），为空则自动计算
        end_date: 结束日期（YYYYMMDD 或 YYYY-MM-DD），为空则用今天

    Returns:
        {"ok": True, "data": [...], "count": N, "error": None}

    每条记录包含:
        turnover_rate  - 换手率（%）
        volume_ratio   - 量比
        pe_ttm         - 市盈率TTM
        pb             - 市净率
        total_mv       - 总市值（万元）
        circ_mv        - 流通市值（万元）
    """
    start_ms = time.time()

    try:
        ts_code = normalize_code(code)

        # 自动计算日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=1250)).strftime("%Y%m%d")

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        service = get_tushare_client()

        if hasattr(service, "get_daily_basic"):
            raw = service.get_daily_basic(ts_code, start, end)
        else:
            raw = []

        if hasattr(raw, "to_dict"):
            records = raw.to_dict("records")
        elif isinstance(raw, list):
            records = raw
        else:
            records = []

        # 按日期正序排列（确保截取的是最新数据）
        records.sort(key=lambda r: r.get("trade_date", ""))

        # 只保留关键字段，减少传给 LLM 的数据量
        trimmed = []
        for r in records:
            trimmed.append({
                "trade_date": r.get("trade_date"),
                "close": r.get("close"),
                "turnover_rate": r.get("turnover_rate"),
                "volume_ratio": r.get("volume_ratio"),
                "pe_ttm": r.get("pe_ttm"),
                "pb": r.get("pb"),
                "total_mv": r.get("total_mv"),
                "circ_mv": r.get("circ_mv"),
                # 估值补充字段
                "ps_ttm": r.get("ps_ttm"),
                "dv_ratio": r.get("dv_ratio"),
                "dv_ttm": r.get("dv_ttm"),
                "total_share": r.get("total_share"),
                "float_share": r.get("float_share"),
                "free_share": r.get("free_share"),
            })

        # 截取最近20条（技术分析只需要近期数据，节省 token）
        total_count = len(trimmed)
        output = trimmed[-20:] if total_count > 20 else trimmed

        # 提取最新一条有效数据（供 LLM 直接引用，避免从20行中找最新）
        latest_record = None
        for r in reversed(trimmed):
            if r.get("pe_ttm") is not None and r.get("total_mv") is not None:
                latest_record = r
                break

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[get_daily_basic] {ts_code} "
            f"{start}-{end}: {total_count} rows total, "
            f"{len(output)} rows output, {duration_ms}ms"
        )

        result = {
            "ok": True,
            "data": output,
            "count": len(output),
            "total_available": total_count,
            "duration_ms": duration_ms,
            "error": None,
        }
        if latest_record:
            result["latest"] = latest_record

        # 估值百分位（用全部数据计算，不只是20天）
        valuation = _calc_valuation_percentile(trimmed)
        if valuation:
            result["valuation"] = valuation

        # 评分建议（换手率 + 估值百分位）
        scoring_hints = {}

        if latest_record:
            tr = latest_record.get("turnover_rate")
            if tr is not None:
                if tr < 1:
                    scoring_hints["volume_turnover"] = {"score": 7, "reason": f"低换手{tr:.2f}%"}
                elif tr <= 3:
                    scoring_hints["volume_turnover"] = {"score": 10, "reason": f"温和换手{tr:.2f}%"}
                elif tr <= 5:
                    scoring_hints["volume_turnover"] = {"score": 5, "reason": f"活跃换手{tr:.2f}%"}
                elif tr <= 8:
                    scoring_hints["volume_turnover"] = {"score": 3, "reason": f"高换手{tr:.2f}%"}
                else:
                    scoring_hints["volume_turnover"] = {"score": 0, "reason": f"极高换手{tr:.2f}%"}

        # 估值百分位评分（P2修复: 之前缺失，LLM需自行计算20%的总分）
        if valuation:
            pe_pct = valuation.get("pe_percentile")
            pb_pct = valuation.get("pb_percentile")

            if pe_pct is not None:
                if pe_pct < 25:
                    scoring_hints["valuation_pe"] = {"score": 10, "reason": f"PE百分位{pe_pct:.1f}%,历史低位(低估)"}
                elif pe_pct < 50:
                    scoring_hints["valuation_pe"] = {"score": 7, "reason": f"PE百分位{pe_pct:.1f}%,合理偏低"}
                elif pe_pct < 75:
                    scoring_hints["valuation_pe"] = {"score": 5, "reason": f"PE百分位{pe_pct:.1f}%,合理偏高"}
                elif pe_pct < 90:
                    scoring_hints["valuation_pe"] = {"score": 3, "reason": f"PE百分位{pe_pct:.1f}%,偏贵"}
                else:
                    scoring_hints["valuation_pe"] = {"score": 0, "reason": f"PE百分位{pe_pct:.1f}%,历史高位(高估)"}

            if pb_pct is not None:
                # P0修复: 检测轻资产公司(PB>15), PB天然偏高,最低给5分
                pb_val = valuation.get("pb_latest", 0)
                is_light_asset = pb_val > 15

                if pb_pct < 25:
                    scoring_hints["valuation_pb"] = {"score": 10, "reason": f"PB百分位{pb_pct:.1f}%,历史低位"}
                elif pb_pct < 50:
                    scoring_hints["valuation_pb"] = {"score": 7, "reason": f"PB百分位{pb_pct:.1f}%,合理偏低"}
                elif pb_pct < 75:
                    scoring_hints["valuation_pb"] = {"score": 5, "reason": f"PB百分位{pb_pct:.1f}%,合理偏高"}
                elif pb_pct < 90:
                    if is_light_asset:
                        scoring_hints["valuation_pb"] = {"score": 5, "reason": f"PB百分位{pb_pct:.1f}%,但PB={pb_val:.1f}属轻资产公司(PB天然偏高),保底5分"}
                    else:
                        scoring_hints["valuation_pb"] = {"score": 3, "reason": f"PB百分位{pb_pct:.1f}%,偏贵"}
                else:
                    if is_light_asset:
                        scoring_hints["valuation_pb"] = {"score": 5, "reason": f"PB百分位{pb_pct:.1f}%,但PB={pb_val:.1f}属轻资产公司(净资产基数小致PB虚高),保底5分,估值以PE/PEG为准"}
                    else:
                        scoring_hints["valuation_pb"] = {"score": 0, "reason": f"PB百分位{pb_pct:.1f}%,历史高位"}

        if scoring_hints:
            result["scoring_hints"] = scoring_hints

        return result

    except TushareError as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_daily_basic] Tushare {e.kind}: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
            "error_type": e.kind,
            "data_degraded": True,
            "retry_exhausted": True,
        }
    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_daily_basic] Error: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
        }


def _calc_valuation_percentile(records: list[dict]) -> dict | None:
    """
    计算PE/PB的历史百分位。

    利用全部250天数据（不只是20天），
    判断当前估值处于历史什么水平。
    """
    if len(records) < 20:
        return None

    # 收集有效的PE/PB序列
    pe_values = [
        float(r["pe_ttm"])
        for r in records
        if r.get("pe_ttm") is not None and r["pe_ttm"] > 0
    ]
    pb_values = [
        float(r["pb"])
        for r in records
        if r.get("pb") is not None and r["pb"] > 0
    ]

    valuation = {}

    if pe_values:
        latest_pe = pe_values[-1]
        sorted_pe = sorted(pe_values)
        rank = sum(1 for v in sorted_pe if v <= latest_pe)
        pe_pct = round(rank / len(sorted_pe) * 100, 1)
        valuation["pe_latest"] = round(latest_pe, 2)
        valuation["pe_percentile"] = pe_pct
        valuation["pe_verdict"] = (
            "high" if pe_pct > 75
            else "low" if pe_pct < 25
            else "moderate"
        )

    if pb_values:
        latest_pb = pb_values[-1]
        sorted_pb = sorted(pb_values)
        rank = sum(1 for v in sorted_pb if v <= latest_pb)
        pb_pct = round(rank / len(sorted_pb) * 100, 1)
        valuation["pb_latest"] = round(latest_pb, 2)
        valuation["pb_percentile"] = pb_pct
        valuation["pb_verdict"] = (
            "high" if pb_pct > 75
            else "low" if pb_pct < 25
            else "moderate"
        )

    # 市值（万元 -> 亿元）
    latest_mv = None
    for r in reversed(records):
        if r.get("total_mv") is not None:
            latest_mv = round(float(r["total_mv"]) / 10000, 2)  # 万元 -> 亿元
            break
    if latest_mv:
        valuation["total_mv_yi"] = latest_mv

    latest_circ = None
    for r in reversed(records):
        if r.get("circ_mv") is not None:
            latest_circ = round(float(r["circ_mv"]) / 10000, 2)
            break
    if latest_circ:
        valuation["circ_mv_yi"] = latest_circ

    return valuation if valuation else None
