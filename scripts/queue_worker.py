# -*- coding: utf-8 -*-
"""queue_worker - W2 M2 队列工人进程（常驻、零 HTTP、假研究模式不调 LLM）。

设计依据：
  - 契约冻结文档：ai-investment-tool/docs/development/2026-10-10-w2-research-contract.md
  - W2 计划第五/七节 M2 行：docs/plans/2026-10-09-w2-ai-bridge-plan.md
  - 本进程零 HTTP：一切与主后端的通信只经 ai_investment.db（WAL 跨进程）

主流程：
  定位锁文件（本仓 output/bridge/worker.lock，目录不存在则建）
  -> acquire_instance_lock（第二个实例礼让退出码 42）
  -> 连库（env AI_INVEST_DB，未配置=配置错误退出码 2）
  -> startup_sweep（无条件收尸 running -> failed(swept_on_restart)）
  -> register_worker（ai_worker 单行 + db_signature 同库校验值）
  -> 主循环：claim_next 领队 -> 假研究 6 阶段 -> finish_run 写假结论

心跳：daemon 线程 15 秒周期双写（run 级 + worker 级）；
  beat_run 返回 False = 所有权已丢 -> 置 abort 标志，阶段间检查后放弃当前 run。
stop_flag 语义（船长拍板）：只在两个 run 之间检查；命中则跑完逻辑退出，
  当前 run 必须先跑完。空闲轮询间隔 env AI_WORKER_POLL_SECONDS 默认 5 秒。

假研究：6 个阶段，每阶段 sleep(env W2_FAKE_STAGE_SECONDS 默认 2 秒) 后
  update_stage（sleep 期间绝不持有任何事务）。跑完 finish_run 写：
  verdict=观望 / score=看多·置信度70% / act=watch /
  summary=比机构成本 便宜12.3%（M2 假研究占位）。

M4 旁听文件桥（假研究与真跑共用）：领队后生成文本运行号
  run_id = r_<6位代码>_<SH|SZ|BJ>_<YYYYMMDD>_<HHMMSS>，在
  output/live/<run_id>/ 下产出三件套（信封与原子快照写法逐字照抄
  src/infra/progress_emitter.py）：
    progress.jsonl  事件逐条追加（冻结信封五类 started/stage_start/
                    agent_msg/stage_end/finalize）
    progress.json   全量快照，tmp+os.replace 原子重写（主仓 live 端点
                    原样转发这个文件）
    result.json     收尾一次写 {verdict, score, act, summary, confidence,
                    meta:{duration_s, fake}}
  文件是旁听副本，库才是事实源：任何写失败只计数+记日志，绝不中断研究。
  事件全在主循环线程写（心跳线程照旧只跳心跳，无跨线程共享）。
  finish_run 把 run_id/run_dir 两文本列写回 ai_runs（run_dir=目录名）。

真跑分支（env W2_REAL_LLM=1 才进；W2 默认 0=假研究，M5 才翻开）：
  try import orchestrator 后 run_analysis(research_context=context_json
  解析)，返回后做首句锚校验，不合规则以确定性模板拼首句放报告顶；
  selftest 恒走假研究。

退出码：正常 0 / 礼让 42 / 配置错误 2 / 未预期异常 1。

用法：
  python -X utf8 scripts/queue_worker.py                 # 生产模式（常驻）
  python -X utf8 scripts/queue_worker.py --selftest      # 自测（自动临时库）
  python -X utf8 scripts/queue_worker.py --selftest D:\\tmp\\xx.db
                                                         # 自测（指定临时库）

注意：--selftest 会抢本仓的正式单实例锁（与双开测试语义一致）；
  若生产 worker 正在跑，selftest 会以 42 礼让退出。selftest 只允许
  系统临时目录或本仓 output/ 下的库路径，绝不触碰真身库。
"""

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))  # python scripts/queue_worker.py 时 src 包可导入

from src.infra.db_bridge import (  # noqa: E402
    DbQueue,
    acquire_instance_lock,
    connect,
    release_instance_lock,
)

REPO_ROOT = PROJECT
BRIDGE_DIR = REPO_ROOT / "output" / "bridge"
LOCK_FILE = BRIDGE_DIR / "worker.lock"
LOG_FILE = BRIDGE_DIR / "worker.log"
# 旁听文件根目录（真跑与假研究共用；selftest 传临时目录，绝不写真目录）
DEFAULT_LIVE_ROOT = REPO_ROOT / "output" / "live"

# 真跑分支开关（W2 默认 0=假研究；M5 才翻开真跑）
REAL_LLM_ENV = "W2_REAL_LLM"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2
EXIT_POLITE = 42

TOTAL_STAGES = 6
STAGE_NAMES = {
    1: "三路侦察", 2: "多空对决", 3: "经理裁决",
    4: "风险听证", 5: "风险裁决", 6: "交易员拍板",
}
# 契约第五节：心跳周期硬编码 15 秒（selftest 为采样密度改用 1 秒，仅测试）
HEARTBEAT_INTERVAL = 15.0

# M2 假研究结论（占位数字，不调 LLM；W3/M5 换真研究管线时整体替换）。
# run_id/run_dir 文本列由 _process_run_fake 按本次运行号成对补入，
# 不放在这份静态结论里。
FAKE_RESULT = {
    "verdict": "观望",
    "score": "看多·置信度70%",
    "act": "watch",
    "summary": "比机构成本 便宜12.3%（M2 假研究占位）",
    "confidence": 0.70,
}

# M4 假研究每阶段的发言 agent（取值必须在冻结信封的 agent 词表内：
# 技术分析师|基本面分析师|新闻分析师|多方|空方|研究经理|激进派|中立派|
# 保守派|风险经理|交易员）；每阶段恰好 2 条 agent_msg
STAGE_AGENTS = {
    1: ("技术分析师", "基本面分析师"),
    2: ("多方", "空方"),
    3: ("研究经理", "研究经理"),
    4: ("激进派", "保守派"),
    5: ("风险经理", "风险经理"),
    6: ("交易员", "交易员"),
}

# 假研究占位发言（同一 agent 一阶段内说两句，取列表前两个）
FAKE_SPEECHES = {
    "技术分析师": [
        "技术面：量价配合尚可，30日均线走平（假研究占位发言）",
        "技术面：MACD 零轴下方收敛，短期压力位未破（假研究占位发言）",
    ],
    "基本面分析师": [
        "基本面：营收增速平稳，经营现金流覆盖尚可（假研究占位发言）",
        "基本面：估值处于行业中位数附近，未见明显高估（假研究占位发言）",
    ],
    "多方": [
        "多方：机构成本就在下方，回踩即是机会（假研究占位发言）",
        "多方：低位筹码锁定良好，抛压有限（假研究占位发言）",
    ],
    "空方": [
        "空方：上方套牢盘密集，反弹高度存疑（假研究占位发言）",
        "空方：量能萎缩，缺乏持续上攻动能（假研究占位发言）",
    ],
    "研究经理": [
        "经理裁决：多空论据大致均衡，倾向中性偏多（假研究占位发言）",
        "经理裁决：维持评分不变，等待量能确认（假研究占位发言）",
    ],
    "激进派": [
        "激进派：风险可控，当前位置可以左侧介入（假研究占位发言）",
        "激进派：回调即是分批建仓窗口（假研究占位发言）",
    ],
    "保守派": [
        "保守派：右侧信号未现，建议继续等待（假研究占位发言）",
        "保守派：仓位宜轻，止损纪律优先（假研究占位发言）",
    ],
    "风险经理": [
        "风险裁决：整体风险中等，建议轻仓观望（假研究占位发言）",
        "风险裁决：止损位参考前低，破位则离场（假研究占位发言）",
    ],
    "交易员": [
        "交易员拍板：观望为主，等待趋势明朗（假研究占位发言）",
        "交易员拍板：不追高，低位挂单试探（假研究占位发言）",
    ],
}

# 冻结信封事件类型词表（契约冻结形状 F；主仓 events/live 端点按此解析）
FROZEN_EVENT_TYPES = ("started", "stage_start", "agent_msg", "stage_end",
                      "finalize")

# 真跑分支：编排层事件类型 -> 冻结信封类型（agent_heartbeat 等其余丢弃）
_REAL_EVENT_TYPE_MAP = {
    "run_started": "started",
    "stage_started": "stage_start",
    "stage_done": "stage_end",
    "agent_done": "agent_msg",
    "speech_done": "agent_msg",
    "run_done": "finalize",
}

# 真跑分支：编排层 agent 英文 id -> 冻结信封中文 agent 名
_REAL_AGENT_NAME_MAP = {
    "tech": "技术分析师", "fund": "基本面分析师", "news": "新闻分析师",
    "bull": "多方", "bear": "空方", "rm": "研究经理",
    "aggressive": "激进派", "neutral": "中立派", "conservative": "保守派",
    "riskmgr": "风险经理", "trader": "交易员",
}


def _make_run_id(stock_code: str) -> str:
    """文本运行号 r_<6位代码>_<市场>_<YYYYMMDD>_<HHMMSS>。

    后缀映射 .SH->SH / .SZ->SZ / .BJ->BJ，日期时间取当天当下。
    """
    num, _, suffix = stock_code.partition(".")
    market = suffix.strip().upper()
    return "r_%s_%s_%s_%s" % (num, market, time.strftime("%Y%m%d"),
                              time.strftime("%H%M%S"))


def _first_sentence_of(text: str) -> str:
    """取首句（中文句号/叹号/问号/换行任一终止，保留终止符）。"""
    for sep in ("。", "！", "？", "\n"):
        idx = text.find(sep)
        if idx >= 0:
            return text[:idx] if sep == "\n" else text[:idx + 1]
    return text


def _load_model_config() -> Dict:
    """读 AI 仓 config/model.json（真跑分支用；与 worker_server 同源）。"""
    with open(REPO_ROOT / "config" / "model.json", encoding="utf-8") as f:
        return json.load(f)


class _FileEventBridge:
    """研究运行的旁听文件桥（progress.jsonl / progress.json / result.json）。

    信封与原子快照写法逐字照抄 src/infra/progress_emitter.py：
      - 事件信封 {seq, ts(自起跑毫秒), run_id, type, stage(1-6|null),
        agent(文本|null), data{...}}（agent_msg 必有 data.text 由调用方保证）
      - 快照 {run_id, stock_code, stock_name, status, started_ts, last_seq,
        events(全量)}，tmp + os.replace 原子重写
    与 progress_emitter 的两点刻意差异：它服务 3 个分析师线程需要加锁，
    本桥只被主循环线程使用（心跳线程不碰文件）故无锁；写失败在本桥
    计数（write_failures）供上层日志透出，progress_emitter 只记日志。

    文件是旁听副本，库才是事实源：一切写失败只计数+记日志，绝不抛出、
    绝不中断研究。
    """

    def __init__(self, run_id: str, run_dir: str, stock_code: str,
                 stock_name: str, log: logging.Logger) -> None:
        self.run_id = run_id
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.run_dir = run_dir
        self.jsonl_path = os.path.join(run_dir, "progress.jsonl")
        self.snapshot_path = os.path.join(run_dir, "progress.json")
        self.status = "running"
        self.events: List[Dict] = []
        self.write_failures = 0
        self._seq = 0
        self._t0 = time.time()
        self._started_ts = int(time.time() * 1000)
        self._log = log
        try:
            os.makedirs(run_dir, exist_ok=True)
        except Exception:
            self._count_failure("建 run 目录")
        self._write_snapshot()  # 初始快照：旁听一接上就有东西可看

    def _count_failure(self, what: str) -> None:
        self.write_failures += 1
        self._log.warning("旁听文件写失败（%s，第 %d 次，不影响研究）",
                          what, self.write_failures, exc_info=True)

    def emit(self, etype: str, stage, data: Dict,
             agent: Optional[str] = None) -> None:
        """按冻结信封落一条事件：追加 jsonl + 原子重写快照。绝不抛出。"""
        ev = {
            "seq": self._seq + 1,
            "ts": int((time.time() - self._t0) * 1000),
            "run_id": self.run_id,
            "type": etype,
            "stage": stage,
        }
        if agent:
            ev["agent"] = agent
        ev["data"] = data
        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        except Exception:
            self._count_failure("追加 progress.jsonl")
        self._seq += 1
        self.events.append(ev)
        self._write_snapshot()

    def finalize(self, status: str = "done") -> None:
        """快照状态收尾（running -> done/error）。"""
        self.status = status
        self._write_snapshot()

    def write_result(self, payload: Dict) -> None:
        """result.json 收尾一次写（tmp+os.replace 原子落盘）。绝不抛出。"""
        path = os.path.join(self.run_dir, "result.json")
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, default=str)
            os.replace(tmp, path)
        except Exception:
            self._count_failure("写 result.json")

    def _snapshot_dict(self) -> Dict:
        return {
            "run_id": self.run_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "status": self.status,
            "started_ts": self._started_ts,
            "last_seq": self._seq,
            "events": list(self.events),
        }

    def _write_snapshot(self) -> None:
        try:
            tmp = self.snapshot_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._snapshot_dict(), f, ensure_ascii=False,
                          default=str)
            os.replace(tmp, self.snapshot_path)
        except Exception:
            self._count_failure("重写 progress.json")


def _env_float(name: str, default: float) -> float:
    """读正浮点 env；缺失/非法/非正值一律回退默认值。"""
    try:
        value = float(os.environ.get(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


def setup_logging() -> logging.Logger:
    """控制台 + 滚动文件双输出（10MB x 3，utf-8）。配置在根 logger，
    使 db_bridge 等模块日志同样落地。"""
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return root
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(threadName)s %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file_handler = RotatingFileHandler(
        str(LOG_FILE), maxBytes=10 * 1024 * 1024, backupCount=3,
        encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(file_handler)
    return root


class QueueWorker:
    """常驻队列工人：领队循环 + 假研究 + 心跳线程 + 终态守卫收尾。"""

    def __init__(self, db_path: Optional[str] = None,
                 stage_seconds: Optional[float] = None,
                 poll_seconds: Optional[float] = None,
                 heartbeat_interval: float = HEARTBEAT_INTERVAL,
                 live_root: Optional[Path] = None,
                 real_llm: Optional[bool] = None):
        self._queue = DbQueue(db_path)
        self._stage_seconds = (stage_seconds if stage_seconds is not None
                               else _env_float("W2_FAKE_STAGE_SECONDS", 2.0))
        self._poll_seconds = (poll_seconds if poll_seconds is not None
                              else _env_float("AI_WORKER_POLL_SECONDS", 5.0))
        self._heartbeat_interval = heartbeat_interval
        # 旁听文件根目录：生产=output/live（相对本仓根）；selftest 注入临时目录
        self._live_root = (Path(live_root) if live_root is not None
                           else DEFAULT_LIVE_ROOT)
        # None=跟 env W2_REAL_LLM；selftest 恒传 False（绝不真调 LLM）
        self._real_llm = real_llm
        self._logger = logging.getLogger("queue_worker")
        # 心跳线程与主循环的共享状态：一把小锁保护两个变量
        self._state_lock = threading.Lock()
        self._current_run_id: Optional[int] = None
        self._ownership_lost = False
        self._hb_stop = threading.Event()

    # -- 共享状态（主线程写为主、心跳线程读写）--

    def _begin_run_tracking(self, run_id: int) -> None:
        """领队成功后登记当前 run 并清掉上一轮的 abort 标志（原子）。"""
        with self._state_lock:
            self._current_run_id = run_id
            self._ownership_lost = False

    def _clear_current_run(self) -> None:
        """写终态前先摘牌：防心跳与 finish/fail 竞态误报所有权丢失。"""
        with self._state_lock:
            self._current_run_id = None

    def _heartbeat_snapshot(self) -> Tuple[Optional[int], bool]:
        with self._state_lock:
            return self._current_run_id, self._ownership_lost

    def _mark_ownership_lost(self) -> None:
        with self._state_lock:
            self._ownership_lost = True

    def _ownership_lost_flag(self) -> bool:
        with self._state_lock:
            return self._ownership_lost

    # -- 心跳线程（daemon，契约：15 秒周期双写 run 级 + worker 级）--

    def _heartbeat_loop(self) -> None:
        q = self._queue  # DbQueue thread-local：本线程自动获得自己的连接
        while not self._hb_stop.wait(self._heartbeat_interval):
            run_id, lost = self._heartbeat_snapshot()
            try:
                if run_id is not None and not lost:
                    if not q.beat_run(run_id):
                        self._mark_ownership_lost()
                        self._logger.warning(
                            "run %d 心跳写 rowcount=0：所有权已丢（判死/收尾过）",
                            run_id)
                q.beat_worker()
            except sqlite3.Error:
                # 心跳失败不致命：记日志下轮重试（绝不静默吞）
                self._logger.warning("心跳写失败（下轮重试）", exc_info=True)
        # 线程退出前关掉本线程连接（Windows 删临时库需要句柄全关）
        try:
            self._queue.close()
        except sqlite3.Error:
            self._logger.warning("心跳线程关连接失败", exc_info=True)

    # -- 假研究（M2 占位：不调 LLM，sleep 模拟六阶段会议）--

    def _db_write_with_retry(self, description: str, fn, *args,
                             attempts: int = 3, interval: float = 2.0):
        """进度/收尾写的锁超时降级（M2 审查 A2）：与 claim_next 同一重试语义。

        主后端超 15 秒的长写会让本侧 UPDATE 收 OperationalError（主仓冒烟
        Gate 用例2 的既有场景）；不重试 = 异常炸出主循环、整个 worker 崩溃
        退出、当前 run 残留 running 被下次启动扫尾误标 swept_on_restart。
        重试间隔短于轮询秒，耗尽后上抛由调用方标 pipeline_error。
        单条 UPDATE 失败不落事务（自动提交态），sleep 期间不持任何锁。
        """
        for attempt in range(1, attempts + 1):
            try:
                return fn(*args)
            except sqlite3.OperationalError:
                self._logger.warning(
                    "%s 撞写锁超时（第 %d/%d 次），%.1f 秒后重试",
                    description, attempt, attempts, interval, exc_info=True)
                if attempt == attempts:
                    raise
                time.sleep(interval)

    def _process_run(self, run: Dict) -> None:
        """领队后的研究本体：生成文本运行号 + 旁听文件桥，按 env 分流。"""
        run_id = run["id"]
        self._begin_run_tracking(run_id)
        run_id_text = _make_run_id(run["stock_code"])
        run_dir_path = self._live_root / run_id_text
        # 桥绝不抛出：目录建不了也只是每次写失败计数，研究照跑（库是事实源）
        bridge = _FileEventBridge(
            run_id_text, str(run_dir_path), run["stock_code"],
            run.get("stock_name") or "", self._logger)
        if self._use_real_llm():
            self._process_run_real(run, run_id_text, bridge)
        else:
            self._process_run_fake(run, run_id_text, bridge)

    def _use_real_llm(self) -> bool:
        """真跑分支裁决：构造参数显式指定 > env W2_REAL_LLM=1（默认假研究）。

        selftest 恒传 False——哪怕外层环境带着 W2_REAL_LLM=1 也不许真调 LLM。
        """
        if self._real_llm is not None:
            return self._real_llm
        return os.environ.get(REAL_LLM_ENV, "0").strip() == "1"

    # -- 假研究（M2 占位：不调 LLM，sleep 模拟六阶段会议；M4 加旁听文件）--

    def _process_run_fake(self, run: Dict, run_id_text: str,
                          bridge: "_FileEventBridge") -> None:
        run_id = run["id"]
        self._logger.info(
            "领到研究 run=%d %s %s（报告期 %s 第 %d 版），假研究开始（运行号 %s）",
            run_id, run["stock_code"], run.get("stock_name") or "",
            run["report_period"], run["version"], run_id_text)
        bridge.emit("started", None, {
            "stock_code": run["stock_code"],
            "stock_name": run.get("stock_name") or "",
        })
        for stage in range(1, TOTAL_STAGES + 1):
            if self._ownership_lost_flag():
                self._abandon_run(run_id, "心跳线程探测到所有权丢失",
                                  bridge=bridge)
                return
            bridge.emit("stage_start", stage, {"label": STAGE_NAMES[stage]})
            # 假研究阶段本体：sleep 期间绝不持有任何事务（连接在自动提交态）
            time.sleep(self._stage_seconds)
            for i, agent_name in enumerate(STAGE_AGENTS[stage]):
                speeches = FAKE_SPEECHES[agent_name]
                bridge.emit("agent_msg", stage,
                            {"text": speeches[min(i, len(speeches) - 1)]},
                            agent=agent_name)
            try:
                ok = self._db_write_with_retry(
                    "阶段写", self._queue.update_stage, run_id, stage)
            except sqlite3.OperationalError:
                self._abandon_run(run_id, "阶段写连续锁超时",
                                  reason="pipeline_error", bridge=bridge)
                return
            if not ok:
                self._abandon_run(run_id, "阶段写被终态守卫拒绝",
                                  bridge=bridge)
                return
            bridge.emit("stage_end", stage,
                        {"duration_ms": int(self._stage_seconds * 1000)})
            self._logger.info("run %d 阶段 %d/6 %s 完成",
                              run_id, stage, STAGE_NAMES[stage])
        # 六阶段跑完：先写旁听副本收尾（finalize + result.json），再摘牌
        # 写终态（防心跳误报），终态守卫兜底竞态
        started_at = run.get("started_at") or int(time.time())
        duration_s = max(time.time() - float(started_at), 0.0)
        finish_fields = {
            "verdict": FAKE_RESULT["verdict"],
            "score": FAKE_RESULT["score"],
            "act": FAKE_RESULT["act"],
            "summary": FAKE_RESULT["summary"],
            "confidence": FAKE_RESULT["confidence"],
            "run_id": run_id_text,
            "run_dir": run_id_text,
        }
        bridge.emit("finalize", None, {
            "verdict": finish_fields["verdict"],
            "score": finish_fields["score"],
            "act": finish_fields["act"],
            "summary": finish_fields["summary"],
        })
        bridge.finalize("done")
        bridge.write_result({
            "verdict": finish_fields["verdict"],
            "score": finish_fields["score"],
            "act": finish_fields["act"],
            "summary": finish_fields["summary"],
            "confidence": finish_fields["confidence"],
            "meta": {"duration_s": round(duration_s, 1), "fake": True},
        })
        self._clear_current_run()
        try:
            done = self._db_write_with_retry(
                "收尾写", self._queue.finish_run, run_id, finish_fields)
        except sqlite3.OperationalError:
            self._abandon_run(run_id, "收尾写连续锁超时",
                              reason="pipeline_error", bridge=bridge)
            return
        if done:
            self._logger.info(
                "run %d 假研究完成（运行号 %s，旁听文件写失败 %d 次）："
                "verdict=%s act=%s score=%s",
                run_id, run_id_text, bridge.write_failures,
                FAKE_RESULT["verdict"], FAKE_RESULT["act"],
                FAKE_RESULT["score"])
        else:
            self._logger.warning(
                "run %d 收尾写被终态守卫拒绝（所有权早已丢失），跳过", run_id)

    # -- 真跑分支（W2_REAL_LLM=1 才进；W2 默认不执行，M5 才翻开）--

    def _process_run_real(self, run: Dict, run_id_text: str,
                          bridge: "_FileEventBridge") -> None:
        """真跑：run_analysis(research_context=ai_runs.context_json 解析)。

        与假研究共用文本运行号与旁听文件桥；编排层事件经映射层翻成冻结
        信封五类。返回后做首句锚校验，不合规则确定性模板拼首句放报告顶。
        """
        db_run_id = run["id"]
        self._logger.info(
            "领到研究 run=%d %s %s（报告期 %s 第 %d 版），真跑模式开始"
            "（运行号 %s）",
            db_run_id, run["stock_code"], run.get("stock_name") or "",
            run["report_period"], run["version"], run_id_text)
        bridge.emit("started", None, {
            "stock_code": run["stock_code"],
            "stock_name": run.get("stock_name") or "",
        })
        try:
            research_context = json.loads(run.get("context_json") or "{}")
            if not isinstance(research_context, dict):
                research_context = {}
        except ValueError:
            self._logger.warning("context_json 解析失败，按空快照继续真跑",
                                 exc_info=True)
            research_context = {}

        def _on_event(etype, stage, data, agent=None):
            frozen_type = _REAL_EVENT_TYPE_MAP.get(etype)
            if frozen_type is None:
                return  # agent_heartbeat 等：旁听副本不落
            payload = dict(data or {})
            if frozen_type == "agent_msg":
                # 冻结信封：agent_msg 必有 data.text
                payload = {"text": (data or {}).get("content") or "",
                           "duration_ms": (data or {}).get("duration_ms")}
            elif frozen_type == "finalize":
                payload = self._real_finalize_payload(data or {})
            if frozen_type == "stage_start":
                self._sync_stage_to_db(db_run_id, stage)
            agent_cn = _REAL_AGENT_NAME_MAP.get(agent or "")
            bridge.emit(frozen_type, stage, payload, agent=agent_cn or agent)

        try:
            from src.agents.orchestrator import MultiAgentOrchestrator
            config = _load_model_config()
            orch = MultiAgentOrchestrator(config)
            result = orch.run_analysis(
                run["stock_code"],
                stock_name=run.get("stock_name") or "",
                research_context=research_context,
                on_event=_on_event,
            )
        except Exception:
            self._logger.exception("真跑分支异常，标记 failed(pipeline_error)")
            bridge.emit("finalize", None, {"error": "pipeline_error"})
            bridge.finalize("error")
            self._abandon_run(db_run_id, "真跑管线异常",
                              reason="pipeline_error", bridge=bridge)
            return

        finish_fields, report_text, first_sentence_ok = \
            self._real_finish_fields(result, research_context, run_id_text)
        # 降级守卫（M4 审查 MEDIUM，M5 翻真跑前修复）：run_analysis 永不抛、
        # 重度降级（LLM 全程故障/预算熔断）返回 success=False 的正常 dict——
        # 不拦会把空壳报告标 done（"已出报告"实为确定性兜底文本）。
        trader = ((result or {}).get("combined_report") or {}).get("trader") or {}
        if not result.get("success") or not trader.get("reasoning"):
            self._logger.warning(
                "run %d 真跑重度降级（success=%s, trader缺失=%s），标记 failed",
                db_run_id, result.get("success"), not trader.get("reasoning"))
            bridge.emit("finalize", None, {"error": "pipeline_error"})
            bridge.finalize("error")
            self._abandon_run(db_run_id, "研究管线重度降级，未产出有效报告",
                              reason="pipeline_error", bridge=bridge)
            return
        self._logger.info("run %d 真跑完成：首句锚校验 first_sentence_ok=%d",
                          db_run_id, first_sentence_ok)
        bridge.emit("finalize", None, {
            "verdict": finish_fields["verdict"],
            "score": finish_fields["score"],
            "act": finish_fields["act"],
            "summary": finish_fields["summary"],
        })
        bridge.finalize("done")
        bridge.write_result({
            "verdict": finish_fields["verdict"],
            "score": finish_fields["score"],
            "act": finish_fields["act"],
            "summary": finish_fields["summary"],
            "confidence": finish_fields["confidence"],
            "meta": {
                "duration_s": round(
                    ((result or {}).get("duration_ms") or 0) / 1000.0, 1),
                "fake": False,
            },
        })
        self._write_report_text(bridge.run_dir, report_text)
        self._clear_current_run()
        try:
            done = self._db_write_with_retry(
                "收尾写", self._queue.finish_run, db_run_id, finish_fields)
        except sqlite3.OperationalError:
            self._abandon_run(db_run_id, "收尾写连续锁超时",
                              reason="pipeline_error", bridge=bridge)
            return
        if done:
            self._logger.info(
                "run %d 真跑收尾完成（运行号 %s）：verdict=%s act=%s",
                db_run_id, run_id_text, finish_fields["verdict"],
                finish_fields["act"])
        else:
            self._logger.warning(
                "run %d 收尾写被终态守卫拒绝（所有权早已丢失），跳过",
                db_run_id)

    @staticmethod
    def _real_finalize_payload(data: Dict) -> Dict:
        """run_done 事件载荷瘦身（原样转发会带上全量归一结果，太大）。"""
        norm = data.get("result") or {}
        combined = norm.get("combined") or {}
        trader = norm.get("trader") or combined.get("trader") or {}
        return {
            "verdict": trader.get("action"),
            "score": combined.get("combined_score"),
            "act": trader.get("action"),
            "summary": str(trader.get("reasoning") or "")[:120],
        }

    @staticmethod
    def _real_finish_fields(result: Dict, ctx: Dict, run_id_text: str):
        """真跑结果 -> finish_run 字段 + 首句锚校验。

        首句不含 headline 关键短语（"比机构成本"/"持平"）时置
        first_sentence_ok=0，并以确定性模板从快照拼首句放报告顶
        （模板："【主结论】{headline}。以下为 AI 全文报告："）；合规则 =1。
        first_sentence_ok 不落库（合规率统计推狗粮期，计划减法清单#6），
        仅随日志透出；它在 fields 里会被 finish_run 白名单静默忽略。
        """
        combined = (result or {}).get("combined_report") or {}
        trader = combined.get("trader") or {}
        headline = (ctx or {}).get("headline") or ""
        report_text = str(
            trader.get("reasoning") or combined.get("rm_summary") or "").strip()
        first_sentence = _first_sentence_of(report_text)
        if ("比机构成本" in first_sentence) or ("持平" in first_sentence):
            first_sentence_ok = 1
            summary = first_sentence
        else:
            first_sentence_ok = 0
            if headline:
                report_text = "【主结论】%s。以下为 AI 全文报告：%s" % (
                    headline, report_text)
                summary = _first_sentence_of(report_text)
            else:
                # 快照没有 headline（cost_missing）：无从兜底，如实用原首句
                summary = first_sentence
        # act 词表映射（M4 审查 MEDIUM，契约第三节钉死枚举 bull/watch/bear）：
        # 交易员 action 是 buy/sell/watch，前端行徽记只认 bull/watch/bear
        action = trader.get("action") or "watch"
        act = {"buy": "bull", "sell": "bear"}.get(action, "watch")
        # score 脏值防御：combined_score 非数值（重度降级缺失）时落 None
        raw_score = combined.get("combined_score")
        score = ("综合%s分" % raw_score
                 if isinstance(raw_score, (int, float)) else None)
        fields = {
            "verdict": {"buy": "谨慎买入", "sell": "看空"}.get(action, "观望"),
            "score": score,
            "act": act,
            "summary": summary,
            "confidence": None,
            "run_id": run_id_text,
            "run_dir": run_id_text,
            "first_sentence_ok": first_sentence_ok,
        }
        conf = trader.get("confidence_total")
        if isinstance(conf, (int, float)):
            fields["confidence"] = round(float(conf) / 100.0, 2)
        return fields, report_text, first_sentence_ok

    def _sync_stage_to_db(self, db_run_id: int, stage) -> None:
        """真跑分支：stage_start 事件同步推进 ai_runs.stage（尽力而为）。"""
        if stage is None:
            return
        try:
            ok = self._db_write_with_retry(
                "阶段写", self._queue.update_stage, db_run_id, int(stage))
        except sqlite3.OperationalError:
            self._logger.warning("真跑阶段写连续锁超时（继续研究，仅记日志）",
                                 exc_info=True)
            return
        if not ok:
            self._logger.warning(
                "真跑阶段写被终态守卫拒绝（行已不在 running，仅记日志）")

    def _write_report_text(self, run_dir: str, report_text: str) -> None:
        """报告全文留档（AI 仓内部文件，非跨仓契约件；M5 决定去留）。"""
        if not report_text:
            return
        try:
            with open(os.path.join(run_dir, "report.txt"), "w",
                      encoding="utf-8") as f:
                f.write(report_text)
        except Exception:
            self._logger.warning("报告全文留档失败（不影响收尾）",
                                 exc_info=True)

    def _abandon_run(self, run_id: int, cause: str,
                     reason: str = "ownership_lost",
                     bridge: Optional["_FileEventBridge"] = None) -> None:
        """放弃当前 run：行若还在 running 则标 failed(reason)。

        reason 走契约 fail_reason 词表（swept_on_restart / heartbeat_timeout /
        pipeline_error / budget_exhausted / ownership_lost——最后一个是
        worker 自探测所有权丢失主动放弃，2026-10-11 已回写契约词表）。
        旁听副本（若有）如实置 error；不写 result.json（失败行没有研究结论）。
        """
        self._clear_current_run()
        if bridge is not None:
            bridge.emit("finalize", None, {"error": reason})
            bridge.finalize("error")
        if self._queue.fail_run(run_id, reason):
            self._logger.warning("run %d 已放弃（%s），标记 failed(%s)",
                                 run_id, cause, reason)
        else:
            self._logger.warning(
                "run %d 已放弃（%s）；行已不在 running，无需收尾", run_id, cause)

    # -- 主入口 --

    def run(self, stop_after_queue_empty: bool = False) -> None:
        """常驻主循环。stop_after_queue_empty=True：队列清空即退出（selftest 用）。"""
        q = self._queue
        swept = q.startup_sweep()
        if swept:
            self._logger.info(
                "启动扫尾：收尸 %d 个残留 running 行（fail_reason=swept_on_restart）",
                swept)
        q.register_worker(q.db_signature())
        self._logger.info("worker 已注册 pid=%d db=%s db_signature=%s 阶段秒=%.1f",
                          os.getpid(), q.db_path, q.db_signature(),
                          self._stage_seconds)
        hb = threading.Thread(target=self._heartbeat_loop, name="heartbeat",
                              daemon=True)
        hb.start()
        try:
            while True:
                # stop_flag 只在两个 run 之间检查（船长拍板：当前 run 必须跑完）
                if q.stop_requested():
                    self._logger.info(
                        "收到停止请求（stop_flag=1）：当前无进行中的研究，"
                        "正常退出（排队保留）")
                    break
                try:
                    run = q.claim_next()
                except sqlite3.OperationalError:
                    # 领队撞写锁超时（主后端长写）：记录后按轮询间隔重试
                    self._logger.warning(
                        "领队失败（写锁繁忙超时），%.1f 秒后重试",
                        self._poll_seconds, exc_info=True)
                    time.sleep(self._poll_seconds)
                    continue
                if run is None:
                    if stop_after_queue_empty:
                        break
                    time.sleep(self._poll_seconds)
                    continue
                self._process_run(run)
        finally:
            self._hb_stop.set()
            hb.join(timeout=5)
            try:
                ok = q.checkpoint_truncate()
                self._logger.info("收尾 wal_checkpoint(TRUNCATE)：%s",
                                  "完成" if ok else "繁忙放弃（best-effort）")
            except sqlite3.Error:
                self._logger.warning("收尾 checkpoint 失败（不影响数据安全）",
                                     exc_info=True)
            q.close()


# ---------------------------------------------------------------------------
# --selftest：临时库上的全自动自测（测试脚手架，生产禁用）
# ---------------------------------------------------------------------------

# 测试脚手架，生产禁用：以下 DDL 逐字抄自契约冻结文档第二节（权属主后端
# create_tables）。仅 --selftest 在自己的临时库铺表用；生产代码永不建表。
_SELFTEST_DDL = """
CREATE TABLE IF NOT EXISTS ai_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code     TEXT NOT NULL,
    stock_name     TEXT,
    report_period  TEXT NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    state          TEXT NOT NULL DEFAULT 'queued'
                   CHECK (state IN ('queued','running','done','failed','cancelled')),
    stage          INTEGER CHECK (stage BETWEEN 1 AND 6),
    enqueued_at    INTEGER NOT NULL,
    started_at     INTEGER,
    heartbeat_at   INTEGER,
    finished_at    INTEGER,
    duration_s     REAL,
    fail_reason    TEXT,
    verdict        TEXT,
    score          TEXT,
    act            TEXT,
    summary        TEXT,
    confidence     REAL,
    context_json   TEXT NOT NULL DEFAULT '{}',
    run_id         TEXT,
    run_dir        TEXT,
    worker_pid     INTEGER,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_runs_spv ON ai_runs(stock_code, report_period, version);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_runs_active_stock
    ON ai_runs(stock_code) WHERE state IN ('queued','running');
CREATE INDEX IF NOT EXISTS ix_ai_runs_state_enqueued ON ai_runs(state, enqueued_at);
CREATE INDEX IF NOT EXISTS ix_ai_runs_stock_ver ON ai_runs(stock_code, version DESC);
CREATE INDEX IF NOT EXISTS ix_ai_runs_done_fin ON ai_runs(state, finished_at);
CREATE TABLE IF NOT EXISTS ai_worker (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    pid           INTEGER,
    started_at    INTEGER,
    heartbeat_at  INTEGER,
    db_signature  TEXT,
    stop_flag     INTEGER NOT NULL DEFAULT 0
);
"""


def _resolve_selftest_db(db_arg: Optional[str]) -> Tuple[str, Optional[str]]:
    """定位 selftest 库：显式参数 > AI_INVEST_DB env > 自动 tempfile。

    返回 (绝对路径, 自建临时目录或 None)。自建临时目录由本函数调用方负责销毁。
    """
    if db_arg:
        return str(Path(db_arg).resolve()), None
    env = os.environ.get("AI_INVEST_DB")
    if env:
        return str(Path(env).resolve()), None
    tmpdir = tempfile.mkdtemp(prefix="w2_selftest_")
    return os.path.join(tmpdir, "selftest.db"), tmpdir


def _selftest_db_allowed(db_path: str) -> bool:
    """selftest 只允许临时库：系统临时目录或本仓 output/ 之下。

    护栏目的：哪怕 AI_INVEST_DB 指向真身库（5.9GB），selftest 也绝不
    往里插假数据。非临时路径直接拒跑。
    """
    def _norm(p) -> str:
        return str(Path(p).resolve()).lower().rstrip("\\/")

    path = _norm(db_path)
    allowed_roots = [_norm(tempfile.gettempdir()), _norm(REPO_ROOT / "output")]
    return any(path.startswith(root + os.sep) for root in allowed_roots)


def _selftest_seed(db_path: str) -> str:
    """铺表（脚手架 DDL）+ 入队一行假研究，返回入队后的 state（应为 queued）。"""
    Path(db_path).touch()  # connect 要求库文件已存在（worker 生产路径不建库）
    conn = connect(db_path)
    try:
        conn.executescript(_SELFTEST_DDL)
        now = int(time.time())
        conn.execute(
            "INSERT INTO ai_runs (stock_code, stock_name, report_period,"
            " version, state, enqueued_at, context_json, created_at, updated_at)"
            " VALUES ('000001.SZ', '平安银行', '2026-06-30', 1, 'queued',"
            " '{}', ?, ?, ?)",
            (now, now, now))
        row = conn.execute(
            "SELECT state FROM ai_runs ORDER BY id DESC LIMIT 1").fetchone()
        return row["state"]
    finally:
        conn.close()


def _selftest_assertions(logger: logging.Logger, db_path: str,
                         pre_state: Optional[str],
                         samples: List[Tuple],
                         live_root: Path) -> int:
    """逐项断言（任一失败返回 1，全过返回 0）。断言清单=任务书自测要求。"""
    failures: List[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        logger.info("[selftest] %s %s %s", "PASS" if ok else "FAIL", name, detail)
        if not ok:
            failures.append(name)

    q = DbQueue(db_path)
    try:
        row = q.fetch_one("SELECT * FROM ai_runs ORDER BY id DESC LIMIT 1")
        assert row is not None, "ai_runs 竟然没有行"
        check("入队起点为 queued", pre_state == "queued",
              "pre_state=%s" % pre_state)
        check("运行中出现 running 态",
              any(s[0] == "running" for s in samples),
              "采样数=%d" % len(samples))
        check("终态为 done", row["state"] == "done", "state=%s" % row["state"])
        check("stage 推进到 6", row["stage"] == 6, "stage=%s" % row["stage"])
        beats = {s[2] for s in samples if s[2] is not None}
        check("heartbeat_at 多次更新", len(beats) >= 2,
              "distinct=%d" % len(beats))
        check("finished_at 非空", row["finished_at"] is not None,
              "finished_at=%s" % row["finished_at"])
        check("duration_s 非空且大于0",
              row["duration_s"] is not None and row["duration_s"] > 0,
              "duration_s=%s" % row["duration_s"])
        check("假结论字段落库",
              row["verdict"] == "观望" and row["act"] == "watch"
              and row["score"] == "看多·置信度70%"
              and "便宜12.3%" in (row["summary"] or "")
              and abs((row["confidence"] or 0) - 0.70) < 1e-9)
        check("claim 写入 worker_pid", row["worker_pid"] == os.getpid(),
              "worker_pid=%s" % row["worker_pid"])
        rid = row["id"]
        check("迟到 stage 写被守卫拒绝", q.update_stage(rid, 6) is False)
        check("迟到心跳写被守卫拒绝", q.beat_run(rid) is False)
        check("迟到收尾写被守卫拒绝", q.finish_run(rid, FAKE_RESULT) is False)
        check("wal_checkpoint(TRUNCATE) 成功", q.checkpoint_truncate() is True)

        # ---- M4 旁听文件桥断言（任务书自测要求新增）----
        run_id_text = row["run_id"]
        run_dir_name = row["run_dir"]
        check("ai_runs 已落库文件运行号 run_id",
              bool(run_id_text) and str(run_id_text).startswith("r_"),
              "run_id=%s" % run_id_text)
        check("ai_runs 已落库 run_dir 且与 run_id 一致",
              run_dir_name == run_id_text, "run_dir=%s" % run_dir_name)
        run_dir_path = Path(live_root) / str(run_dir_name or "")
        check("run 目录存在", run_dir_path.is_dir(), str(run_dir_path))
        jsonl_lines = 0
        snapshot = None
        result_json = None
        if run_dir_path.is_dir():
            jsonl_path = run_dir_path / "progress.jsonl"
            if jsonl_path.exists():
                with open(jsonl_path, encoding="utf-8") as f:
                    jsonl_lines = sum(1 for line in f if line.strip())
            snap_path = run_dir_path / "progress.json"
            if snap_path.exists():
                with open(snap_path, encoding="utf-8") as f:
                    snapshot = json.load(f)
            rj_path = run_dir_path / "result.json"
            if rj_path.exists():
                with open(rj_path, encoding="utf-8") as f:
                    result_json = json.load(f)
        events = (snapshot or {}).get("events") or []
        check("progress.jsonl 行数与事件数一致",
              snapshot is not None and jsonl_lines == len(events),
              "jsonl=%d events=%d" % (jsonl_lines, len(events)))
        check("progress.json 的 events 数与 last_seq 一致",
              snapshot is not None
              and snapshot.get("last_seq") == len(events),
              "last_seq=%s" % ((snapshot or {}).get("last_seq"),))
        check("事件 seq 连续无洞",
              [e.get("seq") for e in events] == list(range(1, len(events) + 1)),
              "events=%d" % len(events))
        check("事件类型全在冻结词表",
              all(e.get("type") in FROZEN_EVENT_TYPES for e in events))
        check("agent_msg 必有 data.text",
              all(isinstance(e.get("data"), dict) and "text" in e["data"]
                  for e in events if e.get("type") == "agent_msg"))
        check("agent 名全在冻结词表",
              all(e.get("agent") in FAKE_SPEECHES
                  for e in events if e.get("type") == "agent_msg"))
        check("快照 status 收尾为 done",
              (snapshot or {}).get("status") == "done",
              "status=%s" % ((snapshot or {}).get("status"),))
        check("result.json 存在且形状冻结",
              result_json is not None
              and set(result_json.keys()) == {
                  "verdict", "score", "act", "summary", "confidence", "meta"}
              and isinstance(result_json.get("meta"), dict)
              and result_json["meta"].get("fake") is True
              and (result_json["meta"].get("duration_s") or 0) > 0)
    finally:
        q.close()
    if failures:
        logger.error("[selftest] 失败项：%s", ", ".join(failures))
        return EXIT_FAIL
    return EXIT_OK


def run_selftest(logger: logging.Logger, db_arg: Optional[str]) -> int:
    """自测主流程：临时库铺表 -> 入队 -> 完整假研究 -> 断言 -> 清理。

    心跳周期缩短到 1 秒仅为采样密度（生产仍是契约的 15 秒）。
    锁先于一切数据库动作获取：保证双开测试中第二个进程在写库前就礼让退出。
    run 目录跟着库所在临时目录走（显式库路径时放库旁兄弟目录，
    结束后删除）——绝不写真 AI 仓的 output/live。
    """
    db_path, own_dir = _resolve_selftest_db(db_arg)
    live_own_dir = None
    try:
        if not _selftest_db_allowed(db_path):
            logger.error("[selftest] 拒绝非临时库路径（真身库绝不允许触碰）：%s",
                         db_path)
            return EXIT_CONFIG
        if own_dir:
            live_root = Path(own_dir) / "live"
        else:
            live_own_dir = Path(db_path).resolve().parent / "w2_selftest_live"
            live_root = live_own_dir
        lock_handle = acquire_instance_lock(str(LOCK_FILE))
        try:
            pre_state = _selftest_seed(db_path)
            samples: List[Tuple] = []
            stop_sampling = threading.Event()

            def _sample() -> None:
                c = connect(db_path)
                try:
                    while not stop_sampling.wait(0.3):
                        r = c.execute(
                            "SELECT state, stage, heartbeat_at FROM ai_runs"
                            " ORDER BY id DESC LIMIT 1").fetchone()
                        if r is not None:
                            samples.append((r["state"], r["stage"],
                                            r["heartbeat_at"]))
                finally:
                    c.close()

            sampler = threading.Thread(target=_sample, name="selftest-sampler",
                                       daemon=True)
            sampler.start()
            code = EXIT_OK
            try:
                worker = QueueWorker(db_path=db_path, heartbeat_interval=1.0,
                                     poll_seconds=0.2, live_root=live_root,
                                     real_llm=False)  # selftest 恒走假研究
                worker.run(stop_after_queue_empty=True)
            except Exception:
                logger.exception("[selftest] 假研究执行异常")
                code = EXIT_FAIL
            finally:
                stop_sampling.set()
                sampler.join(timeout=3)
            if code == EXIT_OK:
                code = _selftest_assertions(logger, db_path, pre_state, samples,
                                            live_root)
        finally:
            release_instance_lock(lock_handle)
        print("SELFTEST %s" % ("PASS" if code == EXIT_OK else "FAIL"), flush=True)
        return code
    finally:
        if own_dir:
            shutil.rmtree(own_dir, ignore_errors=True)  # 产物自清理（23G 教训）
        if live_own_dir:
            shutil.rmtree(live_own_dir, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="W2 M2 队列工人进程（常驻、零 HTTP、假研究不调 LLM）")
    parser.add_argument(
        "--selftest", nargs="?", const=True, default=False, metavar="临时库",
        help="自测模式：不接真库不调 LLM，在临时库跑完整假研究并断言；"
             "可选参数=临时库路径（默认自动创建销毁）")
    args = parser.parse_args(argv)
    logger = setup_logging()
    try:
        if args.selftest is not False:
            return run_selftest(
                logger, args.selftest if isinstance(args.selftest, str) else None)
        # 生产模式：锁 -> worker -> 常驻循环
        lock_handle = acquire_instance_lock(str(LOCK_FILE))
        try:
            worker = QueueWorker()
            worker.run()
            return EXIT_OK
        finally:
            release_instance_lock(lock_handle)
    except RuntimeError as exc:
        # 配置类错误：env 未配置 / OneDrive 护栏 / 库文件不存在
        logger.error("配置错误，退出码 %d：%s", EXIT_CONFIG, exc)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        logger.info("收到手动中断：进行中的 run 将由下次启动扫尾收尸"
                    "（fail_reason=swept_on_restart）")
        return EXIT_OK
    except Exception:
        logger.exception("未预期异常，退出码 %d", EXIT_FAIL)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
