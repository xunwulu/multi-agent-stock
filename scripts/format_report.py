"""
将 E2E 测试结果格式化为可阅读的 Markdown 文档

Usage:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    python scripts/format_report.py
"""

import json
import re
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
result_path = os.path.join(project_root, "output", "full_e2e", "result.json")

with open(result_path, "r", encoding="utf-8") as f:
    data = json.load(f)

output = []

# ====== HEADER ======
output.append("# 同花顺(300033.SZ) 多智能体完整分析报告")
output.append("")
output.append("> 分析时间: 2026-05-08 | 总耗时: 365秒 (约6分钟)")
output.append("> 智能体: 技术分析师 + 基本面分析师 + 看多辩论者 + 看空辩论者")
output.append("")

# ====== PART 1: 综合结论 ======
combined = data["combined_report"]
output.append("---")
output.append("")
output.append("## 一、综合结论")
output.append("")
output.append(f"**综合评分**: {combined['combined_score']}分/100 | **方向**: {combined['combined_direction']}")
output.append(f"**建议**: {combined['recommendation']}")
output.append(f"**信号一致性**: {combined['alignment']} (技术面和基本面方向一致)")
output.append("")
output.append("| 维度 | 评分 | 方向 |")
output.append("|------|------|------|")
output.append(f"| 技术面 | {combined['tech_score']} | {combined['tech_direction']} |")
output.append(f"| 基本面 | {combined['fund_score']} | {combined['fund_direction']} |")
if combined.get("debate_winner"):
    output.append(f"| 辩论调整 | {combined['debate_delta']:+d} | {combined['debate_winner']}胜 |")
output.append("")

# ====== PART 2: 技术面 ======
tech_jd = data["tech_report"]["json_data"]
output.append("---")
output.append("")
output.append("## 二、技术面分析 (77分/看多)")
output.append("")
output.append(f"**短期趋势**: {tech_jd.get('short_term_trend', 'N/A')}")
output.append(f"**中期趋势**: {tech_jd.get('mid_term_trend', 'N/A')}")
output.append(f"**长期趋势**: {tech_jd.get('long_term_trend', 'N/A')}")
output.append(f"**趋势综合**: {tech_jd.get('trend', 'N/A')}")
output.append("")

# 关键价位
output.append("### 关键价位")
output.append("")
output.append(f"- 强支撑: {tech_jd.get('strong_support')} | 弱支撑: {tech_jd.get('weak_support')}")
output.append(f"- 弱压力: {tech_jd.get('weak_resistance')} | 强压力: {tech_jd.get('strong_resistance')}")
output.append(f"- 止损价: {tech_jd.get('stop_loss_price')} | 目标价: {tech_jd.get('target_price')}")
output.append(f"- 风险收益比: {tech_jd.get('risk_reward_ratio')}")
output.append("")

# 信号汇总
output.append("### 技术信号汇总")
output.append("")
output.append("| 指标 | 信号 | 背离/备注 |")
output.append("|------|------|-----------|")
signal_items = [
    ("MACD", tech_jd.get("macd_signal"), tech_jd.get("macd_divergence")),
    ("KDJ", tech_jd.get("kdj_signal"), tech_jd.get("kdj_divergence")),
    ("RSI", tech_jd.get("rsi_signal"), tech_jd.get("rsi_divergence")),
    ("均线形态", tech_jd.get("ma_pattern"), ""),
    ("成交量", tech_jd.get("volume_signal"), ""),
    ("换手率", tech_jd.get("turnover_signal"), ""),
    ("资金流向", tech_jd.get("money_flow_signal"), ""),
    ("相对强度", tech_jd.get("relative_strength"), ""),
]
for name, sig, div in signal_items:
    div_str = div if div and div != "none" else "-"
    output.append(f"| {name} | {sig} | {div_str} |")
output.append("")

# 资金流向详情
mf_summary = tech_jd.get("money_flow_summary", "")
if mf_summary:
    output.append(f"**资金流向详情**: {mf_summary}")
    output.append("")

# K线形态
kline = tech_jd.get("kline_patterns", [])
if kline:
    output.append("**K线形态**: " + " | ".join(str(p) for p in kline))
    output.append("")

# 共振信号
output.append(f"**多指标共振**: {tech_jd.get('resonance', 'N/A')}")
output.append(f"**周线/日线信号**: {tech_jd.get('weekly_signal', 'N/A')}")
output.append("")

# 行业对比
ind_comp = tech_jd.get("industry_comparison", "")
if ind_comp:
    output.append(f"**行业对比**: {ind_comp}")
    output.append("")

# 情景分析
scenario = tech_jd.get("scenario_analysis", {})
if scenario:
    output.append("### 情景分析")
    output.append("")
    output.append("| 情景 | 目标价 | 概率 | 触发条件 |")
    output.append("|------|--------|------|----------|")
    for key in ["bullish", "base", "bearish"]:
        s = scenario.get(key, {})
        if s:
            output.append(
                f"| {key} | {s.get('target_price', 'N/A')} | "
                f"{s.get('probability', 'N/A')}% | "
                f"{s.get('trigger', 'N/A')} |"
            )
    output.append("")

# 失败条件
failure = tech_jd.get("failure_conditions", [])
if failure:
    output.append("### 失败条件 (看空弹药)")
    output.append("")
    for fc in failure:
        if isinstance(fc, dict):
            output.append(f"- **条件**: {fc.get('condition', 'N/A')}")
            output.append(f"  **行动**: {fc.get('action', 'N/A')}")
        else:
            output.append(f"- {fc}")
    output.append("")

# 评分明细
breakdown = tech_jd.get("scoring_breakdown", {})
if breakdown:
    output.append("### 评分明细")
    output.append("")
    output.append("| 评分项 | 得分 |")
    output.append("|--------|------|")
    for k, v in breakdown.items():
        output.append(f"| {k} | {v} |")
    output.append(f"| **总分** | **{sum(breakdown.values())}** |")
    output.append("")

# 关键观察
obs = tech_jd.get("key_observations", [])
if obs:
    output.append("### 关键观察 (Top 5)")
    output.append("")
    for o in obs:
        output.append(f"- {o}")
    output.append("")

# 技术面总结
tech_summary = tech_jd.get("summary", "")
if tech_summary:
    output.append(f"**技术面总结**: {tech_summary}")
    output.append("")

# ====== PART 3: 基本面 ======
fund_jd = data["fund_report"]["json_data"]
output.append("---")
output.append("")
output.append(f"## 三、基本面分析 ({fund_jd.get('score', 'N/A')}分/{fund_jd.get('verdict', 'N/A')})")
output.append("")

# 商业模式
biz = fund_jd.get("business_model", "")
if biz:
    output.append(f"**商业模式**: {biz}")
    output.append("")

# 盈利能力
output.append("### 盈利能力")
output.append("")
output.append(f"- ROE(最新季): {fund_jd.get('roe_latest')}% | ROE(年报): {fund_jd.get('roe_annual')}%")
output.append(f"- ROE趋势: {fund_jd.get('roe_trend')}")
output.append(f"- 毛利率: {fund_jd.get('gross_margin')} | 净利率: {fund_jd.get('net_margin')}")
output.append(f"- 费用泄漏: {fund_jd.get('expense_leakage', 'N/A')}")
output.append(f"- 杜邦分析: {fund_jd.get('dupont_analysis', 'N/A')}")
output.append("")

# 成长性
output.append("### 成长性")
output.append("")
output.append(f"- 营收增速: {fund_jd.get('revenue_yoy')}% | 趋势: {fund_jd.get('revenue_trend')}")
output.append(f"- 净利增速: {fund_jd.get('net_profit_yoy')}% | 趋势: {fund_jd.get('profit_trend')}")
output.append(f"- 扣非占比: {fund_jd.get('deducted_profit_ratio', 'N/A')}")
output.append(f"- 增长归因: {fund_jd.get('growth_attribution', 'N/A')}")
output.append("")

# 安全性
output.append("### 安全性")
output.append("")
output.append(f"- 负债率: {fund_jd.get('debt_ratio')}%")
output.append(f"- 负债结构: {fund_jd.get('debt_structure', 'N/A')}")
output.append(f"- 流动比率: {fund_jd.get('current_ratio')}")
output.append(f"- 经营现金流/净利润: {fund_jd.get('ocf_to_np_ratio')}")
output.append(f"- 自由现金流: {fund_jd.get('free_cash_flow', 'N/A')}亿")
output.append(f"- FCF利润率: {fund_jd.get('fcf_margin', 'N/A')}")
output.append(f"- 现金流类型: {fund_jd.get('cashflow_type', 'N/A')}")
output.append(f"- 质押风险: {fund_jd.get('pledge_risk')}")
output.append("")

# 估值
output.append("### 估值")
output.append("")
output.append(f"- PE(TTM): {fund_jd.get('pe_ttm')} | 百分位: {fund_jd.get('pe_percentile')}%")
output.append(f"- PB: {fund_jd.get('pb')} | 百分位: {fund_jd.get('pb_percentile')}%")
output.append(f"- PEG: {fund_jd.get('peg', 'N/A')}")
output.append(f"- 估值概述: {fund_jd.get('valuation_summary', 'N/A')}")
output.append("")

# DCF
dcf = fund_jd.get("dcf_cross_check", {})
if dcf:
    output.append("### DCF估值交叉验证")
    output.append("")
    if isinstance(dcf, dict):
        for dk, dv in dcf.items():
            output.append(f"- {dk}: {dv}")
    output.append("")

# 股东结构
output.append("### 股东结构")
output.append("")
output.append(f"- 股东户数变化: {fund_jd.get('holder_num_change_pct')}% | 趋势: {fund_jd.get('holder_trend')}")
output.append(f"- 机构持仓数: {fund_jd.get('institutional_holders')}家 | 比例: {fund_jd.get('institutional_ratio')}%")
output.append(f"- 内部人信号: {fund_jd.get('insider_signal')} | {fund_jd.get('insider_note', '')}")
output.append("")

# 行业对比
industry = fund_jd.get("industry_analysis", {})
if industry and isinstance(industry, dict):
    output.append("### 行业对比")
    output.append("")
    for ik, iv in industry.items():
        output.append(f"- **{ik}**: {iv}")
    output.append("")

# 情景分析
fund_scenario = fund_jd.get("scenario_analysis", {})
if fund_scenario:
    output.append("### 情景分析")
    output.append("")
    output.append("| 情景 | 营收增速 | 净利增速 | EPS预测 | 目标价 | 关键驱动 |")
    output.append("|------|---------|---------|---------|--------|----------|")
    for key in ["bull", "base", "bear"]:
        s = fund_scenario.get(key, {})
        if s:
            output.append(
                f"| {key} | {s.get('revenue_yoy', 'N/A')} | "
                f"{s.get('net_profit_yoy', 'N/A')} | "
                f"{s.get('eps_estimate', 'N/A')} | "
                f"{s.get('target_price', 'N/A')} | "
                f"{s.get('key_driver', 'N/A')} |"
            )
    output.append("")

# 目标价
target = fund_jd.get("target_price", {})
if target and isinstance(target, dict):
    output.append("### 概率加权目标价")
    output.append("")
    output.append(f"- 目标价: {target.get('value', 'N/A')}元")
    output.append(f"- 当前价: {target.get('current_price', 'N/A')}元")
    output.append(f"- 上涨空间: {target.get('potential_upside_pct', 'N/A')}%")
    output.append(f"- 计算方式: {target.get('weighted_calculation', 'N/A')}")
    output.append("")

# 核心优势与风险
strengths = fund_jd.get("key_strengths", [])
if strengths:
    output.append("### 核心优势")
    output.append("")
    for s in strengths:
        output.append(f"- {s}")
    output.append("")

risks = fund_jd.get("key_risks", [])
if risks:
    output.append("### 核心风险")
    output.append("")
    for r in risks:
        output.append(f"- {r}")
    output.append("")

# 跨层矛盾
cross = fund_jd.get("cross_layer_notes", "")
if cross:
    output.append("### 跨层矛盾 (多维度交叉验证)")
    output.append("")
    output.append(cross)
    output.append("")

# 评分明细
fund_breakdown = fund_jd.get("scoring_breakdown", {})
if fund_breakdown:
    output.append("### 评分明细")
    output.append("")
    output.append("| 评分项 | 得分 |")
    output.append("|--------|------|")
    for k, v in fund_breakdown.items():
        output.append(f"| {k} | {v} |")
    output.append(f"| **总分** | **{sum(fund_breakdown.values())}** |")
    output.append("")

# 关键观察
fund_obs = fund_jd.get("key_observations", [])
if fund_obs:
    output.append("### 关键观察 (Top 5)")
    output.append("")
    for o in fund_obs:
        output.append(f"- {o}")
    output.append("")

# 基本面总结
fund_summary = fund_jd.get("summary", "")
if fund_summary:
    output.append(f"**基本面总结**: {fund_summary}")
    output.append("")

# ====== PART 4: 辩论 ======
output.append("---")
output.append("")
output.append("## 四、多空辩论 (2轮)")
output.append("")

debate = data.get("debate_result", {})
output.append(f"> 辩论耗时: {debate.get('duration_ms', 0)/1000:.0f}秒 | 消息数: {debate.get('total_messages', 0)}")
output.append(
    f"> 辩论结果: 看多方胜出 "
    f"(delta={combined.get('debate_delta', 'N/A'):+d}, "
    f"看多独有论据={combined.get('debate_bull_unique_points', 'N/A')}, "
    f"看空独有论据={combined.get('debate_bear_unique_points', 'N/A')})"
)
output.append("")

# Debate rounds
rounds = debate.get("rounds", [])
for r in rounds:
    bull_content = r.get("bull", {}).get("content", "")
    bear_content = r.get("bear", {}).get("content", "")

    # Clean up: remove "[Round N] xxx:" prefix
    bull_clean = re.sub(r"^\[Round \d+\]\s*[^：:]+[：:]\s*", "", bull_content).strip()
    bear_clean = re.sub(r"^\[Round \d+\]\s*[^：:]+[：:]\s*", "", bear_content).strip()

    output.append(f"### Round {r['round']} -- 看多分析师")
    output.append("")
    output.append(bull_clean)
    output.append("")

    output.append(f"### Round {r['round']} -- 看空分析师")
    output.append("")
    output.append(bear_clean)
    output.append("")

# Info gain table
output.append("### 信息增益追踪")
output.append("")
output.append("| 轮次 | 角色 | 总引用数字 | 新增数字 | 累计 |")
output.append("|------|------|-----------|---------|------|")
seen = set()
for r in rounds:
    for side in ["bull", "bear"]:
        content = r.get(side, {}).get("content", "")
        numbers = set(re.findall(r"\d+\.?\d*", content))
        new_nums = numbers - seen
        seen.update(numbers)
        role = "Bull" if side == "bull" else "Bear"
        output.append(f"| R{r['round']} | {role} | {len(numbers)} | {len(new_nums)} | {len(seen)} |")
output.append("")

# Write to file
formatted = "\n".join(output)
out_path = os.path.join(project_root, "output", "full_e2e", "full_report.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(formatted)

print(f"Formatted report saved to: {out_path}")
print(f"Total: {len(output)} lines, {len(formatted)} chars")
