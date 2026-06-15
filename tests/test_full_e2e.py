"""
Full E2E test: Tech + Fund + Debate (real data)

Usage:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    python tests/test_full_e2e.py
"""

import json
import sys
import os
import logging
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Load .env
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
logger = logging.getLogger("test_full_e2e")


def main():
    # 1. Load config
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info(f"Model: {config['model']} @ {config['base_url']}")

    # 2. Create orchestrator
    from src.agents.orchestrator import MultiAgentOrchestrator

    output_dir = os.path.join(project_root, "output", "full_e2e")
    os.makedirs(output_dir, exist_ok=True)

    orchestrator = MultiAgentOrchestrator(config, persist_dir=output_dir)
    logger.info("Orchestrator created")

    # 3. Run full analysis WITH debate
    stock_code = "603588.SH"
    logger.info(f"Starting FULL analysis for {stock_code} (debate enabled)...")
    start = time.time()

    result = orchestrator.run_analysis(
        stock_code,
        max_iterations=10,
        debate_rounds=2,
        skip_debate=False,  # explicitly enable debate
    )

    elapsed = time.time() - start
    logger.info(f"Analysis complete in {elapsed:.1f}s")

    # 4. Print summary
    print("\n" + "=" * 60)
    print("FULL E2E TEST RESULT")
    print("=" * 60)
    print(f"Stock:      {result['stock_code']}")
    print(f"Success:    {result['success']}")
    print(f"Duration:   {result['duration_ms']}ms ({result['duration_ms']/1000:.1f}s)")

    # Tech
    tech = result["tech_report"]
    print(f"\n--- Technical Analyst ---")
    print(f"  Success:    {tech['success']}")
    print(f"  Iterations: {tech['iterations']}")
    print(f"  Tool calls: {tech['tool_calls']}")
    print(f"  Duration:   {tech['duration_ms']}ms")
    if tech.get("json_data"):
        jd = tech["json_data"]
        print(f"  Score:      {jd.get('score')}")
        print(f"  Direction:  {jd.get('direction')}")
    if tech.get("validation"):
        print(f"  Valid:      {tech['validation']['valid']}")

    # Fund
    fund = result["fund_report"]
    print(f"\n--- Fundamentals Analyst ---")
    print(f"  Success:    {fund['success']}")
    print(f"  Iterations: {fund['iterations']}")
    print(f"  Tool calls: {fund['tool_calls']}")
    print(f"  Duration:   {fund['duration_ms']}ms")
    if fund.get("json_data"):
        jd = fund["json_data"]
        print(f"  Score:      {jd.get('score')}")
        print(f"  Verdict:    {jd.get('verdict')}")
    if fund.get("validation"):
        print(f"  Valid:      {fund['validation']['valid']}")

    # Debate
    debate = result.get("debate_result")
    if debate:
        print(f"\n--- Debate ---")
        print(f"  Rounds:     {debate.get('rounds_completed')}")
        print(f"  Duration:   {debate.get('duration_ms')}ms")
        bull_len = len(debate.get("bull_arguments", ""))
        bear_len = len(debate.get("bear_arguments", ""))
        print(f"  Bull args:  {bull_len} chars")
        print(f"  Bear args:  {bear_len} chars")
    else:
        print(f"\n--- Debate: SKIPPED ---")

    # Combined
    combined = result["combined_report"]
    print(f"\n--- Combined Report ---")
    print(f"  Score:      {combined['combined_score']}")
    print(f"  Direction:  {combined['combined_direction']}")
    print(f"  Tech:       {combined['tech_score']} ({combined['tech_direction']})")
    print(f"  Fund:       {combined['fund_score']} ({combined['fund_direction']})")
    if combined.get("debate_winner"):
        print(f"  Debate:     {combined['debate_winner']} (delta={combined['debate_delta']})")
    print(f"  Alignment:  {combined['alignment']}")
    print(f"  Rec:        {combined['recommendation']}")
    # D3: stock type and weights
    print(f"  Stock type: {combined.get('stock_type', 'N/A')}")
    print(f"  Weights:    {combined.get('weight_rationale', 'N/A')}")

    # Trader
    trader = combined.get("trader")
    if trader:
        print(f"\n--- Trader ---")
        print(f"  Action:     {trader.get('action')} ({trader.get('action_strength')})")
        print(f"  Target:     {trader.get('target_price')}")
        print(f"  Stop loss:  {trader.get('stop_loss')}")
        print(f"  Confidence: {trader.get('confidence_total')} ({trader.get('confidence_label')})")
        print(f"  Position:   {trader.get('position_advice')} ({trader.get('position_range')})")
        print(f"  Risk score: {trader.get('risk_score')} ({trader.get('risk_level')})")
        print(f"  Horizon:    {trader.get('time_horizon')}")
        if trader.get("reasoning"):
            print(f"  Reasoning:  {trader['reasoning'][:100]}...")
    else:
        print(f"\n--- Trader: MISSING ---")

    # State fields
    state = result["state"]
    print(f"\n--- State (Trader fields) ---")
    print(f"  decision:   {state.get('decision')}")
    print(f"  target:     {state.get('target_price')}")
    print(f"  confidence: {state.get('confidence')}")
    print(f"  risk_score: {state.get('risk_score')}")

    # 5. Save result
    output_file = os.path.join(output_dir, "result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Result saved to {output_file}")

    # 6. Assertions
    print(f"\n--- Assertions ---")
    checks = []

    checks.append(("Overall success", result["success"]))
    checks.append(("Tech success", tech["success"]))
    checks.append(("Fund success", fund["success"]))
    checks.append(("Tech JSON parsed", bool(tech.get("json_data"))))
    checks.append(("Fund JSON parsed", bool(fund.get("json_data"))))
    checks.append(("Debate completed", debate is not None))
    checks.append(("Score 0-100", 0 <= combined["combined_score"] <= 100))

    # Trader checks
    checks.append(("Trader present", trader is not None))
    if trader:
        checks.append(("Trader action valid", trader.get("action") in ("buy", "hold", "sell")))
        checks.append(("Trader target_price > 0", isinstance(trader.get("target_price"), (int, float)) and trader.get("target_price", 0) > 0))
        checks.append(("Trader stop_loss > 0", isinstance(trader.get("stop_loss"), (int, float)) and trader.get("stop_loss", 0) > 0))
        checks.append(("Trader confidence 0-100", isinstance(trader.get("confidence_total"), (int, float)) and 0 <= trader.get("confidence_total", -1) <= 100))
        checks.append(("Trader risk_score 0-100", isinstance(trader.get("risk_score"), (int, float)) and 0 <= trader.get("risk_score", -1) <= 100))
        checks.append(("Trader reasoning present", bool(trader.get("reasoning"))))

    # State field checks
    checks.append(("State decision filled", state.get("decision") is not None))
    checks.append(("State target_price filled", state.get("target_price") is not None))
    checks.append(("State confidence filled", state.get("confidence") is not None))
    checks.append(("State risk_score filled", state.get("risk_score") is not None))

    # D3: Stock type checks
    checks.append(("Stock type present", combined.get("stock_type") is not None))
    checks.append(("Stock type valid", combined.get("stock_type") in ("growth", "value", "cyclical", "quality")))
    checks.append(("Weight rationale present", bool(combined.get("weight_rationale"))))

    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")

    all_passed = all(c[1] for c in checks)
    print(f"\n  Result: {sum(1 for c in checks if c[1])}/{len(checks)} passed")

    if all_passed:
        print("\nFULL E2E TEST PASSED!")
    else:
        failed = [c[0] for c in checks if not c[1]]
        print(f"\nFULL E2E TEST FAILED: {failed}")

    return result


if __name__ == "__main__":
    main()
