"""
get_financials - 财务数据工具

提供基本面分析所需的核心财务数据:
  - 利润表 (income): 营收、成本、净利润
  - 资产负债表 (balancesheet): 资产、负债、净资产
  - 现金流量表 (cashflow): 经营/投资/筹资现金流
  - 财务指标 (fina_indicator): ROE、毛利率、增速等

数据源: Tushare income/balancesheet/cashflow/fina_indicator 接口
"""

import time
import logging
from datetime import datetime, timedelta

from src.tools.tushare_utils import get_tushare_client, normalize_code

logger = logging.getLogger(__name__)

# 每个报表保留的关键字段（减少传给 LLM 的数据量）
INCOME_FIELDS = [
    "ann_date", "end_date", "total_revenue", "revenue",
    "total_cogs", "oper_cost", "sell_exp", "admin_exp",
    "operate_profit", "total_profit", "n_income",
    "n_income_attr_p",
    # 利润质量拆解必需字段
    "rd_exp",                   # 研发费用
    "fin_exp",                  # 财务费用（利息/汇兑）
    "invest_income",            # 投资收益
    "fair_value_change_income", # 公允价值变动收益
    "asset_impairment_loss",    # 资产减值损失
    "other_income",             # 其他收益（补贴等）
]

BALANCESHEET_FIELDS = [
    "ann_date", "end_date", "total_assets", "total_liab",
    "total_hldr_eqy_exc_min_int", "monetary_capital",
    "account_receivable", "inventory",
    "total_cur_assets", "total_cur_liab",
    # P0: 负债结构拆分（区分有息负债 vs 经营性负债）
    "short_term_loan", "long_term_loan", "bonds_payable",
    "advance_peceipts", "contract_liab",
    # P3: 商誉/无形资产风险
    "goodwill", "intan_assets",
    # 营运资本
    "account_payable",
    # 投资持仓识别
    "long_term_equity_invest",   # 长期股权投资
    "trad_fin_assets",           # 交易性金融资产
    "other_equity_invest",       # 其他权益工具投资
    # 固定资产/在建工程（产能扩张信号）
    "fix_assets", "cip",
]

CASHFLOW_FIELDS = [
    "ann_date", "end_date",
    "n_cashflow_act", "n_cashflow_inv_act", "n_cashflow_fnc_act",
    "c_paid_for_assets",
    # P1: 收现比
    "c_sales_services",
    # 投资活动明细
    "c_recv_invest_return",      # 取得投资收益收到的现金
    "c_paid_invest",             # 投资支付的现金
]

INDICATOR_FIELDS = [
    "ann_date", "end_date",
    "roe",
    "grossprofit_margin", "netprofit_margin",
    "or_yoy", "netprofit_yoy",
    "eps",
    "current_ratio", "debt_to_assets",
    # P1: 扣非净利润
    "profit_dedt",
]


# 核心报表(降级分级判定用); 单表模式下动态收缩到只检查请求的表
CORE_REPORTS = ("income", "balancesheet", "cashflow", "indicators")


def get_financials(
    code: str,
    start_date: str = "",
    end_date: str = "",
    report_type: str = "all",
) -> dict:
    """
    获取股票财务报表数据

    Args:
        code: 股票代码（如 300033.SZ 或 300033）
        start_date: 开始日期（YYYYMMDD），为空则自动计算（1年前）
        end_date: 结束日期（YYYYMMDD），为空则用今天
        report_type: 报表类型 "all"/"income"/"balancesheet"/"cashflow"/"indicators"

    Returns:
        {"ok": True, "data": {...}, "summary": {...}, "scoring_hints": {...}, "error": None}
    """
    start_ms = time.time()

    try:
        ts_code = normalize_code(code)

        # 财务报表有滞后，默认查 1 年
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        service = get_tushare_client()

        all_data = {}
        fetch_failures = {}  # 追踪各报表获取失败原因，用于降级标记

        fetch_map = {
            "income": ("income", INCOME_FIELDS),
            "balancesheet": ("balancesheet", BALANCESHEET_FIELDS),
            "cashflow": ("cashflow", CASHFLOW_FIELDS),
            "indicators": ("fina_indicator", INDICATOR_FIELDS),
        }

        for key, (api_name, fields) in fetch_map.items():
            if report_type != "all" and report_type != key:
                continue
            try:
                raw = service._call(api_name, {
                    "ts_code": ts_code,
                    "start_date": start,
                    "end_date": end,
                })
                if not raw:
                    raw = []
                # B4 fix: 船长逻辑 - 按公告日筛选，按截止日排序，同截止日取最新公告
                today_str = datetime.now().strftime("%Y%m%d")
                if raw:
                    # 1. 只取公告日 <= 今天的记录
                    raw = [r for r in raw if (r.get("ann_date") or "99999999") <= today_str]
                    # 2. 按截止日降序
                    raw.sort(key=lambda r: (r.get("end_date") or ""), reverse=True)
                    # 3. 同一截止日取公告日最大的
                    seen_periods = set()
                    deduped = []
                    for r in raw:
                        period = r.get("end_date") or ""
                        if period not in seen_periods:
                            seen_periods.add(period)
                            deduped.append(r)
                    raw = deduped
                # 4. 取前8期（2年季度数据，支持多年趋势分析）
                records = raw[:8]
                # 只保留关键字段
                trimmed = []
                for r in records:
                    row = {}
                    for f in fields:
                        val = r.get(f)
                        if val is not None:
                            row[f] = val
                    trimmed.append(row)
                all_data[key] = trimmed
            except Exception as e:
                logger.warning(f"[get_financials] {api_name} failed: {e}")
                all_data[key] = []
                fetch_failures[key] = str(e)

        # 获取分红数据
        try:
            div_raw = service._call("dividend", {
                "ts_code": ts_code,
                "fields": "ts_code,end_date,ann_date,div_proc,stk_div,cash_div,cash_div_tax,ex_date",
            })
            if not div_raw:
                div_raw = []
            # 按end_date倒序，取最近5次分红
            div_raw.sort(key=lambda r: (r.get("end_date") or ""), reverse=True)
            # 只保留实施的记录（去重：同一年可能有多条预案/实施）
            seen_years = set()
            dividends = []
            for r in div_raw[:15]:
                year = (r.get("end_date") or "")[:4]
                proc = r.get("div_proc", "")
                if year not in seen_years and proc in ("实施", "决案"):
                    dividends.append(r)
                    seen_years.add(year)
                    if len(dividends) >= 5:
                        break
            all_data["dividend"] = dividends
        except Exception as e:
            logger.warning(f"[get_financials] dividend failed: {e}")
            all_data["dividend"] = []
            fetch_failures["dividend"] = str(e)

        # 计算统计摘要
        summary = _build_summary(all_data)

        duration_ms = int((time.time() - start_ms) * 1000)
        total_records = sum(len(v) for v in all_data.values())

        logger.info(
            f"[get_financials] {ts_code} {start}-{end}: "
            f"{total_records} records, {duration_ms}ms"
        )

        # 降级分级: 根据核心报表获取情况标记数据完整度
        # 保守版: 保持 ok=True 不变(不破坏现有成功判定), 只新增标记字段供上游识别
        # 升级版(观察后): 全空时改 ok=False, 让 quality.py 自动拦截
        # 单表模式下只检查请求的表, 避免把"没请求的表"误判为失败
        if report_type == "all":
            checked = list(CORE_REPORTS)
        elif report_type in CORE_REPORTS:
            checked = [report_type]
        else:
            checked = []
        core_failed = [k for k in checked if not all_data.get(k)]
        if not core_failed:
            data_status, data_degraded = "complete", False
            degraded_reports = []
        else:
            data_degraded = True
            degraded_reports = core_failed
            data_status = "empty" if len(core_failed) == len(checked) else "partial"
        if data_degraded:
            logger.warning(
                f"[get_financials] {ts_code} data degraded: "
                f"{data_status}, missing={degraded_reports}"
            )

        result = {
            "ok": True,
            "data": all_data,
            "count": {k: len(v) for k, v in all_data.items()},
            "summary": summary,
            "duration_ms": duration_ms,
            "error": None,
            "data_status": data_status,
            "data_degraded": data_degraded,
            "degraded_reports": degraded_reports,
            "fetch_failures": fetch_failures,
        }

        # 评分建议
        hints = _calc_scoring_hints(summary)
        if hints:
            result["scoring_hints"] = hints

        return result

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_financials] Error: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
            "data_status": "error",
            "data_degraded": True,
            "degraded_reports": list(CORE_REPORTS),
            "fetch_failures": {"_outer": str(e)},
        }


def _build_summary(data: dict) -> dict:
    """从财务数据中提取关键指标摘要"""
    summary = {}

    # 从财务指标中提取
    indicators = data.get("indicators", [])
    if indicators:
        latest = indicators[0]  # 已按日期倒序
        summary["latest_report_date"] = latest.get("end_date")
        summary["latest_ann_date"] = latest.get("ann_date")

        # 盈利能力
        roe = latest.get("roe")
        summary["roe_latest"] = _safe_float(roe)
        gross_margin = latest.get("grossprofit_margin")
        summary["gross_margin"] = _safe_float(gross_margin)
        net_margin = latest.get("netprofit_margin")
        summary["net_margin"] = _safe_float(net_margin)

        # P0: ROE 季节性处理 — 找最近年报 ROE
        annual_roe = _find_annual_roe(indicators)
        if annual_roe is not None:
            summary["roe_annual"] = annual_roe
            latest_roe = _safe_float(roe) or 0
            # 如果最新 ROE < 年报 ROE 的 40%，说明是季节性低点
            if latest_roe < annual_roe * 0.4 and annual_roe > 10:
                summary["roe_seasonal_note"] = (
                    f"最新ROE={latest_roe:.1f}%为Q1季节性低点，"
                    f"年报ROE={annual_roe:.1f}%更具代表性"
                )

        # 成长性
        revenue_yoy = latest.get("or_yoy")
        summary["revenue_yoy"] = _safe_float(revenue_yoy)
        profit_yoy = latest.get("netprofit_yoy")
        summary["net_profit_yoy"] = _safe_float(profit_yoy)

        # 安全性
        debt_ratio = latest.get("debt_to_assets")
        summary["debt_ratio"] = _safe_float(debt_ratio)
        current_ratio = latest.get("current_ratio")
        summary["current_ratio"] = _safe_float(current_ratio)
        eps = latest.get("eps")
        summary["eps"] = _safe_float(eps)

        # 趋势判断（比较最近 2-3 期）
        if len(indicators) >= 2:
            prev = indicators[1]
            summary["roe_trend"] = _trend(latest.get("roe"), prev.get("roe"))
            summary["revenue_trend"] = _trend_yoy(indicators, "or_yoy")
            summary["profit_trend"] = _trend_yoy(indicators, "netprofit_yoy")

    # 从利润表中提取
    income = data.get("income", [])
    if income:
        latest_inc = income[0]
        summary["total_revenue_latest"] = _safe_float(
            latest_inc.get("total_revenue")
        )
        summary["net_income_latest"] = _safe_float(
            latest_inc.get("n_income_attr_p")
        )

        # P1: 费用率分析 — 毛利率到净利率的"漏损路径"
        rev = _safe_float(latest_inc.get("total_revenue")) or 0
        if rev > 0:
            sell_exp = _safe_float(latest_inc.get("sell_exp")) or 0
            admin_exp = _safe_float(latest_inc.get("admin_exp")) or 0
            summary["sell_expense_rate"] = round(sell_exp / rev * 100, 2)
            summary["admin_expense_rate"] = round(admin_exp / rev * 100, 2)
            summary["total_expense_rate"] = round(
                (sell_exp + admin_exp) / rev * 100, 2
            )

    # P1: 扣非净利润分析（区分"真赚钱"vs"卖资产赚钱"）
    if indicators:
        profit_dedt = _safe_float(indicators[0].get("profit_dedt"))
        if profit_dedt is not None:
            summary["deducted_net_profit"] = profit_dedt
            net_income = summary.get("net_income_latest")
            if net_income and net_income != 0:
                non_recurring = net_income - profit_dedt
                non_recurring_ratio = round(abs(non_recurring) / abs(net_income) * 100, 1)
                summary["non_recurring_ratio"] = non_recurring_ratio
                if non_recurring_ratio > 20:
                    summary["non_recurring_warning"] = (
                        f"非经常性损益占归母净利润{non_recurring_ratio:.1f}%>20%，"
                        f"需关注利润可持续性"
                    )

    # 从现金流量表中计算现金流质量
    cashflow = data.get("cashflow", [])
    if cashflow and income:
        latest_cf = cashflow[0]
        ocf = _safe_float(latest_cf.get("n_cashflow_act"))
        np_val = _safe_float(income[0].get("n_income_attr_p"))
        if ocf and np_val and np_val != 0:
            summary["ocf_to_np_ratio"] = round(ocf / np_val, 2)

        # P1: 自由现金流 = 经营现金流 - 资本开支
        capex = _safe_float(latest_cf.get("c_paid_for_assets"))
        if ocf is not None:
            fcf = ocf - (abs(capex) if capex else 0)
            summary["free_cash_flow"] = round(fcf, 2)
            rev = _safe_float(income[0].get("total_revenue"))
            if rev and rev != 0:
                summary["fcf_margin"] = round(fcf / rev * 100, 2)

        # P1: 三大现金流判型（8种类型）
        icf = _safe_float(latest_cf.get("n_cashflow_inv_act"))
        fcf_cf = _safe_float(latest_cf.get("n_cashflow_fnc_act"))
        if ocf is not None and icf is not None:
            cf_type = _classify_cashflow_type(ocf, icf, fcf_cf)
            summary["cashflow_type"] = cf_type

        # P1: 收现比 = 销售商品收到的现金 / 营业收入
        sales_cash = _safe_float(latest_cf.get("c_sales_services"))
        cf_rev = _safe_float(income[0].get("total_revenue"))
        if sales_cash is not None and cf_rev and cf_rev > 0:
            revenue_cash_ratio = round(sales_cash / cf_rev, 4)
            summary["revenue_cash_ratio"] = revenue_cash_ratio

    # P0: 负债结构拆分
    balancesheet = data.get("balancesheet", [])
    if balancesheet:
        latest_bs = balancesheet[0]
        _build_liability_structure(summary, latest_bs)

    # P1: 杜邦分析三因子
    _build_dupont(summary, indicators, balancesheet, income)

    # P3: 商誉风险检查
    if balancesheet:
        latest_bs = balancesheet[0]
        equity = _safe_float(latest_bs.get("total_hldr_eqy_exc_min_int"))
        goodwill = _safe_float(latest_bs.get("goodwill"))
        if equity and goodwill and equity != 0:
            gw_ratio = round(goodwill / equity * 100, 2)
            summary["goodwill_to_equity"] = gw_ratio
            if gw_ratio > 30:
                summary["goodwill_warning"] = (
                    f"商誉/净资产={gw_ratio:.1f}%>30%，高减值风险"
                )

    # P1: 分红分析
    dividends = data.get("dividend", [])
    if dividends:
        _build_dividend_summary(summary, dividends, indicators)

    # P2: 轻资产检测 — 标记行业特征给 LLM 参考
    if indicators and balancesheet:
        gross_m = summary.get("gross_margin") or 0
        total_assets = _safe_float(balancesheet[0].get("total_assets")) or 0
        equity_val = _safe_float(balancesheet[0].get("total_hldr_eqy_exc_min_int")) or 0
        # 轻资产特征: 毛利率>50% 且 权益乘数<3
        equity_mult = total_assets / equity_val if equity_val else 0
        if gross_m > 50 and equity_mult < 3.5:
            summary["asset_type"] = "light_asset"
            summary["asset_type_note"] = (
                "轻资产公司，PB天然偏高（净资产基数小），"
                "估值应以PE/PEG为主，PB评分应降低权重或忽略"
            )

    # P2: 营运资本分析 — 应收/应付/存货周转天数
    if income and balancesheet:
        rev_val = _safe_float(income[0].get("total_revenue")) or 0
        ar = _safe_float(balancesheet[0].get("account_receivable")) or 0
        inv = _safe_float(balancesheet[0].get("inventory")) or 0
        ap = _safe_float(balancesheet[0].get("account_payable")) or 0
        if rev_val > 0:
            wc = {}
            if ar > 0:
                wc["ar_turnover_days"] = round(365 / (rev_val / ar), 1)
            if inv > 0:
                # 营业成本来自income
                cost = _safe_float(income[0].get("oper_cost")) or 0
                if cost > 0:
                    wc["inventory_turnover_days"] = round(365 / (cost / inv), 1)
            if ap > 0:
                wc["ap_turnover_days"] = round(365 / (rev_val / ap), 1)
            if wc:
                summary["working_capital"] = wc

    summary["report_count"] = len(indicators)
    return summary


def _find_annual_roe(indicators: list[dict]) -> float | None:
    """从最近几期指标中找到年报（12-31）的 ROE"""
    for ind in indicators:
        end_date = ind.get("end_date") or ""
        if end_date.endswith("1231"):
            roe = _safe_float(ind.get("roe"))
            if roe is not None:
                return roe
    return None


def _build_dividend_summary(
    summary: dict, dividends: list[dict], indicators: list[dict]
) -> None:
    """分析分红历史：股息率、分红率、分红趋势"""
    if not dividends:
        return

    # 最新一次分红
    latest_div = dividends[0]
    cash_per_10 = _safe_float(latest_div.get("cash_div")) or 0
    stk_per_10 = _safe_float(latest_div.get("stk_div")) or 0
    summary["latest_dividend_year"] = (latest_div.get("end_date") or "")[:4]
    summary["latest_cash_div_per_10"] = cash_per_10
    summary["latest_stk_div_per_10"] = stk_per_10

    # 分红率 = 每股派现 / EPS（年报EPS）
    # cash_div 是每10股派现，EPS是每股收益
    annual_eps = None
    for ind in indicators:
        if (ind.get("end_date") or "").endswith("1231"):
            annual_eps = _safe_float(ind.get("eps"))
            break

    if annual_eps and annual_eps > 0 and cash_per_10 > 0:
        cash_per_share = cash_per_10 / 10
        payout_ratio = round(cash_per_share / annual_eps * 100, 1)
        summary["payout_ratio"] = payout_ratio

    # 近5年分红历史（现金分红趋势）
    div_history = []
    for d in dividends[:5]:
        year = (d.get("end_date") or "")[:4]
        cash = _safe_float(d.get("cash_div")) or 0
        stk = _safe_float(d.get("stk_div")) or 0
        div_history.append({"year": year, "cash_per_10": cash, "stk_per_10": stk})
    summary["dividend_history"] = div_history

    # 分红趋势判断
    cash_values = [d["cash_per_10"] for d in div_history if d["cash_per_10"] > 0]
    if len(cash_values) >= 2:
        if cash_values[0] > cash_values[-1] * 1.2:
            summary["dividend_trend"] = "increasing"
        elif cash_values[0] < cash_values[-1] * 0.8:
            summary["dividend_trend"] = "decreasing"
        else:
            summary["dividend_trend"] = "stable"
    elif len(cash_values) == 1:
        summary["dividend_trend"] = "limited_data"


def _build_liability_structure(summary: dict, bs: dict) -> None:
    """拆分负债结构：有息负债 vs 经营性负债"""
    total_liab = _safe_float(bs.get("total_liab"))
    if not total_liab or total_liab == 0:
        return

    short_loan = _safe_float(bs.get("short_term_loan")) or 0
    long_loan = _safe_float(bs.get("long_term_loan")) or 0
    bonds = _safe_float(bs.get("bonds_payable")) or 0
    advance = _safe_float(bs.get("advance_peceipts")) or 0
    contract = _safe_float(bs.get("contract_liab")) or 0

    interest_bearing = short_loan + long_loan + bonds
    operating_liab = total_liab - interest_bearing

    summary["interest_bearing_debt"] = round(interest_bearing, 2)
    summary["operating_liab"] = round(operating_liab, 2)
    summary["operating_liab_ratio"] = round(operating_liab / total_liab * 100, 1)

    if interest_bearing > 0:
        summary["interest_bearing_ratio"] = round(
            interest_bearing / total_liab * 100, 1
        )

    # 负债跳升原因判断
    debt = summary.get("debt_ratio") or 0
    if debt > 55 and (summary.get("operating_liab_ratio") or 0) > 70:
        summary["debt_jump_note"] = (
            f"负债率{debt:.1f}%偏高，但{summary['operating_liab_ratio']:.0f}%为经营性负债"
            f"（预收/合同负债），有息负债占比低，实际风险可控"
        )
    elif debt > 55 and (summary.get("interest_bearing_ratio") or 0) > 30:
        summary["debt_jump_note"] = (
            f"负债率{debt:.1f}%偏高，且有息负债占比{summary['interest_bearing_ratio']:.0f}%"
            f"，需关注偿债压力"
        )


def _classify_cashflow_type(ocf: float, icf: float, fcf_cf: float | None) -> dict:
    """
    三大现金流判型（8种类型）

    iFinD 第四层要求: 先判定公司现金流类型，再深入分析。
    经营(+)投资(-)筹资(-) = 奶牛型（最健康）
    经营(+)投资(-)筹资(+) = 扩张型（关注回报率）
    经营(-)投资(-)筹资(+) = 烧钱型（高风险）

    支持部分判型：当筹资现金流缺失时，仅用经营+投资判型。
    """
    o = "+" if ocf > 0 else "-"
    i = "+" if icf > 0 else "-"

    if fcf_cf is not None:
        f = "+" if fcf_cf > 0 else "-"
        pattern = o + i + f

        type_map = {
            "+--": ("奶牛型", "经营造血，投资扩张，还债分红，最健康模式"),
            "+-+": ("扩张型", "经营造血+融资输血用于投资扩张，关注投资回报率"),
            "+++": ("全正型", "三大现金流均为正，可能是收缩投资+大量融资"),
            "++-": ("投资收缩型", "经营造血，回收投资，偿还债务"),
            "--+": ("烧钱型", "经营失血靠融资维持，高风险"),
            "-+-": ("转型型", "经营亏损但在收缩投资，有自救迹象"),
            "---": ("失血型", "三大现金流均为负，极度危险"),
            "-++": ("全融型", "经营亏损，靠变卖资产+融资度日"),
        }

        type_name, description = type_map.get(pattern, ("未知型", "无法判断"))
    else:
        # 部分判型：只有经营+投资现金流
        pattern = o + i + "?"
        partial_map = {
            "+-": ("偏奶牛型(部分)", "经营造血+投资扩张，筹资数据缺失，大概率健康"),
            "++": ("偏投资收缩型(部分)", "经营造血+回收投资，筹资数据缺失"),
            "--": ("偏烧钱型(部分)", "经营+投资均失血，需关注筹资能力"),
            "-+": ("偏转型型(部分)", "经营亏损但回收投资，有自救迹象"),
        }
        type_name, description = partial_map.get(
            o + i, ("未知型(部分)", "数据不足，无法判型")
        )

    result = {
        "pattern": pattern,
        "type_name": type_name,
        "description": description,
        "operating": ocf,
        "investing": icf,
    }
    if fcf_cf is not None:
        result["financing"] = fcf_cf
    return result


def _build_dupont(
    summary: dict,
    indicators: list[dict],
    balancesheet: list[dict],
    income: list[dict],
) -> None:
    """计算杜邦分析三因子: ROE = 净利率 x 资产周转率 x 权益乘数"""
    if not indicators or not balancesheet or not income:
        return

    net_margin = summary.get("net_margin")
    revenue = _safe_float(income[0].get("total_revenue"))
    total_assets = _safe_float(balancesheet[0].get("total_assets"))
    equity = _safe_float(balancesheet[0].get("total_hldr_eqy_exc_min_int"))

    if not all([net_margin, revenue, total_assets, equity]):
        return
    if revenue == 0 or equity == 0:
        return

    asset_turnover = round(revenue / total_assets, 4)
    equity_multiplier = round(total_assets / equity, 2)

    summary["dupont_net_margin"] = net_margin
    summary["dupont_asset_turnover"] = asset_turnover
    summary["dupont_equity_multiplier"] = equity_multiplier

    # 杜邦ROE验证: 净利率 * 资产周转率 * 权益乘数 = ROE
    dupont_roe = round(net_margin / 100 * asset_turnover * equity_multiplier * 100, 2)
    summary["dupont_roe_check"] = dupont_roe


def _calc_scoring_hints(summary: dict) -> dict | None:
    """按评分锚定表预计算基本面评分建议"""
    if not summary.get("roe_latest"):
        return None

    hints = {}

    # 1. ROE 盈利能力: 优先用年报ROE（解决Q1季节性问题）
    # 如果有年报ROE且最新Q1明显偏低，用年报打分
    annual_roe = summary.get("roe_annual")
    latest_roe = summary.get("roe_latest") or 0
    if annual_roe and latest_roe < annual_roe * 0.5:
        roe = annual_roe
        roe_note = f"年报ROE={annual_roe:.1f}%(Q1={latest_roe:.1f}%季节性低点)"
    else:
        roe = latest_roe
        roe_note = None

    if roe > 20:
        hints["profitability_roe"] = {"score": 10, "reason": f"ROE={roe:.1f}%,优秀"}
    elif roe > 15:
        hints["profitability_roe"] = {"score": 7, "reason": f"ROE={roe:.1f}%,良好"}
    elif roe > 10:
        hints["profitability_roe"] = {"score": 5, "reason": f"ROE={roe:.1f}%,一般"}
    elif roe > 5:
        hints["profitability_roe"] = {"score": 3, "reason": f"ROE={roe:.1f}%,偏弱"}
    else:
        hints["profitability_roe"] = {"score": 0, "reason": f"ROE={roe:.1f}%,差"}

    if roe_note:
        hints["profitability_roe"]["note"] = roe_note

    # 2. 净利率: >30%:10, 20-30%:7, 10-20%:5, 5-10%:3, <5%:0
    nm = summary.get("net_margin") or 0
    if nm > 30:
        hints["profitability_margin"] = {"score": 10, "reason": f"净利率{nm:.1f}%,优秀"}
    elif nm > 20:
        hints["profitability_margin"] = {"score": 7, "reason": f"净利率{nm:.1f}%,良好"}
    elif nm > 10:
        hints["profitability_margin"] = {"score": 5, "reason": f"净利率{nm:.1f}%,一般"}
    elif nm > 5:
        hints["profitability_margin"] = {"score": 3, "reason": f"净利率{nm:.1f}%,偏弱"}
    else:
        hints["profitability_margin"] = {"score": 0, "reason": f"净利率{nm:.1f}%,差"}

    # 3. 营收增速: >30%:10, 15-30%:7, 5-15%:5, 0-5%:3, <0%:0
    rev_yoy = summary.get("revenue_yoy") or 0
    if rev_yoy > 30:
        hints["growth_revenue"] = {"score": 10, "reason": f"营收增速{rev_yoy:.1f}%,高增长"}
    elif rev_yoy > 15:
        hints["growth_revenue"] = {"score": 7, "reason": f"营收增速{rev_yoy:.1f}%,稳健增长"}
    elif rev_yoy > 5:
        hints["growth_revenue"] = {"score": 5, "reason": f"营收增速{rev_yoy:.1f}%,温和增长"}
    elif rev_yoy > 0:
        hints["growth_revenue"] = {"score": 3, "reason": f"营收增速{rev_yoy:.1f}%,微增长"}
    else:
        hints["growth_revenue"] = {"score": 0, "reason": f"营收增速{rev_yoy:.1f}%,负增长"}

    # 4. 净利润增速: 同上
    np_yoy = summary.get("net_profit_yoy") or 0
    if np_yoy > 30:
        hints["growth_profit"] = {"score": 10, "reason": f"净利增速{np_yoy:.1f}%,高增长"}
    elif np_yoy > 15:
        hints["growth_profit"] = {"score": 7, "reason": f"净利增速{np_yoy:.1f}%,稳健增长"}
    elif np_yoy > 5:
        hints["growth_profit"] = {"score": 5, "reason": f"净利增速{np_yoy:.1f}%,温和增长"}
    elif np_yoy > 0:
        hints["growth_profit"] = {"score": 3, "reason": f"净利增速{np_yoy:.1f}%,微增长"}
    else:
        hints["growth_profit"] = {"score": 0, "reason": f"净利增速{np_yoy:.1f}%,负增长"}

    # 5. 负债率: <30%:10, 30-50%:7, 50-60%:5, 60-70%:3, >70%:0
    # P0修复: 区分有息负债 vs 经营性负债，有息负债=0时加分
    debt = summary.get("debt_ratio") or 50
    interest_debt = summary.get("interest_bearing_debt") or -1
    interest_ratio = summary.get("interest_bearing_ratio") or -1

    if debt < 30:
        base_score, base_reason = 10, f"负债率{debt:.1f}%,极安全"
    elif debt < 50:
        base_score, base_reason = 7, f"负债率{debt:.1f}%,安全"
    elif debt < 60:
        base_score, base_reason = 5, f"负债率{debt:.1f}%,一般"
    elif debt < 70:
        base_score, base_reason = 3, f"负债率{debt:.1f}%,偏高"
    else:
        base_score, base_reason = 0, f"负债率{debt:.1f}%,危险"

    # 有息负债修正: 全部为经营性负债时，安全性远高于表面负债率
    bonus = 0
    bonus_note = ""
    if interest_debt == 0:
        bonus = 5
        bonus_note = "(有息负债=0,全部为经营性负债,加分+5)"
    elif interest_ratio >= 0 and interest_ratio < 10:
        bonus = 3
        bonus_note = f"(有息负债占比仅{interest_ratio:.0f}%,加分+3)"

    final_score = min(base_score + bonus, 10)
    reason = base_reason + bonus_note
    hints["safety_debt"] = {"score": final_score, "reason": reason}

    # 6. 流动性: >2.0:10, 1.5-2.0:7, 1.0-1.5:5, 0.8-1.0:3, <0.8:0
    cr = summary.get("current_ratio") or 1
    if cr > 2.0:
        hints["safety_liquidity"] = {"score": 10, "reason": f"流动比率{cr:.2f},优秀"}
    elif cr > 1.5:
        hints["safety_liquidity"] = {"score": 7, "reason": f"流动比率{cr:.2f},良好"}
    elif cr > 1.0:
        hints["safety_liquidity"] = {"score": 5, "reason": f"流动比率{cr:.2f},一般"}
    elif cr > 0.8:
        hints["safety_liquidity"] = {"score": 3, "reason": f"流动比率{cr:.2f},偏紧"}
    else:
        hints["safety_liquidity"] = {"score": 0, "reason": f"流动比率{cr:.2f},紧张"}

    # 7. 现金流质量 (OCF/NP): >1.2:10, 0.8-1.2:7, 0.5-0.8:5, 0.2-0.5:3, <0.2:0
    ocf_np = summary.get("ocf_to_np_ratio") or 0
    if ocf_np > 1.2:
        hints["cashflow_quality"] = {"score": 10, "reason": f"现金流质量{ocf_np:.2f},优秀"}
    elif ocf_np > 0.8:
        hints["cashflow_quality"] = {"score": 7, "reason": f"现金流质量{ocf_np:.2f},良好"}
    elif ocf_np > 0.5:
        hints["cashflow_quality"] = {"score": 5, "reason": f"现金流质量{ocf_np:.2f},一般"}
    elif ocf_np > 0.2:
        hints["cashflow_quality"] = {"score": 3, "reason": f"现金流质量{ocf_np:.2f},偏弱"}
    else:
        hints["cashflow_quality"] = {"score": 0, "reason": f"现金流质量{ocf_np:.2f},差"}

    # P2: PEG 预计算 = PE(由外部提供) / 净利润增速
    # 这里只预计算增速部分，PE 部分留给 get_daily_basic
    np_yoy_val = summary.get("net_profit_yoy") or 0
    if np_yoy_val > 0:
        hints["peg_hint"] = {
            "profit_growth": round(np_yoy_val, 1),
            "note": f"PEG = PE_TTM / {np_yoy_val:.1f}%, PEG<1偏便宜, PEG>2偏贵",
        }

    # P2: 轻资产标记传递给 scoring_hints
    if summary.get("asset_type") == "light_asset":
        hints["light_asset_note"] = summary.get("asset_type_note", "")

    return hints


def _safe_float(val) -> float | None:
    """安全转换为浮点数"""
    if val is None:
        return None
    try:
        v = float(val)
        return round(v, 2)
    except (ValueError, TypeError):
        return None


def _trend(current, previous) -> str:
    """比较两期数据，判断趋势"""
    c = _safe_float(current)
    p = _safe_float(previous)
    if c is None or p is None:
        return "unknown"
    if c > p * 1.05:
        return "improving"
    elif c < p * 0.95:
        return "declining"
    else:
        return "stable"


def _trend_yoy(indicators: list[dict], field: str) -> str:
    """判断增速的趋势（加速/稳定/减速）"""
    vals = []
    for ind in indicators[:3]:  # 最近 3 期
        v = _safe_float(ind.get(field))
        if v is not None:
            vals.append(v)
    if len(vals) < 2:
        return "unknown"
    # 最新值 vs 上一期值
    if vals[0] > vals[1] * 1.1:
        return "accelerating"
    elif vals[0] < vals[1] * 0.9:
        return "decelerating"
    else:
        return "stable"
