"""
get_dcf - DCF绝对估值工具

提供基于自由现金流的绝对估值分析:
  - 2阶段DCF模型(5年高增长 + 永续增长)
  - WACC敏感性分析
  - 增速敏感性分析
  - PE交叉验证

数据源: 复用 get_financials + get_daily_basic 的数据
"""

import time
import logging
from datetime import datetime

from src.tools.tushare_utils import get_tushare_client, normalize_code
from src.tools.get_financials import get_financials
from src.tools.get_daily_basic import get_daily_basic

logger = logging.getLogger(__name__)


def get_dcf_valuation(code: str) -> dict:
    """
    DCF绝对估值分析

    Args:
        code: 股票代码（如 300033.SZ 或 300033）

    Returns:
        {
            "ok": True,
            "dcf": {
                "intrinsic_value_per_share": float,
                "current_price": float,
                "upside_pct": float,
                "stage1_fcf_projections": [...],
                "terminal_value": float,
                "enterprise_value": float,
                "assumptions": {...},
            },
            "sensitivity": {
                "wacc_growth_table": [[...]],
            },
            "pe_cross_check": {...},
            "scoring_hints": {...},
            "summary": "...",
        }
    """
    start_ms = time.time()

    try:
        ts_code = normalize_code(code)

        # 1. 获取财务数据（含FCF）
        fin_result = get_financials(ts_code)
        if not fin_result.get("ok"):
            return {
                "ok": False,
                "error": f"get_financials failed: {fin_result.get('error')}",
                "duration_ms": int((time.time() - start_ms) * 1000),
            }

        summary = fin_result.get("summary", {})
        data = fin_result.get("data", {})

        # DCF必须用年报数据，不能用季报
        annual_fcf, annual_revenue, annual_np = _get_annual_financials(data)
        if not annual_fcf or annual_fcf <= 0:
            fcf = summary.get("free_cash_flow")  # fallback to summary
            fcf_note = "warning: using latest period data (annual not available)"
        else:
            fcf = annual_fcf
            fcf_note = None

        fcf_margin = round(fcf / annual_revenue * 100, 2) if annual_revenue else summary.get("fcf_margin")
        revenue_yoy = summary.get("revenue_yoy", 0)
        net_profit_yoy = summary.get("net_profit_yoy", 0)
        debt_ratio = summary.get("debt_ratio", 50)
        interest_bearing = summary.get("interest_bearing_debt", -1)

        # 2. 获取估值数据（含市值、PE）
        db_result = get_daily_basic(ts_code)
        if not db_result.get("ok"):
            return {
                "ok": False,
                "error": f"get_daily_basic failed: {db_result.get('error')}",
                "duration_ms": int((time.time() - start_ms) * 1000),
            }

        latest = db_result.get("latest", {})
        valuation = db_result.get("valuation", {})
        total_mv_wan = latest.get("total_mv")  # 万元

        pe_ttm = latest.get("pe_ttm")
        pb = latest.get("pb")
        total_mv_yi = round(total_mv_wan / 10000, 2) if total_mv_wan else None  # 亿

        # 3. 获取当前股价（从 daily_basic 的 close 字段，与市值同一天）
        current_price = _safe_float(latest.get("close"))
        if not current_price:
            # 备选：通过 kline 获取（可能存在复权差异）
            current_price = _get_latest_price(ts_code)
        if not current_price:
            return {
                "ok": False,
                "error": "Cannot determine current price",
                "duration_ms": int((time.time() - start_ms) * 1000),
            }

        total_shares_yi = (
            round(total_mv_yi / current_price, 4) if total_mv_yi and current_price else None
        )

        # 4. 参数准备
        if fcf is None or fcf <= 0:
            return {
                "ok": True,
                "dcf": None,
                "note": "FCF<=0，DCF模型不适用（常见于成长初期或重投入期公司）",
                "current_price": current_price,
                "duration_ms": int((time.time() - start_ms) * 1000),
            }

        fcf_yi = round(fcf / 1e8, 4)  # 转为亿元
        # 用利润增速作为FCF增速代理（保守取增速的60-80%）
        growth_proxy = max(revenue_yoy, net_profit_yoy) if net_profit_yoy > 0 else revenue_yoy
        base_growth = min(growth_proxy * 0.7, 50)  # 保守打7折，上限50%
        terminal_growth = 3.0  # 永续增长率3%

        # WACC估算
        # 权益成本: 无风险利率(3%) + beta(1.0) * 风险溢价(6%) = 9%
        # 有息负债=0时，WACC = 权益成本
        risk_free = 3.0
        equity_risk_premium = 6.0
        beta = 1.1  # A股软件行业beta
        cost_of_equity = risk_free + beta * equity_risk_premium  # 9.6%

        if interest_bearing == 0 or interest_bearing < 0:
            wacc = cost_of_equity  # 无有息负债，WACC=权益成本
        else:
            # 简化WACC: D/(D+E)*cost_of_debt*(1-tax) + E/(D+E)*cost_of_equity
            cost_of_debt = 5.0  # 假设5%借款利率
            tax_rate = 25.0
            debt_weight = debt_ratio / 100
            equity_weight = 1 - debt_weight
            wacc = (
                debt_weight * cost_of_debt * (1 - tax_rate / 100)
                + equity_weight * cost_of_equity
            )

        wacc = round(wacc, 1)

        # 5. 2阶段DCF计算
        projections = []
        discount_factors = []
        discounted_fcfs = []

        for year in range(1, 6):
            projected_fcf = fcf_yi * (1 + base_growth / 100) ** year
            discount_factor = 1 / (1 + wacc / 100) ** year
            discounted_fcf = projected_fcf * discount_factor
            projections.append({
                "year": year,
                "fcf": round(projected_fcf, 2),
                "discount_factor": round(discount_factor, 4),
                "discounted_fcf": round(discounted_fcf, 2),
            })
            discounted_fcfs.append(discounted_fcf)

        # 终端价值
        terminal_fcf = projections[-1]["fcf"] * (1 + terminal_growth / 100)
        terminal_value = terminal_fcf / (wacc / 100 - terminal_growth / 100)
        discount_factor_tv = 1 / (1 + wacc / 100) ** 5
        discounted_tv = terminal_value * discount_factor_tv

        # 企业价值 = 阶段1折现FCF之和 + 折现终端价值
        ev = sum(discounted_fcfs) + discounted_tv

        # 每股内在价值
        intrinsic_per_share = round(ev / total_shares_yi, 2) if total_shares_yi else None

        upside_pct = (
            round((intrinsic_per_share - current_price) / current_price * 100, 1)
            if intrinsic_per_share and current_price
            else None
        )

        # 6. 敏感性分析（WACC x 增速）
        sensitivity_table = _build_sensitivity_table(
            fcf_yi, total_shares_yi, base_growth, terminal_growth
        )

        # 7. PE交叉验证
        pe_cross = None
        if pe_ttm and net_profit_yoy > 0:
            peg = round(pe_ttm / net_profit_yoy, 2)
            pe_cross = {
                "pe_ttm": pe_ttm,
                "peg": peg,
                "peg_verdict": "undervalued" if peg < 1 else ("fair" if peg < 2 else "overvalued"),
                "dcf_vs_pe": (
                    f"DCF内在价值{intrinsic_per_share}元 vs 当前PE{pe_ttm}倍隐含价格{current_price}元"
                    if intrinsic_per_share
                    else None
                ),
            }

        # 8. 评分建议
        hints = _calc_dcf_scoring(intrinsic_per_share, current_price, upside_pct, pe_cross)

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[get_dcf] {ts_code}: FCF={fcf_yi}亿, "
            f"intrinsic={intrinsic_per_share}, current={current_price}, "
            f"upside={upside_pct}%, {duration_ms}ms"
        )

        return {
            "ok": True,
            "dcf": {
                "intrinsic_value_per_share": intrinsic_per_share,
                "current_price": current_price,
                "upside_pct": upside_pct,
                "total_shares_yi": total_shares_yi,
                "fcf_yi": fcf_yi,
                "fcf_margin": fcf_margin,
                "stage1_projections": projections,
                "stage1_pv_sum": round(sum(discounted_fcfs), 2),
                "terminal_value": round(terminal_value, 2),
                "terminal_value_pv": round(discounted_tv, 2),
                "enterprise_value": round(ev, 2),
                "assumptions": {
                    "base_fcf": fcf_yi,
                    "fcf_source": "annual_report" if fcf_note is None else "latest_quarter",
                    "growth_rate_5y": round(base_growth, 1),
                    "growth_source": f"取max(营收{revenue_yoy:.1f}%, 利润{net_profit_yoy:.1f}%)x0.7保守折算",
                    "terminal_growth": terminal_growth,
                    "wacc": wacc,
                    "wacc_composition": f"无风险{risk_free}% + beta{beta} x ERP{equity_risk_premium}% = {cost_of_equity}%",
                    "debt_adjusted": interest_bearing == 0,
                },
            },
            "sensitivity": sensitivity_table,
            "pe_cross_check": pe_cross,
            "scoring_hints": hints,
            "summary": _build_dcf_summary(
                ts_code, intrinsic_per_share, current_price, upside_pct, base_growth, wacc
            ),
            "duration_ms": duration_ms,
            "error": None,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_dcf] Error: {e}")
        return {
            "ok": False,
            "error": str(e),
            "duration_ms": duration_ms,
        }


def _safe_float(val) -> float | None:
    """安全转换为浮点数"""
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def _get_annual_financials(data: dict) -> tuple[float | None, float | None, float | None]:
    """
    从财务数据中提取年报（12月31日）数据。

    DCF必须用年度FCF，不能用季报数据。

    Returns:
        (annual_fcf, annual_revenue, annual_net_profit)
    """
    # 找年报现金流量表
    cashflow = data.get("cashflow", [])
    annual_cf = next((cf for cf in cashflow if cf.get("end_date", "").endswith("1231")), None)

    annual_fcf = None
    if annual_cf:
        ocf = _safe_float(annual_cf.get("n_cashflow_act"))
        capex = _safe_float(annual_cf.get("c_paid_for_assets"))
        if ocf is not None:
            annual_fcf = ocf - (abs(capex) if capex else 0)

    # 找年报利润表
    income = data.get("income", [])
    annual_inc = next((inc for inc in income if inc.get("end_date", "").endswith("1231")), None)

    annual_revenue = None
    annual_np = None
    if annual_inc:
        annual_revenue = _safe_float(annual_inc.get("total_revenue"))
        annual_np = _safe_float(annual_inc.get("n_income"))

    return annual_fcf, annual_revenue, annual_np


def _get_latest_price(ts_code: str) -> float | None:
    """通过 Tushare daily 接口获取最新不复权收盘价"""
    try:
        from src.tools.tushare_utils import get_tushare_client
        service = get_tushare_client()

        # 获取最近3个交易日的日线数据（不复权）
        end_date = datetime.now().strftime("%Y%m%d")
        start_date_offset = 10  # 10个自然日，确保覆盖至少2个交易日
        from datetime import timedelta
        start_date = (datetime.now() - timedelta(days=start_date_offset)).strftime("%Y%m%d")

        raw = service._call("daily", {
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
            "fields": "trade_date,close",
        })
        if raw:
            # 取最新一天
            raw.sort(key=lambda r: r.get("trade_date", ""), reverse=True)
            close = raw[0].get("close")
            if close:
                return round(float(close), 2)
    except Exception as e:
        logger.warning(f"[get_dcf] Failed to get latest price: {e}")

    return None


def _build_sensitivity_table(
    fcf_yi: float,
    shares_yi: float | None,
    base_growth: float,
    terminal_growth: float,
) -> dict:
    """构建WACC x 增速敏感性分析表"""
    wacc_range = [8.0, 9.0, 10.0, 11.0, 12.0]
    growth_range = [
        round(base_growth * 0.5, 1),
        round(base_growth * 0.75, 1),
        round(base_growth, 1),
        round(base_growth * 1.25, 1),
        round(base_growth * 1.5, 1),
    ]

    if not shares_yi:
        return {"note": "Shares data unavailable"}

    table = []
    for g in growth_range:
        row = []
        for w in wacc_range:
            if w <= terminal_growth:
                row.append(None)
                continue
            # 计算5年FCF + 终端价值
            pv_sum = 0
            for yr in range(1, 6):
                proj_fcf = fcf_yi * (1 + g / 100) ** yr
                pv_sum += proj_fcf / (1 + w / 100) ** yr

            tv_fcf = fcf_yi * (1 + g / 100) ** 5 * (1 + terminal_growth / 100)
            tv = tv_fcf / (w / 100 - terminal_growth / 100)
            pv_sum += tv / (1 + w / 100) ** 5

            per_share = round(pv_sum / shares_yi, 1)
            row.append(per_share)
        table.append({"growth": g, "prices": row})

    return {
        "wacc_columns": wacc_range,
        "rows": table,
        "note": "每格为DCF内在价值(元/股)，当前增速对应的行高亮",
    }


def _calc_dcf_scoring(
    intrinsic: float | None,
    current: float | None,
    upside: float | None,
    pe_cross: dict | None,
) -> dict:
    """DCF估值评分建议"""
    hints = {}

    if intrinsic and current and upside is not None:
        if upside > 50:
            hints["dcf_valuation"] = {
                "score": 10,
                "reason": f"DCF内在价值{intrinsic}元，当前价{current}元，低估{upside}%",
            }
        elif upside > 30:
            hints["dcf_valuation"] = {
                "score": 8,
                "reason": f"DCF内在价值{intrinsic}元，低估{upside}%",
            }
        elif upside > 15:
            hints["dcf_valuation"] = {
                "score": 6,
                "reason": f"DCF内在价值{intrinsic}元，轻度低估{upside}%",
            }
        elif upside > 0:
            hints["dcf_valuation"] = {
                "score": 5,
                "reason": f"DCF内在价值{intrinsic}元，接近合理{upside}%",
            }
        elif upside > -15:
            hints["dcf_valuation"] = {
                "score": 3,
                "reason": f"DCF内在价值{intrinsic}元，轻度高估{upside}%",
            }
        else:
            hints["dcf_valuation"] = {
                "score": 1,
                "reason": f"DCF内在价值{intrinsic}元，明显高估{upside}%",
            }

    if pe_cross and pe_cross.get("peg"):
        peg = pe_cross["peg"]
        if peg < 0.8:
            hints["peg_signal"] = {"score": 10, "reason": f"PEG={peg},显著低估"}
        elif peg < 1.0:
            hints["peg_signal"] = {"score": 8, "reason": f"PEG={peg},偏便宜"}
        elif peg < 1.5:
            hints["peg_signal"] = {"score": 6, "reason": f"PEG={peg},合理"}
        elif peg < 2.0:
            hints["peg_signal"] = {"score": 4, "reason": f"PEG={peg},偏贵"}
        else:
            hints["peg_signal"] = {"score": 2, "reason": f"PEG={peg},明显偏贵"}

    return hints


def _build_dcf_summary(
    ts_code: str,
    intrinsic: float | None,
    current: float | None,
    upside: float | None,
    growth: float,
    wacc: float,
) -> str:
    """生成DCF估值总结"""
    if not intrinsic or not current:
        return f"{ts_code} DCF分析: FCF不足或数据缺失，DCF不适用"

    verdict = "低估" if upside and upside > 15 else ("合理" if upside and upside > 0 else "高估")
    return (
        f"{ts_code} DCF估值: 内在价值{intrinsic}元，"
        f"当前价{current}元，{verdict}{upside}%。"
        f"假设5年FCF增速{growth:.1f}%，WACC{wacc}%，永续增长率3%"
    )
