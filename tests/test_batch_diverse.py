"""
Batch E2E test with diverse stock types.
Tests the unified news scoring convention (negative numbers for negative factors).

Usage: python tests/test_batch_diverse.py
"""
import json
import sys
import os
import logging
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

_env_file = os.path.join(project_root, ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as f:
        for _line in f:
            _line = _line.strip()
            if _line.startswith("TUSHARE_TOKEN="):
                os.environ["TUSHARE_TOKEN"] = _line.split("=", 1)[1].strip()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("batch_diverse")

# Diverse stock types
STOCKS = [
    ("600519.SH", "贵州茅台"),   # 蓝筹/消费龙头
    ("002594.SZ", "比亚迪"),     # 成长/新能源
    ("601318.SH", "中国平安"),   # 金融/价值
    ("000858.SZ", "五粮液"),     # 消费/白马
    ("300750.SZ", "宁德时代"),   # 成长/新能源
    ("600036.SH", "招商银行"),   # 金融/蓝筹
]


def run_single(stock_code: str, stock_name: str) -> dict:
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    from src.agents.orchestrator import MultiAgentOrchestrator

    output_dir = os.path.join(project_root, "output", "batch_diverse")
    os.makedirs(output_dir, exist_ok=True)

    orchestrator = MultiAgentOrchestrator(config, persist_dir=output_dir)
    logger.info(f"[{stock_name}] Starting analysis...")

    start = time.time()
    result = orchestrator.run_analysis(
        stock_code,
        max_iterations=10,
        debate_rounds=2,
        skip_debate=False,
    )
    elapsed = time.time() - start

    out_file = os.path.join(output_dir, f"result_{stock_code.replace('.', '_')}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    combined = result.get("combined_report", {})
    trader = combined.get("trader", {})
    tech = result.get("tech_report", {})
    news_r = result.get("news_report", {})
    news_jd = news_r.get("json_data") or {}

    summary = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "success": result.get("success", False),
        "duration_s": round(elapsed, 1),
        "tech_score": combined.get("tech_score"),
        "fund_score": combined.get("fund_score"),
        "news_score": combined.get("news_score"),
        "news_direction": combined.get("news_direction"),
        "news_raw_score": news_jd.get("score"),
        "news_breakdown": news_jd.get("scoring_breakdown"),
        "combined_score": combined.get("combined_score"),
        "combined_direction": combined.get("combined_direction"),
        "debate_winner": combined.get("debate_winner"),
        "action": trader.get("action"),
        "action_strength": trader.get("action_strength"),
        "confidence": trader.get("confidence_total"),
        "confidence_label": trader.get("confidence_label"),
        "risk_level": trader.get("risk_level"),
        "risk_score": trader.get("risk_score"),
        "target_price": trader.get("target_price"),
        "stop_loss": trader.get("stop_loss"),
        "position_advice": trader.get("position_advice"),
        "position_range": trader.get("position_range"),
        "time_horizon": trader.get("time_horizon"),
        "entry_conditions": trader.get("entry_conditions"),
        "take_profit_levels": trader.get("take_profit_levels"),
        "reasoning_summary": (trader.get("reasoning") or "")[:200],
        "warnings": trader.get("warnings"),
        "result_file": out_file,
    }

    # Validate news score consistency
    if news_jd.get("scoring_breakdown"):
        sb = news_jd["scoring_breakdown"]
        calc = 50 + sum(v for v in sb.values() if isinstance(v, (int, float)))
        calc = max(0, min(100, round(calc, 1)))
        summary["news_formula_calc"] = calc
        actual = news_jd.get("score")
        if actual is not None and abs(actual - calc) > 1:
            summary["news_score_mismatch"] = f"LLM={actual} vs formula={calc}"
            logger.warning(f"[{stock_name}] News score mismatch: LLM={actual}, formula={calc}")

    status = "OK" if result.get("success") else "FAILED"
    logger.info(
        f"[{stock_name}] {status} | "
        f"Combined: {combined.get('combined_score', 'N/A')} | "
        f"News: {news_jd.get('score', 'N/A')} | "
        f"Action: {trader.get('action', 'N/A')} | "
        f"Time: {elapsed:.0f}s"
    )

    return summary


_ACTION_CN = {
    "buy": "买入",
    "sell": "卖出",
    "hold": "持有",
    "watch": "观望",
}


def _action_cn(action):
    if not action:
        return "--"
    cn = _ACTION_CN.get(action, action)
    return f"{action}({cn})"


def _fmt_price(v):
    if v is None:
        return "--"
    if isinstance(v, (int, float)):
        return f"{v:.2f}"
    return str(v)


def _score_str(v):
    return f"{v:.0f}" if isinstance(v, (int, float)) else "--"


def render_watchlist_md(all_results, output_path):
    """Render batch results into a captain-readable markdown decision board.

    Two layers: a compact comparison table (one row per stock, sorted by
    combined score) so the captain can scan across stocks, then per-stock
    details (entry conditions, reasoning, warnings) for drilling in.
    Mirrors the trader field layout used in scripts/gen_report.py.
    """
    lines = []

    def w(s=""):
        lines.append(s)

    sorted_results = sorted(
        all_results,
        key=lambda r: (
            r.get("combined_score")
            if isinstance(r.get("combined_score"), (int, float))
            else -1
        ),
        reverse=True,
    )
    ok = sum(1 for r in all_results if r.get("success"))

    w("# 批量决策看板")
    w()
    w(f"> 共 {len(all_results)} 只 | 成功 {ok} 只 | 按综合分降序")
    w()
    w("---")
    w()
    w("## 一、横向对比表")
    w()
    w("| 股票 | 名称 | 综合分 | 方向 | 动作 | 目标价 | 止损 | 仓位 | 置信 | 风险 | 耗时 |")
    w("|------|------|--------|------|------|--------|------|------|------|------|------|")
    for r in sorted_results:
        pos = r.get("position_advice") or "--"
        if r.get("position_range"):
            pos = f"{pos}({r['position_range']})"
        dur = r.get("duration_s")
        dur_str = f"{dur:.0f}s" if isinstance(dur, (int, float)) else "--"
        w(
            f"| {r.get('stock_code', '--')} "
            f"| {r.get('stock_name', '--')} "
            f"| {_score_str(r.get('combined_score'))} "
            f"| {r.get('combined_direction') or '--'} "
            f"| {_action_cn(r.get('action'))} "
            f"| {_fmt_price(r.get('target_price'))} "
            f"| {_fmt_price(r.get('stop_loss'))} "
            f"| {pos} "
            f"| {_score_str(r.get('confidence'))} "
            f"| {r.get('risk_level') or '--'} "
            f"| {dur_str} |"
        )
    w()

    w("## 二、逐只决策详情")
    w()
    for r in sorted_results:
        code = r.get("stock_code", "--")
        name = r.get("stock_name", "--")
        w(
            f"### {name}（{code}）— 综合 "
            f"{_score_str(r.get('combined_score'))} | {_action_cn(r.get('action'))}"
        )
        w()
        pos = r.get("position_advice") or "--"
        pos_range = r.get("position_range") or "--"
        w(
            f"- 方向: {r.get('combined_direction') or '--'} "
            f"| 辩论胜方: {r.get('debate_winner') or '--'}"
        )
        w(
            f"- 目标价: **{_fmt_price(r.get('target_price'))}** "
            f"| 止损: **{_fmt_price(r.get('stop_loss'))}** "
            f"| 仓位: {pos}({pos_range})"
        )
        w(
            f"- 置信度: {_score_str(r.get('confidence'))} "
            f"| 风险等级: {r.get('risk_level') or '--'} "
            f"| 时间框架: {r.get('time_horizon') or '--'}"
        )
        ec = r.get("entry_conditions") or []
        if ec:
            w("- 入场条件:")
            for c in ec:
                w(f"  - {c}")
        reasoning = (r.get("reasoning_summary") or "").strip()
        if reasoning:
            w(f"- 决策理由: {reasoning}")
        warns = r.get("warnings") or []
        if warns:
            w("- 风险提示:")
            for wa in warns:
                w(f"  - {wa}")
        w()

    output = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    return output_path


def main():
    all_results = []
    total_start = time.time()

    for i, (code, name) in enumerate(STOCKS, 1):
        logger.info(f"===== [{i}/{len(STOCKS)}] {name} ({code}) =====")
        try:
            result = run_single(code, name)
            all_results.append(result)
        except Exception as e:
            logger.error(f"[{name}] FAILED with error: {e}")
            all_results.append({
                "stock_code": code,
                "stock_name": name,
                "success": False,
                "error": str(e),
            })

    total_elapsed = time.time() - total_start

    # Print summary table
    print("\n" + "=" * 100)
    print("DIVERSE BATCH TEST SUMMARY")
    print("=" * 100)
    print(
        f"{'Stock':<12} {'Name':<8} {'Score':>6} {'Dir':<8} "
        f"{'News':>6} {'NewsOK':>7} {'Action':>6} {'Conf':>5} {'Risk':>5} {'Time':>6} {'Status':>7}"
    )
    print("-" * 100)
    for r in all_results:
        ns = r.get("news_score")
        ns_str = f"{ns:.0f}" if isinstance(ns, (int, float)) and ns else "-"
        mismatch = r.get("news_score_mismatch")
        news_ok = "OK" if not mismatch else f"ERR:{mismatch[:20]}"
        print(
            f"{r.get('stock_code', 'N/A'):<12} "
            f"{r.get('stock_name', 'N/A'):<8} "
            f"{str(r.get('combined_score', '-')):>6} "
            f"{str(r.get('combined_direction', '-')):<8} "
            f"{ns_str:>6} "
            f"{news_ok:>7} "
            f"{str(r.get('action', '-')):>6} "
            f"{str(r.get('confidence', '-')):>5} "
            f"{str(r.get('risk_level', '-')):>5} "
            f"{str(r.get('duration_s', '-')):>5}s "
            f"{'OK' if r.get('success') else 'FAIL':>7}"
        )
    print("-" * 100)
    ok = sum(1 for r in all_results if r.get("success"))
    print(f"Total: {ok}/{len(all_results)} passed | Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")

    # Check news score consistency
    mismatches = [r for r in all_results if r.get("news_score_mismatch")]
    if mismatches:
        print(f"\nNews score mismatches ({len(mismatches)}):")
        for r in mismatches:
            print(f"  {r['stock_name']}: {r['news_score_mismatch']}")
            print(f"    breakdown: {r.get('news_breakdown')}")

    summary_file = os.path.join(
        project_root, "output", "batch_diverse", "batch_summary.json"
    )
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    logger.info(f"Summary saved to {summary_file}")

    # Captain-readable markdown decision board (table + per-stock details)
    watchlist_md = os.path.join(
        project_root, "output", "batch_diverse", "batch_watchlist.md"
    )
    render_watchlist_md(all_results, watchlist_md)
    logger.info(f"Readable watchlist saved to {watchlist_md}")

    return all_results


if __name__ == "__main__":
    main()
