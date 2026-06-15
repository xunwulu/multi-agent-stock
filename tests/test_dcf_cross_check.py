"""
Tests for conditional dcf_cross_check validation in quality.py.

Background:
  The fundamentals skill prompt tells the LLM to "skip DCF step" when FCF<=0.
  But quality.py previously marked dcf_cross_check as unconditionally required,
  causing a validation failure whenever the LLM followed that instruction.

Fix:
  dcf_cross_check is now removed from required_fields. Instead, a conditional
  check (3b) fires only when DCF valuation data IS present
  (scoring_breakdown.dcf_valuation > 0) but dcf_cross_check is missing.
"""
import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.infra.quality import (
    validate_analyst_output,
    FUNDAMENTALS_ANALYST_SCHEMA,
)


def make_fund_json(
    score=50,
    include_dcf_cross_check=True,
    dcf_valuation_score=7,
    dcf_cross_check_data=None,
    **extra,
):
    """Build a minimal valid fundamentals analyst JSON.

    Args:
        include_dcf_cross_check: whether to include dcf_cross_check field at all
        dcf_valuation_score: value of scoring_breakdown.dcf_valuation (0 = DCF not applicable)
        dcf_cross_check_data: dict for dcf_cross_check, or None for null placeholder
    """
    base = {
        "score": score,
        "verdict": "neutral",
        "profitability_grade": "B",
        "growth_grade": "B",
        "safety_grade": "B",
        "valuation_grade": "fair",
        "roe_latest": 15.0,
        "roe_trend": "stable",
        "gross_margin": 30.0,
        "net_margin": 10.0,
        "revenue_yoy": 10.0,
        "revenue_trend": "stable",
        "net_profit_yoy": 12.0,
        "profit_trend": "stable",
        "debt_ratio": 40.0,
        "current_ratio": 2.0,
        "ocf_to_np_ratio": 1.1,
        "debt_structure": "结构健康",
        "pe_ttm": 20.0,
        "pe_percentile": 50.0,
        "pb": 2.0,
        "pb_percentile": 50.0,
        "valuation_summary": "估值合理",
        "holder_num_change_pct": -5.0,
        "holder_trend": "concentrating",
        "institutional_holders": ["机构A"],
        "institutional_ratio": 30.0,
        "key_strengths": ["优势1", "优势2", "优势3"],
        "key_risks": ["风险1", "风险2", "风险3"],
        "business_model": "商业模式描述",
        "expense_leakage": "无明显漏出",
        "dupont_analysis": {"roe": 15, "net_margin": 10, "asset_turnover": 0.8, "equity_multiplier": 1.5},
        "cross_layer_notes": "跨层验证：利润与现金流一致",
        "peg": 1.2,
        "growth_attribution": "主要由销量驱动",
        "insider_signal": "neutral",
        "pledge_risk": "none",
        "industry_analysis": {"trend": "stable"},
        "scenario_analysis": {
            "bull": {"revenue_yoy": 20, "net_profit_yoy": 25, "target_price": 15, "key_driver": "d"},
            "base": {"revenue_yoy": 10, "net_profit_yoy": 12, "target_price": 12, "key_driver": "d"},
            "bear": {"revenue_yoy": 0, "net_profit_yoy": -5, "target_price": 9, "key_driver": "d"},
        },
        "key_observations": ["观察1", "观察2", "观察3", "观察4", "观察5"],
        "scoring_breakdown": {
            "profitability_roe": 5,
            "profitability_margin": 5,
            "growth_revenue": 5,
            "growth_profit": 5,
            "safety_debt": 5,
            "cashflow_quality": 5,
            "valuation_pe": 5,
            "valuation_pb": 5,
            "holder_concentration": 5,
            "institutional_presence": 5,
            "safety_liquidity": 5,
            "dcf_valuation": dcf_valuation_score,
            "peg_signal": 5,
            "peer_valuation": 5,
        },
        "summary": "测试总结",
    }
    # sum of 14 fields with all 5s = 70, except dcf_valuation which is param.
    # score auto-correct = 70*100/140 = 50 (when dcf_valuation=5). We set score
    # explicitly so auto-correct matches; the test focus is dcf_cross_check.
    if include_dcf_cross_check:
        if dcf_cross_check_data is None:
            base["dcf_cross_check"] = {
                "intrinsic_value": 12.0,
                "dcf_upside_pct": 20.0,
                "sensitivity_note": "稳健",
                "pe_vs_dcf": "DCF略高于PE",
            }
        else:
            base["dcf_cross_check"] = dcf_cross_check_data
    # Adjust score to match breakdown sum to avoid unrelated score-correction noise
    total = sum(v for v in base["scoring_breakdown"].values())
    base["score"] = round(total * 100 / 140, 1)
    base.update(extra)
    return base


def run_validation(jd):
    return validate_analyst_output(json.dumps(jd, ensure_ascii=False), "fundamentals")


def test_dcf_not_in_required_fields():
    """dcf_cross_check should no longer be in required_fields."""
    assert "dcf_cross_check" not in FUNDAMENTALS_ANALYST_SCHEMA["required_fields"], (
        "dcf_cross_check must be removed from required_fields"
    )
    print("PASS: dcf_cross_check removed from required_fields")


def test_dcf_present_with_real_data_passes():
    """dcf_cross_check present with real data + dcf_valuation>0 -> valid."""
    jd = make_fund_json(include_dcf_cross_check=True, dcf_valuation_score=7)
    result = run_validation(jd)
    dcf_errors = [e for e in result.get("errors", []) if "dcf_cross_check" in e]
    assert len(dcf_errors) == 0, f"Should have no dcf errors: {dcf_errors}"
    print("PASS: dcf_cross_check with real data accepted")


def test_dcf_present_null_placeholder_passes():
    """dcf_cross_check present as null placeholder + dcf_valuation=0 -> valid."""
    null_placeholder = {
        "note": "FCF<=0, DCF not applicable",
        "intrinsic_value": None,
        "dcf_upside_pct": None,
        "sensitivity_note": "N/A",
        "pe_vs_dcf": "PE/PEG only",
    }
    jd = make_fund_json(
        include_dcf_cross_check=True,
        dcf_valuation_score=0,
        dcf_cross_check_data=null_placeholder,
    )
    result = run_validation(jd)
    dcf_errors = [e for e in result.get("errors", []) if "dcf_cross_check" in e]
    assert len(dcf_errors) == 0, f"Null placeholder should pass: {dcf_errors}"
    print("PASS: null placeholder accepted when FCF<=0")


def test_dcf_missing_no_dcf_score_is_warning():
    """dcf_cross_check missing + dcf_valuation=0 -> warning only, valid=True."""
    jd = make_fund_json(include_dcf_cross_check=False, dcf_valuation_score=0)
    result = run_validation(jd)
    dcf_errors = [e for e in result.get("errors", []) if "dcf_cross_check" in e]
    assert len(dcf_errors) == 0, (
        f"Missing dcf with dcf_valuation=0 should NOT error: {dcf_errors}"
    )
    dcf_warnings = [w for w in result.get("warnings", []) if "dcf_cross_check" in w]
    assert len(dcf_warnings) == 1, (
        f"Should have 1 dcf warning, got: {dcf_warnings}"
    )
    # valid should be True (warning, not error) -- unless other unrelated errors
    # We only assert no dcf-related error here since other validation may warn.
    print(f"PASS: missing dcf with dcf_valuation=0 -> warning (no error)")


def test_dcf_missing_with_dcf_score_is_error():
    """dcf_cross_check missing + dcf_valuation>0 -> error."""
    jd = make_fund_json(include_dcf_cross_check=False, dcf_valuation_score=7)
    result = run_validation(jd)
    dcf_errors = [e for e in result.get("errors", []) if "dcf_cross_check" in e]
    assert len(dcf_errors) == 1, (
        f"Missing dcf with dcf_valuation>0 SHOULD error, got: {dcf_errors}"
    )
    assert "required when DCF valuation data is present" in dcf_errors[0], (
        f"Wrong error message: {dcf_errors[0]}"
    )
    assert result["valid"] is False, "Should be invalid when DCF data present but cross_check missing"
    print("PASS: missing dcf with dcf_valuation>0 -> error (genuine missing data)")


def test_dcf_present_but_wrong_shape_warns():
    """dcf_cross_check present but not an object (e.g. a string) -> shape warning."""
    jd = make_fund_json(
        include_dcf_cross_check=True,
        dcf_valuation_score=7,
        dcf_cross_check_data="N/A",
    )
    result = run_validation(jd)
    dcf_errors = [e for e in result.get("errors", []) if "dcf_cross_check" in e]
    assert len(dcf_errors) == 0, f"Wrong shape should warn not error: {dcf_errors}"
    shape_warnings = [
        w for w in result.get("warnings", [])
        if "dcf_cross_check should be an object" in w
    ]
    assert len(shape_warnings) == 1, f"Expected 1 shape warning: {shape_warnings}"
    print("PASS: dcf_cross_check as string -> shape warning")


def test_dcf_missing_no_dcf_field_in_breakdown_is_warning():
    """dcf_cross_check missing + dcf_valuation field absent entirely -> warning."""
    jd = make_fund_json(include_dcf_cross_check=False, dcf_valuation_score=5)
    # Remove dcf_valuation from breakdown entirely
    del jd["scoring_breakdown"]["dcf_valuation"]
    result = run_validation(jd)
    dcf_errors = [e for e in result.get("errors", []) if "dcf_cross_check" in e]
    assert len(dcf_errors) == 0, (
        f"Missing dcf + no dcf_valuation field should NOT error: {dcf_errors}"
    )
    dcf_warnings = [w for w in result.get("warnings", []) if "dcf_cross_check" in w]
    assert len(dcf_warnings) == 1, f"Should have 1 dcf warning: {dcf_warnings}"
    print("PASS: missing dcf + absent dcf_valuation field -> warning")


def test_real_case_fcf_zero_stock_passes():
    """Real-world case: FCF<=0 stock where LLM omits dcf_cross_check per prompt.

    Before fix: 'Missing required field: dcf_cross_check' -> valid=False
    After fix:  warning only -> valid=True (assuming no other errors)
    """
    jd = make_fund_json(include_dcf_cross_check=False, dcf_valuation_score=0)
    result = run_validation(jd)
    # The specific dcf error must be gone
    dcf_errors = [e for e in result.get("errors", []) if "dcf_cross_check" in e]
    assert len(dcf_errors) == 0, f"FCF<=0 stock should not get dcf error: {dcf_errors}"
    print("PASS: FCF<=0 stock no longer flagged for missing dcf_cross_check")


if __name__ == "__main__":
    print("=" * 50)
    print("dcf_cross_check Conditional Validation Tests")
    print("=" * 50)

    tests = [
        test_dcf_not_in_required_fields,
        test_dcf_present_with_real_data_passes,
        test_dcf_present_null_placeholder_passes,
        test_dcf_present_but_wrong_shape_warns,
        test_dcf_missing_no_dcf_score_is_warning,
        test_dcf_missing_with_dcf_score_is_error,
        test_dcf_missing_no_dcf_field_in_breakdown_is_warning,
        test_real_case_fcf_zero_stock_passes,
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
