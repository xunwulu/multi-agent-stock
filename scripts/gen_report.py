"""
Generate full readable report from result.json
Usage: python scripts/gen_report.py [result_json_path]
"""
import sys
import json
import os

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
default_path = os.path.join(project_root, "output", "full_e2e", "result.json")

result_path = sys.argv[1] if len(sys.argv) > 1 else default_path

with open(result_path, "r", encoding="utf-8") as f:
    r = json.load(f)

tech = r["tech_report"]
fund = r["fund_report"]
debate = r.get("debate_result", {})
combined = r.get("combined_report", {})
state = r.get("state", {})
trader = combined.get("trader", {})

lines = []


def w(s=""):
    lines.append(s)


# ===================== Header =====================
w("# 603588.SH 高能环境 — 全流程分析报告（完整版）")
w()
w(
    f"> 生成时间: {state.get('created_at', 'N/A')} | "
    f"总耗时: {r.get('duration_ms', 0) / 1000:.0f}秒"
    f"({r.get('duration_ms', 0) / 1000 / 60:.1f}分钟)"
)
w()
w("---")
w()

# ===================== 一、技术面分析师 =====================
tech_jd = tech.get("json_data", {})
w("## 一、技术面分析师（完整输出）")
w()
w(
    f"> 得分: **{tech_jd.get('score', 'N/A')} / 100** | "
    f"方向: **{tech_jd.get('direction', 'N/A')}** | "
    f"迭代{tech.get('iterations', 0)}次 | "
    f"工具调用{tech.get('tool_calls', 0)}次 | "
    f"耗时{tech.get('duration_ms', 0) / 1000:.0f}秒"
)
w()
w("### 原始分析内容")
w()
content = tech.get("content", "")
# Strip leading boilerplate
idx = content.find("# ")
if idx > 0:
    content = content[idx:]
w(content)
w()
w("---")
w()

# ===================== 二、基本面分析师 =====================
fund_jd = fund.get("json_data", {})
w("## 二、基本面分析师（完整输出）")
w()
w(
    f"> 得分: **{fund_jd.get('score', 'N/A')} / 100** | "
    f"方向: **{fund_jd.get('verdict', 'N/A')}** | "
    f"迭代{fund.get('iterations', 0)}次 | "
    f"工具调用{fund.get('tool_calls', 0)}次 | "
    f"耗时{fund.get('duration_ms', 0) / 1000:.0f}秒"
)
w()
w("### 原始分析内容")
w()
content = fund.get("content", "")
idx = content.find("# ")
if idx > 0:
    content = content[idx:]
w(content)
w()
w("---")
w()

# ===================== 三、辩论 =====================
w("## 三、辩论（完整记录）")
w()
w(
    f"> 轮次: {debate.get('rounds_completed', 0)} | "
    f"消息数: {debate.get('total_messages', 0)} | "
    f"耗时{debate.get('duration_ms', 0) / 1000:.0f}秒"
)
w()
w("### 辩论完整记录")
w()
w(debate.get("transcript", "无数据"))
w()
w("---")
w()

# ===================== 四、综合报告 =====================
w("## 四、综合报告（Research Manager）")
w()

w("### 评分与权重")
w()
w("| 项目 | 值 |")
w("|------|-----|")
w(f"| 综合评分 | **{combined.get('combined_score', 'N/A')}** |")
w(f"| 综合方向 | **{combined.get('combined_direction', 'N/A')}** |")
w(f"| 股票类型 | **{combined.get('stock_type', 'N/A')}** |")
w(
    f"| 技术面(权重60%) | {combined.get('tech_score', 'N/A')} "
    f"({combined.get('tech_direction', 'N/A')}) |"
)
w(
    f"| 基本面(权重40%) | {combined.get('fund_score', 'N/A')} "
    f"({combined.get('fund_direction', 'N/A')}) |"
)
w(
    f"| 辩论胜方 | {combined.get('debate_winner', 'N/A')} "
    f"(delta={combined.get('debate_delta', 'N/A')}) |"
)
w(f"| 方向一致性 | {combined.get('alignment', 'N/A')} |")
w(f"| 权重依据 | {combined.get('weight_rationale', 'N/A')} |")
w()

# Tech scoring breakdown
w("### 评分明细")
w()
tech_sb = combined.get("tech_scoring_breakdown", {})
if tech_sb:
    w("**技术面评分明细:**")
    w()
    w("| 评分项 | 得分 | 满分 |")
    w("|--------|------|------|")
    for k, v in tech_sb.items():
        w(f"| {k} | {v} | 10 |")
    tech_total = sum(v for v in tech_sb.values() if isinstance(v, (int, float)))
    w(f"| **合计** | **{tech_total}** | **{len(tech_sb) * 10}** |")
    w()

fund_sb = combined.get("fund_scoring_breakdown", {})
if fund_sb:
    w("**基本面评分明细:**")
    w()
    w("| 评分项 | 得分 | 依据 |")
    w("|--------|------|------|")
    for k, v in fund_sb.items():
        if isinstance(v, dict):
            w(f"| {k} | {v.get('score', v)} | {v.get('reason', '')} |")
        else:
            w(f"| {k} | {v} | |")
    w()

w("### 综合摘要")
w()
w(combined.get("summary", "无"))
w()

w("### 推荐意见")
w()
w(combined.get("recommendation", "无"))
w()

# Key observations
tech_obs = combined.get("tech_key_observations", [])
if tech_obs:
    w("### 技术面关键观察")
    w()
    for i, obs in enumerate(tech_obs, 1):
        w(f"{i}. {obs}")
    w()

fund_str = combined.get("fund_key_strengths", [])
if fund_str:
    w("### 基本面优势")
    w()
    for i, s in enumerate(fund_str, 1):
        w(f"{i}. {s}")
    w()

fund_risk = combined.get("fund_key_risks", [])
if fund_risk:
    w("### 基本面风险")
    w()
    for i, s in enumerate(fund_risk, 1):
        w(f"{i}. {s}")
    w()

# Debate details
w("### 辩论详情")
w()
w(
    f"- 胜方: **{combined.get('debate_winner', 'N/A')}** "
    f"(delta={combined.get('debate_delta', 'N/A')})"
)
w(f"- 裁决理由: {combined.get('debate_rationale', 'N/A')}")
w(f"- 最强看多论点: {combined.get('strongest_bull_point', 'N/A')}")
w(f"- 最强看空论点: {combined.get('strongest_bear_point', 'N/A')}")
w()
w("#### 看多方论点")
w()
w(combined.get("bull_arguments", "无"))
w()
w("#### 看空方论点")
w()
w(combined.get("bear_arguments", "无"))
w()

risks = combined.get("risk_warnings", [])
if risks:
    w("### 风险提示")
    w()
    for i, risk in enumerate(risks, 1):
        w(f"{i}. {risk}")
    w()

w("---")
w()

# ===================== 五、交易员 =====================
w("## 五、交易员 (Trader)")
w()
if trader:
    w(
        f"> 操作: **{trader.get('action', 'N/A')}** | "
        f"强度: **{trader.get('action_strength', 'N/A')}**"
    )
    w()
    w("### 核心决策")
    w()
    w("| 项目 | 值 |")
    w("|------|-----|")
    w(f"| 操作 | **{trader.get('action', 'N/A')}** |")
    w(f"| 强度 | {trader.get('action_strength', 'N/A')} |")
    w(f"| 目标价 | **{trader.get('target_price', 'N/A')}元** |")
    w(f"| 止损价 | **{trader.get('stop_loss', 'N/A')}元** |")
    w(f"| 当前价 | 14.77元 |")
    w(
        f"| 置信度 | **{trader.get('confidence_total', 'N/A')} "
        f"({trader.get('confidence_label', 'N/A')})** |"
    )
    w(
        f"| 仓位建议 | {trader.get('position_advice', 'N/A')} "
        f"({trader.get('position_range', 'N/A')}) |"
    )
    w(
        f"| 风险评分 | **{trader.get('risk_score', 'N/A')} "
        f"({trader.get('risk_level', 'N/A')})** |"
    )
    w(f"| 时间框架 | {trader.get('time_horizon', 'N/A')} |")
    w()

    cc = trader.get("confidence_components", {})
    if cc:
        w("### 置信度组件")
        w()
        w("| 维度 | 得分 | 满分 | 说明 |")
        w("|------|------|------|------|")
        desc_map = {
            "signal_consistency": "信号一致性",
            "data_sufficiency": "数据充分性",
            "debate_certainty": "辩论确定性",
            "risk_controllability": "风险可控性",
            "valuation_reasonableness": "估值合理性",
        }
        for k, v in cc.items():
            w(f"| {desc_map.get(k, k)} | {v} | 20 | |")
        w(
            f"| **合计** | **{trader.get('confidence_total', 0)}** "
            f"| **100** | |"
        )
        w()

    tp = trader.get("take_profit_levels", [])
    if tp:
        w("### 止盈层级")
        w()
        w("| 价格 | 比例 | 理由 |")
        w("|------|------|------|")
        for t in tp:
            w(
                f"| {t.get('price', 'N/A')} | "
                f"{t.get('portion', 'N/A')} | "
                f"{t.get('reason', 'N/A')} |"
            )
        w()

    w("### 目标价理由")
    w()
    w(trader.get("target_price_rationale", "无"))
    w()

    w("### 止损理由")
    w()
    w(trader.get("stop_loss_rationale", "无"))
    w()

    ec = trader.get("entry_conditions", [])
    if ec:
        w("### 入场条件")
        w()
        for i, c in enumerate(ec, 1):
            w(f"{i}. {c}")
        w()

    kc = trader.get("key_catalysts", [])
    if kc:
        w("### 关键催化剂")
        w()
        for i, c in enumerate(kc, 1):
            w(f"{i}. {c}")
        w()

    w("### 决策推理")
    w()
    w(trader.get("reasoning", "无"))
    w()

    tw = trader.get("warnings", [])
    if tw:
        w("### 警告")
        w()
        for i, wa in enumerate(tw, 1):
            w(f"{i}. {wa}")
        w()
else:
    w("> 交易员数据缺失")
    w()

w("---")
w()

# ===================== 六、数据新鲜度 =====================
w("## 六、数据新鲜度")
w()
tf = combined.get("tech_data_freshness", {})
if tf:
    w("**技术面:**")
    w()
    for k, v in tf.items():
        w(f"- {k}: {v}")
    w()

ff = combined.get("fund_data_freshness", {})
if ff:
    w("**基本面:**")
    w()
    for k, v in ff.items():
        w(f"- {k}: {v}")
    w()

# ===================== 七、Token 统计 =====================
w("---")
w()
w("## 七、Token 使用统计")
w()
tech_tok = tech.get("token_usage", {})
fund_tok = fund.get("token_usage", {})
if tech_tok:
    w(
        f"**技术面:** input={tech_tok.get('total_input', 0)}, "
        f"output={tech_tok.get('total_output', 0)}, "
        f"total={tech_tok.get('total_tokens', 0)}"
    )
if fund_tok:
    w(
        f"**基本面:** input={fund_tok.get('total_input', 0)}, "
        f"output={fund_tok.get('total_output', 0)}, "
        f"total={fund_tok.get('total_tokens', 0)}"
    )
w()

# ===================== Write =====================
output = "\n".join(lines)
outpath = os.path.join(os.path.dirname(result_path), "report_603588_full.md")
with open(outpath, "w", encoding="utf-8") as f:
    f.write(output)

print(f"Report written: {len(lines)} lines, {len(output)} chars -> {outpath}")
