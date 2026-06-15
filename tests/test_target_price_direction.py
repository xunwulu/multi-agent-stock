"""
Tests for direction vs target_price auto-correction in quality.py.

When the technical analyst LLM outputs a contradictory target_price
(e.g. direction=bearish but target_price >= latest_close), quality.py
should auto-correct the target rather than just flag an error.

Auto-correction rules:
  bullish + target <= latest_close -> max(weak_resistance * 1.05, latest_close * 1.05)
  bearish + target >= latest_close -> min(weak_support * 0.95, latest_close * 0.95)
"""
import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.infra.quality import validate_analyst_output


def make_tech_json(
    score=60,
    direction="bullish",
    latest_close=10.0,
    target_price=16.0,
    strong_support=6.0,
    weak_support=8.0,
    weak_resistance=12.0,
    strong_resistance=15.0,
    **extra,
):
    """Build a minimal valid technical analyst JSON with latest_close."""
    base = {
        "score": score,
        "direction": direction,
        "latest_close": latest_close,
        "short_term_trend": "温和上涨",
        "mid_term_trend": "多头排列",
        "long_term_trend": "上升趋势",
        "trend": "综合趋势描述",
        "strong_support": strong_support,
        "weak_support": weak_support,
        "weak_resistance": weak_resistance,
        "strong_resistance": strong_resistance,
        "stop_loss_price": 9.0,
        "target_price": target_price,
        "risk_reward_ratio": "1:2",
        "volume_signal": "放量",
        "turnover_signal": "正常",
        "macd_signal": "golden_cross",
        "macd_divergence": "none",
        "kdj_signal": "neutral",
        "kdj_divergence": "none",
        "rsi_signal": "neutral",
        "rsi_divergence": "none",
        "kline_patterns": [],
        "money_flow_signal": "neutral",
        "money_flow_summary": "资金流向描述",
        "relative_strength": "outperform",
        "industry_comparison": "跑赢行业",
        "ma_pattern": "bullish_alignment",
        "weekly_signal": "一致",
        "resonance": "none",
        "scoring_breakdown": {
            "trend_ma": 7,
            "trend_macd": 7,
            "trend_price_position": 7,
            "signal_macd": 7,
            "signal_kdj": 7,
            "signal_rsi": 5,
            "volume_price": 7,
            "volume_turnover": 7,
            "relative_vs_index": 7,
            "relative_volatility": 7,
            "risk_reward": 5,
        },
        "key_observations": ["观察1", "观察2", "观察3"],
        "summary": "总结",
        "scenario_analysis": {
            "bullish": {"trigger": "t", "target": 18, "probability": 30},
            "base": {"trigger": "t", "target": 15, "probability": 40},
            "bearish": {"trigger": "t", "target": 10, "probability": 30},
        },
        "failure_conditions": [{"condition": "c", "action": "a"}],
        "data_freshness": {
            "kline_latest": "2026-05-14",
            "daily_basic_latest": "2026-05-14",
            "moneyflow_latest": "2026-05-14",
        },
    }
    base.update(extra)
    return base


def run_validation(jd):
    return validate_analyst_output(json.dumps(jd, ensure_ascii=False), "technical")


def test_bearish_target_above_close_autocorrect():
    """bearish + target >= latest_close should auto-correct downward."""
    # direction=bearish, latest_close=10, target=11 (contradiction), weak_support=8
    jd = make_tech_json(
        direction="bearish",
        latest_close=10.0,
        target_price=11.0,
        weak_support=8.0,
        stop_loss_sell=11.5,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    # corrected = min(8 * 0.95, 10 * 0.95) = min(7.6, 9.5) = 7.6
    assert corrected["target_price"] == 7.6, (
        f"Expected 7.6, got {corrected['target_price']}"
    )
    # valid should stay True (warning, not error)
    assert result["valid"] is True, (
        f"Should remain valid after auto-correct, errors: {result.get('errors')}"
    )
    autocorr = [w for w in result.get("warnings", []) if "auto-corrected target" in w]
    assert len(autocorr) == 1, f"Expected 1 auto-correct warning, got {autocorr}"
    print(f"PASS: bearish target {11.0} -> {corrected['target_price']}")


def test_bullish_target_below_close_autocorrect():
    """bullish + target <= latest_close should auto-correct upward."""
    # direction=bullish, latest_close=10, target=9 (contradiction), weak_resistance=12
    jd = make_tech_json(
        direction="bullish",
        latest_close=10.0,
        target_price=9.0,
        weak_resistance=12.0,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    # corrected = max(12 * 1.05, 10 * 1.05) = max(12.6, 10.5) = 12.6
    assert corrected["target_price"] == 12.6, (
        f"Expected 12.6, got {corrected['target_price']}"
    )
    assert result["valid"] is True, (
        f"Should remain valid after auto-correct, errors: {result.get('errors')}"
    )
    autocorr = [w for w in result.get("warnings", []) if "auto-corrected target" in w]
    assert len(autocorr) == 1, f"Expected 1 auto-correct warning, got {autocorr}"
    print(f"PASS: bullish target {9.0} -> {corrected['target_price']}")


def test_bearish_target_correct_no_change():
    """bearish + target < latest_close (consistent) should NOT be corrected."""
    jd = make_tech_json(
        direction="bearish",
        latest_close=10.0,
        target_price=8.0,
        weak_support=8.0,
        stop_loss_sell=11.5,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    assert corrected["target_price"] == 8.0, "Consistent target should be untouched"
    autocorr = [w for w in result.get("warnings", []) if "auto-corrected target" in w]
    assert len(autocorr) == 0, f"Should not auto-correct consistent target: {autocorr}"
    print("PASS: consistent bearish target untouched")


def test_bullish_target_correct_no_change():
    """bullish + target > latest_close (consistent) should NOT be corrected."""
    jd = make_tech_json(
        direction="bullish",
        latest_close=10.0,
        target_price=13.0,
        weak_resistance=12.0,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    assert corrected["target_price"] == 13.0, "Consistent target should be untouched"
    autocorr = [w for w in result.get("warnings", []) if "auto-corrected target" in w]
    assert len(autocorr) == 0, f"Should not auto-correct consistent target: {autocorr}"
    print("PASS: consistent bullish target untouched")


def test_bearish_autocorrect_prefers_lower_of_support_and_close():
    """bearish correction takes min(weak_support*0.95, close*0.95)."""
    # weak_support=9.5 is close to latest_close=10
    # min(9.5*0.95, 10*0.95) = min(9.025, 9.5) = 9.025
    jd = make_tech_json(
        direction="bearish",
        latest_close=10.0,
        target_price=11.0,
        weak_support=9.5,
        stop_loss_sell=11.5,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    assert corrected["target_price"] == 9.03, (
        f"Expected 9.03 (9.5*0.95 rounded), got {corrected['target_price']}"
    )
    print(f"PASS: bearish min() logic -> {corrected['target_price']}")


def test_bullish_autocorrect_prefers_higher_of_resistance_and_close():
    """bullish correction takes max(weak_resistance*1.05, close*1.05)."""
    # weak_resistance=9 (below close=10, abnormal but possible)
    # max(9*1.05, 10*1.05) = max(9.45, 10.5) = 10.5
    jd = make_tech_json(
        direction="bullish",
        latest_close=10.0,
        target_price=8.0,
        weak_resistance=9.0,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    assert corrected["target_price"] == 10.5, (
        f"Expected 10.5 (close*1.05, higher than weak_r*1.05), got {corrected['target_price']}"
    )
    print(f"PASS: bullish max() logic -> {corrected['target_price']}")


def test_bearish_autocorrect_with_none_support_falls_back_to_close():
    """bearish with weak_support=None falls back to latest_close * 0.95."""
    jd = make_tech_json(
        direction="bearish",
        latest_close=10.0,
        target_price=11.0,
        weak_support=None,
        strong_support=None,
        stop_loss_sell=11.5,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    # No support -> only candidate is latest_close * 0.95 = 9.5
    assert corrected["target_price"] == 9.5, (
        f"Expected 9.5 (close*0.95 fallback), got {corrected['target_price']}"
    )
    assert result["valid"] is True, "Should remain valid after fallback correction"
    print(f"PASS: None support fallback -> {corrected['target_price']}")


def test_bullish_autocorrect_with_none_resistance_falls_back_to_close():
    """bullish with weak_resistance=None falls back to latest_close * 1.05."""
    jd = make_tech_json(
        direction="bullish",
        latest_close=10.0,
        target_price=8.0,
        weak_resistance=None,
        strong_resistance=None,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    assert corrected["target_price"] == 10.5, (
        f"Expected 10.5 (close*1.05 fallback), got {corrected['target_price']}"
    )
    print(f"PASS: None resistance fallback -> {corrected['target_price']}")


def test_real_bug_002131_bearish_target_above_close():
    """Real-world case: 002131.SZ had direction=bearish but target_price=7.17 > close=6.63."""
    jd = make_tech_json(
        direction="bearish",
        latest_close=6.63,
        target_price=7.17,  # contradiction: above close
        strong_support=5.5,
        weak_support=6.0,
        weak_resistance=7.17,
        strong_resistance=8.0,
        stop_loss_sell=7.5,
    )
    result = run_validation(jd)
    corrected = result["json_data"]
    # corrected = min(6.0 * 0.95, 6.63 * 0.95) = min(5.7, 6.2985) = 5.7
    assert corrected["target_price"] == 5.7, (
        f"Expected 5.7 (weak_support*0.95), got {corrected['target_price']}"
    )
    # Most importantly: the corrected target is now BELOW close (consistent with bearish)
    assert corrected["target_price"] < 6.63, "Corrected bearish target must be below close"
    assert result["valid"] is True, "Real bug case should remain valid after correction"
    print(f"PASS: real bug 002131 corrected 7.17 -> {corrected['target_price']} (below close)")


if __name__ == "__main__":
    print("=" * 50)
    print("Target Price vs Direction Auto-Correct Tests")
    print("=" * 50)

    tests = [
        test_bearish_target_above_close_autocorrect,
        test_bullish_target_below_close_autocorrect,
        test_bearish_target_correct_no_change,
        test_bullish_target_correct_no_change,
        test_bearish_autocorrect_prefers_lower_of_support_and_close,
        test_bullish_autocorrect_prefers_higher_of_resistance_and_close,
        test_bearish_autocorrect_with_none_support_falls_back_to_close,
        test_bullish_autocorrect_with_none_resistance_falls_back_to_close,
        test_real_bug_002131_bearish_target_above_close,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Result: {passed}/{passed+failed} passed")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"FAILED: {failed} tests")
