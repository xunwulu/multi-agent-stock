"""
test_stage_timeout - 验证第4刀阶段超时围栏

验证点:
  1. ANALYST_TIMEOUT / TOTAL_BUDGET 常量是合理的防挂死值
  2. 分析师单股超时 -> 走降级(error_type=timeout)
  3. 总预算超时 -> 交易员 LLM 被跳过, 走确定性兜底
  4. 极端: 分析师全超时 + 预算超 -> run_analysis 仍返回有效 dict(不抛异常)
  5. read_timeout 降到 90(缓解慢吐字)

Usage: python -m pytest tests/test_stage_timeout.py -v
"""
import sys
import os
import time
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.core.agent_loop import AgentLoop
from src.agents.orchestrator import (
    MultiAgentOrchestrator,
    ANALYST_TIMEOUT,
    TOTAL_BUDGET,
)


def make_config(**overrides):
    base = {"api_key": "test-key", "base_url": "http://test.local", "model": "test-model"}
    base.update(overrides)
    return base


def _fail_result():
    return {
        "success": False, "content": "", "json_data": {},
        "structured_output": None, "tool_calls": 0, "iterations": 0,
        "duration_ms": 0, "error": "mocked failure",
    }


def test_constants_set_to_safe_values():
    """ANALYST_TIMEOUT 和 TOTAL_BUDGET 是合理的防挂死值"""
    assert ANALYST_TIMEOUT == 180, f"ANALYST_TIMEOUT 应为 180, 实际 {ANALYST_TIMEOUT}"
    assert TOTAL_BUDGET == 600, f"TOTAL_BUDGET 应为 600, 实际 {TOTAL_BUDGET}"


def test_analyst_timeout_degrades():
    """分析师超时 -> error_type=timeout, run_analysis 返回有效 dict"""
    orch = MultiAgentOrchestrator(make_config())

    def slow_analyst(*a, **k):
        time.sleep(1.0)  # 超过 timeout(0.3)
        return _fail_result()

    with patch("src.agents.orchestrator.ANALYST_TIMEOUT", 0.3), \
         patch.object(orch, "_run_technical_analyst", side_effect=slow_analyst), \
         patch.object(orch, "_run_fundamentals_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_news_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_trader", return_value=None):
        result = orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=True)
    assert isinstance(result, dict), "run_analysis 应返回 dict 不抛异常"
    assert result["tech_report"]["success"] is False, "超时分析师应 success=False"
    assert result["tech_report"]["error_type"] == "timeout", "超时应透传 error_type=timeout"


def test_deadline_skips_trader():
    """总预算超时(TOTAL_BUDGET=0) -> 交易员 LLM 被跳过, 走确定性兜底"""
    orch = MultiAgentOrchestrator(make_config())
    with patch("src.agents.orchestrator.TOTAL_BUDGET", 0), \
         patch.object(orch, "_run_technical_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_fundamentals_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_news_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_trader") as mock_trader:
        result = orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=True)
    mock_trader.assert_not_called()  # deadline 超时, trader LLM 被跳过
    cr = result["combined_report"]
    assert "_deterministic_trader" in cr.get("synthesis_method", ""), \
        f"应走确定性兜底, 实际 synthesis_method={cr.get('synthesis_method')}"


def test_total_timeout_still_returns_valid_dict():
    """极端: 分析师全超时 + 总预算超 -> run_analysis 仍返回有效 dict"""
    orch = MultiAgentOrchestrator(make_config())

    def slow(*a, **k):
        time.sleep(1.0)
        return _fail_result()

    with patch("src.agents.orchestrator.ANALYST_TIMEOUT", 0.3), \
         patch("src.agents.orchestrator.TOTAL_BUDGET", 0), \
         patch.object(orch, "_run_technical_analyst", side_effect=slow), \
         patch.object(orch, "_run_fundamentals_analyst", side_effect=slow), \
         patch.object(orch, "_run_news_analyst", side_effect=slow), \
         patch.object(orch, "_run_trader") as mock_trader:
        result = orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=True)
    assert isinstance(result, dict), "极端超时也应返回有效 dict"
    assert result["tech_report"]["error_type"] == "timeout"  # 超时降级透传
    mock_trader.assert_not_called()
    cr = result["combined_report"]
    assert isinstance(cr.get("combined_score"), (int, float)), "combined_score 应是数字"


def test_read_timeout_lowered_to_90():
    """read_timeout 降到 90(缓解慢吐字, 第4刀)"""
    config = make_config(read_timeout=90)
    with patch("src.core.agent_loop.anthropic.Anthropic") as mock_client:
        AgentLoop(config)
        t = mock_client.call_args.kwargs["timeout"]
        assert t.read == 90, f"read_timeout 应为 90, 实际 {t.read}"


# ---------- 辅助: 构造"有效"分析师结果(过 _is_valid_analysis) ----------
def _ok_analyst_result():
    """有效分析师结果(含 structured_output, 让 _validate_report 提取出有效 json_data)"""
    return {
        "success": True, "content": "",
        "structured_output": {"score": 60, "scoring_breakdown": {"t1": 5}},
        "json_data": {}, "tool_calls": 1, "iterations": 1,
        "duration_ms": 100, "token_usage": None,
    }


_VALID_VALIDATION = {
    "valid": True,
    "json_data": {"score": 60, "scoring_breakdown": {"t1": 5}, "direction": "neutral"},
}


def test_deadline_skips_debate():
    """总预算超时(TOTAL_BUDGET=0) + 有效分析 + skip_debate=False -> 辩论被 deadline 跳过"""
    orch = MultiAgentOrchestrator(make_config())
    ok = _ok_analyst_result()
    with patch("src.agents.orchestrator.TOTAL_BUDGET", 0), \
         patch("src.agents.orchestrator.validate_structured_output", return_value=_VALID_VALIDATION), \
         patch.object(orch, "_run_technical_analyst", return_value=ok), \
         patch.object(orch, "_run_fundamentals_analyst", return_value=ok), \
         patch.object(orch, "_run_news_analyst", return_value=ok), \
         patch("src.agents.orchestrator.DebateLoop") as MockDebate, \
         patch.object(orch, "_run_trader", return_value=None):
        orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=False)
    MockDebate.return_value.run.assert_not_called()  # 辩论被 deadline 跳过


def test_deadline_skips_risk_debate():
    """辩论跑完但耗时超预算 -> 风险辩论(Phase 4-5)被 deadline 跳过"""
    orch = MultiAgentOrchestrator(make_config())
    ok = _ok_analyst_result()
    rm_ok = {  # 研究经理有效结果(让 synthesis_method 非 deterministic)
        "adjusted_score": 60, "adjusted_direction": "neutral", "debate_winner": "bull",
        "debate_delta": 0, "debate_rationale": "", "strongest_bull_point": "",
        "strongest_bear_point": "",
    }

    def slow_debate(*a, **k):
        time.sleep(0.4)  # 辩论耗时让后续风险辩论入口超 deadline
        return {"bull_arguments": "x", "bear_arguments": "y", "rounds_completed": 1,
                "transcript": "t", "duration_ms": 400}

    with patch("src.agents.orchestrator.TOTAL_BUDGET", 0.2), \
         patch("src.agents.orchestrator.validate_structured_output", return_value=_VALID_VALIDATION), \
         patch.object(orch, "_run_technical_analyst", return_value=ok), \
         patch.object(orch, "_run_fundamentals_analyst", return_value=ok), \
         patch.object(orch, "_run_news_analyst", return_value=ok), \
         patch("src.agents.orchestrator.DebateLoop") as MockDebate, \
         patch.object(orch, "_run_research_manager", return_value=rm_ok), \
         patch("src.agents.orchestrator.RiskLoop") as MockRisk, \
         patch.object(orch, "_run_trader", return_value=None):
        MockDebate.return_value.run.side_effect = slow_debate
        orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=False)
    MockDebate.return_value.run.assert_called_once()  # 辩论跑了
    MockRisk.return_value.run.assert_not_called()  # 风险辩论被 deadline 跳过


def test_degradation_summary_reflects_timeout():
    """C: 超时降级时 degradation_summary.overall_degraded=True, tech_analyst=timeout"""
    orch = MultiAgentOrchestrator(make_config())

    def slow_analyst(*a, **k):
        time.sleep(1.0)
        return _fail_result()

    with patch("src.agents.orchestrator.ANALYST_TIMEOUT", 0.3), \
         patch.object(orch, "_run_technical_analyst", side_effect=slow_analyst), \
         patch.object(orch, "_run_fundamentals_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_news_analyst", return_value=_fail_result()), \
         patch.object(orch, "_run_trader", return_value=None):
        result = orch.run_analysis("300033.SZ", max_iterations=2, debate_rounds=1, skip_debate=True)
    ds = result["degradation_summary"]
    assert ds["tech_analyst"] == "timeout", "tech 超时应记入 degradation_summary"
    assert ds["overall_degraded"] is True, "有超时降级时 overall_degraded 应为 True"
