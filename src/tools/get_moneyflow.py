"""
get_moneyflow - 个股资金流向工具

获取个股的资金流向数据，包含大单/中单/小单/特大单的买卖金额。
用于判断主力资金动向，是技术分析的重要辅助维度。

数据源: Tushare moneyflow 接口
"""

import time
import logging
from datetime import datetime, timedelta

from src.tools.tushare_utils import get_tushare_client, normalize_code

logger = logging.getLogger(__name__)


def get_moneyflow(
    code: str,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """
    获取个股资金流向数据

    Args:
        code: 股票代码（如 300033.SZ 或 300033）
        start_date: 开始日期（YYYYMMDD），可省略
        end_date: 结束日期（YYYYMMDD），可省略

    Returns:
        {
            "ok": True,
            "data": [最近N天的资金流向],
            "summary": {
                "latest_net_mf": 最新净流入金额,
                "recent_5d_net": 近5日净流入,
                "main_force_signal": 主力信号,
                ...
            },
            "count": N,
            "error": None
        }
    """
    start_ms = time.time()

    try:
        ts_code = normalize_code(code)

        # 默认近30天
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        service = get_tushare_client()

        if hasattr(service, "get_moneyflow"):
            raw = service.get_moneyflow(ts_code, start, end)
        else:
            raw = []

        if isinstance(raw, list):
            records = raw
        else:
            records = []

        records.sort(key=lambda r: r.get("trade_date", ""))

        if not records:
            return {
                "ok": True,
                "data": [],
                "summary": {},
                "count": 0,
                "duration_ms": int((time.time() - start_ms) * 1000),
                "error": None,
            }

        # 精简输出：只保留关键字段
        trimmed = []
        for r in records:
            trimmed.append({
                "trade_date": r.get("trade_date"),
                "buy_sm_amount": r.get("buy_sm_amount"),
                "sell_sm_amount": r.get("sell_sm_amount"),
                "buy_lg_amount": r.get("buy_lg_amount"),
                "sell_lg_amount": r.get("sell_lg_amount"),
                "buy_elg_amount": r.get("buy_elg_amount"),
                "sell_elg_amount": r.get("sell_elg_amount"),
                "net_mf_amount": r.get("net_mf_amount"),
            })

        # 截取最近20条（资金流向不需要太长）
        output = trimmed[-20:]

        # 构建摘要
        summary = _build_moneyflow_summary(trimmed)

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[get_moneyflow] {ts_code} "
            f"{start}-{end}: {len(records)} rows, {duration_ms}ms"
        )

        return {
            "ok": True,
            "data": output,
            "summary": summary,
            "count": len(output),
            "duration_ms": duration_ms,
            "error": None,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_moneyflow] Error: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
        }


def _build_moneyflow_summary(records: list[dict]) -> dict:
    """构建资金流向摘要"""
    if not records:
        return {}

    # 最新一天
    latest = records[-1]
    latest_net = float(latest.get("net_mf_amount", 0) or 0)

    # 大单净流入 = (buy_lg - sell_lg) + (buy_elg - sell_elg)
    latest_lg_net = (
        float(latest.get("buy_lg_amount", 0) or 0)
        - float(latest.get("sell_lg_amount", 0) or 0)
        + float(latest.get("buy_elg_amount", 0) or 0)
        - float(latest.get("sell_elg_amount", 0) or 0)
    )

    # 近5日累计净流入
    recent = records[-5:] if len(records) >= 5 else records
    recent_5d_net = sum(
        float(r.get("net_mf_amount", 0) or 0) for r in recent
    )
    recent_5d_lg_net = sum(
        float(r.get("buy_lg_amount", 0) or 0)
        - float(r.get("sell_lg_amount", 0) or 0)
        + float(r.get("buy_elg_amount", 0) or 0)
        - float(r.get("sell_elg_amount", 0) or 0)
        for r in recent
    )

    # 全部数据的累计净流入
    total_net = sum(
        float(r.get("net_mf_amount", 0) or 0) for r in records
    )

    # 主力信号判断
    if recent_5d_lg_net > 0 and latest_net > 0:
        main_signal = "continuous_inflow"
    elif recent_5d_lg_net > 0 and latest_net < 0:
        main_signal = "inflow_reversal"
    elif recent_5d_lg_net < 0 and latest_net > 0:
        main_signal = "outflow_reversal"
    elif recent_5d_lg_net < 0 and latest_net < 0:
        main_signal = "continuous_outflow"
    else:
        main_signal = "neutral"

    # 近5日大单占比（大单净流入 / 总净流入）
    total_amount = sum(
        abs(float(r.get("net_mf_amount", 0) or 0)) for r in recent
    )

    summary = {
        "latest_net_mf": round(latest_net, 2),
        "latest_main_force_net": round(latest_lg_net, 2),
        "recent_5d_net_mf": round(recent_5d_net, 2),
        "recent_5d_main_force_net": round(recent_5d_lg_net, 2),
        "total_period_net_mf": round(total_net, 2),
        "main_force_signal": main_signal,
        "latest_date": latest.get("trade_date"),
    }

    # 信号中文说明
    signal_desc = {
        "continuous_inflow": "主力资金持续净流入，资金面偏多",
        "inflow_reversal": "近5日主力净流入但最新一天转流出，需警惕",
        "outflow_reversal": "近5日主力净流出但最新一天转流入，可能止跌",
        "continuous_outflow": "主力资金持续净流出，资金面偏空",
        "neutral": "资金流向无明显趋势",
    }
    summary["signal_description"] = signal_desc.get(main_signal, "")

    return summary
