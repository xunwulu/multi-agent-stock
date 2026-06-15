"""
Phase A: Run 3 representative stocks, save full results, generate HTML reports.
Captain reviews HTML reports to evaluate analysis quality.
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
for name in ["httpx", "urllib3", "src.tools.get_stock_news", "src.tools.get_kline"]:
    logging.getLogger(name).setLevel(logging.ERROR)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.agents.orchestrator import MultiAgentOrchestrator

# 3 stocks for captain review: blue-chip, growth, cyclical
STOCKS = [
    ("600036.SH", "招商银行"),
    ("300750.SZ", "宁德时代"),
    ("601225.SH", "陕西煤业"),
]

OUTPUT_DIR = os.path.join(project_root, "output", "phase_a_review")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def main():
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path) as f:
        config = json.load(f)

    orch = MultiAgentOrchestrator(config)

    for code, name in STOCKS:
        print(f"\n{'='*50}")
        print(f"Analyzing: {code} {name}")
        print(f"{'='*50}")

        start = time.time()
        result = orch.run_analysis(
            code,
            max_iterations=8,
            debate_rounds=1,
            skip_debate=False,
        )
        elapsed = time.time() - start

        # Save full result
        out_path = os.path.join(OUTPUT_DIR, f"result_{code.replace('.', '_')}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Done: {elapsed:.0f}s -> {os.path.basename(out_path)}")

        # Cooldown between stocks
        print(f"  Cooldown 30s...")
        time.sleep(30)

    # Generate HTML reports
    print(f"\nGenerating HTML reports...")
    sys.path.insert(0, os.path.join(project_root, "scripts"))
    from gen_html_report import process_file

    for code, name in STOCKS:
        result_path = os.path.join(
            OUTPUT_DIR, f"result_{code.replace('.', '_')}.json"
        )
        try:
            html_path = process_file(result_path)
            print(f"  HTML: {os.path.basename(html_path)}")
        except Exception as e:
            print(f"  FAIL {code}: {e}")

    print(f"\nReports saved to: {OUTPUT_DIR}")
    print("Captain: please open the HTML files in a browser to review quality.")


if __name__ == "__main__":
    main()
