"""
Tests for price level auto-sorting fix in quality.py
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
    strong_support=10.0,
    weak_support=12.0,
    weak_resistance=15.0,
    strong_resistance=18.0,
    **extra,
):
    """Build a minimal valid technical analyst JSON"""
    base = {
        "score": score,
        "direction": direction,
        "short_term_trend": "温和上涨",
        "mid_term_trend": "多头排列",
        "long_term_trend": "上升趋势",
        "trend": "综合趋势描述",
        "strong_support": strong_support,
        "weak_support": weak_support,
        "weak_resistance": weak_resistance,
        "strong_resistance": strong_resistance,
        "stop_loss_price": 9.0,
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
            "kline_latest": "2026-05-14",
            "daily_basic_latest": "2026-05-14",
            "moneyflow_latest": "2026-05-14",
        },
    }
    base.update(extra)
    return base


def test_price_levels_correctly_sorted():
    """正常排序不应被修改"""
    jd = make_tech_json(strong_support=10, weak_support=12, weak_resistance=15, strong_resistance=18)
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")
    assert result["valid"] is True

    corrected = result["json_data"]
    assert corrected["strong_support"] == 10
    assert corrected["weak_support"] == 12
    assert corrected["weak_resistance"] == 15
    assert corrected["strong_resistance"] == 18
    # Should NOT have auto-correct warning
    price_warnings = [w for w in result.get("warnings", []) if "Price levels" in w]
    assert len(price_warnings) == 0, f"Unexpected warning: {price_warnings}"
    print("PASS: correctly sorted prices left untouched")


def test_price_levels_strong_resistance_lower_than_weak():
    """strong_resistance < weak_resistance 应自动修正"""
    # 300308 实际bug: strong_r=1088 < weak_r=1100
    jd = make_tech_json(
        strong_support=866.0,
        weak_support=951.18,
        weak_resistance=1100.0,
        strong_resistance=1088.88,  # WRONG: should be highest
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")

    corrected = result["json_data"]
    # After sorting: [866.0, 951.18, 1088.88, 1100.0]
    assert corrected["strong_support"] == 866.0
    assert corrected["weak_support"] == 951.18
    assert corrected["weak_resistance"] == 1088.88
    assert corrected["strong_resistance"] == 1100.0

    # Should have auto-correct warning
    price_warnings = [w for w in result.get("warnings", []) if "Auto-corrected" in w]
    assert len(price_warnings) == 1, f"Expected auto-correct warning, got: {result.get('warnings', [])}"
    print(f"PASS: swapped resistance auto-corrected. Warning: {price_warnings[0]}")


def test_price_levels_completely_reversed():
    """完全逆序应自动修正"""
    jd = make_tech_json(
        strong_support=20.0,   # highest
        weak_support=18.0,
        weak_resistance=12.0,
        strong_resistance=10.0,  # lowest
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")

    corrected = result["json_data"]
    assert corrected["strong_support"] == 10.0
    assert corrected["weak_support"] == 12.0
    assert corrected["weak_resistance"] == 18.0
    assert corrected["strong_resistance"] == 20.0
    print("PASS: completely reversed prices auto-corrected")


def test_price_levels_support_crossing_resistance():
    """支撑位和压力位交叉"""
    jd = make_tech_json(
        strong_support=14.0,
        weak_support=16.0,
        weak_resistance=13.0,   # below support!
        strong_resistance=18.0,
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")

    corrected = result["json_data"]
    # After sorting: [13.0, 14.0, 16.0, 18.0]
    assert corrected["strong_support"] == 13.0
    assert corrected["weak_support"] == 14.0
    assert corrected["weak_resistance"] == 16.0
    assert corrected["strong_resistance"] == 18.0
    print("PASS: crossing support/resistance auto-corrected")


def test_price_levels_with_none():
    """有None值时不排序（不崩溃）"""
    jd = make_tech_json(
        strong_support=10.0,
        weak_support=None,
        weak_resistance=15.0,
        strong_resistance=18.0,
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")

    # Should not crash, values unchanged
    corrected = result["json_data"]
    assert corrected["strong_support"] == 10.0
    assert corrected["weak_resistance"] == 15.0
    assert corrected["strong_resistance"] == 18.0
    print("PASS: None values handled without crash")


def test_price_levels_equal_values():
    """相等的值不应触发排序"""
    jd = make_tech_json(
        strong_support=12.0,
        weak_support=12.0,
        weak_resistance=15.0,
        strong_resistance=15.0,
    )
    content = json.dumps(jd, ensure_ascii=False)
    result = validate_analyst_output(content, "technical")

    corrected = result["json_data"]
    assert corrected["strong_support"] == 12.0
    assert corrected["weak_resistance"] == 15.0
    price_warnings = [w for w in result.get("warnings", []) if "Auto-corrected" in w]
    assert len(price_warnings) == 0, "Equal values should not trigger auto-correct"
    print("PASS: equal values left untouched")


if __name__ == "__main__":
    print("=" * 50)
    print("Price Level Auto-Sort Tests")
    print("=" * 50)

    tests = [
        test_price_levels_correctly_sorted,
        test_price_levels_strong_resistance_lower_than_weak,
        test_price_levels_completely_reversed,
        test_price_levels_support_crossing_resistance,
        test_price_levels_with_none,
        test_price_levels_equal_values,
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
