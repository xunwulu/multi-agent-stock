"""
Generate shareable HTML report from result.json
Supports single file or batch directory mode.

Usage:
    python scripts/gen_html_report.py output/batch_test/result_300308_SZ.json
    python scripts/gen_html_report.py output/batch_test/          # batch mode
"""
import sys
import json
import os
import html as html_lib
import glob

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def esc(s):
    if s is None:
        return ""
    return html_lib.escape(str(s))


def score_bar(score, max_val=100):
    pct = min(score / max_val * 100, 100) if max_val > 0 else 0
    if score >= max_val * 0.7:
        color = "#22c55e"
    elif score >= max_val * 0.5:
        color = "#eab308"
    elif score >= max_val * 0.3:
        color = "#f97316"
    else:
        color = "#ef4444"
    return (
        f'<div class="score-bar">'
        f'<div class="score-bar-track">'
        f'<div class="score-bar-fill" style="width:{pct}%;background:{color}"></div>'
        f"</div>"
        f'<span class="score-bar-value" style="color:{color}">{score}/{max_val}</span>'
        f"</div>"
    )


def direction_badge(direction):
    colors = {
        "bullish": ("#22c55e", "#dcfce7", "看多"),
        "bearish": ("#ef4444", "#fee2e2", "看空"),
        "neutral": ("#eab308", "#fef9c3", "中性"),
        "buy": ("#22c55e", "#dcfce7", "买入"),
        "sell": ("#ef4444", "#fee2e2", "卖出"),
        "hold": ("#eab308", "#fef9c3", "持有"),
    }
    fg, bg, label = colors.get(direction, ("#6b7280", "#f3f4f6", direction))
    return f'<span class="badge" style="color:{fg};background:{bg}">{label}</span>'


def risk_badge(score):
    if score >= 70:
        fg, bg, label = "#ef4444", "#fee2e2", "极高风险"
    elif score >= 50:
        fg, bg, label = "#f97316", "#fff7ed", "高风险"
    elif score >= 30:
        fg, bg, label = "#eab308", "#fef9c3", "中等风险"
    else:
        fg, bg, label = "#22c55e", "#dcfce7", "低风险"
    return f'<span class="badge" style="color:{fg};background:{bg}">{label} ({score})</span>'


def md_table_to_html(table_text):
    lines = [l.strip() for l in table_text.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return f"<p>{esc(table_text)}</p>"
    header_cells = [c.strip() for c in lines[0].split("|") if c.strip()]
    data_lines = [l for l in lines[1:] if not all(c in "-|: " for c in l)]
    h = '<table class="data-table"><thead><tr>'
    for c in header_cells:
        h += f"<th>{esc(c)}</th>"
    h += "</tr></thead><tbody>"
    for line in data_lines:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        h += "<tr>"
        for c in cells:
            text = esc(c).replace("**", "")
            h += f"<td>{text}</td>"
        h += "</tr>"
    h += "</tbody></table>"
    return h


def format_content(content):
    lines = content.split("\n")
    html_parts = []
    in_table = False
    table_buffer = []
    for line in lines:
        stripped = line.strip()
        if "|" in stripped and stripped.startswith("|"):
            if not in_table:
                in_table = True
                table_buffer = []
            table_buffer.append(stripped)
            continue
        else:
            if in_table:
                html_parts.append(md_table_to_html("\n".join(table_buffer)))
                in_table = False
                table_buffer = []
        if stripped.startswith("#### "):
            html_parts.append(f"<h5>{esc(stripped[5:])}</h5>")
        elif stripped.startswith("### "):
            html_parts.append(f"<h4>{esc(stripped[4:])}</h4>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h3>{esc(stripped[3:])}</h3>")
        elif stripped.startswith("# "):
            html_parts.append(f"<h2>{esc(stripped[2:])}</h2>")
        elif stripped == "---":
            html_parts.append("<hr>")
        elif stripped.startswith("```"):
            continue
        elif stripped == "":
            html_parts.append("")
        elif stripped.startswith("> "):
            text = esc(stripped[2:]).replace("**", "")
            html_parts.append(f"<blockquote><p>{text}</p></blockquote>")
        elif stripped.startswith("- "):
            text = esc(stripped[2:])
            text = text.replace("**", "<strong>").replace("**", "</strong>")
            html_parts.append(
                f'<div class="list-item"><span class="bullet">&#8226;</span> {text}</div>'
            )
        else:
            text = esc(stripped)
            text = text.replace("**", "<strong>").replace("**", "</strong>")
            html_parts.append(f"<p>{text}</p>")
    if in_table:
        html_parts.append(md_table_to_html("\n".join(table_buffer)))
    return "\n".join(html_parts)


def generate_html(result_path: str) -> str:
    """Generate HTML string from a result.json file."""
    with open(result_path, "r", encoding="utf-8") as f:
        r = json.load(f)

    tech = r.get("tech_report", {})
    fund = r.get("fund_report", {})
    news = r.get("news_report", {})
    debate = r.get("debate_result", {})
    combined = r.get("combined_report", {})
    state = r.get("state", {})
    trader = combined.get("trader", {})
    tech_jd = tech.get("json_data", {}) or {}
    fund_jd = fund.get("json_data", {}) or {}
    news_jd = news.get("json_data", {}) or {}
    has_news = bool(news_jd and news_jd.get("score") is not None)

    # Extract content
    tech_content = tech.get("content", "")
    idx = tech_content.find("# ")
    if idx > 0:
        tech_content = tech_content[idx:]

    fund_content = fund.get("content", "")
    idx = fund_content.find("# ")
    if idx > 0:
        fund_content = fund_content[idx:]

    # Scoring breakdown
    tech_sb = combined.get("tech_scoring_breakdown", {})
    fund_sb = combined.get("fund_scoring_breakdown", {})

    tech_sb_rows = ""
    tech_total = 0
    for k, v in tech_sb.items():
        tech_total += v if isinstance(v, (int, float)) else 0
        tech_sb_rows += f"<tr><td>{esc(k)}</td><td>{v}</td><td>{score_bar(v, 10)}</td></tr>"

    fund_sb_rows = ""
    fund_total = 0
    for k, v in fund_sb.items():
        sv = v.get("score", v) if isinstance(v, dict) else v
        fund_total += sv if isinstance(sv, (int, float)) else 0
        fund_sb_rows += f"<tr><td>{esc(k)}</td><td>{sv}</td><td>{score_bar(sv, 10)}</td></tr>"

    # News scoring breakdown
    news_sb = combined.get("news_scoring_breakdown", {})
    news_sb_rows = ""
    news_total = 0
    for k, v in news_sb.items():
        news_total += v if isinstance(v, (int, float)) else 0
        news_sb_rows += f"<tr><td>{esc(k)}</td><td>{v}</td><td>{score_bar(v, 10)}</td></tr>"

    # News key events
    news_events_html = ""
    for e in combined.get("news_key_events", []):
        if isinstance(e, dict):
            news_events_html += (
                f'<div class="list-item"><span class="bullet">&#8226;</span> '
                f'{esc(e.get("event",""))} '
                f'({esc(e.get("type",""))} | {esc(e.get("direction",""))} | {esc(e.get("impact",""))})</div>'
            )
        else:
            news_events_html += f'<div class="list-item"><span class="bullet">&#8226;</span> {esc(e)}</div>'

    # News risk events
    news_risks_html = ""
    for e in combined.get("news_risk_events", []):
        if isinstance(e, dict):
            news_risks_html += (
                f'<div class="list-item risk"><span class="icon">&#9888;</span> '
                f'{esc(e.get("event",""))} '
                f'(严重={esc(e.get("severity",""))} | 概率={esc(e.get("probability",""))})</div>'
            )
        else:
            news_risks_html += f'<div class="list-item risk"><span class="icon">&#9888;</span> {esc(e)}</div>'

    # Confidence
    cc = trader.get("confidence_components", {})
    cc_rows = ""
    desc_map = {
        "signal_consistency": "信号一致性",
        "data_sufficiency": "数据充分性",
        "debate_certainty": "辩论确定性",
        "risk_controllability": "风险可控性",
        "valuation_reasonableness": "估值合理性",
    }
    for k, v in cc.items():
        cc_rows += f"<tr><td>{esc(desc_map.get(k, k))}</td><td>{v}</td><td>{score_bar(v, 20)}</td></tr>"

    # Lists
    tech_obs_html = ""
    for obs in combined.get("tech_key_observations", []):
        text = esc(obs).lstrip("0123456789. ")
        text = text.replace("**", "<strong>").replace("**", "</strong>")
        tech_obs_html += f'<div class="list-item"><span class="bullet">&#8226;</span> {text}</div>'

    strengths_html = ""
    for s in combined.get("fund_key_strengths", []):
        strengths_html += f'<div class="list-item strength"><span class="icon">&#10003;</span> {esc(s)}</div>'

    risks_html = ""
    for s in combined.get("fund_key_risks", []):
        risks_html += f'<div class="list-item risk"><span class="icon">&#9888;</span> {esc(s)}</div>'

    risk_warn_html = ""
    for i, w in enumerate(combined.get("risk_warnings", []), 1):
        risk_warn_html += f'<div class="risk-warning-item"><span class="risk-num">{i}</span> {esc(w)}</div>'

    tw_html = ""
    for i, w in enumerate(trader.get("warnings", []), 1):
        tw_html += f'<div class="risk-warning-item"><span class="risk-num">{i}</span> {esc(w)}</div>'

    ec_html = ""
    for c in trader.get("entry_conditions", []):
        ec_html += f'<div class="list-item"><span class="bullet">&#8226;</span> {esc(c)}</div>'

    kc_html = ""
    for c in trader.get("key_catalysts", []):
        kc_html += f'<div class="list-item"><span class="bullet">&#8226;</span> {esc(c)}</div>'

    tp_html = ""
    for t in trader.get("take_profit_levels", []):
        tp_html += f'<tr><td>{t.get("price","N/A")}</td><td>{t.get("portion","N/A")}</td><td>{esc(t.get("reason",""))}</td></tr>'

    tf = combined.get("tech_data_freshness", {})
    ff = combined.get("fund_data_freshness", {})
    nf = combined.get("news_data_freshness", {})

    # Stock name resolution
    stock_code = r.get("stock_code", state.get("stock_code", "N/A"))
    stock_names = {
        "300308.SZ": "中际旭创",
        "000066.SZ": "中国长城",
        "601869.SH": "长飞光纤",
        "300326.SZ": "ST凯利",
        "600358.SH": "国旅联合",
        "603588.SH": "高能环境",
    }
    stock_name = stock_names.get(stock_code, stock_code)

    # Current price from tech data
    current_price = tech_jd.get("weak_support", "N/A")

    # Action styling
    action = trader.get("action", "hold")
    action_class = action if action in ("buy", "sell", "hold") else "hold"
    action_labels = {"buy": "买入", "sell": "卖出", "hold": "持有"}
    action_label = action_labels.get(action, action)
    action_colors = {"buy": "var(--success)", "sell": "var(--danger)", "hold": "var(--warning)"}
    action_color = action_colors.get(action, "var(--warning)")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(stock_code)} {esc(stock_name)} — AI分析报告</title>
<style>
:root {{
  --bg: #0f172a;
  --card: #1e293b;
  --card-hover: #253449;
  --border: #334155;
  --text: #e2e8f0;
  --text-muted: #94a3b8;
  --accent: #3b82f6;
  --accent-light: #60a5fa;
  --success: #22c55e;
  --warning: #eab308;
  --danger: #ef4444;
  --orange: #f97316;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.7; padding: 0;
}}
.container {{ max-width: 960px; margin: 0 auto; padding: 24px 20px; }}
.header {{
  text-align: center; padding: 40px 20px 30px;
  background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%);
  border-bottom: 1px solid var(--border); margin-bottom: 32px;
}}
.header h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 8px; }}
.header .subtitle {{ color: var(--text-muted); font-size: 14px; }}
.header .meta {{ display: flex; justify-content: center; gap: 24px; margin-top: 16px; flex-wrap: wrap; }}
.header .meta-item {{
  background: var(--card); padding: 6px 16px; border-radius: 20px;
  font-size: 13px; color: var(--text-muted); border: 1px solid var(--border);
}}
.score-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
.score-card {{
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; text-align: center; transition: transform 0.2s;
}}
.score-card:hover {{ transform: translateY(-2px); }}
.score-card .label {{ font-size: 13px; color: var(--text-muted); margin-bottom: 8px; }}
.score-card .value {{ font-size: 32px; font-weight: 700; }}
.score-card .sub {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}
.section {{
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px; margin-bottom: 24px;
}}
.section-title {{
  font-size: 20px; font-weight: 700; margin-bottom: 16px; padding-bottom: 12px;
  border-bottom: 2px solid var(--border); display: flex; align-items: center; gap: 10px;
  flex-wrap: wrap;
}}
.section-title .icon {{
  width: 32px; height: 32px; border-radius: 8px; display: flex;
  align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0;
}}
.data-table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 14px; }}
.data-table th {{
  background: rgba(59,130,246,0.1); color: var(--accent-light);
  padding: 10px 12px; text-align: left; font-weight: 600;
  border-bottom: 2px solid var(--border); font-size: 13px;
}}
.data-table td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
.data-table tr:hover td {{ background: rgba(255,255,255,0.02); }}
.data-table tr:last-child td {{ border-bottom: none; }}
.badge {{ display: inline-block; padding: 3px 12px; border-radius: 12px; font-size: 13px; font-weight: 600; }}
.score-bar {{ display: flex; align-items: center; gap: 10px; }}
.score-bar-track {{ flex: 1; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; min-width: 60px; }}
.score-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
.score-bar-value {{ font-weight: 700; font-size: 14px; min-width: 50px; }}
h3 {{ font-size: 17px; font-weight: 700; margin: 20px 0 10px; color: var(--accent-light); }}
h4 {{ font-size: 15px; font-weight: 600; margin: 16px 0 8px; }}
h5 {{ font-size: 14px; font-weight: 600; margin: 12px 0 6px; color: var(--text-muted); }}
p {{ margin: 6px 0; font-size: 14px; }}
blockquote {{
  border-left: 3px solid var(--accent); padding: 8px 16px; margin: 8px 0;
  background: rgba(59,130,246,0.05); border-radius: 0 8px 8px 0; font-size: 14px; color: var(--text-muted);
}}
.list-item {{ padding: 4px 0 4px 16px; position: relative; font-size: 14px; }}
.list-item .bullet {{ position: absolute; left: 0; color: var(--accent-light); }}
.list-item .icon {{ position: absolute; left: 0; font-weight: 700; }}
.list-item.strength .icon {{ color: var(--success); }}
.list-item.risk .icon {{ color: var(--danger); }}
hr {{ border: none; border-top: 1px solid var(--border); margin: 16px 0; }}
strong {{ color: #f1f5f9; }}
.risk-warning-item {{
  background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px; padding: 10px 14px; margin: 8px 0; font-size: 14px;
  display: flex; align-items: flex-start; gap: 10px;
}}
.risk-num {{
  background: var(--danger); color: white; width: 22px; height: 22px;
  border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; flex-shrink: 0;
}}
.debate-msg {{ margin: 16px 0; padding: 16px; border-radius: 10px; border-left: 4px solid; }}
.debate-msg.bull {{ background: rgba(34,197,94,0.06); border-color: var(--success); }}
.debate-msg.bear {{ background: rgba(239,68,68,0.06); border-color: var(--danger); }}
.debate-msg .speaker {{ font-weight: 700; font-size: 14px; margin-bottom: 8px; }}
.debate-msg.bull .speaker {{ color: var(--success); }}
.debate-msg.bear .speaker {{ color: var(--danger); }}
.action-card {{
  text-align: center; padding: 24px; border-radius: 12px; margin-bottom: 16px;
}}
.action-card.sell {{ background: linear-gradient(135deg, rgba(239,68,68,0.15), rgba(239,68,68,0.05)); border: 1px solid rgba(239,68,68,0.3); }}
.action-card.buy {{ background: linear-gradient(135deg, rgba(34,197,94,0.15), rgba(34,197,94,0.05)); border: 1px solid rgba(34,197,94,0.3); }}
.action-card.hold {{ background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(234,179,8,0.05)); border: 1px solid rgba(234,179,8,0.3); }}
.action-card .action-label {{ font-size: 36px; font-weight: 800; }}
.action-card .action-sub {{ font-size: 14px; color: var(--text-muted); margin-top: 4px; }}
details {{ margin-bottom: 8px; }}
details summary {{
  cursor: pointer; padding: 12px 16px; background: var(--card);
  border: 1px solid var(--border); border-radius: 8px;
  font-weight: 600; font-size: 15px; transition: background 0.2s;
  list-style: none; display: flex; align-items: center; gap: 8px;
}}
details summary:hover {{ background: var(--card-hover); }}
details summary::before {{ content: "\\25B6"; font-size: 10px; color: var(--text-muted); transition: transform 0.2s; }}
details[open] summary::before {{ transform: rotate(90deg); }}
details .detail-content {{ padding: 16px; border: 1px solid var(--border); border-top: none; border-radius: 0 0 8px 8px; }}
.footer {{
  text-align: center; padding: 24px; color: var(--text-muted);
  font-size: 12px; border-top: 1px solid var(--border); margin-top: 32px;
}}
@media (max-width: 640px) {{
  .container {{ padding: 16px 12px; }}
  .score-cards {{ grid-template-columns: 1fr 1fr; }}
  .header h1 {{ font-size: 22px; }}
  .section {{ padding: 16px; }}
}}
@media print {{
  body {{ background: white; color: #1a1a1a; }}
  .section {{ border: 1px solid #ddd; break-inside: avoid; }}
  .data-table th {{ background: #f0f0f0; }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>{esc(stock_code)} {esc(stock_name)}</h1>
  <div class="subtitle">AI 多智能体全流程分析报告</div>
  <div class="meta">
    <span class="meta-item">股票类型: {esc(combined.get("stock_type","N/A"))}</span>
    <span class="meta-item">生成: {esc(state.get("created_at",""))}</span>
    <span class="meta-item">耗时: {r.get("duration_ms",0)/1000:.0f}秒</span>
  </div>
</div>

<div class="container">

<!-- SCORE OVERVIEW -->
<div class="score-cards">
  <div class="score-card">
    <div class="label">综合评分</div>
    <div class="value" style="color:var(--warning)">{combined.get("combined_score","N/A")}</div>
    <div class="sub">{direction_badge(combined.get("combined_direction",""))}</div>
  </div>
  <div class="score-card">
    <div class="label">技术面 ({esc(str(60) if combined.get("stock_type")=="growth" else str(35))}%)</div>
    <div class="value" style="color:var(--warning)">{combined.get("tech_score","N/A")}</div>
    <div class="sub">{direction_badge(combined.get("tech_direction",""))}</div>
  </div>
  <div class="score-card">
    <div class="label">基本面 ({esc(str(40) if combined.get("stock_type")=="growth" else str(65))}%)</div>
    <div class="value" style="color:var(--warning)">{combined.get("fund_score","N/A")}</div>
    <div class="sub">{direction_badge(combined.get("fund_direction",""))}</div>
  </div>
  {"<div class='score-card'><div class='label'>新闻面 (15%)</div><div class='value' style='color:var(--warning)'>" + str(combined.get("news_score","N/A")) + "</div><div class='sub'>" + direction_badge(combined.get("news_direction","")) + "</div></div>" if has_news else ""}
  <div class="score-card">
    <div class="label">风险评分</div>
    <div class="value" style="color:var(--danger)">{trader.get("risk_score","N/A")}</div>
    <div class="sub">{risk_badge(trader.get("risk_score",0))}</div>
  </div>
</div>

<!-- TRADER DECISION -->
<div class="section">
  <div class="section-title">
    <span class="icon" style="background:rgba(239,68,68,0.15);color:var(--danger);">&#9879;</span>
    交易员决策
  </div>
  <div class="action-card {esc(action_class)}">
    <div class="action-label" style="color:{action_color}">{esc(action_label)}</div>
    <div class="action-sub">强度: {esc(trader.get("action_strength","N/A"))} | 置信度: {trader.get("confidence_total","N/A")}/100 | 仓位: {esc(trader.get("position_advice",""))} ({esc(trader.get("position_range",""))})</div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:16px;">
    <div style="text-align:center;">
      <h5>目标价</h5>
      <p style="font-size:20px;font-weight:700;color:var(--success)">{trader.get("target_price","N/A")}元</p>
    </div>
    <div style="text-align:center;">
      <h5>止损价</h5>
      <p style="font-size:20px;font-weight:700;color:var(--danger)">{trader.get("stop_loss","N/A")}元</p>
    </div>
    <div style="text-align:center;">
      <h5>风险收益比</h5>
      <p style="font-size:20px;font-weight:700;color:var(--warning)">{esc(tech_jd.get("risk_reward_ratio","N/A"))}</p>
    </div>
  </div>
  <p style="margin-top:12px;font-size:14px;color:var(--text-muted);">{esc(trader.get("reasoning",""))}</p>
</div>

<!-- TECH ANALYST -->
<div class="section">
  <div class="section-title">
    <span class="icon" style="background:rgba(59,130,246,0.15);color:var(--accent);">&#128200;</span>
    技术面分析
    <span style="margin-left:auto;font-size:14px;">{score_bar(combined.get("tech_score",0))} {direction_badge(combined.get("tech_direction",""))}</span>
  </div>

  <h3>趋势定位</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0;">
    <div style="background:rgba(255,255,255,0.03);padding:12px;border-radius:8px;border:1px solid var(--border);">
      <div style="font-size:12px;color:var(--text-muted);">短期 (5-10日)</div>
      <div style="font-size:15px;font-weight:600;color:var(--orange);">{esc(tech_jd.get("short_term_trend","N/A"))}</div>
    </div>
    <div style="background:rgba(255,255,255,0.03);padding:12px;border-radius:8px;border:1px solid var(--border);">
      <div style="font-size:12px;color:var(--text-muted);">中期 (20-60日)</div>
      <div style="font-size:15px;font-weight:600;color:var(--warning);">{esc(tech_jd.get("mid_term_trend","N/A"))}</div>
    </div>
    <div style="background:rgba(255,255,255,0.03);padding:12px;border-radius:8px;border:1px solid var(--border);">
      <div style="font-size:12px;color:var(--text-muted);">长期 (60-120日)</div>
      <div style="font-size:15px;font-weight:600;color:var(--success);">{esc(tech_jd.get("long_term_trend","N/A"))}</div>
    </div>
  </div>

  <h3>关键价位</h3>
  <table class="data-table">
    <thead><tr><th>类型</th><th>价位</th></tr></thead>
    <tbody>
      <tr><td>强支撑</td><td style="font-weight:700;color:var(--success)">{tech_jd.get("strong_support","N/A")}</td></tr>
      <tr><td>弱支撑</td><td style="color:var(--success)">{tech_jd.get("weak_support","N/A")}</td></tr>
      <tr><td>弱压力</td><td style="color:var(--danger)">{tech_jd.get("weak_resistance","N/A")}</td></tr>
      <tr><td>强压力</td><td style="font-weight:700;color:var(--danger)">{tech_jd.get("strong_resistance","N/A")}</td></tr>
    </tbody>
  </table>

  <h3>技术信号</h3>
  <table class="data-table">
    <thead><tr><th>指标</th><th>信号</th><th>详情</th></tr></thead>
    <tbody>
      <tr><td>MACD</td><td>{esc(str(tech_jd.get("macd_signal","N/A")))}</td><td>{esc(str(tech_jd.get("macd_divergence","N/A")))}</td></tr>
      <tr><td>KDJ</td><td>{esc(str(tech_jd.get("kdj_signal","N/A")))}</td><td>{esc(str(tech_jd.get("kdj_divergence","N/A")))}</td></tr>
      <tr><td>RSI</td><td>{esc(str(tech_jd.get("rsi_signal","N/A")))}</td><td>{esc(str(tech_jd.get("rsi_divergence","N/A")))}</td></tr>
      <tr><td>量能</td><td>{esc(str(tech_jd.get("volume_signal","N/A")))}</td><td>{esc(str(tech_jd.get("turnover_signal","N/A")))}</td></tr>
      <tr><td>资金</td><td colspan="2">{esc(str(tech_jd.get("money_flow_signal","N/A")))}</td></tr>
    </tbody>
  </table>

  <blockquote><p>{esc(tech_jd.get("money_flow_summary",""))}</p></blockquote>

  <h3>评分明细</h3>
  <table class="data-table">
    <thead><tr><th>评分项</th><th>得分</th><th>可视化</th></tr></thead>
    <tbody>
      {tech_sb_rows}
      <tr><td colspan="3" style="text-align:center;font-weight:700;border-top:2px solid var(--border);">合计: {tech_total}/{len(tech_sb)*10} &rarr; {combined.get("tech_score",0)}/100</td></tr>
    </tbody>
  </table>

  <details>
    <summary>查看完整技术分析报告</summary>
    <div class="detail-content">{format_content(tech_content)}</div>
  </details>
</div>

<!-- FUND ANALYST -->
<div class="section">
  <div class="section-title">
    <span class="icon" style="background:rgba(34,197,94,0.15);color:var(--success);">&#128176;</span>
    基本面分析
    <span style="margin-left:auto;font-size:14px;">{score_bar(combined.get("fund_score",0))} {direction_badge(combined.get("fund_direction",""))}</span>
  </div>

  <h3>核心财务数据</h3>
  <table class="data-table">
    <thead><tr><th>指标</th><th>值</th></tr></thead>
    <tbody>
      <tr><td>ROE(最新)</td><td>{fund_jd.get("roe_latest","N/A")}%</td></tr>
      <tr><td>毛利率</td><td>{esc(str(fund_jd.get("gross_margin","N/A")))}</td></tr>
      <tr><td>净利率</td><td>{esc(str(fund_jd.get("net_margin","N/A")))}</td></tr>
      <tr><td>营收增速(Q1)</td><td>+{fund_jd.get("revenue_yoy","N/A")}%</td></tr>
      <tr><td>净利增速(Q1)</td><td>+{fund_jd.get("net_profit_yoy","N/A")}%</td></tr>
      <tr><td>资产负债率</td><td>{fund_jd.get("debt_ratio","N/A")}%</td></tr>
      <tr><td>PE(TTM)</td><td>{fund_jd.get("pe_ttm","N/A")}</td></tr>
      <tr><td>PB</td><td>{fund_jd.get("pb","N/A")}</td></tr>
      <tr><td>PEG</td><td>{esc(str(fund_jd.get("peg","N/A")))}</td></tr>
    </tbody>
  </table>

  <h3>杜邦分析</h3>
  <p>{esc(str(fund_jd.get("dupont_analysis","N/A")))}</p>

  <h3>优势</h3>
  {strengths_html}
  <h3>风险</h3>
  {risks_html}

  <h3>场景分析</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0;">
    <div style="background:rgba(34,197,94,0.08);padding:12px;border-radius:8px;text-align:center;border:1px solid rgba(34,197,94,0.2);">
      <div style="font-size:12px;color:var(--text-muted);">乐观</div>
      <div style="font-size:18px;font-weight:700;color:var(--success)">{esc(str(fund_jd.get("scenario_analysis",{}).get("bull",{}).get("target_price","N/A"))) if isinstance(fund_jd.get("scenario_analysis"), dict) else "N/A"}元</div>
    </div>
    <div style="background:rgba(234,179,8,0.08);padding:12px;border-radius:8px;text-align:center;border:1px solid rgba(234,179,8,0.2);">
      <div style="font-size:12px;color:var(--text-muted);">中性</div>
      <div style="font-size:18px;font-weight:700;color:var(--warning)">{esc(str(fund_jd.get("target_price",{}).get("value","N/A"))) if isinstance(fund_jd.get("target_price"), dict) else "N/A"}元</div>
    </div>
    <div style="background:rgba(239,68,68,0.08);padding:12px;border-radius:8px;text-align:center;border:1px solid rgba(239,68,68,0.2);">
      <div style="font-size:12px;color:var(--text-muted);">悲观</div>
      <div style="font-size:18px;font-weight:700;color:var(--danger)">{esc(str(fund_jd.get("scenario_analysis",{}).get("bear",{}).get("target_price","N/A"))) if isinstance(fund_jd.get("scenario_analysis"), dict) else "N/A"}元</div>
    </div>
  </div>

  <h3>评分明细</h3>
  <table class="data-table">
    <thead><tr><th>评分项</th><th>得分</th><th>可视化</th></tr></thead>
    <tbody>
      {fund_sb_rows}
      <tr><td colspan="3" style="text-align:center;font-weight:700;border-top:2px solid var(--border);">合计: {fund_total}/{len(fund_sb)*10} &rarr; {combined.get("fund_score",0)}/100</td></tr>
    </tbody>
  </table>

  <details>
    <summary>查看完整基本面分析报告</summary>
    <div class="detail-content">{format_content(fund_content)}</div>
  </details>
</div>

<!-- NEWS ANALYST -->
{"<div class='section'><div class='section-title'><span class='icon' style='background:rgba(249,115,22,0.15);color:var(--orange);'>&#128240;</span> 新闻面分析<span style='margin-left:auto;font-size:14px;'>" + score_bar(combined.get("news_score",0)) + " " + direction_badge(combined.get("news_direction","")) + "</span></div><h3>市场情绪</h3><div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0;'><div style='background:rgba(255,255,255,0.03);padding:12px;border-radius:8px;border:1px solid var(--border);'><div style='font-size:12px;color:var(--text-muted);'>情绪方向</div><div style='font-size:15px;font-weight:600;'>" + esc(str(news_jd.get('sentiment','N/A'))) + "</div></div><div style='background:rgba(255,255,255,0.03);padding:12px;border-radius:8px;border:1px solid var(--border);'><div style='font-size:12px;color:var(--text-muted);'>情绪置信度</div><div style='font-size:15px;font-weight:600;'>" + esc(str(news_jd.get('sentiment_confidence','N/A'))) + "</div></div><div style='background:rgba(255,255,255,0.03);padding:12px;border-radius:8px;border:1px solid var(--border);'><div style='font-size:12px;color:var(--text-muted);'>市场关注度</div><div style='font-size:15px;font-weight:600;'>" + esc(str(news_jd.get('market_attention','N/A'))) + "</div></div></div><h3>关键事件</h3>" + (news_events_html if news_events_html else "<p>无关键事件</p>") + "<h3>新闻风险事件</h3>" + (news_risks_html if news_risks_html else "<p>无显著风险事件</p>") + "<h3>评分明细</h3><table class='data-table'><thead><tr><th>评分项</th><th>得分</th><th>可视化</th></tr></thead><tbody>" + news_sb_rows + "<tr><td colspan='3' style='text-align:center;font-weight:700;border-top:2px solid var(--border);'>合计: " + str(news_total) + "/" + str(len(news_sb)*10) + " &rarr; " + str(combined.get('news_score',0)) + "/100</td></tr></tbody></table>" + ("<details><summary>查看完整新闻分析报告</summary><div class='detail-content'>" + format_content(news.get('content','')) + "</div></details>" if news.get('content') else "") + "</div>" if has_news else ""}

<!-- DEBATE -->
<div class="section">
  <div class="section-title">
    <span class="icon" style="background:rgba(168,85,247,0.15);color:#a855f7;">&#9876;</span>
    辩论记录
    <span style="margin-left:auto;font-size:14px;">胜方: {direction_badge(combined.get("debate_winner","bearish"))} (delta={combined.get("debate_delta","N/A")})</span>
  </div>
  <blockquote><p>{esc(combined.get("debate_rationale",""))}</p></blockquote>

  <h3>最强论点</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0;">
    <div style="background:rgba(34,197,94,0.06);padding:12px;border-radius:8px;border-left:3px solid var(--success);">
      <div style="font-size:12px;color:var(--success);font-weight:600;margin-bottom:6px;">看多最强</div>
      <div style="font-size:13px;">{esc(combined.get("strongest_bull_point",""))}</div>
    </div>
    <div style="background:rgba(239,68,68,0.06);padding:12px;border-radius:8px;border-left:3px solid var(--danger);">
      <div style="font-size:12px;color:var(--danger);font-weight:600;margin-bottom:6px;">看空最强</div>
      <div style="font-size:13px;">{esc(combined.get("strongest_bear_point",""))}</div>
    </div>
  </div>

  <details>
    <summary>查看完整辩论记录 ({combined.get("debate_rounds",2)}轮)</summary>
    <div class="detail-content">
      <div class="debate-msg bull">
        <div class="speaker">看多方</div>
        <p>{esc(combined.get("bull_arguments",""))}</p>
      </div>
      <div class="debate-msg bear">
        <div class="speaker">看空方</div>
        <p>{esc(combined.get("bear_arguments",""))}</p>
      </div>
    </div>
  </details>
</div>

<!-- RISK WARNINGS -->
<div class="section">
  <div class="section-title">
    <span class="icon" style="background:rgba(239,68,68,0.15);color:var(--danger);">&#9888;</span>
    风险提示
  </div>
  {risk_warn_html}
</div>

<!-- TRADER DETAILS -->
<div class="section">
  <div class="section-title">
    <span class="icon" style="background:rgba(59,130,246,0.15);color:var(--accent);">&#128203;</span>
    交易员详细分析
  </div>

  <h3>置信度组件</h3>
  <table class="data-table">
    <thead><tr><th>维度</th><th>得分</th><th>可视化</th></tr></thead>
    <tbody>
      {cc_rows}
      <tr><td colspan="3" style="text-align:center;font-weight:700;border-top:2px solid var(--border);">合计: {trader.get("confidence_total",0)}/100 ({esc(trader.get("confidence_label",""))})</td></tr>
    </tbody>
  </table>

  <h3>止盈层级</h3>
  <table class="data-table">
    <thead><tr><th>价格</th><th>比例</th><th>理由</th></tr></thead>
    <tbody>{tp_html}</tbody>
  </table>

  <h3>入场条件</h3>
  {ec_html}

  <h3>关键催化剂</h3>
  {kc_html}

  <h3>目标价理由</h3>
  <p>{esc(trader.get("target_price_rationale",""))}</p>

  <h3>止损理由</h3>
  <p>{esc(trader.get("stop_loss_rationale",""))}</p>

  {"<h3>警告</h3>" + tw_html if tw_html else ""}
</div>

<!-- DATA FRESHNESS -->
<div class="section">
  <div class="section-title">
    <span class="icon" style="background:rgba(148,163,184,0.15);color:var(--text-muted);">&#128197;</span>
    数据新鲜度
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;">
    <div>
      <h4>技术面数据</h4>
      {"".join(f"<p>{esc(k)}: {esc(v)}</p>" for k, v in tf.items()) if tf else "<p>N/A</p>"}
    </div>
    <div>
      <h4>基本面数据</h4>
      {"".join(f"<p>{esc(k)}: {esc(v)}</p>" for k, v in ff.items()) if ff else "<p>N/A</p>"}
    </div>
    <div>
      <h4>新闻面数据</h4>
      {"".join(f"<p>{esc(k)}: {esc(v)}</p>" for k, v in nf.items()) if nf else "<p>N/A</p>"}
    </div>
  </div>
</div>

<!-- FOOTER -->
<div class="footer">
  <p>本报告由 AI 多智能体系统自动生成，仅供参考，不构成投资建议。</p>
  <p>权重依据: {esc(combined.get("weight_rationale","N/A"))} | 辩论胜方: {esc(combined.get("debate_winner","N/A"))}</p>
  <p style="margin-top:8px;">Token消耗 — 技术面: {tech.get("token_usage",{}).get("total_tokens",0):,} | 基本面: {fund.get("token_usage",{}).get("total_tokens",0):,} | 新闻面: {news.get("token_usage",{}).get("total_tokens",0):,}</p>
</div>

</div>
</body>
</html>"""
    return html


def process_file(result_path: str) -> str:
    """Generate HTML from a single result.json file and save it."""
    html = generate_html(result_path)

    # Derive output path
    base = os.path.splitext(result_path)[0]
    outpath = base + ".html"

    # Or put in same directory with stock code name
    dirname = os.path.dirname(result_path)
    # Try to get stock code from the json
    with open(result_path, "r", encoding="utf-8") as f:
        r = json.load(f)
    code = r.get("stock_code", r.get("state", {}).get("stock_code", "unknown"))
    outpath = os.path.join(dirname, f"report_{code.replace('.', '_')}.html")

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html)
    return outpath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python gen_html_report.py <result.json or directory>")
        sys.exit(1)

    target = sys.argv[1]
    if os.path.isdir(target):
        # Batch mode: process all result_*.json in directory
        files = sorted(glob.glob(os.path.join(target, "result_*.json")))
        if not files:
            print(f"No result_*.json found in {target}")
            sys.exit(1)
        print(f"Found {len(files)} result files")
        for fp in files:
            try:
                out = process_file(fp)
                print(f"  OK: {os.path.basename(fp)} -> {os.path.basename(out)}")
            except Exception as e:
                print(f"  FAIL: {os.path.basename(fp)} -> {e}")
    else:
        out = process_file(target)
        print(f"Generated: {out}")
