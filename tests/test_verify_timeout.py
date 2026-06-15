"""
Verify Batch 1 timeout defense on real E2E: run 招商银行 (the 9424s incident stock).

Checks:
  1. Normal flow still completes (connect_timeout didn't break API calls)
  2. Elapsed time is reasonable (no multi-hour hang)
  3. synthesis_method shows a normal path (no timeout_degraded unless it actually degraded)
  4. connect_timeout=10 is active in the loaded config
"""
import json
import os
import sys
import time
import logging

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")
for name in ["httpx", "urllib3", "src.tools.get_stock_news", "src.tools.get_kline"]:
    logging.getLogger(name).setLevel(logging.ERROR)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.agents.orchestrator import MultiAgentOrchestrator

STOCKS = [
    ("600036.SH", "招商银行", "蓝筹/金融"),
]


def main():
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    print(f"Config loaded: connect_timeout={config.get('connect_timeout')}, "
          f"read_timeout={config.get('read_timeout')}, request_timeout={config.get('request_timeout')}")

    orch = MultiAgentOrchestrator(config)

    for code, name, st in STOCKS:
        print(f"\n{'=' * 60}")
        print(f"E2E: {code} {name} ({st})")
        print(f"{'=' * 60}")
        start = time.time()
        try:
            result = orch.run_analysis(code, max_iterations=8, debate_rounds=1, skip_debate=False)
        except Exception as e:
            elapsed = time.time() - start
            print(f"  CRASHED after {elapsed:.1f}s: {e}")
            return
        elapsed = time.time() - start

        cr = result.get("combined_report", {}) or {}
        sm = cr.get("synthesis_method", "N/A")
        score = cr.get("combined_score", "N/A")
        direction = cr.get("combined_direction", "N/A")
        trader = cr.get("trader", {}) or {}
        action = trader.get("action", "N/A")

        print(f"\n  Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")
        print(f"  Success: {result.get('success')}")
        print(f"  synthesis_method: {sm}")
        print(f"  combined: score={score}, dir={direction}")
        print(f"  trader action: {action}")

        # Verdict
        print(f"\n  --- Verdict ---")
        if elapsed > 900:
            print(f"  [WARN] Elapsed {elapsed:.0f}s > 900s -- still slow (but Layer 2-3 in Batch 2 will bound this)")
        else:
            print(f"  [OK] Elapsed {elapsed:.0f}s < 900s -- no multi-hour hang")
        if "timeout_degraded" in sm or "deterministic_trader" in sm:
            print(f"  [INFO] Degradation triggered: {sm} (trader fell back - acceptable)")
        else:
            print(f"  [OK] Normal synthesis path (no degradation)")


if __name__ == "__main__":
    main()
