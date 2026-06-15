"""
get_peers - 同行业可比公司对标工具

获取同行业公司的关键财务指标和估值数据，形成对标表。
用于基本面分析师进行"可比公司估值"和"行业对比"分析。

数据源: Tushare stock_basic + fina_indicator + daily_basic
"""

import time
import logging
from datetime import datetime, timedelta
from statistics import median

from src.tools.tushare_utils import get_tushare_client, normalize_code
from src.tools.get_index import _get_stock_industry

logger = logging.getLogger(__name__)

# 对标比较的关键指标
COMPARE_METRICS = [
    "roe", "grossprofit_margin", "netprofit_margin",
    "or_yoy", "netprofit_yoy",
    "debt_to_assets", "current_ratio",
]

COMPARE_FIELDS = [
    "ts_code", "end_date",
    "roe", "grossprofit_margin", "netprofit_margin",
    "or_yoy", "netprofit_yoy",
    "debt_to_assets", "current_ratio",
    "eps",
]


def get_peers(code: str, top_n: int = 8) -> dict:
    """
    获取同行业可比公司对标数据

    Args:
        code: 股票代码（如 300033.SZ 或 300033）
        top_n: 获取同行业前N家公司（按市值排序），默认8家

    Returns:
        {
            "ok": True,
            "target_code": "300033.SZ",
            "industry": "计算机",
            "peers": [...],
            "industry_median": {...},
            "target_vs_median": {...},
            "scoring_hints": {...},
            "summary": "...",
        }
    """
    start_ms = time.time()

    try:
        ts_code = normalize_code(code)

        # 1. 获取目标公司行业
        industry_info = _get_stock_industry(ts_code)
        industry = industry_info.get("industry")
        if not industry:
            return {
                "ok": False,
                "error": f"Cannot determine industry for {ts_code}",
                "duration_ms": int((time.time() - start_ms) * 1000),
            }

        logger.info(f"[get_peers] {ts_code} -> industry: {industry}")

        service = get_tushare_client()

        # 2. 获取同行业公司列表
        peer_list = _get_industry_stocks(service, industry, ts_code, top_n)
        if not peer_list:
            return {
                "ok": False,
                "error": f"No peers found for industry '{industry}'",
                "industry": industry,
                "duration_ms": int((time.time() - start_ms) * 1000),
            }

        # 3. 批量获取财务指标（包含目标公司）
        peer_codes = [p["ts_code"] for p in peer_list]
        all_codes = [ts_code] + peer_codes
        financial_data = _batch_get_financials(service, all_codes)

        # 4. 批量获取估值数据（包含目标公司）
        valuation_data = _batch_get_valuation(service, all_codes)

        # 4.5 按市值排序，取前N家（修复: 之前是随机选取）
        peer_list.sort(
            key=lambda p: (valuation_data.get(p["ts_code"], {}).get("total_mv") or 0),
            reverse=True,
        )
        peer_list = peer_list[:top_n]
        # 更新 all_codes
        peer_codes = [p["ts_code"] for p in peer_list]
        all_codes = [ts_code] + peer_codes

        # 5. 组装对标表
        peers = _build_peer_table(
            ts_code, peer_list, financial_data, valuation_data
        )

        # 6. 计算行业中位数
        ind_median = _calc_industry_median(peers)

        # 7. 目标公司 vs 行业中位数对比
        target = next((p for p in peers if p["ts_code"] == ts_code), None)
        vs_median = _calc_target_vs_median(target, ind_median) if target else {}

        # 8. 生成评分建议
        hints = _calc_peer_scoring_hints(target, ind_median)

        # 9. 生成文字总结
        summary_text = _build_summary_text(
            ts_code, industry_info.get("stock_name", ""),
            industry, target, ind_median, len(peers)
        )

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[get_peers] {ts_code}: {len(peers)} peers in '{industry}', "
            f"{duration_ms}ms"
        )

        return {
            "ok": True,
            "target_code": ts_code,
            "target_name": industry_info.get("stock_name", ""),
            "industry": industry,
            "peer_count": len(peers),
            "peers": peers,
            "industry_median": ind_median,
            "target_vs_median": vs_median,
            "scoring_hints": hints,
            "summary": summary_text,
            "duration_ms": duration_ms,
            "error": None,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_peers] Error: {e}")
        return {
            "ok": False,
            "error": str(e),
            "duration_ms": duration_ms,
        }


def _get_industry_stocks(
    service, industry: str, target_code: str, top_n: int
) -> list[dict]:
    """获取同行业公司列表（排除目标公司，按市值取前N家）"""
    try:
        # Tushare stock_basic 的 industry 参数不过滤，需要全量获取后手动过滤
        raw = service._call("stock_basic", {
            "list_status": "L",
            "fields": "ts_code,name,industry,market,list_date",
        })

        if not raw:
            return []

        # 手动按 industry 字段过滤，排除目标公司
        peers = [
            r for r in raw
            if r.get("ts_code") != target_code
            and r.get("industry") == industry
        ]

        if not peers:
            logger.warning(
                f"[get_peers] No peers found for industry '{industry}'"
            )
            return []

        # 优先选同市场（创业板/科创板/主板）
        target_market = target_code.split(".")[1] if "." in target_code else ""
        if target_market:
            same_market = [p for p in peers if p.get("ts_code", "").endswith(target_market)]
            if len(same_market) >= top_n // 2:
                peers = same_market

        # 多取一些候选（后续获取估值数据后再按市值排序截取）
        return peers[:top_n * 3]

    except Exception as e:
        logger.warning(f"[get_peers] Failed to get industry stocks: {e}")
        return []


def _batch_get_financials(service, codes: list[str]) -> dict:
    """批量获取多只股票的最新财务指标"""
    result = {}
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")

    for code in codes:
        try:
            raw = service._call("fina_indicator", {
                "ts_code": code,
                "start_date": start_date,
                "end_date": end_date,
            })
            if raw:
                # 取最新一期
                raw.sort(key=lambda r: r.get("end_date", ""), reverse=True)
                result[code] = raw[0]
        except Exception as e:
            logger.warning(f"[get_peers] fina_indicator {code} failed: {e}")

    return result


def _batch_get_valuation(service, codes: list[str]) -> dict:
    """批量获取多只股票的最新估值数据"""
    result = {}
    end_date = datetime.now().strftime("%Y%m%d")

    for code in codes:
        raw = None
        # B3 fix: dynamically expand window for holidays/weekends
        for window_days in [5, 10, 20, 30]:
            start_date = (datetime.now() - timedelta(days=window_days)).strftime("%Y%m%d")
            try:
                raw = service._call("daily_basic", {
                    "ts_code": code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "fields": "trade_date,pe_ttm,pb,total_mv,circ_mv",
                })
            except Exception as e:
                logger.warning(f"[get_peers] daily_basic {code} window={window_days} failed: {e}")
                raw = None
            if raw and len(raw) >= 1:
                break
        if raw:
            # 取最新一天
            raw.sort(key=lambda r: r.get("trade_date", ""), reverse=True)
            result[code] = raw[0]

    return result


def _safe_float(val) -> float | None:
    """安全转换为浮点数"""
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def _build_peer_table(
    target_code: str,
    peer_list: list[dict],
    financial_data: dict,
    valuation_data: dict,
) -> list[dict]:
    """组装对标表"""
    # 把目标公司也加进去（放在第一个位置）
    all_codes = [target_code] + [p["ts_code"] for p in peer_list]
    name_map = {p["ts_code"]: p.get("name", "") for p in peer_list}

    peers = []
    for code in all_codes:
        fin = financial_data.get(code, {})
        val = valuation_data.get(code, {})
        name = name_map.get(code, "")

        peer = {
            "ts_code": code,
            "name": name,
            "roe": _safe_float(fin.get("roe")),
            "gross_margin": _safe_float(fin.get("grossprofit_margin")),
            "net_margin": _safe_float(fin.get("netprofit_margin")),
            "revenue_yoy": _safe_float(fin.get("or_yoy")),
            "profit_yoy": _safe_float(fin.get("netprofit_yoy")),
            "debt_ratio": _safe_float(fin.get("debt_to_assets")),
            "current_ratio": _safe_float(fin.get("current_ratio")),
            "pe_ttm": _safe_float(val.get("pe_ttm")),
            "pb": _safe_float(val.get("pb")),
            "market_cap_yi": round(_safe_float(val.get("total_mv")) / 10000, 2)
                if _safe_float(val.get("total_mv")) else None,
        }
        peers.append(peer)

    return peers


def _calc_industry_median(peers: list[dict]) -> dict:
    """计算行业中位数（排除目标公司）"""
    # 跳过第一个（目标公司）
    industry_peers = peers[1:] if len(peers) > 1 else peers

    metrics = [
        "roe", "gross_margin", "net_margin",
        "revenue_yoy", "profit_yoy",
        "debt_ratio", "current_ratio",
        "pe_ttm", "pb", "market_cap_yi",
    ]

    result = {}
    for m in metrics:
        vals = [p[m] for p in industry_peers if p.get(m) is not None]
        if vals:
            result[m] = round(median(vals), 2)

    return result


def _calc_target_vs_median(target: dict, ind_median: dict) -> dict:
    """计算目标公司 vs 行业中位数的差异"""
    result = {}
    metrics = [
        "roe", "gross_margin", "net_margin",
        "revenue_yoy", "profit_yoy",
        "debt_ratio", "pe_ttm", "pb",
    ]

    for m in metrics:
        t_val = target.get(m)
        m_val = ind_median.get(m)
        if t_val is not None and m_val is not None and m_val != 0:
            diff_pct = round((t_val - m_val) / abs(m_val) * 100, 1)
            direction = "高于" if diff_pct > 0 else "低于"
            result[m] = f"{direction}行业中位数{abs(diff_pct):.0f}%"

    return result


def _calc_peer_scoring_hints(target: dict, ind_median: dict) -> dict:
    """基于同行对比生成评分建议"""
    hints = {}

    # 估值同行对比
    t_pe = target.get("pe_ttm")
    m_pe = ind_median.get("pe_ttm")
    if t_pe and m_pe and m_pe > 0:
        pe_premium = (t_pe - m_pe) / m_pe * 100
        if pe_premium < -20:
            hints["peer_valuation"] = {
                "score": 8,
                "reason": f"PE({t_pe:.1f})低于行业中位数{abs(pe_premium):.0f}%",
            }
        elif pe_premium < 20:
            hints["peer_valuation"] = {
                "score": 6,
                "reason": f"PE({t_pe:.1f})接近行业中位数({m_pe:.1f})",
            }
        elif pe_premium < 50:
            hints["peer_valuation"] = {
                "score": 4,
                "reason": f"PE({t_pe:.1f})高于行业中位数{pe_premium:.0f}%",
            }
        else:
            hints["peer_valuation"] = {
                "score": 2,
                "reason": f"PE({t_pe:.1f})远高于行业中位数{pe_premium:.0f}%",
            }

    return hints


def _build_summary_text(
    ts_code: str,
    name: str,
    industry: str,
    target: dict | None,
    ind_median: dict,
    peer_count: int,
) -> str:
    """生成文字总结"""
    if not target:
        return f"{ts_code}在{industry}行业有{peer_count}家可比公司，但目标公司数据缺失"

    parts = [f"{name or ts_code}在{industry}行业有{peer_count}家可比公司"]

    t_roe = target.get("roe")
    m_roe = ind_median.get("roe")
    if t_roe and m_roe:
        if t_roe > m_roe * 1.5:
            parts.append(f"ROE({t_roe:.1f}%)远高于行业中位数({m_roe:.1f}%)")
        elif t_roe > m_roe:
            parts.append(f"ROE({t_roe:.1f}%)高于行业中位数({m_roe:.1f}%)")
        else:
            parts.append(f"ROE({t_roe:.1f}%)低于行业中位数({m_roe:.1f}%)")

    t_pe = target.get("pe_ttm")
    m_pe = ind_median.get("pe_ttm")
    if t_pe and m_pe:
        if t_pe > m_pe * 1.5:
            parts.append(f"PE({t_pe:.1f})显著高于行业中位数({m_pe:.1f})")
        elif t_pe < m_pe * 0.8:
            parts.append(f"PE({t_pe:.1f})低于行业中位数({m_pe:.1f})，估值有吸引力")

    return "，".join(parts)
