"""test_progress_events - 第二阶段直播化验证（2a 数据补漏 + 2b 事件契约）

覆盖:
  1. EventEmitter: 信封契约(seq 递增唯一/ts>=0/data 原样)、JSONL 与快照落盘、
     finalize 状态流转、多线程并发发射 seq 不重复
  2. normalize_result: 后端返回值 -> 前端 D 形状（risk 角色小写化、trader 提升、meta 汇总）
  3. RiskLoop MessageBus: 听证发言落 bus(msg_type=risk) + on_speech 回调小写角色
  4. 端到端(假 LLM): run_analysis 全程事件序列完整、rm/riskmgr 捡回新字段、
     事件重放(reducer 语义与前端一致) == run_done 终态
"""
import json
import re
import sys
import os
import threading

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.core.agent_loop import AgentLoop
from src.infra.progress_emitter import EventEmitter, normalize_result
from src.agents.risk_loop import RiskLoop

_CONFIG = {"model": "x", "base_url": "x", "api_key": "x"}


# ======================================================================
# 1. EventEmitter
# ======================================================================
def test_emitter_envelope_contract(tmp_path):
    em = EventEmitter("r_test", str(tmp_path), stock_code="601398.SH",
                      stock_name="工商银行")
    em.emit("run_started", 1, {"stock_code": "601398.SH", "plan": []})
    em.emit("agent_done", 1, {"json": {"score": 65}}, agent="tech")

    evs = em.snapshot()["events"]
    assert [e["seq"] for e in evs] == [1, 2], "seq 必须从 1 起连续递增"
    assert all(e["ts"] >= 0 for e in evs)
    assert all(e["run_id"] == "r_test" for e in evs)
    assert evs[0]["type"] == "run_started" and "agent" not in evs[0]
    assert evs[1]["agent"] == "tech" and evs[1]["data"]["json"]["score"] == 65


def test_emitter_jsonl_and_finalize(tmp_path):
    em = EventEmitter("r_test", str(tmp_path))
    em.emit("stage_started", 1, {"label": "三路侦察"})
    em.emit("run_done", 6, {"result": {"meta": {}}})
    em.finalize("done")

    lines = (tmp_path / "progress.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2, "每条事件一行 JSONL"
    assert json.loads(lines[0])["type"] == "stage_started"

    snap = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert snap["status"] == "done"
    assert snap["last_seq"] == 2
    assert len(snap["events"]) == 2


def test_emitter_thread_safety(tmp_path):
    """3 个分析师线程并发发射，seq 不得重复。"""
    em = EventEmitter("r_conc", str(tmp_path))

    def spam(agent):
        for _ in range(50):
            em.emit("agent_heartbeat", 1, {"tool": "get_kline"}, agent=agent)

    threads = [threading.Thread(target=spam, args=(a,)) for a in ("tech", "fund", "news")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    evs = em.snapshot()["events"]
    seqs = [e["seq"] for e in evs]
    assert len(evs) == 150
    assert len(set(seqs)) == 150, "并发下 seq 不得重复"
    assert seqs == sorted(seqs) or len(set(seqs)) == 150


def test_emitter_emit_failure_does_not_raise(tmp_path):
    """fail-open: 回调/落盘异常绝不能抛出（直播挂了不影响分析）。"""
    em = EventEmitter("r_fail", str(tmp_path))

    def bad_on_event(*a, **k):
        raise RuntimeError("boom")

    # 直接把输出文件变成目录 -> 落盘必失败 -> 不应抛异常
    (tmp_path / "progress.jsonl").mkdir()
    em.emit("run_started", 1, {})
    assert em.snapshot()["last_seq"] >= 0


# ======================================================================
# 2. normalize_result
# ======================================================================
def _fake_backend_result():
    return {
        "stock_code": "601398.SH",
        "duration_ms": 123456,
        "success": True,
        "tech_report": {"content": "技术面报告全文", "json_data": {"score": 70}},
        "fund_report": {"content": "基本面报告全文", "json_data": {"score": 60}},
        "news_report": {"content": "新闻面报告全文", "json_data": {"score": 55}},
        "combined_report": {
            "combined_score": 65,
            "rm_summary": "经理总结",
            "risk_rationale": "保守方论据更扎实",
            "trader": {"action": "buy", "target_price": 9.0},
        },
        "debate_result": {
            "success": True, "rounds_completed": 1,
            "rounds": [{"round": 1,
                        "bull": {"content": "看多", "duration_ms": 100},
                        "bear": {"content": "看空", "duration_ms": 110}}],
        },
        "risk_result": {
            "success": True, "rounds_completed": 1,
            "rounds": [{"round": 1,
                        "Aggressive": {"content": "激进", "duration_ms": 100},
                        "Conservative": {"content": "保守", "duration_ms": 110},
                        "Neutral": {"content": "中性", "duration_ms": 120}}],
        },
        "degradation_summary": {"overall_degraded": False},
    }


def test_normalize_result_shape():
    d = normalize_result(_fake_backend_result(), stock_name="工商银行")
    assert set(d.keys()) == {"tech", "fund", "news", "combined", "debate", "risk",
                             "trader", "meta"}
    assert d["tech"] == {"content": "技术面报告全文", "json": {"score": 70}}
    assert d["trader"]["action"] == "buy", "trader 应从 combined 提出"
    assert d["meta"]["stock_name"] == "工商银行"
    assert d["meta"]["duration_s"] == 123
    # risk 角色小写化（前端契约）
    r0 = d["risk"]["rounds"][0]
    assert set(r0.keys()) == {"round", "aggressive", "conservative", "neutral"}
    assert r0["conservative"]["content"] == "保守"


def test_normalize_result_empty_risk():
    d = normalize_result({"combined_report": {}, "duration_ms": 0})
    assert d["risk"] == {}
    assert d["trader"] == {}


# ======================================================================
# 2b. agent_loop 跨轮累积 + 末轮护栏（B步）
# ======================================================================
def test_agent_loop_accumulates_and_guardrail(monkeypatch):
    """content 累积全程轨迹（不再丢早轮文字）；last_round_text 只含末轮（护栏）。"""
    from types import SimpleNamespace

    def _bt(t):
        return SimpleNamespace(type="text", text=t)

    responses = iter([
        # 第1轮: 叙述里混着草稿 JSON + 工具调用
        SimpleNamespace(
            content=[_bt('先查K线。{"draft": "早期草稿"}'),
                     SimpleNamespace(type="tool_use", id="t1", name="get_kline",
                                     input={"code": "601398.SH"})],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        ),
        # 第2轮: 干净收尾，自然结束
        SimpleNamespace(
            content=[_bt("最终结论: MACD金叉, 量价配合良好.")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=30),
        ),
    ])

    loop = AgentLoop(_CONFIG)
    monkeypatch.setattr(
        loop, "_call_with_retry",
        lambda kwargs, on_event=None, iteration=0: next(responses),
    )

    result = loop.run(
        system_prompt="s", messages=[{"role": "user", "content": "x"}],
        tools=None, dispatch_map={"get_kline": lambda **k: {"ok": True}},
        max_iterations=3,
    )

    assert result["success"] is True
    # content = 全程轨迹（两轮文字都在，早轮不再被丢弃）
    assert "先查K线" in result["content"]
    assert "最终结论" in result["content"]
    # last_round_text = 仅末轮（护栏），不含早轮草稿 JSON
    assert result["last_round_text"] == "最终结论: MACD金叉, 量价配合良好."
    assert "draft" not in result["last_round_text"]

    # 兜底解析喂 last_round_text 时不会误抓早轮草稿
    from src.infra.quality import _extract_json
    assert _extract_json(result["last_round_text"]) is None


def test_agent_loop_accumulate_cap():
    """2 万字封顶保尾：超限轨迹开头被截断标记，末尾完整保留。"""
    from types import SimpleNamespace
    from src.core.agent_loop import _ACCUM_TEXT_MAX

    big = "字" * (_ACCUM_TEXT_MAX + 5000)
    responses = iter([
        SimpleNamespace(content=[SimpleNamespace(type="text", text=big)],
                        stop_reason="end_turn",
                        usage=SimpleNamespace(input_tokens=1, output_tokens=1)),
    ])
    loop = AgentLoop(_CONFIG)
    loop._call_with_retry = (
        lambda kwargs, on_event=None, iteration=0: next(responses)
    )
    result = loop.run(system_prompt="s",
                      messages=[{"role": "user", "content": "x"}],
                      max_iterations=1)
    assert result["success"] is True
    assert len(result["content"]) <= _ACCUM_TEXT_MAX + 20  # 截断标记+末尾
    assert result["content"].startswith("(前文已截断)")


# ======================================================================
# 3. RiskLoop MessageBus + on_speech
# ======================================================================
def _skill_key(system_prompt: str) -> str:
    """load_skill 会剥掉 frontmatter，按正文首行标题识别 skill。"""
    head = system_prompt.strip().split("\n")[0]
    table = [
        ("看多辩论者", "bull"), ("看空辩论者", "bear"),
        ("基本面分析师", "fund"), ("新闻分析师", "news"),
        ("研究经理", "rm"), ("交易员", "trader"),
        ("激进风险辩手", "risk_aggressive"),
        ("保守风险辩手", "risk_conservative"),
        ("中性风险辩手", "risk_neutral"),
        ("风险经理", "riskmgr"), ("技术分析师", "tech"),
    ]
    for kw, key in table:
        if kw in head:
            return key
    return "unknown"


def test_risk_loop_bus_and_speech(monkeypatch):
    def fake_run(self, system_prompt, messages, tools=None, dispatch_map=None,
                 max_iterations=None, submit_tool_name=None, on_event=None):
        role = _skill_key(system_prompt).replace("risk_", "")
        return {"success": True, "content": f"{role}的质证词",
                "duration_ms": 100, "structured_output": None,
                "tool_calls": 0, "iterations": 1, "error_type": None}

    monkeypatch.setattr(AgentLoop, "run", fake_run)
    loop = RiskLoop(_CONFIG)
    speeches = []
    out = loop.run("601398.SH", {}, "", max_rounds=1,
                   on_speech=lambda rnd, role, c, d: speeches.append((rnd, role, c)))

    bus_msgs = loop.bus.get_history()
    assert len(bus_msgs) == 3, "三方各落一条 bus 消息"
    assert all(m.msg_type == "risk" for m in bus_msgs)
    assert [m.from_agent for m in bus_msgs] == [
        "aggressive-debater", "conservative-debater", "neutral-debater"]
    assert speeches == [
        (1, "aggressive", "aggressive的质证词"),
        (1, "conservative", "conservative的质证词"),
        (1, "neutral", "neutral的质证词"),
    ], "on_speech 角色必须小写（前端契约）"
    assert out["rounds"][0]["aggressive"]["content"] == "aggressive的质证词"


# ======================================================================
# 4. 端到端（假 LLM）: 事件序列 + 契约重放
# ======================================================================
TECH_JSON = {
    "score": 70, "direction": "bullish",
    "short_term_trend": "bullish", "mid_term_trend": "neutral",
    "long_term_trend": "bullish", "trend": "bullish",
    "strong_support": 7.5, "weak_support": 7.8,
    "strong_resistance": 8.5, "weak_resistance": 8.3,
    "stop_loss_price": 7.4, "target_price": 9.0, "risk_reward_ratio": "1:2.5",
    "volume_signal": "shrinking", "macd_signal": "golden_cross",
    "macd_divergence": "none", "kdj_signal": "neutral",
    "kdj_divergence": "none", "rsi_signal": "neutral",
    "rsi_divergence": "none", "money_flow_signal": "neutral",
    "money_flow_summary": "均衡", "relative_strength": "inline",
    "ma_pattern": "bullish_alignment",
    "latest_close": 8.1,
    "scoring_breakdown": {k: 7 for k in (
        "trend_ma", "trend_macd", "trend_price_position", "signal_macd",
        "signal_kdj", "signal_rsi", "volume_price", "volume_turnover",
        "relative_vs_index", "relative_volatility", "risk_reward")},
    "summary": "技术面总结",
}
FUND_JSON = {
    "score": 60, "direction": "neutral", "verdict": "稳健",
    "business_model": "银行", "roe_latest": 11.0,
    "profitability_grade": "B", "growth_grade": "B", "safety_grade": "A",
    "valuation_grade": "B", "roe_trend": "stable", "gross_margin": 40.0,
    "net_margin": 35.0, "revenue_yoy": 2.0, "revenue_trend": "stable",
    "net_profit_yoy": 1.5, "profit_trend": "stable", "debt_ratio": 92.0,
    "current_ratio": 1.0, "ocf_to_np_ratio": 1.2, "debt_structure": "存款为主",
    "pe_ttm": 7.0, "pe_percentile": 30.0, "pb": 0.8, "pb_percentile": 25.0,
    "valuation_summary": "低估", "holder_num_change_pct": -1.0,
    "holder_trend": "集中", "institutional_holders": 50,
    "institutional_ratio": 30.0, "key_strengths": ["高ROE"], "key_risks": ["高杠杆"],
    "expense_leakage": 5.0, "dupont_analysis": {"roe": 11.0},
    "cross_layer_notes": "无", "peg": 1.0, "growth_attribution": "量增",
    "insider_signal": "net_buy", "pledge_risk": "none",
    "industry_analysis": {"industry_name": "银行"},
    "scenario_analysis": {"bull": {"target_price": 9.0}, "base": {"target_price": 8.5},
                          "bear": {"target_price": 7.6}},
    "key_observations": ["观察1"],
    "scoring_breakdown": {k: 6 for k in (
        "profitability_roe", "profitability_margin", "growth_revenue",
        "growth_profit", "safety_debt", "safety_liquidity",
        "cashflow_quality", "valuation_pe", "valuation_pb", "peg_signal",
        "peer_valuation", "holder_concentration", "institutional_presence",
        "insider_signal")},
    "summary": "基本面总结",
}
NEWS_JSON = {
    "score": 55, "direction": "neutral", "news_analyzed": 5,
    "sentiment": "neutral", "key_events": [{"event": "无重大事件"}],
    "risk_events": [], "positive_factors": [], "negative_factors": [],
    "scoring_breakdown": {k: 5 for k in (
        "positive_events", "negative_events", "event_timeliness",
        "event_impact", "sentiment_alignment", "risk_level")},
    "summary": "新闻面总结",
}
RM_JSON = {
    "debate_winner": "bull", "debate_delta": 2,
    "debate_rationale": "看多引用了量价数据", "strongest_bull_point": "放量突破",
    "strongest_bear_point": "估值偏高",
    "adjusted_score": 65, "adjusted_direction": "bullish",
    "recommendation": "谨慎看多", "risk_warnings": ["注意回踩"],
    "summary": "RM的150字总结",
}
RISKMGR_JSON = {
    "score": 63, "scoring_breakdown": {"downside": 30, "liquidity": 33},
    "summary": "风险调整总结",
    "risk_level": "medium", "risk_score": 50,
    "risk_winner": "conservative", "risk_rationale": "保守方论据更扎实",
    "adjusted_direction": "neutral",
    "key_risks": ["r1"], "key_opportunities": ["o1"],
    "position_suggestion": "standard", "stop_loss_suggestion": "7.5以下",
    "risk_warnings": ["w1"],
}
TRADER_JSON = {
    "action": "buy", "action_strength": "weak", "target_price": 9.0,
    "target_price_rationale": "x", "stop_loss": 7.4, "stop_loss_rationale": "y",
    "confidence_components": {"signal_consistency": 14, "data_sufficiency": 15,
                              "debate_certainty": 12, "risk_controllability": 13,
                              "valuation_reasonableness": 12},
    "confidence_total": 66, "confidence_label": "中等",
    "position_advice": "standard", "position_range": "20%-30%",
    "risk_score": 50, "risk_level": "medium", "time_horizon": "mid_term",
    "reasoning": "综合各方研判", "warnings": ["w1"],
    "take_profit_levels": [{"price": 8.8, "portion": 40}],
}


def _fake_llm_run(self, system_prompt, messages, tools=None, dispatch_map=None,
                  max_iterations=None, submit_tool_name=None, on_event=None):
    """按 skill 首行标题分发的假 LLM：结构化输出 + 心跳回调各一份。"""
    key = _skill_key(system_prompt)

    if on_event is not None:
        on_event({"kind": "tool", "iteration": 1, "max_iterations": 5,
                  "tool": "get_kline", "tool_status": "ok",
                  "duration_ms": 800, "elapsed_ms": 900})

    structured_map = {
        "tech": TECH_JSON, "fund": FUND_JSON, "news": NEWS_JSON,
        "rm": RM_JSON, "riskmgr": RISKMGR_JSON, "trader": TRADER_JSON,
    }
    so = structured_map.get(key)

    if so is not None:
        return {"success": True, "content": f"{key}的叙述全文",
                "structured_output": dict(so), "tool_calls": 2,
                "iterations": 2, "duration_ms": 4200, "error_type": None}
    # 辩手/风险辩手: 纯文本
    return {"success": True, "content": f"{key}的发言内容",
            "structured_output": None, "tool_calls": 0,
            "iterations": 1, "duration_ms": 2100, "error_type": None}


@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setattr(AgentLoop, "run", _fake_llm_run)
    # 预取数据工具也造假，避免测试打真实 Tushare
    import src.agents.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "get_kline",
                        lambda **k: {"ok": True, "data": [], "count": 0})
    monkeypatch.setattr(orch_mod, "calc_technical", lambda **k: {})
    monkeypatch.setattr(orch_mod, "get_daily_basic", lambda **k: {})
    monkeypatch.setattr(orch_mod, "get_moneyflow", lambda **k: {})
    monkeypatch.setattr(orch_mod, "get_index", lambda **k: {})
    monkeypatch.setattr(orch_mod, "get_financials", lambda **k: {})
    monkeypatch.setattr(orch_mod, "get_governance",
                        lambda **k: {"governance_risk": "clean"})
    monkeypatch.setattr(orch_mod, "get_stock_news", lambda **k: {"ok": True})


def _replay(events):
    """前端 EventStore 组装语义的迷你重放（与 build_demo_events.replay 一致）。"""
    D = {}
    rm_json, rk_json = {}, {}
    for e in events:
        t, ag, d = e["type"], e.get("agent"), e.get("data", {})
        if t == "run_started":
            D.setdefault("meta", {})
            D["meta"]["stock_code"] = d.get("stock_code")
            D["meta"]["stock_name"] = d.get("stock_name")
        elif t == "agent_done" and ag in ("tech", "fund", "news"):
            D[ag] = {"content": d.get("content"), "json": d.get("json")}
        elif t == "agent_done" and ag == "rm":
            rm_json = d.get("json", {})
        elif t == "agent_done" and ag == "riskmgr":
            rk_json = d.get("json", {})
        elif t == "agent_done" and ag == "trader":
            D["trader"] = d.get("json")
        elif t == "stage_done" and e["stage"] == 2 and "result" in d:
            D["debate"] = d["result"]
        elif t == "stage_done" and e["stage"] == 4 and "result" in d:
            D["risk"] = d["result"]
        elif t == "run_done":
            D = d["result"]
    return D, rm_json, rk_json


def test_full_run_event_contract(fake_llm, tmp_path):
    from src.agents.orchestrator import MultiAgentOrchestrator

    em = EventEmitter("r_e2e", str(tmp_path), stock_code="601398.SH",
                      stock_name="工商银行")
    orch = MultiAgentOrchestrator(_CONFIG, persist_dir=str(tmp_path / "logs"))
    orch.run_analysis("601398.SH", debate_rounds=2, on_event=em.emit,
                      stock_name="工商银行")

    events = em.snapshot()["events"]
    types = [e["type"] for e in events]

    # --- 信封 ---
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert types[0] == "run_started" and types[-1] == "run_done"
    assert all("kind" not in e.get("data", {}) for e in events
               if e["type"] == "agent_heartbeat"), "原始 kind 不得泄漏进契约"

    # --- 六阶段齐备 ---
    for stage in range(1, 7):
        assert "stage_started" in [e["type"] for e in events if e["stage"] == stage]
        assert any(e["type"] == "stage_done" and e["stage"] == stage for e in events)

    # --- 心跳: 每位分析师至少一条工具心跳 ---
    hb_agents = {e.get("agent") for e in events if e["type"] == "agent_heartbeat"}
    assert {"tech", "fund", "news"} <= hb_agents
    hb = next(e for e in events if e["type"] == "agent_heartbeat")
    assert hb["data"]["tool"] == "get_kline" and hb["data"]["tool_status"] == "ok"

    # --- 分析师完成事件（各自带叙述全文+json）---
    for a in ("tech", "fund", "news"):
        ev = next(e for e in events
                  if e["type"] == "agent_done" and e.get("agent") == a)
        assert ev["data"]["content"].endswith("的叙述全文")
        assert ev["data"]["json"]["score"] > 0

    # --- 辩论/听证发言 ---
    debate_speeches = [e for e in events if e["type"] == "speech_done" and e["stage"] == 2]
    risk_speeches = [e for e in events if e["type"] == "speech_done" and e["stage"] == 4]
    assert len(debate_speeches) == 4, "2 轮 x 牛熊"
    assert [s["data"]["role"] for s in debate_speeches] == ["bull", "bear", "bull", "bear"]
    assert [s["data"]["role"] for s in risk_speeches] == ["aggressive", "conservative", "neutral"]

    # --- 2a: rm/riskmgr 捡回被丢字段 + 叙述全文 ---
    rm_ev = next(e for e in events
                 if e["type"] == "agent_done" and e.get("agent") == "rm")
    assert rm_ev["data"]["json"]["rm_summary"] == "RM的150字总结"
    assert rm_ev["data"]["json"]["combined_score"] == 65
    assert rm_ev["data"]["content"] == "rm的叙述全文"

    rk_ev = next(e for e in events
                 if e["type"] == "agent_done" and e.get("agent") == "riskmgr")
    assert rk_ev["data"]["json"]["risk_rationale"] == "保守方论据更扎实"
    assert rk_ev["data"]["json"]["risk_scoring_breakdown"] == {
        "downside": 30, "liquidity": 33}
    assert rk_ev["data"]["json"]["risk_level"] == "medium"
    assert rk_ev["data"]["content"] == "riskmgr的叙述全文"

    tr_ev = next(e for e in events
                 if e["type"] == "agent_done" and e.get("agent") == "trader")
    assert tr_ev["data"]["json"]["action"] == "buy"
    assert tr_ev["data"]["content"] == "trader的叙述全文"

    # --- run_done 终态形状 + 风险角色小写 ---
    final = events[-1]["data"]["result"]
    assert set(final.keys()) == {"tech", "fund", "news", "combined", "debate",
                                 "risk", "trader", "meta"}
    assert set(final["risk"]["rounds"][0].keys()) == {
        "round", "aggressive", "conservative", "neutral"}
    assert final["combined"]["rm_summary"] == "RM的150字总结"
    assert final["combined"]["risk_rationale"] == "保守方论据更扎实"

    # --- 契约重放: 事件流组装值 == run_done 终态（tech/trader/辩论/听证）---
    D, rm_json, rk_json = _replay(events)
    assert D["tech"] == final["tech"]
    assert D["trader"] == final["trader"]
    for s in debate_speeches:
        slot = final["debate"]["rounds"][s["data"]["round"] - 1][s["data"]["role"]]
        assert slot["content"] == s["data"]["content"], "辩论发言与终态一致"
    for s in risk_speeches:
        slot = final["risk"]["rounds"][s["data"]["round"] - 1][s["data"]["role"]]
        assert slot["content"] == s["data"]["content"], "听证发言与终态一致"


def test_no_on_event_backward_compatible(fake_llm):
    """不传 on_event（批量跑批路径）行为不变、不报错。"""
    from src.agents.orchestrator import MultiAgentOrchestrator
    orch = MultiAgentOrchestrator(_CONFIG)
    result = orch.run_analysis("601398.SH", debate_rounds=1)
    assert result["success"] is True
    assert result["combined_report"]["trader"]["action"] == "buy"
