"""
Verify the 4 bug fixes (P0-P3) via E2E analysis on 4 representative stocks.

Stocks (captain's pick):
  600036.SH  招商银行    - validate P0 (trader timeout: was 1584s)
  600525.SH  ST长园      - validate P2 (dcf_cross_check on ST/governance)
  300503.SZ  昊志机电    - validate P3 (SZ weekly kline, was 0 records)
  600745.SH  ST闻泰      - validate P1 (risk debate + target_price direction)

Per-stock verification metrics extracted:
  P0: elapsed_s + synthesis_method (no forced deterministic fallback)
  P1: tech target_price vs latest_close consistency + risk_debate ran
  P2: fund dcf_cross_check present + no "dcf_cross_check required" error
  P3: weekly kline count (SZ stock should now have data or daily-resample)
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
    ("600525.SH", "ST长园", "ST风险"),
    ("300503.SZ", "昊志机电", "中小盘/SZ"),
    ("600745.SH", "ST闻泰", "ST/风险辩论"),
]


def extract_verification(result, elapsed_s):
    """Pull the P0-P3 verification signals from one analysis result."""
    v = {"elapsed_s": round(elapsed_s, 1)}

    # P0: timeout + fallback path
    cr = result.get("combined_report", {}) or {}
    v["synthesis_method"] = cr.get("synthesis_method", "N/A")
    v["p0_timeout_ok"] = elapsed_s < 900  # under 15 min = no 26-min hang

    # P1: tech target_price direction consistency
    tech = (result.get("tech_report", {}) or {}).get("json_data") or {}
    target = tech.get("target_price")
    close = tech.get("latest_close")
    direction = tech.get("direction")
    v["tech_direction"] = direction
    v["tech_target"] = target
    v["tech_close"] = close
    if target is not None and close is not None and direction:
        if direction == "bearish":
            v["p1_target_consistent"] = target < close
        elif direction == "bullish":
            v["p1_target_consistent"] = target > close
        else:
            v["p1_target_consistent"] = True
    else:
        v["p1_target_consistent"] = "N/A"

    # P1: risk debate ran (the core fix from prior round + this round's gate)
    rd = result.get("risk_result")
    v["risk_debate_ran"] = bool(rd)
    rm = result.get("risk_result") or {}
    v["risk_level"] = (rm or {}).get("risk_level", "N/A")

    # P2: dcf_cross_check presence + validation errors
    fund = (result.get("fund_report", {}) or {}).get("json_data") or {}
    v["dcf_cross_check_present"] = "dcf_cross_check" in fund and fund.get("dcf_cross_check") is not None
    fund_val = (result.get("fund_report", {}) or {}).get("validation") or {}
    fund_errors = fund_val.get("errors", []) if isinstance(fund_val, dict) else []
    v["dcf_error"] = next(
        (e for e in fund_errors if "dcf_cross_check" in str(e)), None
    )

    # P3: weekly kline — we cannot directly read tool call counts from result,
    # but tech_report.weekly_signal reflects whether weekly data was usable.
    v["weekly_signal"] = tech.get("weekly_signal", "N/A")

    # combined basics
    v["combined_score"] = cr.get("combined_score", "N/A")
    v["combined_dir"] = cr.get("combined_direction", "N/A")
    v["success"] = result.get("success", False)
    return v


def test_stock(orch, code, name, stock_type):
    print(f"\n{'=' * 60}")
    print(f"Testing: {code} {name} ({stock_type})")
    print(f"{'=' * 60}")
    start = time.time()
    try:
        result = orch.run_analysis(code, max_iterations=8, debate_rounds=1, skip_debate=False)
    except Exception as e:
        elapsed = time.time() - start
        print(f"  CRASHED after {elapsed:.1f}s: {e}")
        return {"code": code, "name": name, "type": stock_type, "crashed": True,
                "error": str(e), "elapsed_s": round(elapsed, 1)}

    elapsed = time.time() - start
    v = extract_verification(result, elapsed)
    v.update({"code": code, "name": name, "type": stock_type, "crashed": False})

    print(f"  Time: {v['elapsed_s']}s  |  success={v['success']}")
    print(f"  [P0 timeout] under 900s={v['p0_timeout_ok']}  method={v['synthesis_method']}")
    print(f"  [P1 target]   dir={v['tech_direction']} target={v['tech_target']} close={v['tech_close']} consistent={v['p1_target_consistent']}")
    print(f"  [P1 risk]     risk_debate_ran={v['risk_debate_ran']} risk_level={v['risk_level']}")
    print(f"  [P2 dcf]      present={v['dcf_cross_check_present']} error={v['dcf_error']}")
    print(f"  [P3 weekly]   weekly_signal={v['weekly_signal']}")
    print(f"  combined: score={v['combined_score']} dir={v['combined_dir']}")
    return v


def main():
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    print(f"Config: model={config['model']} request_timeout={config.get('request_timeout', 'N/A')}")

    orch = MultiAgentOrchestrator(config)
    results = []
    total_start = time.time()

    for i, (code, name, st) in enumerate(STOCKS):
        results.append(test_stock(orch, code, name, st))
        if i < len(STOCKS) - 1:
            print(f"\n-- Cooldown 30s before next stock --")
            time.sleep(30)

    total = time.time() - total_start

    print(f"\n{'=' * 70}")
    print("VERIFICATION SUMMARY (4 fixes)")
    print(f"{'=' * 70}")
    print(f"{'Stock':<10} {'Time':>7} {'P0<900s':<8} {'P1 consistent':<14} {'RiskDebate':<11} "
          f"{'P2 dcf':<8} {'P3 weekly':<10} {'Score':<7}")
    print("-" * 70)
    for r in results:
        if r.get("crashed"):
            print(f"{r['name']:<10} {r.get('elapsed_s',0):>6.0f}s CRASHED: {r.get('error','')[:40]}")
            continue
        p0 = "OK" if r.get("p0_timeout_ok") else "FAIL"
        p1 = str(r.get("p1_target_consistent"))
        rd = "ran" if r.get("risk_debate_ran") else "SKIP"
        p2 = "OK" if r.get("dcf_cross_check_present") and not r.get("dcf_error") else "issue"
        p3 = str(r.get("weekly_signal"))[:9]
        print(f"{r['name']:<10} {r.get('elapsed_s',0):>6.0f}s {p0:<8} {p1:<14} {rd:<11} "
              f"{p2:<8} {p3:<10} {r.get('combined_score','?'):<7}")
    print("-" * 70)
    print(f"Total: {total:.0f}s ({total/60:.1f} min)")

    out = os.path.join(project_root, "output", "verify_4fixes_results.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"Results saved: {out}")


if __name__ == "__main__":
    main()
