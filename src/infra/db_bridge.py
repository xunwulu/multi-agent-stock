# -*- coding: utf-8 -*-
"""db_bridge - W2 M2 跨进程数据库桥（multi-agent-stock 侧）。

AI worker 进程访问主仓 ai_investment.db 的唯一通道。契约基准：
  - 契约冻结文档：ai-investment-tool/docs/development/2026-10-10-w2-research-contract.md
  - 连接契约 9+1 条：ai-investment-tool/docs/development/2026-10-05-db-connection-standards.md
  - 锁语义照抄：ai-investment-tool/backend/scripts/w2_mock_ai_worker.py 的 mode_lockchild

要点（违反即事故）：
  1. 一线程一连接：DbQueue 内部 thread-local 建连接，绝不用
     check_same_thread=False 共享一条连接（10-05 事故形态）
  2. 读改写（领队）一律显式 BEGIN IMMEDIATE；单条写走自动提交
  3. 事务绝不跨 sleep / 网络 / LLM 调用；读 fetchall/fetchone 即取即弃
  4. 一切进度写带终态守卫 AND state=...：迟到写 rowcount=0 静默放弃返回 False
  5. DDL 权属主后端：本模块永不建表（--selftest 的铺表脚手架在
     scripts/queue_worker.py 里，仅限临时库）
"""

import logging
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("db_bridge")

# 环境变量名（契约第五节常量表）：worker 连哪个库由主后端 supervisor 注入
DB_ENV_VAR = "AI_INVEST_DB"


def resolve_db_path(db_path: Optional[str] = None) -> str:
    """解析库路径：显式参数 > 环境变量 AI_INVEST_DB；两者皆空大声报错。

    worker 没有"默认库"概念——默认路径正是主仓三个分裂库的老病根，
    所以未配置直接抛 RuntimeError（配置错误，退出码 2）。
    """
    if db_path is None:
        db_path = os.environ.get(DB_ENV_VAR, "")
        if not db_path:
            raise RuntimeError(
                "%s 未配置：worker 不知道该连哪个库"
                "（由主后端 supervisor 启动时注入绝对路径）" % DB_ENV_VAR)
    return str(Path(db_path).resolve())


def _guard_not_on_onedrive(path: str) -> None:
    """连接契约第 10 条：库目录落在 OneDrive 同步目录下即拒启（中文红牌）。

    SQLite(WAL) 在网盘同步目录上属官方明确不支持的损坏场景。
    """
    if "onedrive" in str(path).lower():
        raise RuntimeError(
            "库目录位于 OneDrive 同步目录内，拒绝启动"
            "（SQLite WAL 在同步目录上属官方不支持的损坏场景）：%s" % path)


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """契约同款连接（与主后端 / 冒烟 Gate mock worker 完全一致）。

    - timeout=15.0 + busy_timeout=15000：跨进程写竞争透明等待
    - isolation_level=None：显式事务模式（读改写手写 BEGIN IMMEDIATE）
    - WAL / synchronous=NORMAL：与主后端一致
    - 库文件必须已存在：建库建表权属主后端，worker 不创建库
      （防 worker 在错误 cwd 静默造出分裂空库）
    """
    path = resolve_db_path(db_path)
    _guard_not_on_onedrive(path)
    if not os.path.isfile(path):
        raise RuntimeError(
            "库文件不存在：%s（建库建表权属主后端，worker 不创建库）" % path)
    conn = sqlite3.connect(path, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ---- 单实例锁（照抄 w2_mock_ai_worker.mode_lockchild 的锁语义）----


def acquire_instance_lock(lockfile: str):
    """msvcrt 单实例锁：锁 1 字节非阻塞；被占则礼让退出（退出码 42）。

    - 进程死亡 OS 自动释放（不需要僵尸锁清理逻辑）
    - 返回文件句柄，调用方持有到进程退出（句柄一关锁即释放）
    - 锁文件内容写入 pid，纯诊断用途（锁语义不依赖文件内容）
    """
    try:
        import msvcrt
    except ImportError as e:  # 非 Windows 平台：明确报错而不是裸崩
        raise RuntimeError("单实例锁依赖 msvcrt，仅支持 Windows 平台") from e

    path = Path(lockfile)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        # 锁被占 = 已有 worker 实例活着：礼让退出（supervisor 见 42 不计故障）
        logger.info("单实例锁已被占用（已有 worker 存活），本进程礼让退出：%s", path)
        try:
            handle.close()
        except OSError:
            pass
        print("POLITE_EXIT", flush=True)
        sys.exit(42)
    # 锁定成功：写入 pid 便于人工诊断（失败不影响锁语义）
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
    except OSError:
        logger.warning("锁文件写入 pid 失败（不影响锁语义）", exc_info=True)
    logger.info("已获取单实例锁：path=%s pid=%d", path, os.getpid())
    return handle


def release_instance_lock(handle) -> None:
    """释放单实例锁并关闭句柄（进程退出路径收尾用）。"""
    if handle is None:
        return
    try:
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except (OSError, ImportError):
        # 解锁失败不致命：进程退出后 OS 强制释放该锁
        logger.warning("释放单实例锁失败（进程退出后 OS 会强制释放）", exc_info=True)
    finally:
        try:
            handle.close()
        except OSError:
            pass


# ---- 队列操作层（六态状态机的 worker 侧全部写路径）----


class DbQueue:
    """ai_runs / ai_worker 两表的 worker 侧操作集。

    连接策略：thread-local 每线程一连接（懒建）——心跳线程与主循环线程
    各自持连接，满足连接契约第 4 条；单条写自动提交，读改写显式
    BEGIN IMMEDIATE，全部短事务。
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = resolve_db_path(db_path)
        self._local = threading.local()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        """取本线程连接（懒建；禁止跨线程传递——契约第一条）。"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self._db_path)
            self._local.conn = conn
        return conn

    def close(self) -> None:
        """关闭调用方线程自己的连接（线程退出前的礼貌收尾）。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                self._local.conn = None

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """单行读助手：fetchone 即取即弃（契约第 7 条）。"""
        row = self._conn().execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    # -- E2 领队：BEGIN IMMEDIATE 内 SELECT 最老 queued + UPDATE 置 running --

    def claim_next(self) -> Optional[Dict]:
        """抢最老的一条 queued 转 running。

        契约 6.2：claim 的 UPDATE 必须同时写 heartbeat_at（防"领队后首心跳
        未写、worker 又死亡"的永生行）。rowcount=1 才算领到，返回行 dict；
        无任务或被抢走返回 None。
        """
        conn = self._conn()
        now = int(time.time())
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM ai_runs WHERE state='queued'"
                " ORDER BY enqueued_at, id LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            cur = conn.execute(
                "UPDATE ai_runs SET state='running', stage=1, started_at=?,"
                " heartbeat_at=?, worker_pid=?, updated_at=?"
                " WHERE id=? AND state='queued'",
                (now, now, os.getpid(), now, row["id"]),
            )
            if cur.rowcount != 1:
                # 并发对手先领走：守卫生效，本方放弃
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        claimed = dict(row)
        claimed.update({
            "state": "running", "stage": 1, "started_at": now,
            "heartbeat_at": now, "worker_pid": os.getpid(),
            "updated_at": now,
        })
        return claimed

    # -- E3 阶段推进 / 心跳（守卫 state='running'）--

    def update_stage(self, run_id: int, stage: int) -> bool:
        """推进阶段：UPDATE stage + heartbeat_at；迟到写返回 False。"""
        now = int(time.time())
        cur = self._conn().execute(
            "UPDATE ai_runs SET stage=?, heartbeat_at=?, updated_at=?"
            " WHERE id=? AND state='running'",
            (stage, now, now, run_id),
        )
        return cur.rowcount == 1

    def beat_run(self, run_id: int) -> bool:
        """run 级心跳；rowcount=0 = 所有权已丢（判死/收尾过）。"""
        now = int(time.time())
        cur = self._conn().execute(
            "UPDATE ai_runs SET heartbeat_at=? WHERE id=? AND state='running'",
            (now, run_id),
        )
        return cur.rowcount == 1

    def set_run_identity(self, run_id: int, run_id_text: str) -> bool:
        """领取后立即落 run_id/run_dir 文本列（守卫 state='running'）。

        主后端直播端点靠行上的 run_dir 定位转录目录；此前只在 finish_run
        收尾写，running 期间行上目录为空 -> 旁听全程"还没开始"（2026-10-25
        果麦文化旁听定格事故根因）。迟到写（已终态）rowcount=0 返回 False。
        """
        now = int(time.time())
        cur = self._conn().execute(
            "UPDATE ai_runs SET run_id=?, run_dir=?, updated_at=?"
            " WHERE id=? AND state='running'",
            (run_id_text, run_id_text, now, run_id),
        )
        return cur.rowcount == 1

    def beat_worker(self) -> None:
        """worker 级心跳：空转也跳（健康灯与判死第二因子），同时刷新 pid。"""
        now = int(time.time())
        self._conn().execute(
            "INSERT INTO ai_worker (id, pid, started_at, heartbeat_at)"
            " VALUES (1, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET heartbeat_at=excluded.heartbeat_at,"
            " pid=excluded.pid",
            (os.getpid(), now, now),
        )

    def register_worker(self, db_signature: str) -> None:
        """写 ai_worker 单行（id=1）：pid / started_at / heartbeat / 库签名。

        同时把 stop_flag 复位为 0——上一代 worker 收到停止请求退出后，
        新一代 worker 注册即应开始工作，不继承旧停止位。
        """
        now = int(time.time())
        self._conn().execute(
            "INSERT INTO ai_worker (id, pid, started_at, heartbeat_at,"
            " db_signature) VALUES (1, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET pid=excluded.pid,"
            " started_at=excluded.started_at, heartbeat_at=excluded.heartbeat_at,"
            " db_signature=excluded.db_signature, stop_flag=0",
            (os.getpid(), now, now, db_signature),
        )

    def stop_requested(self) -> bool:
        """读关停请求（ai_worker.stop_flag，id=1）。"""
        row = self._conn().execute(
            "SELECT stop_flag FROM ai_worker WHERE id=1").fetchone()
        return bool(row is not None and row["stop_flag"])

    # -- E4/E5 终态收尾（守卫 state='running'）--

    # finish_run 允许写入的列白名单（防 SQL 注入：列名固定，只有值动态）。
    # run_id/run_dir = AI 侧文件运行号与 output/live 下目录名（M4 起假研究
    # 也产出旁听文件，两列恒成对写入；fields 传 None 即不写该列）
    _FINISH_FIELDS = ("verdict", "score", "act", "summary", "confidence",
                      "run_id", "run_dir")

    def finish_run(self, run_id: int, fields: Optional[Dict] = None) -> bool:
        """收尾置 done：finished_at / duration_s（按 started_at 现算）+ 结论列。

        duration_s 在同一条 UPDATE 里用表达式 now - started_at 计算
        （SQLite 的 SET 右侧可引用本行旧值），保持单语句短事务。
        AI 侧文件运行号 run_id / output/live 目录名 run_dir：fields 里
        传 None 即不写该列（白名单之外的键静默忽略）。
        """
        now = int(time.time())
        fields = fields or {}
        sets = [
            "state='done'",
            "finished_at=?",
            "duration_s=? - COALESCE(started_at, ?)",
            "heartbeat_at=?",
            "updated_at=?",
        ]
        params = [now, float(now), now, now, now]
        for name in self._FINISH_FIELDS:
            if fields.get(name) is not None:
                sets.append("%s=?" % name)
                params.append(fields[name])
        params.append(run_id)
        cur = self._conn().execute(
            "UPDATE ai_runs SET %s WHERE id=? AND state='running'"
            % ", ".join(sets),
            params,
        )
        return cur.rowcount == 1

    def fail_run(self, run_id: int, reason: str) -> bool:
        """收尾置 failed（守卫 state='running'）；行已不在 running 返回 False。"""
        now = int(time.time())
        cur = self._conn().execute(
            "UPDATE ai_runs SET state='failed', fail_reason=?, finished_at=?,"
            " heartbeat_at=?, updated_at=? WHERE id=? AND state='running'",
            (reason, now, now, now, run_id),
        )
        return cur.rowcount == 1

    # -- 月度用量账本（W2+ 真研究模式产品化 P1，2026-10-27）--
    # 表 ai_usage 由主后端建表（权属契约），worker 只写；SQL 与主仓
    # ai_runs_service.record_usage 逐字一致（契约冻结：两仓不得偏离）。

    def record_usage(self, tokens: int = 0) -> None:
        """真研究完成时记账：当月行 +1 只 / +token 合计（upsert）。

        只在真跑收尾成功后调用（假研究/自测绝不记账）；token 拿不到
        传 0，绝不编数。
        """
        now = int(time.time())
        ym = time.strftime("%Y-%m", time.localtime(now))
        self._conn().execute(
            "INSERT INTO ai_usage (ym, real_runs, tokens, updated_at)"
            " VALUES (?, 1, ?, ?)"
            " ON CONFLICT(ym) DO UPDATE SET"
            " real_runs = real_runs + 1, tokens = tokens + excluded.tokens,"
            " updated_at = excluded.updated_at",
            (ym, max(int(tokens), 0), now),
        )

    def startup_sweep(self) -> int:
        """启动扫尾：无条件把全部 running 收尸为 failed(swept_on_restart)。

        单实例锁保证此刻不可能有活 run 在别的进程里跑——谁启动谁全权收尸
        （带 90 秒条件的扫尾与 5 秒快速重启构成漏扫竞态，会让僵尸 running
        永久占用在途上限，契约第六节#4 明确裁定无条件）。
        """
        now = int(time.time())
        cur = self._conn().execute(
            "UPDATE ai_runs SET state='failed', fail_reason='swept_on_restart',"
            " finished_at=?, updated_at=? WHERE state='running'",
            (now, now),
        )
        return cur.rowcount

    # -- 诊断与收尾 --

    def db_signature(self) -> str:
        """库文件签名（mtime+size 拼串）：supervisor 同库校验用。

        防"双 cwd 静默分库"——主后端把自己算的签名与 worker 回报的对不上
        即红灯，绝不静默连错库。
        """
        st = os.stat(self._db_path)
        return "%d_%d" % (int(st.st_mtime), st.st_size)

    def checkpoint_truncate(self) -> bool:
        """收尾 best-effort：PRAGMA wal_checkpoint(TRUNCATE)。

        有别的连接钉住 WAL 时返回 busy——放弃截断不算错误（-wal 可自动
        恢复，只是脏）。契约第 9 条。
        """
        try:
            row = self._conn().execute(
                "PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.OperationalError:
            logger.warning("wal_checkpoint(TRUNCATE) 执行失败（best-effort 放弃）",
                           exc_info=True)
            return False
        busy = int(row[0]) if row is not None else 1
        if busy:
            logger.info("wal_checkpoint(TRUNCATE) 返回 busy=%d（有读者钉住，放弃截断）",
                        busy)
            return False
        return True
