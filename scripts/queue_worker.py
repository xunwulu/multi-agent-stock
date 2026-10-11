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

# M2 假研究结论（占位数字，不调 LLM；W3/M5 换真研究管线时整体替换）
FAKE_RESULT = {
    "verdict": "观望",
    "score": "看多·置信度70%",
    "act": "watch",
    "summary": "比机构成本 便宜12.3%（M2 假研究占位）",
    "confidence": 0.70,
    # AI 侧文件运行号 run_id 文本列：M2 假研究不产生文件，留空（None = 不写）
    "run_id": None,
}


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
                 heartbeat_interval: float = HEARTBEAT_INTERVAL):
        self._queue = DbQueue(db_path)
        self._stage_seconds = (stage_seconds if stage_seconds is not None
                               else _env_float("W2_FAKE_STAGE_SECONDS", 2.0))
        self._poll_seconds = (poll_seconds if poll_seconds is not None
                              else _env_float("AI_WORKER_POLL_SECONDS", 5.0))
        self._heartbeat_interval = heartbeat_interval
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
        run_id = run["id"]
        self._begin_run_tracking(run_id)
        self._logger.info(
            "领到研究 run=%d %s %s（报告期 %s 第 %d 版），假研究开始",
            run_id, run["stock_code"], run.get("stock_name") or "",
            run["report_period"], run["version"])
        for stage in range(1, TOTAL_STAGES + 1):
            if self._ownership_lost_flag():
                self._abandon_run(run_id, "心跳线程探测到所有权丢失")
                return
            # 假研究阶段本体：sleep 期间绝不持有任何事务（连接在自动提交态）
            time.sleep(self._stage_seconds)
            try:
                ok = self._db_write_with_retry(
                    "阶段写", self._queue.update_stage, run_id, stage)
            except sqlite3.OperationalError:
                self._abandon_run(run_id, "阶段写连续锁超时",
                                  reason="pipeline_error")
                return
            if not ok:
                self._abandon_run(run_id, "阶段写被终态守卫拒绝")
                return
            self._logger.info("run %d 阶段 %d/6 %s 完成",
                              run_id, stage, STAGE_NAMES[stage])
        # 六阶段跑完：先摘牌再写终态（防心跳误报），终态守卫兜底竞态
        self._clear_current_run()
        try:
            done = self._db_write_with_retry(
                "收尾写", self._queue.finish_run, run_id, FAKE_RESULT)
        except sqlite3.OperationalError:
            self._abandon_run(run_id, "收尾写连续锁超时",
                              reason="pipeline_error")
            return
        if done:
            self._logger.info(
                "run %d 假研究完成：verdict=%s act=%s score=%s",
                run_id, FAKE_RESULT["verdict"], FAKE_RESULT["act"],
                FAKE_RESULT["score"])
        else:
            self._logger.warning(
                "run %d 收尾写被终态守卫拒绝（所有权早已丢失），跳过", run_id)

    def _abandon_run(self, run_id: int, cause: str,
                     reason: str = "ownership_lost") -> None:
        """放弃当前 run：行若还在 running 则标 failed(reason)。

        reason 走契约 fail_reason 词表（swept_on_restart / heartbeat_timeout /
        pipeline_error / budget_exhausted / ownership_lost——最后一个是
        worker 自探测所有权丢失主动放弃，2026-10-11 已回写契约词表）。
        """
        self._clear_current_run()
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
                         samples: List[Tuple]) -> int:
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
    """
    db_path, own_dir = _resolve_selftest_db(db_arg)
    try:
        if not _selftest_db_allowed(db_path):
            logger.error("[selftest] 拒绝非临时库路径（真身库绝不允许触碰）：%s",
                         db_path)
            return EXIT_CONFIG
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
                                     poll_seconds=0.2)
                worker.run(stop_after_queue_empty=True)
            except Exception:
                logger.exception("[selftest] 假研究执行异常")
                code = EXIT_FAIL
            finally:
                stop_sampling.set()
                sampler.join(timeout=3)
            if code == EXIT_OK:
                code = _selftest_assertions(logger, db_path, pre_state, samples)
        finally:
            release_instance_lock(lock_handle)
        print("SELFTEST %s" % ("PASS" if code == EXIT_OK else "FAIL"), flush=True)
        return code
    finally:
        if own_dir:
            shutil.rmtree(own_dir, ignore_errors=True)  # 产物自清理（23G 教训）


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
