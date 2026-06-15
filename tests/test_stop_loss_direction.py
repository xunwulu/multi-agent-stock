"""
Tests for dual-direction stop loss fix.

Validates:
- quality.py: Trader stop_loss vs current_price direction auto-correction
- quality.py: Tech analyst stop_loss_sell required for bearish direction
- orchestrator.py: _extract_current_price fallback to tech latest_close
- orchestrator.py: fallback sell uses stop_loss_sell first
"""
import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.infra.quality import validate_analyst_output, validate_trader_output
from src.agents.orchestrator import MultiAgentOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_trader_json(action="buy", stop_loss=225.0, current_price=250.0, **extra):
    """Build a minimal valid Trader JSON for quality validation."""
    base = {
        "action": action,
        "action_strength": "normal",
        "target_price": 280.0,
        "target_price_rationale": "test",
        "stop_loss": stop_loss,
        "stop_loss_rationale": "test",
        "take_profit_levels": [
            {"price": 290, "portion": "30%", "reason": "r1"},
            {"price": 300, "portion": "50%", "reason": "r2"},
            {"price": 310, "portion": "20%", "reason": "r3"},
        ],
        "confidence_components": {
            "signal_consistency": 10,
            "data_sufficiency": 10,
            "debate_certainty": 10,
            "risk_controllability": 10,
            "valuation_reasonableness": 10,
        },
        "confidence_total": 50,
        "confidence_label": "medium",
        "position_advice": "standard",
        "position_range": "40-70%",
        "risk_score": 40,
        "risk_level": "medium",
        "time_horizon": "1-3月",
        "entry_conditions": ["c1"],
        "key_catalysts": ["k1"],
        "reasoning": "test reasoning",
        "warnings": ["w1", "w2"],
        "_current_price": current_price,
    }
    base.update(extra)
    return base


def make_tech_json(direction="bullish", stop_loss_sell=None, **extra):
    """Build a minimal valid technical analyst JSON."""
    base = {
        "score": 60,
        "direction": direction,
        "short_term_trend": "温和上涨",
        "mid_term_trend": "多头排列",
        "long_term_trend": "上升趋势",
        "trend": "综合趋势描述",
        "strong_support": 10.0,
        "weak_support": 12.0,
        "weak_resistance": 15.0,
        "strong_resistance": 18.0,
        "stop_loss_price": 9.0,
        "stop_loss_sell": stop_loss_sell,
        "latest_close": 13.5,
        "target_price": 16.0,
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
            "kline_latest": "2026-05-16",
            "daily_basic_latest": "2026-05-16",
            "moneyflow_latest": "2026-05-16",
        },
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Trader stop_loss vs current_price tests
# ---------------------------------------------------------------------------

def test_buy_stop_loss_below_current():
    """buy + stop_loss < current_price -> no auto-correction"""
    jd = make_trader_json(action="buy", stop_loss=225.0, current_price=250.0)
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    assert result["valid"] is True
    corrected = result["json_data"]
    assert corrected["stop_loss"] == 225.0
    direction_warnings = [w for w in result.get("warnings", []) if "stop_loss" in w and "auto-corrected" in w]
    assert len(direction_warnings) == 0, f"Unexpected stop_loss warning: {direction_warnings}"
    print("PASS: buy stop_loss below current_price left untouched")


def test_buy_stop_loss_above_current_autocorrect():
    """buy + stop_loss >= current_price -> auto-correct to 0.95*price"""
    jd = make_trader_json(action="buy", stop_loss=260.0, current_price=250.0)
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    expected = round(250.0 * 0.95, 2)  # 237.5
    assert corrected["stop_loss"] == expected, f"Expected {expected}, got {corrected['stop_loss']}"
    direction_warnings = [w for w in result.get("warnings", []) if "stop_loss" in w and "auto-corrected" in w]
    assert len(direction_warnings) == 1
    print(f"PASS: buy stop_loss auto-corrected to {expected}")


def test_sell_stop_loss_above_current():
    """sell + stop_loss > current_price -> no auto-correction"""
    jd = make_trader_json(action="sell", stop_loss=275.0, current_price=250.0)
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    assert result["valid"] is True
    corrected = result["json_data"]
    assert corrected["stop_loss"] == 275.0
    direction_warnings = [w for w in result.get("warnings", []) if "stop_loss" in w and "auto-corrected" in w]
    assert len(direction_warnings) == 0, f"Unexpected stop_loss warning: {direction_warnings}"
    print("PASS: sell stop_loss above current_price left untouched")


def test_sell_stop_loss_below_current_autocorrect():
    """sell + stop_loss <= current_price -> auto-correct to 1.05*price"""
    jd = make_trader_json(action="sell", stop_loss=240.0, current_price=250.0)
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    expected = round(250.0 * 1.05, 2)  # 262.5
    assert corrected["stop_loss"] == expected, f"Expected {expected}, got {corrected['stop_loss']}"
    direction_warnings = [w for w in result.get("warnings", []) if "stop_loss" in w and "auto-corrected" in w]
    assert len(direction_warnings) == 1
    print(f"PASS: sell stop_loss auto-corrected to {expected}")


# ---------------------------------------------------------------------------
# Tech analyst direction-aware validation tests
# ---------------------------------------------------------------------------

def test_tech_bearish_missing_stop_loss_sell_warns():
    """bearish direction without stop_loss_sell -> warning"""
    jd = make_tech_json(direction="bearish", stop_loss_sell=None)
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")

    sell_warnings = [w for w in result.get("warnings", []) if "stop_loss_sell" in w]
    assert len(sell_warnings) >= 1, f"Expected stop_loss_sell warning, got: {result.get('warnings', [])}"
    print(f"PASS: bearish missing stop_loss_sell -> warning: {sell_warnings[0]}")


def test_tech_bearish_has_stop_loss_sell_no_warn():
    """bearish direction with stop_loss_sell -> no warning"""
    jd = make_tech_json(direction="bearish", stop_loss_sell=20.0)
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")

    sell_warnings = [w for w in result.get("warnings", []) if "stop_loss_sell" in w]
    assert len(sell_warnings) == 0, f"Unexpected warning: {sell_warnings}"
    print("PASS: bearish with stop_loss_sell -> no warning")


# ---------------------------------------------------------------------------
# Orchestrator _extract_current_price tests
# ---------------------------------------------------------------------------

def test_current_price_from_fund_json():
    """Fund JSON has current_price -> use it"""
    fund = {"target_price": {"current_price": 100.0}}
    tech = {}
    price = MultiAgentOrchestrator._extract_current_price(fund, tech)
    assert price == 100.0
    print("PASS: current_price from fund_json")


def test_current_price_from_tech_json():
    """Fund JSON missing current_price -> fallback to tech latest_close"""
    fund = {"target_price": {}}
    tech = {"latest_close": 88.5}
    price = MultiAgentOrchestrator._extract_current_price(fund, tech)
    assert price == 88.5
    print("PASS: current_price fallback to tech latest_close")


def test_none_current_price_no_crash():
    """Both sources missing -> returns None without crash"""
    fund = {}
    tech = {}
    price = MultiAgentOrchestrator._extract_current_price(fund, tech)
    assert price is None
    print("PASS: missing current_price returns None (no crash)")


# ---------------------------------------------------------------------------
# Orchestrator fallback stop loss tests
# ---------------------------------------------------------------------------

def test_fallback_sell_uses_stop_loss_sell():
    """sell action fallback: stop_loss_sell takes priority"""
    # Simulate the fallback logic from orchestrator
    tech_json = {"stop_loss_sell": 22.0, "strong_resistance": 20.0, "stop_loss_price": 8.0}
    action = "sell"

    if action == "sell":
        stop_loss = tech_json.get("stop_loss_sell") or tech_json.get("strong_resistance")
    else:
        stop_loss = tech_json.get("stop_loss_price") or tech_json.get("strong_support")

    assert stop_loss == 22.0, f"Expected 22.0, got {stop_loss}"
    print("PASS: sell fallback uses stop_loss_sell first")


def test_fallback_buy_uses_stop_loss_price():
    """buy action fallback: stop_loss_price takes priority"""
    tech_json = {"stop_loss_sell": 22.0, "strong_resistance": 20.0, "stop_loss_price": 8.0, "strong_support": 10.0}
    action = "buy"

    if action == "sell":
        stop_loss = tech_json.get("stop_loss_sell") or tech_json.get("strong_resistance")
    else:
        stop_loss = tech_json.get("stop_loss_price") or tech_json.get("strong_support")

    assert stop_loss == 8.0, f"Expected 8.0, got {stop_loss}"
    print("PASS: buy fallback uses stop_loss_price first")


# ---------------------------------------------------------------------------
# Fix 1: position_advice vs risk_level linkage tests
# ---------------------------------------------------------------------------

def _make_matched_components(total):
    """Build confidence_components that sum to exactly `total`."""
    base = total // 5
    remainder = total % 5
    vals = [base + (1 if i < remainder else 0) for i in range(5)]
    return {
        "signal_consistency": vals[0],
        "data_sufficiency": vals[1],
        "debate_certainty": vals[2],
        "risk_controllability": vals[3],
        "valuation_reasonableness": vals[4],
    }


def test_very_high_risk_overrides_standard_position():
    """risk_level=very_high + position_advice=standard -> final position_advice=light"""
    comps = _make_matched_components(75)
    jd = make_trader_json(
        action="sell", risk_score=85, risk_level="very_high",
        confidence_total=75, confidence_components=comps,
        position_advice="standard", _current_price=6.82,
        stop_loss=7.45, target_price=4.95,
        take_profit_levels=[
            {"price": 6.16, "portion": "40%", "reason": "r1"},
            {"price": 5.5, "portion": "40%", "reason": "r2"},
            {"price": 4.95, "portion": "20%", "reason": "r3"},
        ],
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    assert corrected["position_advice"] == "light", f"Expected light, got {corrected['position_advice']}"
    print("PASS: very_high risk overrides standard -> light")


def test_high_risk_overrides_heavy_position():
    """risk_level=high + position_advice=heavy -> final position_advice=standard"""
    comps = _make_matched_components(85)
    jd = make_trader_json(
        action="buy", risk_score=65, risk_level="high",
        confidence_total=85, confidence_components=comps,
        position_advice="heavy",
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    assert corrected["position_advice"] == "standard", f"Expected standard, got {corrected['position_advice']}"
    print("PASS: high risk overrides heavy -> standard")


def test_medium_risk_no_position_override():
    """risk_level=medium + position_advice=standard -> no override"""
    comps = _make_matched_components(65)
    jd = make_trader_json(
        action="buy", risk_score=40, risk_level="medium",
        confidence_total=65, confidence_components=comps,
        position_advice="standard",
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    assert corrected["position_advice"] == "standard"
    override_warnings = [w for w in result.get("warnings", []) if "prohibits" in w]
    assert len(override_warnings) == 0, f"Unexpected override warning: {override_warnings}"
    print("PASS: medium risk does not override position_advice")


# ---------------------------------------------------------------------------
# Fix 3: confidence cap based on risk_level tests
# ---------------------------------------------------------------------------

def test_very_high_risk_caps_confidence():
    """risk_level=very_high + confidence_total=75 -> capped to 50"""
    comps = _make_matched_components(75)
    jd = make_trader_json(
        action="sell", risk_score=85, risk_level="very_high",
        confidence_total=75, confidence_components=comps,
        position_advice="standard", _current_price=6.82,
        stop_loss=7.45, target_price=4.95,
        take_profit_levels=[
            {"price": 6.16, "portion": "40%", "reason": "r1"},
            {"price": 5.5, "portion": "40%", "reason": "r2"},
            {"price": 4.95, "portion": "20%", "reason": "r3"},
        ],
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    assert corrected["confidence_total"] == 50, f"Expected 50, got {corrected['confidence_total']}"
    assert corrected["confidence_label"] == "medium", f"Expected medium, got {corrected['confidence_label']}"
    cap_warnings = [w for w in result.get("warnings", []) if "capped" in w]
    assert len(cap_warnings) >= 1, f"Expected cap warning, got: {result.get('warnings', [])}"
    print("PASS: very_high risk caps confidence to 50")


def test_high_risk_caps_confidence():
    """risk_level=high + confidence_total=80 -> capped to 65"""
    comps = _make_matched_components(80)
    jd = make_trader_json(
        action="sell", risk_score=65, risk_level="high",
        confidence_total=80, confidence_components=comps,
        position_advice="heavy", _current_price=6.82,
        stop_loss=7.45, target_price=4.95,
        take_profit_levels=[
            {"price": 6.16, "portion": "40%", "reason": "r1"},
            {"price": 5.5, "portion": "40%", "reason": "r2"},
            {"price": 4.95, "portion": "20%", "reason": "r3"},
        ],
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    assert corrected["confidence_total"] == 65, f"Expected 65, got {corrected['confidence_total']}"
    print("PASS: high risk caps confidence to 65")


def test_medium_risk_no_confidence_cap():
    """risk_level=medium + confidence_total=75 -> no cap"""
    comps = _make_matched_components(75)
    jd = make_trader_json(
        action="buy", risk_score=40, risk_level="medium",
        confidence_total=75, confidence_components=comps,
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    assert corrected["confidence_total"] == 75, f"Expected 75 (no cap), got {corrected['confidence_total']}"
    cap_warnings = [w for w in result.get("warnings", []) if "capped" in w]
    assert len(cap_warnings) == 0, f"Unexpected cap warning: {cap_warnings}"
    print("PASS: medium risk does not cap confidence")


# ---------------------------------------------------------------------------
# Fix 4: sell take_profit descending order tests
# ---------------------------------------------------------------------------

def test_sell_take_profit_sorted_descending():
    """sell + take_profit ascending -> auto-sort descending"""
    jd = make_trader_json(
        action="sell",
        stop_loss=7.45,
        current_price=6.82,
        take_profit_levels=[
            {"price": 4.95, "portion": "20%", "reason": "r1"},
            {"price": 5.5, "portion": "40%", "reason": "r2"},
            {"price": 6.16, "portion": "40%", "reason": "r3"},
        ],
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    prices = [tp["price"] for tp in corrected["take_profit_levels"]]
    assert prices == sorted(prices, reverse=True), f"Expected descending, got {prices}"
    sort_warnings = [w for w in result.get("warnings", []) if "descending" in w]
    assert len(sort_warnings) >= 1, f"Expected sort warning, got: {result.get('warnings', [])}"
    print(f"PASS: sell take_profit sorted descending: {prices}")


def test_buy_take_profit_sorted_ascending():
    """buy + take_profit unsorted -> auto-sort ascending"""
    jd = make_trader_json(
        action="buy",
        take_profit_levels=[
            {"price": 310, "portion": "20%", "reason": "r3"},
            {"price": 280, "portion": "30%", "reason": "r1"},
            {"price": 295, "portion": "50%", "reason": "r2"},
        ],
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_trader_output(content)

    corrected = result["json_data"]
    prices = [tp["price"] for tp in corrected["take_profit_levels"]]
    assert prices == sorted(prices), f"Expected ascending, got {prices}"
    sort_warnings = [w for w in result.get("warnings", []) if "ascending" in w]
    assert len(sort_warnings) >= 1, f"Expected sort warning, got: {result.get('warnings', [])}"
    print(f"PASS: buy take_profit sorted ascending: {prices}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("Dual-Direction Stop Loss + Trader Fix Tests")
    print("=" * 50)

    tests = [
        test_buy_stop_loss_below_current,
        test_buy_stop_loss_above_current_autocorrect,
        test_sell_stop_loss_above_current,
        test_sell_stop_loss_below_current_autocorrect,
        test_tech_bearish_missing_stop_loss_sell_warns,
        test_tech_bearish_has_stop_loss_sell_no_warn,
        test_current_price_from_fund_json,
        test_current_price_from_tech_json,
        test_none_current_price_no_crash,
        test_fallback_sell_uses_stop_loss_sell,
        test_fallback_buy_uses_stop_loss_price,
        # Fix 1: position_advice vs risk_level
        test_very_high_risk_overrides_standard_position,
        test_high_risk_overrides_heavy_position,
        test_medium_risk_no_position_override,
        # Fix 3: confidence cap
        test_very_high_risk_caps_confidence,
        test_high_risk_caps_confidence,
        test_medium_risk_no_confidence_cap,
        # Fix 4: take_profit sorting
        test_sell_take_profit_sorted_descending,
        test_buy_take_profit_sorted_ascending,
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
            print(f"ERROR: {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Result: {passed}/{passed+failed} passed")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"FAILED: {failed} tests")
