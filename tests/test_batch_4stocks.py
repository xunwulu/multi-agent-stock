"""
批量测试: 4只代表性股票
验证 scoring_hints / schema 分裂 / 防幻觉兜底 / 质量校验 在不同股票类型上的表现
"""

import json
import os
import sys
import time
import logging

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(name)s %(message)s",
)

# Suppress noisy loggers
for name in ["httpx", "urllib3", "src.tools.get_stock_news", "src.tools.get_kline"]:
    logging.getLogger(name).setLevel(logging.ERROR)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.agents.orchestrator import MultiAgentOrchestrator

STOCKS = [
    ("600036.SH", "招商银行", "蓝筹/金融"),
    ("300750.SZ", "宁德时代", "成长/新能源"),
    ("002131.SZ", "利欧股份", "中小盘/传媒"),
    ("601225.SH", "陕西煤业", "周期/能源"),
]


def test_stock(orch, code, name, stock_type):
    """Run full analysis on one stock, return summary dict."""
    print(f"\n{'=' * 50}")
    print(f"Testing: {code} {name} ({stock_type})")
    print(f"{'=' * 50}")

    start = time.time()
    try:
        result = orch.run_analysis(
            code,
            max_iterations=8,
            debate_rounds=1,
            skip_debate=False,
        )
        elapsed = time.time() - start
    except Exception as e:
        elapsed = time.time() - start
        print(f"  CRASHED: {e}")
        return {
            "code": code,
            "name": name,
            "type": stock_type,
            "crashed": True,
            "error": str(e),
            "elapsed_s": round(elapsed, 1),
        }

    summary = {
        "code": code,
        "name": name,
        "type": stock_type,
        "crashed": False,
        "success": result.get("success", False),
        "elapsed_s": round(elapsed, 1),
    }

    # Per-analyst results
    for key, label in [
        ("tech_report", "Tech"),
        ("fund_report", "Fund"),
        ("news_report", "News"),
    ]:
        r = result.get(key, {})
        so = r.get("structured_output") or {}
        summary[f"{label}_ok"] = r.get("success", False)
        summary[f"{label}_calls"] = r.get("tool_calls", 0)
        summary[f"{label}_iter"] = r.get("iterations", 0)
        summary[f"{label}_ms"] = r.get("duration_ms", 0)
        summary[f"{label}_score"] = so.get("score", "N/A")
        summary[f"{label}_dir"] = so.get("direction", so.get("verdict", "N/A"))

        # Check for fallback trigger (tool_calls == 0 means fallback was used)
        if r.get("tool_calls", -1) == 0:
            summary[f"{label}_fallback"] = True
        else:
            summary[f"{label}_fallback"] = False

    # Combined report
    cr = result.get("combined_report", {})
    summary["combined_score"] = cr.get("score", "N/A")
    summary["combined_dir"] = cr.get("direction", "N/A")
    summary["stock_type_class"] = cr.get("stock_type", "N/A")

    # Debate result
    dr = result.get("debate_result")
    if dr:
        summary["debate_winner"] = dr.get("debate_winner", "N/A")
        summary["debate_delta"] = dr.get("debate_delta", "N/A")
    else:
        summary["debate_winner"] = "N/A"
        summary["debate_delta"] = "N/A"

    # Errors
    errors = []
    if result.get("error"):
        errors.append(f"Overall: {result['error']}")
    for key, label in [
        ("tech_report", "Tech"),
        ("fund_report", "Fund"),
        ("news_report", "News"),
    ]:
        r = result.get(key, {})
        if r.get("error"):
            errors.append(f"{label}: {r['error'][:100]}")
    summary["errors"] = errors

    # Print inline
    print(f"  Success: {summary['success']}, Time: {summary['elapsed_s']}s")
    for label in ["Tech", "Fund", "News"]:
        ok = summary.get(f"{label}_ok")
        calls = summary.get(f"{label}_calls")
        score = summary.get(f"{label}_score")
        d = summary.get(f"{label}_dir")
        fb = " [FALLBACK]" if summary.get(f"{label}_fallback") else ""
        print(f"  {label}: ok={ok}, calls={calls}, score={score}, dir={d}{fb}")
    print(f"  Combined: score={summary['combined_score']}, dir={summary['combined_dir']}, type={summary['stock_type_class']}")
    print(f"  Debate: winner={summary['debate_winner']}, delta={summary['debate_delta']}")
    if errors:
        for e in errors:
            print(f"  Error: {e}")

    return summary


def main():
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path) as f:
        config = json.load(f)

    orch = MultiAgentOrchestrator(config)

    results = []
    total_start = time.time()

    for i, (code, name, stock_type) in enumerate(STOCKS):
        r = test_stock(orch, code, name, stock_type)
        results.append(r)

        # Inter-stock cooldown: avoid API rate limiting
        # (each stock triggers ~20 API calls; 30s gap lets the proxy recover)
        if i < len(STOCKS) - 1:
            cooldown = 30
            print(f"\n-- Cooldown {cooldown}s before next stock --")
            time.sleep(cooldown)

    total_elapsed = time.time() - total_start

    # Summary table
    print(f"\n{'=' * 70}")
    print("BATCH TEST SUMMARY")
    print(f"{'=' * 70}")
    print(
        f"{'Code':<12} {'Name':<8} {'Type':<10} "
        f"{'OK':<5} {'Time':<7} "
        f"{'Tech':<10} {'Fund':<10} {'News':<10} "
        f"{'Comb':<8} {'Errors'}"
    )
    print("-" * 70)

    crash_count = 0
    fail_count = 0
    fallback_count = 0
    issue_list = []

    for r in results:
        if r.get("crashed"):
            crash_count += 1
            tech_s = "CRASH"
            fund_s = "CRASH"
            news_s = "CRASH"
            comb_s = "CRASH"
        else:
            tech_s = f"{r.get('Tech_score', '?')}/{r.get('Tech_dir', '?')}"
            fund_s = f"{r.get('Fund_score', '?')}/{r.get('Fund_dir', '?')}"
            news_s = f"{r.get('News_score', '?')}/{r.get('News_dir', '?')}"
            comb_s = f"{r.get('combined_score', '?')}/{r.get('combined_dir', '?')}"

            if not r.get("success"):
                fail_count += 1

            # Check for fallback triggers
            for label in ["Tech", "Fund", "News"]:
                if r.get(f"{label}_fallback"):
                    fallback_count += 1
                    issue_list.append(f"{r['code']}: {label} triggered fallback")

            # Check for score=0 (auto-corrected)
            for label in ["Tech", "Fund", "News"]:
                if r.get(f"{label}_score") == 0:
                    issue_list.append(f"{r['code']}: {label} score=0 (LLM did not calculate)")

            # Check for missing scores
            for label in ["Tech", "Fund", "News"]:
                if not r.get(f"{label}_ok"):
                    issue_list.append(f"{r['code']}: {label} analyst failed")

        errs = r.get("errors", [])
        err_str = f"{len(errs)} issues" if errs else "OK"

        print(
            f"{r['code']:<12} {r['name']:<8} {r['type']:<10} "
            f"{'Y' if r.get('success') else 'N':<5} {r.get('elapsed_s', 0):>5.0f}s  "
            f"{tech_s:<10} {fund_s:<10} {news_s:<10} "
            f"{comb_s:<8} {err_str}"
        )

    print("-" * 70)
    print(f"Total time: {total_elapsed:.0f}s ({total_elapsed / 60:.1f} min)")
    print(f"Crashes: {crash_count}, Failures: {fail_count}, Fallbacks: {fallback_count}")

    if issue_list:
        print(f"\nIssues found ({len(issue_list)}):")
        for i, issue in enumerate(issue_list, 1):
            print(f"  {i}. {issue}")
    else:
        print("\nNo issues found!")

    # Save results to JSON
    output_path = os.path.join(project_root, "output", "batch_test_results.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
