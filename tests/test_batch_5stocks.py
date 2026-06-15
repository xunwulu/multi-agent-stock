"""
Batch E2E test for multiple stocks
Usage: python tests/test_batch_5stocks.py
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
logger = logging.getLogger("batch_e2e")

# Stock list
STOCKS = [
    ("300308.SZ", "中际旭创"),
    ("000066.SZ", "中国长城"),
    ("601869.SH", "长飞光纤"),
    ("300326.SZ", "ST凯利"),
    ("600358.SH", "国旅联合"),
]


def run_single(stock_code: str, stock_name: str) -> dict:
    """Run full E2E analysis for a single stock."""
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    from src.agents.orchestrator import MultiAgentOrchestrator

    output_dir = os.path.join(project_root, "output", "batch_test")
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

    # Save result
    out_file = os.path.join(output_dir, f"result_{stock_code.replace('.', '_')}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    # Summary
    combined = result.get("combined_report", {})
    trader = combined.get("trader", {})
    tech = result.get("tech_report", {})
    fund = result.get("fund_report", {})

    summary = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "success": result.get("success", False),
        "duration_s": round(elapsed, 1),
        "tech_score": combined.get("tech_score"),
        "tech_direction": combined.get("tech_direction"),
        "fund_score": combined.get("fund_score"),
        "fund_direction": combined.get("fund_direction"),
        "news_score": combined.get("news_score"),
        "news_direction": combined.get("news_direction"),
        "combined_score": combined.get("combined_score"),
        "combined_direction": combined.get("combined_direction"),
        "stock_type": combined.get("stock_type"),
        "weight_rationale": combined.get("weight_rationale"),
        "debate_winner": combined.get("debate_winner"),
        "debate_delta": combined.get("debate_delta"),
        "action": trader.get("action"),
        "action_strength": trader.get("action_strength"),
        "target_price": trader.get("target_price"),
        "stop_loss": trader.get("stop_loss"),
        "confidence": trader.get("confidence_total"),
        "confidence_label": trader.get("confidence_label"),
        "risk_score": trader.get("risk_score"),
        "risk_level": trader.get("risk_level"),
        "position_advice": trader.get("position_advice"),
        "trader_warnings": trader.get("warnings", []),
        "result_file": out_file,
    }

    status = "OK" if result.get("success") else "FAILED"
    logger.info(
        f"[{stock_name}] {status} | "
        f"Score: {combined.get('combined_score', 'N/A')} | "
        f"Action: {trader.get('action', 'N/A')} | "
        f"Time: {elapsed:.0f}s"
    )

    return summary


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
    print("\n" + "=" * 80)
    print("BATCH TEST SUMMARY")
    print("=" * 80)
    print(
        f"{'Stock':<12} {'Name':<8} {'Score':>6} {'Dir':<8} "
        f"{'News':>6} {'Action':>6} {'Conf':>5} {'Risk':>5} {'Time':>6} {'Status':>7}"
    )
    print("-" * 80)
    for r in all_results:
        news_s = r.get("news_score")
        news_str = f"{news_s:.0f}" if isinstance(news_s, (int, float)) and news_s else "-"
        print(
            f"{r.get('stock_code', 'N/A'):<12} "
            f"{r.get('stock_name', 'N/A'):<8} "
            f"{str(r.get('combined_score', '-')):>6} "
            f"{str(r.get('combined_direction', '-')):<8} "
            f"{news_str:>6} "
            f"{str(r.get('action', '-')):>6} "
            f"{str(r.get('confidence', '-')):>5} "
            f"{str(r.get('risk_score', '-')):>5} "
            f"{str(r.get('duration_s', '-')):>5}s "
            f"{'OK' if r.get('success') else 'FAIL':>7}"
        )
    print("-" * 80)
    ok = sum(1 for r in all_results if r.get("success"))
    print(f"Total: {ok}/{len(all_results)} passed | Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")

    # Save summary
    summary_file = os.path.join(
        project_root, "output", "batch_test", "batch_summary.json"
    )
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    logger.info(f"Summary saved to {summary_file}")

    return all_results


if __name__ == "__main__":
    main()
