"""
Tests for the submit_analysis tool submission flow.

Covers:
- validate_structured_output for all schema types
- validate_research_manager_structured
- validate_trader_structured
- Text-based fallback still works
- agent_loop returns structured_output correctly
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.infra.quality import (
    validate_structured_output,
    validate_analyst_output,
    validate_research_manager_structured,
    validate_research_manager_output,
    validate_trader_structured,
    validate_trader_output,
    _validate_analyst_dict,
)


# ---- validate_structured_output ----

def test_structured_news_valid():
    data = {
        "score": 0,
        "direction": "bullish",
        "news_analyzed": 8,
        "sentiment": "positive",
        "key_events": [],
        "risk_events": [],
        "positive_factors": ["good"],
        "negative_factors": [],
        "scoring_breakdown": {
            "positive_events": 12,
            "negative_events": -3,
            "event_timeliness": 10,
            "event_impact": 10,
            "sentiment_alignment": 7,
            "risk_level": -3,
        },
        "summary": "test summary",
    }
    result = validate_structured_output(data, "news")
    assert result["valid"] is True
    assert result["json_data"]["score"] == 83  # 50 + 12 - 3 + 10 + 10 + 7 - 3


def test_structured_news_not_dict():
    result = validate_structured_output("not a dict", "news")
    assert result["valid"] is False
    assert "Expected dict" in result["errors"][0]


def test_structured_tech_valid():
    data = {
        "score": 0,
        "direction": "bullish",
        "short_term_trend": "up",
        "mid_term_trend": "up",
        "long_term_trend": "up",
        "trend": "uptrend",
        "strong_support": 100.0,
        "weak_support": 105.0,
        "strong_resistance": 120.0,
        "weak_resistance": 115.0,
        "stop_loss_price": 98.0,
        "target_price": 118.0,
        "risk_reward_ratio": "1:2",
        "volume_signal": "normal",
        "macd_signal": "golden_cross",
        "macd_divergence": "none",
        "kdj_signal": "neutral",
        "kdj_divergence": "none",
        "rsi_signal": "neutral",
        "rsi_divergence": "none",
        "money_flow_signal": "neutral",
        "money_flow_summary": "neutral",
        "relative_strength": "inline",
        "ma_pattern": "bullish_alignment",
        "scoring_breakdown": {
            "trend_ma": 8, "trend_macd": 7, "trend_price_position": 6,
            "signal_macd": 8, "signal_kdj": 5, "signal_rsi": 5,
            "volume_price": 6, "volume_turnover": 5,
            "relative_vs_index": 7, "relative_volatility": 4,
            "risk_reward": 6,
        },
        "summary": "bullish tech summary",
    }
    result = validate_structured_output(data, "technical")
    assert result["valid"] is True
    assert result["json_data"]["score"] > 0


def test_structured_text_fallback_produces_same_result():
    """Text-based parsing and structured output should give same score."""
    news_dict = {
        "score": 0,
        "direction": "neutral",
        "news_analyzed": 5,
        "sentiment": "neutral",
        "key_events": [],
        "risk_events": [],
        "positive_factors": [],
        "negative_factors": [],
        "scoring_breakdown": {
            "positive_events": 5,
            "negative_events": -2,
            "event_timeliness": 7,
            "event_impact": 6,
            "sentiment_alignment": 5,
            "risk_level": -3,
        },
        "summary": "test",
    }
    structured = validate_structured_output(news_dict, "news")

    import json
    text_output = "```json\n" + json.dumps(news_dict, ensure_ascii=False) + "\n```"
    text_based = validate_analyst_output(text_output, "news")

    assert structured["json_data"]["score"] == text_based["json_data"]["score"]


# ---- validate_research_manager_structured ----

def test_rm_structured_valid():
    data = {
        "debate_winner": "bull",
        "debate_delta": 3,
        "debate_rationale": "bull made stronger points",
        "strongest_bull_point": "growth acceleration",
        "strongest_bear_point": "valuation risk",
        "adjusted_score": 65,
        "adjusted_direction": "bullish",
        "recommendation": "hold with positive bias",
        "risk_warnings": ["valuation stretched"],
        "summary": "bull won",
    }
    result = validate_research_manager_structured(data)
    assert result["valid"] is True
    assert result["json_data"]["debate_winner"] == "bull"


def test_rm_structured_invalid_winner():
    data = {
        "debate_winner": "invalid",
        "debate_delta": 0,
        "debate_rationale": "test",
        "strongest_bull_point": "test",
        "strongest_bear_point": "test",
        "adjusted_score": 50,
        "adjusted_direction": "neutral",
        "recommendation": "test",
        "risk_warnings": [],
        "summary": "test",
    }
    result = validate_research_manager_structured(data)
    assert result["valid"] is False
    assert any("Invalid debate_winner" in e for e in result["errors"])


# ---- validate_trader_structured ----

def test_trader_structured_valid():
    data = {
        "action": "hold",
        "action_strength": "normal",
        "target_price": 150.0,
        "target_price_rationale": "based on analysis",
        "stop_loss": 140.0,
        "stop_loss_rationale": "below support",
        "confidence_components": {
            "signal_consistency": 15,
            "data_sufficiency": 14,
            "debate_certainty": 10,
            "risk_controllability": 12,
            "valuation_reasonableness": 13,
        },
        "confidence_total": 64,
        "confidence_label": "high",
        "position_advice": "standard",
        "position_range": "40-70%",
        "risk_score": 35,
        "risk_level": "low",
        "time_horizon": "2-4 weeks",
        "reasoning": "mixed signals, hold recommended",
        "warnings": ["valuation risk", "market volatility"],
    }
    result = validate_trader_structured(data)
    assert result["valid"] is True
    assert result["json_data"]["action"] == "hold"


def test_trader_structured_missing_stop_loss():
    data = {
        "action": "buy",
        "action_strength": "strong",
        "target_price": 150.0,
        "target_price_rationale": "test",
        "stop_loss_rationale": "test",
        "confidence_components": {
            "signal_consistency": 10,
            "data_sufficiency": 10,
            "debate_certainty": 10,
            "risk_controllability": 10,
            "valuation_reasonableness": 10,
        },
        "confidence_total": 50,
        "confidence_label": "medium",
        "position_advice": "light",
        "position_range": "20-40%",
        "risk_score": 40,
        "risk_level": "medium",
        "time_horizon": "1-2 weeks",
        "reasoning": "test",
        "warnings": ["risk1", "risk2"],
    }
    result = validate_trader_structured(data)
    assert result["valid"] is False
    assert any("stop_loss" in e for e in result["errors"])


# ---- agent_loop structured_output ----

def test_agent_loop_return_has_structured_output_key():
    """Verify agent_loop.run() returns structured_output in result dict."""
    from unittest.mock import MagicMock, patch
    from src.core.agent_loop import AgentLoop

    config = {
        "api_key": "test",
        "base_url": "http://localhost",
        "model": "test-model",
        "max_tokens": 1024,
    }

    # Mock the client to avoid real API calls
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "analysis text"
    mock_response.content = [text_block]

    with patch.object(
        AgentLoop, "__init__", lambda self, config: None
    ):
        loop = AgentLoop(config)
        loop.client = MagicMock()
        loop.model = "test"
        loop.max_tokens = 1024
        loop.max_iterations = 5
        loop.max_retries = 2
        loop.retry_base_delay = 1.0
        loop._call_with_retry = MagicMock(return_value=mock_response)

        result = loop.run(
            system_prompt="test",
            messages=[{"role": "user", "content": "analyze"}],
            tools=None,
            dispatch_map=None,
            max_iterations=1,
        )

        assert "structured_output" in result
        assert result["structured_output"] is None  # end_turn returns None


# ---- submit_tool definition ----

def test_submit_tool_definition():
    from src.core.submit_tool import get_submit_tool
    tool = get_submit_tool()
    assert tool["name"] == "submit_analysis"
    assert "input_schema" in tool
    props = tool["input_schema"]["properties"]
    assert "score" in props
    assert "scoring_breakdown" in props
    assert "summary" in props
    assert "direction" in props
    assert "action" in props
    assert tool["input_schema"]["required"] == ["score", "scoring_breakdown", "summary"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
