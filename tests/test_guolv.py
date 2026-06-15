"""
Test analysis for 600358.SH (国旅联合) with stop-loss direction monitoring.
Runs full pipeline, saves result JSON, then generates HTML report.

Usage:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    python tests/test_guolv.py
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
logger = logging.getLogger("test_guolv")


def main():
    # 1. Load config
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info(f"Model: {config['model']} @ {config['base_url']}")

    # 2. Create orchestrator
    from src.agents.orchestrator import MultiAgentOrchestrator

    # 3. Stock selection
    stock_code = os.environ.get("TEST_STOCK", "600358.SH")
    stock_names = {
        "600358.SH": "国旅联合",
        "601899.SH": "紫金矿业",
    }
    stock_name = stock_names.get(stock_code, stock_code)

    output_dir = os.path.join(project_root, "output", f"test_{stock_code.replace('.', '_')}")
    os.makedirs(output_dir, exist_ok=True)

    orchestrator = MultiAgentOrchestrator(config, persist_dir=output_dir)
    logger.info("Orchestrator created")

    # 4. Run full analysis
    logger.info(f"Starting analysis for {stock_code} ({stock_name})...")
    start = time.time()

    result = orchestrator.run_analysis(
        stock_code,
        max_iterations=10,
        debate_rounds=2,
        skip_debate=False,
    )

    elapsed = time.time() - start
    logger.info(f"Analysis complete in {elapsed:.1f}s")

    # 4. Save result
    output_file = os.path.join(output_dir, "result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Result saved to {output_file}")

    # 5. Print summary with stop-loss focus
    print("\n" + "=" * 60)
    print(f"  {stock_code} {stock_name} - Analysis Result")
    print("=" * 60)
    print(f"Success:    {result['success']}")
    print(f"Duration:   {result['duration_ms']}ms ({result['duration_ms']/1000:.1f}s)")

    # Tech report
    tech = result["tech_report"]
    print(f"\n--- Technical Analyst ---")
    print(f"  Success:    {tech['success']}")
    print(f"  Iterations: {tech['iterations']}")
    print(f"  Tool calls: {tech['tool_calls']}")
    if tech.get("json_data"):
        jd = tech["json_data"]
        print(f"  Score:      {jd.get('score')}")
        print(f"  Direction:  {jd.get('direction')}")
        print(f"  Latest close: {jd.get('latest_close')}")
        print(f"  Stop loss (buy):  {jd.get('stop_loss_price')}")
        print(f"  Stop loss (sell): {jd.get('stop_loss_sell')}")
        print(f"  Target price:     {jd.get('target_price')}")
        # Validate stop loss direction
        direction = jd.get('direction', 'neutral')
        lc = jd.get('latest_close')
        sl_buy = jd.get('stop_loss_price')
        sl_sell = jd.get('stop_loss_sell')
        if lc and sl_buy:
            if sl_buy < lc:
                print(f"  [OK] buy stop_loss ({sl_buy}) < latest_close ({lc})")
            else:
                print(f"  [BUG] buy stop_loss ({sl_buy}) >= latest_close ({lc})!")
        if direction == "bearish" and sl_sell is None:
            print(f"  [WARN] bearish but stop_loss_sell is missing!")
        elif direction == "bearish" and lc and sl_sell:
            if sl_sell > lc:
                print(f"  [OK] sell stop_loss ({sl_sell}) > latest_close ({lc})")
            else:
                print(f"  [BUG] sell stop_loss ({sl_sell}) <= latest_close ({lc})!")

    if tech.get("validation"):
        print(f"  Valid:      {tech['validation']['valid']}")
        if tech['validation'].get('warnings'):
            for w in tech['validation']['warnings']:
                print(f"  Warning:    {w}")

    # Fund report
    fund = result["fund_report"]
    print(f"\n--- Fundamentals Analyst ---")
    print(f"  Success:    {fund['success']}")
    if fund.get("json_data"):
        jd = fund["json_data"]
        print(f"  Score:      {jd.get('score')}")
        print(f"  Verdict:    {jd.get('verdict')}")

    # Debate
    debate = result.get("debate_result")
    if debate:
        print(f"\n--- Debate ---")
        print(f"  Rounds:     {debate.get('rounds_completed')}")
        print(f"  Winner:     {debate.get('winner', 'N/A')}")

    # Combined
    combined = result["combined_report"]
    print(f"\n--- Combined ---")
    print(f"  Score:      {combined['combined_score']}")
    print(f"  Direction:  {combined['combined_direction']}")
    print(f"  Stock type: {combined.get('stock_type', 'N/A')}")

    # Trader - FOCUS on stop loss direction
    trader = combined.get("trader")
    if trader:
        print(f"\n--- Trader ---")
        print(f"  Action:     {trader.get('action')} ({trader.get('action_strength')})")
        print(f"  Target:     {trader.get('target_price')}")
        print(f"  Stop loss:  {trader.get('stop_loss')}")

        # Check stop loss vs current price direction
        action = trader.get('action')
        sl = trader.get('stop_loss')
        # Try to find current price
        _cp = trader.get('_current_price')
        if not _cp and tech.get("json_data"):
            _cp = tech["json_data"].get("latest_close")
        if _cp and sl and action:
            if action in ("buy", "hold") and sl < _cp:
                print(f"  [OK] {action} stop_loss ({sl}) < current ({_cp})")
            elif action == "sell" and sl > _cp:
                print(f"  [OK] {action} stop_loss ({sl}) > current ({_cp})")
            elif action in ("buy", "hold") and sl >= _cp:
                print(f"  [BUG!] {action} stop_loss ({sl}) >= current ({_cp}) - WRONG DIRECTION!")
            elif action == "sell" and sl <= _cp:
                print(f"  [BUG!] {action} stop_loss ({sl}) <= current ({_cp}) - WRONG DIRECTION!")
        else:
            print(f"  [WARN] Cannot verify stop loss direction (cp={_cp}, sl={sl}, action={action})")

        print(f"  Confidence: {trader.get('confidence_total')} ({trader.get('confidence_label')})")
        print(f"  Risk score: {trader.get('risk_score')} ({trader.get('risk_level')})")
        if trader.get("reasoning"):
            print(f"  Reasoning:  {trader['reasoning'][:200]}...")
    else:
        print(f"\n--- Trader: MISSING (using fallback) ---")

    # 6. Generate HTML report
    try:
        from scripts.gen_html_report import generate_html

        html_str = generate_html(output_file)
        html_file = os.path.join(output_dir, f"report_{stock_code.replace('.', '_')}.html")
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_str)
        logger.info(f"HTML report saved to {html_file}")
        print(f"\nHTML report: {html_file}")
    except Exception as e:
        logger.error(f"Failed to generate HTML: {e}")
        import traceback
        traceback.print_exc()

    print(f"\nResult JSON: {output_file}")
    return result


if __name__ == "__main__":
    main()
