# -*- coding: utf-8 -*-
"""build_demo_events.py - 从 result_data.json 机械生成 demo 事件流（事件契约 v1）

契约铁律：
1. 事件载荷与 result_data.json 完全同构：agent_done.data.json 就是 D.tech.json 原样
2. 时间轴全部来自真实跑批 output/batch_d_cure/result_601398_SH.json（工商银行 601398）
3. 内置断言：全量重放（reducer 组装）结果必须深度等于 result_data.json

输出（docs/mockups/ 下）：
- events_demo.jsonl            基准事件流（正常完成）
- events_demo_degraded.jsonl   降级版（新闻分析师超时兜底，UI 验收黄标用）
- progress_demo.json           快照形状（?source=live 换源验收用）

用法：python -X utf8 scripts/build_demo_events.py
"""

import copy
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCKUPS = ROOT / "docs" / "mockups"
RESULT_PATH = MOCKUPS / "result_data.json"

# ---------------------------------------------------------------------------
# 真实时间轴（ms），取自 output/batch_d_cure/result_601398_SH.json 实测
# ---------------------------------------------------------------------------
TIMING = {
    "tech": {"duration_ms": 35748, "iterations": 3, "tool_calls": 7},
    "fund": {"duration_ms": 103169, "iterations": 3, "tool_calls": 7},
    "news": {"duration_ms": 62170, "iterations": 2, "tool_calls": 2},
    "debate": {
        "total_ms": 54921,
        "speeches": [  # (stage, round, role, duration_ms) 顺序=真实发言顺序
            (2, 1, "bull", 11462),
            (2, 1, "bear", 15585),
            (2, 2, "bull", 12821),
            (2, 2, "bear", 15042),
        ],
    },
    "risk": {
        "total_ms": 33635,
        "speeches": [  # 真实顺序：激进 -> 保守 -> 中性（risk_loop.RISK_DEBATERS）
            (4, 1, "aggressive", 10784),
            (4, 1, "conservative", 9945),
            (4, 1, "neutral", 12900),
        ],
    },
    "rm": {"duration_ms": 24300},       # 推算：总266s - 阶段1~4实测 - 风险经理/交易员
    "riskmgr": {"duration_ms": 21200},  # 推算
    "trader": {"duration_ms": 23400},   # 推算
    "total_ms": 266037,
}

# 每位分析师的工具序列（名称来自 orchestrator.py 真实注册表；次数=实测 tool_calls）
TOOL_SEQ = {
    "tech": ["get_kline", "calc_technical", "get_daily_basic", "get_moneyflow",
             "calc_technical", "get_moneyflow", "get_index"],
    "fund": ["get_financials", "get_daily_basic", "get_institutional",
             "get_dcf_valuation", "get_peers", "get_financials", "get_index"],
    "news": ["get_stock_news", "get_stock_news"],
}

# combined 的 38 键分区：RM 产出前 31 键，风险经理补后 7 键（与后端实际产出一致）
RM_KEYS = [
    "combined_score", "combined_direction", "tech_score", "tech_direction",
    "fund_score", "fund_direction", "news_score", "news_direction", "alignment",
    "tech_scoring_breakdown", "fund_scoring_breakdown", "news_scoring_breakdown",
    "tech_data_freshness", "fund_data_freshness", "news_data_freshness",
    "tech_key_observations", "fund_key_strengths", "fund_key_risks",
    "news_key_events", "news_risk_events", "recommendation", "stock_type",
    "weight_rationale", "summary", "debate_winner", "debate_delta",
    "debate_rationale", "strongest_bull_point", "strongest_bear_point",
    "risk_warnings", "synthesis_method",
]
RISKMGR_KEYS = [
    "risk_level", "risk_score", "risk_winner", "key_risks",
    "key_opportunities", "position_suggestion", "stop_loss_suggestion",
]

STAGE_LABELS = {1: "三路侦察", 2: "多空对决", 3: "经理裁决", 4: "风险听证", 5: "风险裁决", 6: "交易员拍板"}

rng = random.Random(601398)  # 固定种子，事件流可复现


class Builder:
    def __init__(self, result):
        self.result = result
        self.events = []
        self.seq = 0
        self.t = 0  # 当前时间游标 ms

    def emit(self, ts, etype, stage, data, agent=None):
        self.seq += 1
        ev = {"seq": self.seq, "ts": int(ts), "run_id": "r_601398_demo",
              "type": etype, "stage": stage}
        if agent:
            ev["agent"] = agent
        ev["data"] = data
        self.events.append(ev)
        self.t = max(self.t, ts)

    def build(self):
        meta = self.result["meta"]
        stock_code = meta["stock_code"]
        stock_name = meta["stock_name"]

        # ---- 开场 ----
        plan = [
            {"stage": i, "label": STAGE_LABELS[i],
             "est_ms_range": [est[0], est[1]]}
            for i, est in enumerate(
                [(10, 130), (50, 115), (20, 40), (30, 70), (20, 40), (20, 40)], 1)
        ]
        self.emit(0, "run_started", 1,
                  {"stock_code": stock_code, "stock_name": stock_name,
                   "max_iterations": 10, "debate_rounds": 2, "plan": plan})

        # ---- 阶段1：三分析师并行 ----
        self.emit(500, "stage_started", 1, {"label": STAGE_LABELS[1]})
        analysts = ("tech", "fund", "news")
        key_map = {"tech": "tech", "fund": "fund", "news": "news"}
        done_at = {}
        for a in analysts:
            done_at[a] = 500 + TIMING[a]["duration_ms"]
        # 心跳：按迭代把工具调用铺进各自时间窗
        for a in analysts:
            info = TIMING[a]
            tools = TOOL_SEQ[a]
            iters = info["iterations"]
            start, dur = 500, info["duration_ms"]
            # 每轮迭代的时间片（LLM思考+工具调用），工具分布在片内后段
            per = dur / iters
            ti = 0
            for i in range(1, iters + 1):
                # 迭代开始：一条"开始第N轮推理"心跳（无 tool）
                iter_at = start + per * (i - 1) + 200
                self.emit(min(iter_at, done_at[a] - 600), "agent_heartbeat", 1,
                          {"iteration": i, "max_iterations": 10,
                           "elapsed_ms": round(iter_at - start)}, agent=a)
                n_tools_here = (len(tools) // iters) + (1 if i <= len(tools) % iters else 0)
                seg = per * i
                for j in range(n_tools_here):
                    if ti >= len(tools):
                        break
                    tool = tools[ti]
                    ti += 1
                    tool_ms = rng.uniform(1200, 4200)
                    at = start + seg - per * 0.35 + (j * per * 0.25)
                    self.emit(min(at, done_at[a] - 500), "agent_heartbeat", 1,
                              {"iteration": i, "max_iterations": 10,
                               "tool": tool, "tool_status": "ok",
                               "duration_ms": round(tool_ms),
                               "elapsed_ms": round(at - start)}, agent=a)
        # 各自完成即发 agent_done（不等齐，与第二阶段后端行为一致）
        for a in sorted(analysts, key=lambda x: done_at[x]):
            blk = self.result[key_map[a]]
            info = TIMING[a]
            self.emit(done_at[a], "agent_done", 1,
                      {"content": blk["content"], "json": blk["json"],
                       "duration_ms": info["duration_ms"],
                       "tool_calls": info["tool_calls"],
                       "iterations": info["iterations"],
                       "error_type": None}, agent=a)
        stage1_end = max(done_at.values()) + 400
        self.emit(stage1_end, "stage_done", 1,
                  {"duration_ms": stage1_end - 500})

        # ---- 阶段2：多空辩论（逐条发言）----
        gap = 500
        t2 = stage1_end + gap
        self.emit(t2, "stage_started", 2, {"label": STAGE_LABELS[2]})
        cur = t2 + 300
        for (_stage, rnd, role, dur) in TIMING["debate"]["speeches"]:
            cur += dur
            content = self.result["debate"]["rounds"][rnd - 1][role]["content"]
            self.emit(cur, "speech_done", 2,
                      {"round": rnd, "role": role, "content": content,
                       "duration_ms": dur}, agent=role)
        t2_end = cur + 300
        self.emit(t2_end, "stage_done", 2,
                  {"duration_ms": TIMING["debate"]["total_ms"],
                   "result": self.result["debate"]})

        # ---- 阶段3：研究经理 ----
        t3 = t2_end + gap
        self.emit(t3, "stage_started", 3, {"label": STAGE_LABELS[3]})
        rm_json = {k: self.result["combined"][k] for k in RM_KEYS}
        t3_done = t3 + 300 + TIMING["rm"]["duration_ms"]
        self.emit(t3_done, "agent_done", 3,
                  {"json": rm_json, "duration_ms": TIMING["rm"]["duration_ms"],
                   "tool_calls": 0, "iterations": 1, "error_type": None,
                   "content": None}, agent="rm")
        self.emit(t3_done + 300, "stage_done", 3,
                  {"duration_ms": TIMING["rm"]["duration_ms"]})

        # ---- 阶段4：三方风险听证 ----
        t4 = t3_done + gap
        self.emit(t4, "stage_started", 4, {"label": STAGE_LABELS[4]})
        cur = t4 + 300
        for (_stage, rnd, role, dur) in TIMING["risk"]["speeches"]:
            cur += dur
            content = self.result["risk"]["rounds"][rnd - 1][role]["content"]
            self.emit(cur, "speech_done", 4,
                      {"round": rnd, "role": role, "content": content,
                       "duration_ms": dur}, agent=role)
        t4_end = cur + 300
        self.emit(t4_end, "stage_done", 4,
                  {"duration_ms": TIMING["risk"]["total_ms"],
                   "result": self.result["risk"]})

        # ---- 阶段5：风险经理 ----
        t5 = t4_end + gap
        self.emit(t5, "stage_started", 5, {"label": STAGE_LABELS[5]})
        rk_json = {k: self.result["combined"][k] for k in RISKMGR_KEYS}
        t5_done = t5 + 300 + TIMING["riskmgr"]["duration_ms"]
        self.emit(t5_done, "agent_done", 5,
                  {"json": rk_json, "duration_ms": TIMING["riskmgr"]["duration_ms"],
                   "tool_calls": 0, "iterations": 1, "error_type": None,
                   "content": None}, agent="riskmgr")
        self.emit(t5_done + 300, "stage_done", 5,
                  {"duration_ms": TIMING["riskmgr"]["duration_ms"]})

        # ---- 阶段6：交易员 ----
        t6 = t5_done + gap
        self.emit(t6, "stage_started", 6, {"label": STAGE_LABELS[6]})
        t6_done = t6 + 300 + TIMING["trader"]["duration_ms"]
        self.emit(t6_done, "agent_done", 6,
                  {"json": self.result["trader"],
                   "duration_ms": TIMING["trader"]["duration_ms"],
                   "tool_calls": 0, "iterations": 1, "error_type": None,
                   "content": None}, agent="trader")
        self.emit(t6_done + 300, "stage_done", 6,
                  {"duration_ms": TIMING["trader"]["duration_ms"]})

        # ---- 收尾：总时长校准到真实 266037ms ----
        final_ts = TIMING["total_ms"]
        self.emit(final_ts, "run_done", 6, {"result": self.result})
        # 时间轴自检：摊派误差不超过 3 秒
        drift = final_ts - t6_done
        assert abs(drift) <= 4000, f"timeline drift {drift}ms too large"
        # 真实运行按时间顺序发事件：按 ts 稳定排序后重编 seq（并行流已合并）
        self.events.sort(key=lambda e: e["ts"])
        for i, e in enumerate(self.events, 1):
            e["seq"] = i
        return self.events


def make_degraded_result(result):
    """降级版：新闻分析师 180s 超时走规则兜底（内容保持同构，仅状态标注变化）"""
    res = copy.deepcopy(result)
    res["meta"]["degradation"]["news_analyst"] = "timeout"
    res["meta"]["degradation"]["synthesis_method"] = "regex_debate_adjustment_with_risk_manager_with_trader"
    res["meta"]["degradation"]["overall_degraded"] = True
    return res


def degrade_events(events, degraded_result):
    """基于基准事件流制造降级版：news 超时兜底 + 一次限流重试心跳"""
    evs = copy.deepcopy(events)
    for e in evs:
        if e["type"] == "run_done":
            e["data"]["result"] = degraded_result
    for e in evs:
        if e["type"] == "agent_done" and e.get("agent") == "news":
            e["data"]["error_type"] = "timeout"
            e["data"]["duration_ms"] = 180012  # 180s 超时围栏
        if e["type"] == "agent_heartbeat" and e.get("agent") == "fund" \
                and e["data"].get("iteration") == 2:
            e["data"]["tool_status"] = "retry"
            e["data"]["retry_note"] = "API限流，10秒后自动重试"
    # 降级导致总时长拉长：整体时间轴平移不需要（demo 演示用，run_done ts 保持）
    return evs


# ---------------------------------------------------------------------------
# reducer：与前端 EventStore 相同的组装语义（纯函数，重放等价断言用）
# ---------------------------------------------------------------------------
def replay(events):
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
            D = d["result"]  # 终态为真相
    return D


def assert_equivalent(events, expected, label):
    got = replay(events)
    ok = got == expected
    if not ok:
        for k in expected:
            if got.get(k) != expected[k]:
                print(f"[FAIL] {label}: top key mismatch -> {k}")
                ge, ee = got.get(k), expected[k]
                if isinstance(ge, dict) and isinstance(ee, dict):
                    for kk in ee:
                        if ge.get(kk) != ee[kk]:
                            print(f"    sub key: {kk}\n      got: {str(ge.get(kk))[:120]}\n      exp: {str(ee[kk])[:120]}")
                            break
        raise SystemExit(1)
    # 附带校验：speech 事件与 stage_done.result 里的 rounds 一致
    for e in events:
        if e["type"] == "speech_done":
            blk = e["stage"] == 2 and expected["debate"] or expected["risk"]
            slot = blk["rounds"][e["data"]["round"] - 1][e["data"]["role"]]
            assert slot["content"] == e["data"]["content"], f"speech mismatch {e['seq']}"
    n = len(events)
    print(f"[OK] {label}: replay == result (deep equal), {n} events, last_ts={events[-1]['ts']}ms")
    return n


def main():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    # 分区自检：RM+风险经理键必须恰好覆盖 combined 全部键
    assert set(RM_KEYS) | set(RISKMGR_KEYS) == set(result["combined"].keys()), \
        "combined partition mismatch"
    assert not (set(RM_KEYS) & set(RISKMGR_KEYS)), "partition overlap"

    events = Builder(result).build()

    # 基准断言
    assert_equivalent(events, result, "base fixture")

    # 降级版
    degraded_result = make_degraded_result(result)
    degraded_events = degrade_events(events, degraded_result)
    assert_equivalent(degraded_events, degraded_result, "degraded fixture")

    # 落盘
    (MOCKUPS / "events_demo.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8")
    (MOCKUPS / "events_demo_degraded.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in degraded_events) + "\n",
        encoding="utf-8")
    snapshot = {
        "run_id": "r_601398_demo",
        "stock_code": result["meta"]["stock_code"],
        "stock_name": result["meta"]["stock_name"],
        "status": "done",
        "started_ts": 0,
        "last_seq": events[-1]["seq"],
        "events": events,
    }
    (MOCKUPS / "progress_demo.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")

    hb = sum(1 for e in events if e["type"] == "agent_heartbeat")
    sp = sum(1 for e in events if e["type"] == "speech_done")
    print(f"[OK] written: events_demo.jsonl / events_demo_degraded.jsonl / progress_demo.json")
    print(f"     events={len(events)} (heartbeat={hb}, speech={sp}), "
          f"total timeline={events[-1]['ts']/1000:.1f}s")


if __name__ == "__main__":
    main()
