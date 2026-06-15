"""
get_institutional - 机构持仓与股东结构工具

提供基本面分析所需的股东数据:
  - 前十大股东 (top10_holders): 持股名称、数量、比例
  - 前十大流通股东 (top10_floatholders): 同上
  - 股东户数变化 (stk_holdernumber): 筹码集中/分散趋势
  - 高管增减持 (stk_holdertrade): 管理层买卖动向
  - 股权质押 (share_pledge): 质押比例与风险

数据源: Tushare top10_holders / top10_floatholders / stk_holdernumber / stk_holdertrade / share_pledge
"""

import time
import logging
from datetime import datetime, timedelta

from src.tools.tushare_utils import get_tushare_client, normalize_code

logger = logging.getLogger(__name__)

# 机构关键词（用于识别机构持仓者）
_INSTITUTIONAL_KEYWORDS = [
    "基金", "社保", "信托", "保险", "证券", "银行",
    "资管", "投资", "QFII", "香港", "陆股通",
    "中央汇金", "中国证金",
]

# 每类数据保留的关键字段
HOLDER_FIELDS = [
    "ann_date", "end_date", "holder_name", "hold_amount", "hold_ratio",
]

HOLDER_NUM_FIELDS = [
    "ann_date", "holder_num",
]


def get_institutional(
    code: str,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """
    获取股东结构和机构持仓数据

    Args:
        code: 股票代码（如 300033.SZ 或 300033）
        start_date: 开始日期（YYYYMMDD），为空则自动计算（1年前）
        end_date: 结束日期（YYYYMMDD），为空则用今天

    Returns:
        {"ok": True, "data": {...}, "summary": {...}, "scoring_hints": {...}, "error": None}
    """
    start_ms = time.time()

    try:
        ts_code = normalize_code(code)

        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        service = get_tushare_client()

        all_data = {}

        # 1. 前十大股东
        try:
            raw_holders = service._call("top10_holders", {
                "ts_code": ts_code,
                "start_date": start,
                "end_date": end,
            })
            raw_holders.sort(key=lambda r: r.get("end_date", ""), reverse=True)
            # A2 fix: use sorted unique instead of set() to preserve ordering
            latest_periods = sorted(
                set(r.get("end_date", "") for r in raw_holders),
                reverse=True
            )[:2]
            holders = [
                {f: r.get(f) for f in HOLDER_FIELDS}
                for r in raw_holders
                if r.get("end_date") in latest_periods
            ]
            all_data["top10_holders"] = holders
        except Exception as e:
            logger.warning(f"[get_institutional] top10_holders failed: {e}")
            all_data["top10_holders"] = []

        # 2. 前十大流通股东
        try:
            raw_float = service._call("top10_floatholders", {
                "ts_code": ts_code,
                "start_date": start,
                "end_date": end,
            })
            raw_float.sort(key=lambda r: r.get("end_date", ""), reverse=True)
            latest_periods_f = list(set(
                r.get("end_date", "") for r in raw_float
            ))[:2]
            float_holders = [
                {f: r.get(f) for f in HOLDER_FIELDS}
                for r in raw_float
                if r.get("end_date") in latest_periods_f
            ]
            all_data["top10_floatholders"] = float_holders
        except Exception as e:
            logger.warning(f"[get_institutional] top10_floatholders failed: {e}")
            all_data["top10_floatholders"] = []

        # 3. 股东户数
        try:
            raw_num = service._call("stk_holdernumber", {
                "ts_code": ts_code,
                "start_date": start,
                "end_date": end,
            })
            raw_num.sort(key=lambda r: r.get("ann_date", ""), reverse=True)
            holder_nums = [
                {f: r.get(f) for f in HOLDER_NUM_FIELDS}
                for r in raw_num[:6]  # 最近 6 期
            ]
            all_data["holder_count"] = holder_nums
        except Exception as e:
            logger.warning(f"[get_institutional] stk_holdernumber failed: {e}")
            all_data["holder_count"] = []

        # 4. 高管增减持（P3: 管理层分析）
        try:
            raw_trade = service._call("stk_holdertrade", {
                "ts_code": ts_code,
                "start_date": start,
                "end_date": end,
            })
            if raw_trade:
                raw_trade.sort(key=lambda r: r.get("ann_date", ""), reverse=True)
                insider_trades = [
                    {
                        "ann_date": r.get("ann_date"),
                        "holder_name": r.get("holder_name"),
                        "holder_type": r.get("holder_type"),  # G=高管 C=公司
                        "in_de": r.get("in_de"),  # IN=增持 DE=减持
                        "change_vol": r.get("change_vol"),
                        "change_ratio": r.get("change_ratio"),
                        "after_share": r.get("after_share"),
                        "after_ratio": r.get("after_ratio"),
                    }
                    for r in raw_trade[:20]
                ]
                all_data["insider_trades"] = insider_trades
            else:
                all_data["insider_trades"] = []
        except Exception as e:
            logger.warning(f"[get_institutional] stk_holdertrade failed: {e}")
            all_data["insider_trades"] = []

        # 5. 股权质押（P3: 管理层分析）
        try:
            raw_pledge = service._call("pledge_stat", {
                "ts_code": ts_code,
            })
            if raw_pledge:
                raw_pledge.sort(key=lambda r: r.get("end_date", ""), reverse=True)
                # 取最近一条（包含最新质押比例）
                latest = raw_pledge[0]
                all_data["pledge_stat"] = {
                    "end_date": latest.get("end_date"),
                    "pledge_count": latest.get("pledge_count"),
                    "unrest_pledge": latest.get("unrest_pledge"),
                    "rest_pledge": latest.get("rest_pledge"),
                    "total_share": latest.get("total_share"),
                    "pledge_ratio": latest.get("pledge_ratio"),
                }
            else:
                all_data["pledge_stat"] = None
        except Exception as e:
            logger.warning(f"[get_institutional] pledge_stat failed: {e}")
            all_data["pledge_stat"] = None

        # 计算统计摘要
        summary = _build_summary(all_data)

        duration_ms = int((time.time() - start_ms) * 1000)
        total_records = sum(len(v) for v in all_data.values())

        logger.info(
            f"[get_institutional] {ts_code} {start}-{end}: "
            f"{total_records} records, {duration_ms}ms"
        )

        result = {
            "ok": True,
            "data": all_data,
            "count": {k: len(v) for k, v in all_data.items()},
            "summary": summary,
            "duration_ms": duration_ms,
            "error": None,
        }

        # 评分建议
        hints = _calc_scoring_hints(summary)
        if hints:
            result["scoring_hints"] = hints

        return result

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_institutional] Error: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
        }


def _is_institutional(holder_name: str) -> bool:
    """判断是否为机构持仓者"""
    if not holder_name:
        return False
    return any(kw in holder_name for kw in _INSTITUTIONAL_KEYWORDS)


def _build_summary(data: dict) -> dict:
    """从股东数据中提取关键指标摘要"""
    summary = {}

    # 从前十大股东中分析
    holders = data.get("top10_holders", [])
    if holders:
        # 最新一期
        latest_date = holders[0].get("end_date") if holders else None
        summary["latest_report_date"] = latest_date
        summary["latest_ann_date"] = holders[0].get("ann_date") if holders else None

        latest_holders = [h for h in holders if h.get("end_date") == latest_date]
        prev_date = None
        prev_holders = []
        all_dates = sorted(set(h.get("end_date", "") for h in holders), reverse=True)
        if len(all_dates) >= 2:
            prev_date = all_dates[1]
            prev_holders = [h for h in holders if h.get("end_date") == prev_date]

        # 前10大合计持股比例
        total_ratio = sum(
            _safe_float(h.get("hold_ratio", 0)) or 0
            for h in latest_holders
        )
        summary["top10_concentration"] = round(total_ratio, 2)

        # 第一大股东
        if latest_holders:
            top1 = latest_holders[0]
            summary["top1_holder"] = top1.get("holder_name", "")
            summary["top1_ratio"] = _safe_float(top1.get("hold_ratio"))

        # 机构持仓统计
        inst_holders = [
            h for h in latest_holders if _is_institutional(h.get("holder_name", ""))
        ]
        summary["institutional_count"] = len(inst_holders)
        inst_ratio = sum(
            _safe_float(h.get("hold_ratio", 0)) or 0
            for h in inst_holders
        )
        summary["institutional_ratio"] = round(inst_ratio, 2)

    # 从股东户数中分析筹码集中度
    holder_nums = data.get("holder_count", [])
    if len(holder_nums) >= 2:
        latest_num = _safe_float(holder_nums[0].get("holder_num"))
        prev_num = _safe_float(holder_nums[1].get("holder_num"))
        if latest_num and prev_num and prev_num != 0:
            change_pct = round((latest_num - prev_num) / prev_num * 100, 2)
            summary["holder_num_latest"] = latest_num
            summary["holder_num_prev"] = prev_num
            summary["holder_num_change_pct"] = change_pct
            if change_pct < -8:
                summary["holder_trend"] = "concentrating"
            elif change_pct > 8:
                summary["holder_trend"] = "dispersing"
            else:
                summary["holder_trend"] = "stable"

    # P3: 管理层分析 - 高管增减持
    insider_trades = data.get("insider_trades", [])
    if insider_trades:
        buy_count = sum(1 for t in insider_trades if t.get("in_de") == "IN")
        sell_count = sum(1 for t in insider_trades if t.get("in_de") == "DE")
        summary["insider_buy_count"] = buy_count
        summary["insider_sell_count"] = sell_count
        if buy_count > 0 and sell_count == 0:
            summary["insider_signal"] = "net_buy"
            summary["insider_note"] = f"近1年高管净买入{buy_count}次，无减持"
        elif sell_count > 0 and buy_count == 0:
            summary["insider_signal"] = "net_sell"
            summary["insider_note"] = f"近1年高管净减持{sell_count}次"
        elif buy_count > sell_count:
            summary["insider_signal"] = "leaning_buy"
            summary["insider_note"] = f"近1年高管买入{buy_count}次 > 减持{sell_count}次"
        elif sell_count > buy_count:
            summary["insider_signal"] = "leaning_sell"
            summary["insider_note"] = f"近1年高管减持{sell_count}次 > 买入{buy_count}次"
        else:
            summary["insider_signal"] = "neutral"
            summary["insider_note"] = "近1年无高管增减持记录"

    # P3: 管理层分析 - 股权质押
    pledge_stat = data.get("pledge_stat")
    if pledge_stat:
        pledge_ratio = _safe_float(pledge_stat.get("pledge_ratio"))
        if pledge_ratio is not None:
            summary["pledge_ratio"] = pledge_ratio
            if pledge_ratio > 50:
                summary["pledge_risk"] = "high"
                summary["pledge_note"] = f"质押比例{pledge_ratio:.1f}%，风险较高"
            elif pledge_ratio > 30:
                summary["pledge_risk"] = "medium"
                summary["pledge_note"] = f"质押比例{pledge_ratio:.1f}%，需关注"
            elif pledge_ratio > 0:
                summary["pledge_risk"] = "low"
                summary["pledge_note"] = f"质押比例{pledge_ratio:.1f}%，风险可控"
            else:
                summary["pledge_risk"] = "none"
                summary["pledge_note"] = "无股权质押"

    return summary


def _calc_scoring_hints(summary: dict) -> dict | None:
    """预计算股东结构相关的评分建议"""
    has_data = summary.get("holder_num_change_pct") is not None
    if not has_data and summary.get("institutional_count") is None:
        return None

    hints = {}

    # 1. 筹码集中度（户数变化）
    # 评分: 减>15%:10, 减8-15%:7, 减0-8%:5, 增0-8%:3, 增>8%:0
    change = summary.get("holder_num_change_pct", 0)
    if change < -15:
        hints["holder_concentration"] = {
            "score": 10, "reason": f"股东户数环比{change:+.1f}%,筹码快速集中",
        }
    elif change < -8:
        hints["holder_concentration"] = {
            "score": 7, "reason": f"股东户数环比{change:+.1f}%,筹码集中",
        }
    elif change < 0:
        hints["holder_concentration"] = {
            "score": 5, "reason": f"股东户数环比{change:+.1f}%,筹码微集中",
        }
    elif change <= 8:
        hints["holder_concentration"] = {
            "score": 3, "reason": f"股东户数环比{change:+.1f}%,筹码微散",
        }
    else:
        hints["holder_concentration"] = {
            "score": 0, "reason": f"股东户数环比{change:+.1f}%,筹码分散",
        }

    # 2. 机构持仓: 占比>20%:10, 10-20%:7, 5-10%:5, 1-5%:3, 0%:0
    inst_count = summary.get("institutional_count", 0)
    inst_ratio = summary.get("institutional_ratio", 0)
    if inst_ratio > 20:
        hints["institutional_presence"] = {
            "score": 10, "reason": f"{inst_count}家机构持仓,占比{inst_ratio:.1f}%",
        }
    elif inst_ratio > 10:
        hints["institutional_presence"] = {
            "score": 7, "reason": f"{inst_count}家机构持仓,占比{inst_ratio:.1f}%",
        }
    elif inst_ratio > 5:
        hints["institutional_presence"] = {
            "score": 5, "reason": f"{inst_count}家机构持仓,占比{inst_ratio:.1f}%",
        }
    elif inst_ratio > 1:
        hints["institutional_presence"] = {
            "score": 3, "reason": f"{inst_count}家机构持仓,占比{inst_ratio:.1f}%",
        }
    else:
        hints["institutional_presence"] = {
            "score": 0, "reason": "无机构持仓",
        }

    # 3. 高管增减持信号（P3: 辅助参考，不影响总分但给LLM参考）
    insider_signal = summary.get("insider_signal")
    if insider_signal:
        hints["insider_signal"] = {
            "signal": insider_signal,
            "note": summary.get("insider_note", ""),
        }

    # 4. 肨押风险（P3: 辅助参考）
    pledge_risk = summary.get("pledge_risk")
    if pledge_risk:
        hints["pledge_risk"] = {
            "risk": pledge_risk,
            "note": summary.get("pledge_note", ""),
        }

    return hints


def _safe_float(val) -> float | None:
    """安全转换为浮点数"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
