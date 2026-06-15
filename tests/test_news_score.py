"""
Test news score auto-correct formula in quality.py.
Verifies that news scoring uses: score = 50 + sum(all breakdown values)
This works whether the LLM expresses negative factors as positive or negative numbers.

Convention A (positive values): negative_events=10, risk_level=6
  -> score = 50 + sum = 50 + 15 + 10 + 10 + 10 + 3 + 6 = 104 -> clamp 100
  WRONG for convention A! Must use: 50 + positive - negative + ...

Convention B (negative for subtractors): negative_events=-9, risk_level=-6
  -> score = 50 + sum = 50 + 9 + (-9) + 10 + 10 + 3 + (-6) = 67
  This is what the auto-correct uses now.
"""
import sys
import os
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.infra.quality import validate_analyst_output


def make_news_json(score, breakdown):
    data = {
        "score": score,
        "direction": "bullish",
        "news_analyzed": 5,
        "sentiment": "mixed",
        "key_events": [],
        "risk_events": [],
        "positive_factors": ["test"],
        "negative_factors": ["test"],
        "scoring_breakdown": breakdown,
        "summary": "test summary",
    }
    return json.dumps(data, ensure_ascii=False)


def test_news_positive_convention():
    """LLM uses positive values for negative fields -> auto-flipped to negative."""
    breakdown = {
        "positive_events": 15,
        "negative_events": 10,  # wrong sign, should be negative
        "event_timeliness": 10,
        "event_impact": 10,
        "sentiment_alignment": 3,
        "risk_level": 6,  # wrong sign, should be negative
    }
    # After sign flip: negative_events -> -10, risk_level -> -6
    # sum = 15+(-10)+10+10+3+(-6) = 22, score = 50+22 = 72
    expected = 72
    result = validate_analyst_output(make_news_json(100, breakdown), "news")
    assert result["json_data"]["score"] == expected, (
        f"Expected {expected}, got {result['json_data']['score']}"
    )
    # Verify sign flip warnings were generated
    flip_warnings = [w for w in result["warnings"] if "auto-flipped" in w]
    assert len(flip_warnings) == 2, (
        f"Expected 2 flip warnings, got {flip_warnings}"
    )
    print(f"[PASS] positive convention: auto-flipped, score={expected}")


def test_news_negative_convention():
    """LLM uses negative values for subtractors (negative_events, risk_level)."""
    breakdown = {
        "positive_events": 9,
        "negative_events": -9,
        "event_timeliness": 10,
        "event_impact": 10,
        "sentiment_alignment": 3,
        "risk_level": -6,
    }
    # sum = 9+(-9)+10+10+3+(-6) = 17, score = 50+17 = 67
    expected = 67
    result = validate_analyst_output(make_news_json(67, breakdown), "news")
    assert result["json_data"]["score"] == expected, (
        f"Expected {expected}, got {result['json_data']['score']}"
    )
    assert not any("auto-corrected" in w for w in result["warnings"]), (
        f"Unexpected auto-correct: {result['warnings']}"
    )
    print(f"[PASS] negative convention: score={expected} (no auto-correct)")


def test_news_auto_correct_from_wrong():
    """Wrong score gets auto-corrected."""
    breakdown = {
        "positive_events": 12,
        "negative_events": -6,
        "event_timeliness": 10,
        "event_impact": 6,
        "sentiment_alignment": 7,
        "risk_level": -3,
    }
    # sum = 12+(-6)+10+6+7+(-3) = 26, score = 50+26 = 76
    expected = 76
    result = validate_analyst_output(make_news_json(0, breakdown), "news")
    assert result["json_data"]["score"] == expected, (
        f"Expected {expected}, got {result['json_data']['score']}"
    )
    corrected = [w for w in result["warnings"] if "auto-corrected" in w]
    assert len(corrected) == 1, f"Expected 1 auto-correct, got {corrected}"
    print(f"[PASS] auto-corrected from 0 to {expected}")


def test_news_score_clamped_high():
    """Score above 100 clamped."""
    breakdown = {
        "positive_events": 15,
        "negative_events": 0,
        "event_timeliness": 10,
        "event_impact": 10,
        "sentiment_alignment": 10,
        "risk_level": 0,
    }
    # sum = 45, score = 95
    result = validate_analyst_output(make_news_json(95, breakdown), "news")
    assert result["json_data"]["score"] == 95
    print("[PASS] score=95 within range")


def test_news_score_low():
    """Very negative breakdown -> score clamped to 0."""
    breakdown = {
        "positive_events": 0,
        "negative_events": -15,
        "event_timeliness": 0,
        "event_impact": 0,
        "sentiment_alignment": 0,
        "risk_level": -10,
    }
    # sum = 0+(-15)+0+0+0+(-10) = -25, score = 50+(-25) = 25
    expected = 25
    result = validate_analyst_output(make_news_json(expected, breakdown), "news")
    assert result["json_data"]["score"] == expected
    print(f"[PASS] low score={expected}")


def test_news_old_bug_72_becomes_72_with_flip():
    """LLM submits positive values for negative fields -> sign flip -> correct 72."""
    breakdown = {
        "positive_events": 15,
        "negative_events": 10,  # wrong sign, auto-flipped to -10
        "event_timeliness": 10,
        "event_impact": 10,
        "sentiment_alignment": 3,
        "risk_level": 6,  # wrong sign, auto-flipped to -6
    }
    # After sign flip: sum = 15+(-10)+10+10+3+(-6) = 22, score = 72
    expected = 72
    result = validate_analyst_output(make_news_json(90, breakdown), "news")
    assert result["json_data"]["score"] == expected, (
        f"Expected {expected}, got {result['json_data']['score']}"
    )
    print(f"[PASS] wrong-sign fields auto-flipped: score={expected}")


def test_news_negative_convention_gives_same_result():
    """Negative convention with same magnitude gives correct 72."""
    breakdown = {
        "positive_events": 15,
        "negative_events": -10,
        "event_timeliness": 10,
        "event_impact": 10,
        "sentiment_alignment": 3,
        "risk_level": -6,
    }
    # sum = 15+(-10)+10+10+3+(-6) = 22, score = 50+22 = 72
    expected = 72
    result = validate_analyst_output(make_news_json(72, breakdown), "news")
    assert result["json_data"]["score"] == expected, (
        f"Expected {expected}, got {result['json_data']['score']}"
    )
    print(f"[PASS] negative convention: 50+sum = {expected}")


def test_tech_score_still_works():
    """Verify tech score auto-correct still works."""
    breakdown = {
        "trend_ma": 10, "trend_macd": 10, "trend_price_position": 0,
        "signal_macd": 10, "signal_kdj": 10, "signal_rsi": 10,
        "volume_price": 10, "volume_turnover": 10,
        "relative_vs_index": 10, "relative_volatility": 10,
        "risk_reward": 10,
    }
    # 11 items sum=100, 100*100/110 = 90.9
    expected = round(100 * 100 / 110, 1)
    tech_json = json.dumps({
        "score": 0,
        "direction": "bullish",
        "latest_close": 10.0,
        "stop_loss_price": 9.0,
        "scoring_breakdown": breakdown,
    }, ensure_ascii=False)
    result = validate_analyst_output(tech_json, "technical")
    assert result["json_data"]["score"] == expected, (
        f"Tech expected {expected}, got {result['json_data']['score']}"
    )
    print(f"[PASS] tech score auto-correct: {expected}")


if __name__ == "__main__":
    tests = [
        test_news_positive_convention,
        test_news_negative_convention,
        test_news_auto_correct_from_wrong,
        test_news_score_clamped_high,
        test_news_score_low,
        test_news_old_bug_72_becomes_72_with_flip,
        test_news_negative_convention_gives_same_result,
        test_tech_score_still_works,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("All tests passed!")
