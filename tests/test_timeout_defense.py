"""
Tests for the layered timeout defense (Batch 1: Layer 1 + safe fallback).

Batch 1 covers:
  - Layer 1: granular httpx.Timeout(connect=10s) to kill TCP-handshake hangs
            (the 9424s incident root cause)
  - Safe fallback: run_analysis always returns a valid result dict even if
            analysts fail or time out (no NameError, no None dereference)

These tests use mocks - no real LLM API calls.
"""
import sys
import os
import time
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import httpx
from src.core.agent_loop import AgentLoop
from src.agents.orchestrator import MultiAgentOrchestrator


def make_config(**overrides):
    """Minimal config for AgentLoop/Orchestrator construction."""
    base = {
        "api_key": "test-key",
        "base_url": "http://test.local",
        "model": "test-model",
    }
    base.update(overrides)
    return base


# ---------- Layer 1: granular httpx Timeout ----------

def test_layer1_granular_timeout_config():
    """config with connect/read/write/pool -> httpx.Timeout applied to client."""
    config = make_config(
        connect_timeout=10, read_timeout=120, write_timeout=30, pool_timeout=10
    )
    with patch("src.core.agent_loop.anthropic.Anthropic") as mock_client:
        AgentLoop(config)
        kwargs = mock_client.call_args.kwargs
        assert "timeout" in kwargs, "timeout not passed to Anthropic client"
        t = kwargs["timeout"]
        assert isinstance(t, httpx.Timeout), f"Expected httpx.Timeout, got {type(t)}"
        assert t.connect == 10, f"connect: expected 10, got {t.connect}"
        assert t.read == 120, f"read: expected 120, got {t.read}"
        assert t.write == 30, f"write: expected 30, got {t.write}"
        assert t.pool == 10, f"pool: expected 10, got {t.pool}"
    print("PASS: Layer1 granular Timeout(connect=10) applied")


def test_layer1_falls_back_to_default_when_missing():
    """Old config without granular timeout fields -> sensible defaults, no crash."""
    config = make_config()  # no connect_timeout etc.
    with patch("src.core.agent_loop.anthropic.Anthropic") as mock_client:
        AgentLoop(config)
        t = mock_client.call_args.kwargs["timeout"]
        assert isinstance(t, httpx.Timeout)
        # Defaults: connect=10, read=request_timeout default=120, write=30, pool=10
        assert t.connect == 10, f"connect default: expected 10, got {t.connect}"
        assert t.read == 120, f"read default: expected 120, got {t.read}"
    print("PASS: Layer1 falls back to defaults when config fields missing")


def test_layer1_connect_timeout_is_short():
    """The connect timeout must be short (<=15s) to kill TCP-handshake hangs."""
    config = make_config()
    with patch("src.core.agent_loop.anthropic.Anthropic") as mock_client:
        AgentLoop(config)
        t = mock_client.call_args.kwargs["timeout"]
        # This is the whole point: connect must be short, not 120s or unbounded.
        assert t.connect <= 15, (
            f"connect timeout {t.connect}s too long - must kill TCP hangs fast"
        )
    print(f"PASS: connect timeout {mock_client.call_args.kwargs['timeout'].connect}s is short")


# ---------- Safe fallback: run_analysis always returns a valid dict ----------

def _fail_result():
    """A failure analyst result (simulates Phase 1 analyst failing/timing out)."""
    return {
        "success": False,
        "content": "",
        "json_data": {},
        "structured_output": None,
        "tool_calls": 0,
        "iterations": 0,
        "duration_ms": 0,
        "error": "mocked failure",
    }


def test_safe_fallback_phase1_all_fail_returns_valid_dict():
    """All 3 analysts fail + trader fails -> run_analysis still returns a valid dict.

    This is the core safety guarantee: even worst-case failure produces a usable
    result (no exception, no crash), via _synthesize_reports + deterministic trader.
    """
    orch = MultiAgentOrchestrator(make_config())
    with patch.object(orch, "_run_technical_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_fundamentals_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_news_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_trader", return_value=None):  # triggers deterministic fallback
        result = orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=True)

    # Must be a dict, not an exception
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    cr = result.get("combined_report", {})
    # combined_score must be a number (synthesized from empty -> 50)
    assert isinstance(cr.get("combined_score"), (int, float)), (
        f"combined_score not numeric: {cr.get('combined_score')}"
    )
    # trader must exist with a valid action (deterministic fallback)
    assert "trader" in cr, "trader missing from combined_report"
    action = cr["trader"].get("action")
    assert action in ("buy", "hold", "sell", "watch"), f"Invalid trader action: {action}"
    # synthesis_method should reflect degradation
    sm = cr.get("synthesis_method", "")
    assert "deterministic" in sm or "fallback" in sm or "degraded" in sm, (
        f"synthesis_method should show degradation: {sm}"
    )
    print(f"PASS: Phase1 all-fail -> valid dict (score={cr['combined_score']}, "
          f"action={action}, method={sm})")


def test_safe_fallback_synthesizes_empty_inputs():
    """Directly verify the two cornerstone fallbacks tolerate fully-empty inputs."""
    orch = MultiAgentOrchestrator(make_config())
    combined = orch._synthesize_reports({}, {}, {})
    assert isinstance(combined.get("combined_score"), (int, float)), (
        f"_synthesize_reports on empty inputs failed: {combined}"
    )
    trader = orch._deterministic_trader_fallback(combined, {}, {})
    assert trader.get("action") in ("buy", "hold", "sell", "watch"), (
        f"deterministic trader on empty inputs failed: {trader.get('action')}"
    )
    # Empty inputs -> neutral 50 -> should map to a conservative action
    print(f"PASS: empty inputs -> score={combined['combined_score']}, "
          f"action={trader['action']}")


def test_result_dict_has_required_keys_on_failure():
    """Even on failure path, result dict has all keys callers expect."""
    orch = MultiAgentOrchestrator(make_config())
    with patch.object(orch, "_run_technical_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_fundamentals_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_news_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_trader", return_value=None):
        result = orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=True)

    required = ["stock_code", "state", "tech_report", "fund_report", "news_report",
                "combined_report", "success", "duration_ms", "error"]
    for k in required:
        assert k in result, f"Missing required key in result dict: {k}"
    # Sub-report structure intact
    for sub in ["tech_report", "fund_report", "news_report"]:
        assert "json_data" in result[sub], f"{sub} missing json_data"
        assert "success" in result[sub], f"{sub} missing success"
    print("PASS: result dict has all required keys on failure path")


def test_no_nameerror_when_phase1_raises():
    """If an analyst raises (not just fails), run_analysis must not NameError.

    This guards the 3a init: tech_json/fund_json/news_json default to {} so
    _synthesize_reports at the fallback never hits an unbound variable.
    """
    orch = MultiAgentOrchestrator(make_config())

    def raise_fn(*a, **k):
        raise RuntimeError("simulated Phase 1 crash")

    with patch.object(orch, "_run_technical_analyst", side_effect=raise_fn), \
         patch.object(orch, "_run_fundamentals_analyst", side_effect=raise_fn), \
         patch.object(orch, "_run_news_analyst", side_effect=raise_fn), \
         patch.object(orch, "_run_trader", return_value=None):
        # Phase 1 runs analysts in threads; thread crashes are caught by the
        # executor's future.result() try/except -> synthetic failure dicts.
        # So this should still return a dict, not propagate the RuntimeError.
        result = orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=True)
    assert isinstance(result, dict), f"Expected dict even when analysts raise: {type(result)}"
    assert isinstance(result["combined_report"]["combined_score"], (int, float))
    print("PASS: no NameError / no propagated exception when analysts raise")


if __name__ == "__main__":
    print("=" * 55)
    print("Timeout Defense Tests (Batch 1: Layer 1 + Safe Fallback)")
    print("=" * 55)

    tests = [
        test_layer1_granular_timeout_config,
        test_layer1_falls_back_to_default_when_missing,
        test_layer1_connect_timeout_is_short,
        test_safe_fallback_phase1_all_fail_returns_valid_dict,
        test_safe_fallback_synthesizes_empty_inputs,
        test_result_dict_has_required_keys_on_failure,
        test_no_nameerror_when_phase1_raises,
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

    print(f"\n{'='*55}")
    print(f"Result: {passed}/{passed+failed} passed")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"FAILED: {failed} tests")
