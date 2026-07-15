"""
test_value_left_side - 验证 D3 价值股左侧口子

验证多重 AND 门槛:
  1. 价值股(低PE+好OCF+增持+够分) -> weak buy(不依赖 bullish)
  2. 高PE题材股(PE116) -> 挡
  3. 坏现金流(OCF-13.8) -> 挡
  4. 机构未增持 -> 挡
  5. 分数不够(<52) -> 挡
  6. 非价值股(growth) -> 挡

Usage: python -m pytest tests/test_value_left_side.py -v
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.agents.orchestrator import MultiAgentOrchestrator


def _config():
    return {"api_key": "test", "base_url": "http://test", "model": "test"}


def _combined(score=63, stock_type="value", direction="neutral", winner="draw"):
    return {
        "combined_score": score,
        "combined_direction": direction,
        "debate_winner": winner,
        "stock_type": stock_type,
    }


def _fund(pe=18, ocf=1.5, insider="net_buy"):
    return {
        "pe_ttm": pe,
        "ocf_to_np_ratio": ocf,
        "insider_signal": insider,
        "score": 60,
        "target_price": 30,
        "verdict": "neutral",
        "valuation_grade": "undervalued",
        "industry": "电力",
    }


TECH = {
    "target_price": 30,
    "direction": "neutral",
    "score": 55,
    "stop_loss_price": 25,
    "risk_reward_ratio": "1:2",
}


def test_value_left_side_allows_undervalued():
    """价值股(低PE+好OCF+增持+够分) -> weak buy, 不依赖 bullish"""
    orch = MultiAgentOrchestrator(_config())
    result = orch._deterministic_trader_fallback(_combined(63), TECH, _fund())
    assert result["action"] == "buy", f"价值股左侧应 buy, 实际 {result.get('action')}"
    assert result["action_strength"] == "weak"


def test_value_left_side_blocks_high_pe():
    """高PE题材股(PE116, 如有研新材) -> 不走口子"""
    orch = MultiAgentOrchestrator(_config())
    result = orch._deterministic_trader_fallback(_combined(63), TECH, _fund(pe=116))
    assert result["action"] != "buy", "PE116 题材股应被挡"


def test_value_left_side_blocks_bad_ocf():
    """坏现金流(OCF-13.8, 如有研新材) -> 不走口子"""
    orch = MultiAgentOrchestrator(_config())
    result = orch._deterministic_trader_fallback(_combined(63), TECH, _fund(ocf=-13.8))
    assert result["action"] != "buy", "OCF-13.8 现金流失血应被挡"


def test_value_left_side_blocks_no_insider():
    """机构未增持(net_sell) -> 不走口子"""
    orch = MultiAgentOrchestrator(_config())
    result = orch._deterministic_trader_fallback(_combined(63), TECH, _fund(insider="net_sell"))
    assert result["action"] != "buy", "net_sell 应被挡"


def test_value_left_side_blocks_low_score():
    """分数不够(<52) -> 不走口子"""
    orch = MultiAgentOrchestrator(_config())
    result = orch._deterministic_trader_fallback(_combined(45), TECH, _fund())
    assert result["action"] != "buy", "score<52 应被挡"


def test_value_left_side_blocks_non_value_stock():
    """非价值股(growth) -> 不走口子"""
    orch = MultiAgentOrchestrator(_config())
    result = orch._deterministic_trader_fallback(
        _combined(63, stock_type="growth"), TECH, _fund()
    )
    assert result["action"] != "buy", "growth 股不应走价值口子"


# ---------- D3 全天候覆盖: _apply_value_left_override ----------
def test_override_forces_buy_when_llm_says_watch():
    """LLM trader 判 watch + 满足价值口子 -> 强制覆盖为 buy"""
    orch = MultiAgentOrchestrator(_config())
    trader_data = {"action": "watch", "action_strength": "normal", "target_price": 30}
    result, overridden = orch._apply_value_left_override(
        trader_data, _combined(63), _fund()
    )
    assert overridden is True
    assert result["action"] == "buy"
    assert result["action_strength"] == "weak"


def test_override_no_op_when_already_buy():
    """LLM 已判 buy -> 不覆盖"""
    orch = MultiAgentOrchestrator(_config())
    trader_data = {"action": "buy", "action_strength": "weak"}
    result, overridden = orch._apply_value_left_override(
        trader_data, _combined(63), _fund()
    )
    assert overridden is False
    assert result["action"] == "buy"


def test_override_no_op_when_conditions_not_met():
    """不满足口子(高PE如题材股) -> 不覆盖, 保持 LLM 判断"""
    orch = MultiAgentOrchestrator(_config())
    trader_data = {"action": "watch"}
    result, overridden = orch._apply_value_left_override(
        trader_data, _combined(63), _fund(pe=116)
    )
    assert overridden is False
    assert result["action"] == "watch"
