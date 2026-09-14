"""
progress_emitter - 直播事件发射器 + 结果归一化

事件契约 v1（与 docs/mockups/events_demo.jsonl 同构）:
    {seq, ts(ms 自 run 起点), run_id, type, stage(1-6), agent?, data{}}

职责:
  1. EventEmitter: 把编排层的语义事件包装成契约信封，
     追加写 progress.jsonl + 全量重写快照 progress.json（线程安全）
  2. normalize_result: 把 run_analysis 的返回值归一为前端 D 视图模型形状
     （与 docs/mockups/result_data.json 同构）

设计原则:
  - fail-open: 发射器任何异常绝不影响分析主流程（只记日志）
  - 线程安全: 分析师并行跑在 3 个线程里，心跳/完成事件并发到达
"""

import json
import os
import threading
import time
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class EventEmitter:
    """契约事件的信封封装与持久化。

    用法:
        em = EventEmitter(run_id, out_dir, stock_code="601398.SH", stock_name="工商银行")
        em.emit("run_started", 1, {"stock_code": "...", "plan": [...]})
        ...
        em.finalize("done")
    """

    def __init__(
        self,
        run_id: str,
        out_dir: str,
        stock_code: str = "",
        stock_name: str = "",
    ):
        self.run_id = run_id
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.out_dir = out_dir
        self.jsonl_path = os.path.join(out_dir, "progress.jsonl")
        self.snapshot_path = os.path.join(out_dir, "progress.json")
        self._lock = threading.Lock()
        self._seq = 0
        self._t0 = time.time()
        self._started_ts = int(time.time() * 1000)
        self._events: list[dict] = []
        self.status = "running"

        os.makedirs(out_dir, exist_ok=True)
        # 落一份初始快照，保证前端轮询一接上就有东西可看
        self._write_snapshot()

    # ------------------------------------------------------------------
    # 对外主入口：编排层只管报语义事件，信封/序号/时间戳/落盘全在这里
    # ------------------------------------------------------------------
    def emit(
        self,
        etype: str,
        stage: int,
        data: dict,
        agent: Optional[str] = None,
    ):
        """包装信封并持久化。任何异常吞掉（直播挂了不能影响分析）。"""
        try:
            with self._lock:
                self._seq += 1
                ev = {
                    "seq": self._seq,
                    "ts": int((time.time() - self._t0) * 1000),
                    "run_id": self.run_id,
                    "type": etype,
                    "stage": stage,
                }
                if agent:
                    ev["agent"] = agent
                ev["data"] = data
                self._events.append(ev)
                self._append_jsonl(ev)
                self._write_snapshot_locked()
        except Exception as e:  # pragma: no cover - 防御性
            logger.warning(f"[Emitter] emit failed ({etype}): {e}")

    def finalize(self, status: str = "done"):
        """收尾：把快照状态置为 done/error。"""
        try:
            with self._lock:
                self.status = status
                self._write_snapshot_locked()
        except Exception as e:  # pragma: no cover
            logger.warning(f"[Emitter] finalize failed: {e}")

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def snapshot(self) -> dict:
        """内存快照（GET /progress 直接读这个，不碰文件）。"""
        with self._lock:
            return self._snapshot_dict_locked()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _snapshot_dict_locked(self) -> dict:
        return {
            "run_id": self.run_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "status": self.status,
            "started_ts": self._started_ts,
            "last_seq": self._seq,
            "events": list(self._events),
        }

    def _append_jsonl(self, ev: dict):
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")

    def _write_snapshot_locked(self):
        tmp = self.snapshot_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._snapshot_dict_locked(), f, ensure_ascii=False, default=str)
        os.replace(tmp, self.snapshot_path)

    def _write_snapshot(self):
        with self._lock:
            self._write_snapshot_locked()


# ----------------------------------------------------------------------
# 结果归一化：run_analysis 返回值 -> 前端 D 视图模型（== result_data.json 形状）
# ----------------------------------------------------------------------
def normalize_result(result: dict, stock_name: str = "") -> dict:
    """把 orchestrator.run_analysis 的返回值映射为 demo 契约的 D 形状。

    映射要点:
      - tech/fund/news: {content, json_data} -> {content, json}
      - risk.rounds: 大写角色名(Aggressive) -> 小写(aggressive)，与前端一致
      - trader: 从 combined_report.trader 提出为顶层
      - meta: 汇总降级信息 + duration_s
    """
    combined = result.get("combined_report") or {}
    degradation = result.get("degradation_summary") or {}

    def _analyst(key: str) -> dict:
        blk = result.get(key) or {}
        return {"content": blk.get("content") or "", "json": blk.get("json_data") or {}}

    risk_raw = result.get("risk_result") or {}
    risk_norm = _normalize_risk(risk_raw)

    return {
        "tech": _analyst("tech_report"),
        "fund": _analyst("fund_report"),
        "news": _analyst("news_report"),
        "combined": combined,
        "debate": result.get("debate_result") or {},
        "risk": risk_norm,
        "trader": combined.get("trader") or {},
        "meta": {
            "stock_code": result.get("stock_code", ""),
            "stock_name": stock_name or result.get("stock_name", ""),
            "success": bool(result.get("success")),
            "duration_s": round((result.get("duration_ms") or 0) / 1000),
            "degradation": degradation,
        },
    }


def _normalize_risk(risk_raw: dict) -> dict:
    """risk_result 的 rounds 键归一为小写角色名（前端契约）。

    兼容两种来源: risk_loop 原生小写键 / 历史批量结果的大写键。
    """
    if not risk_raw:
        return {}
    out = dict(risk_raw)
    rounds = []
    for rd in risk_raw.get("rounds") or []:
        nrd = {"round": rd.get("round")}
        for role in ("aggressive", "conservative", "neutral"):
            if role in rd:
                nrd[role] = rd[role]
            elif role.capitalize() in rd:
                nrd[role] = rd[role.capitalize()]
        rounds.append(nrd)
    out["rounds"] = rounds
    return out
