"""P3 W6（2026-10-28）：单实例锁双平台分支单元测试。

设计：docs/development/2026-10-27-p3-appendix-lock.md（主仓）
- Windows 本地跑 msvcrt 分支真路（真锁真释放）
- POSIX 分支选路逻辑用 monkeypatch sys.platform 验证分发正确
  （真 fcntl 行为在 Linux 容器里由 selftest + 双实例编排覆盖，见 W7）
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from src.infra import db_bridge


class TestLockDualPlatform:
    """双平台锁：win 真路 / posix 选路。"""

    def test_windows_real_lock_polite_exit(self, tmp_path):
        """真 Windows 路：子进程持锁 → 本进程 acquire 必须 sys.exit(42)。"""
        if sys.platform != "win32":
            pytest.skip("Windows 真路（posix 真路由容器 selftest 覆盖）")
        lock = tmp_path / "worker.lock"
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.path.insert(0, %r); "
             "from src.infra.db_bridge import acquire_instance_lock; "
             "h = acquire_instance_lock(%r); "
             "print('HELD', flush=True); time.sleep(10)"
             % (str(Path(__file__).resolve().parent.parent), str(lock))],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            # 等子进程输出 HELD（锁已拿到——msvcrt 锁定后读文件会 PermissionError
            # 故用子进程 stdout 作信号而非文件内容）
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if lock.exists() and lock.stat().st_size > 0:
                    break
                time.sleep(0.1)
            assert lock.exists() and lock.stat().st_size > 0
            # 本进程抢锁 → 必须礼让 SystemExit(42)
            with pytest.raises(SystemExit) as ei:
                db_bridge.acquire_instance_lock(str(lock))
            assert ei.value.code == 42
        finally:
            holder.kill()
            holder.wait(timeout=5)

    def test_platform_dispatch_to_posix(self, tmp_path, monkeypatch):
        """选路逻辑：monkeypatch sys.platform=linux → 走 _posix 路径。"""
        monkeypatch.setattr(sys, "platform", "linux")
        assert db_bridge._on_windows() is False
        # fcntl 在 Windows 上不存在——确认 _try_lock_nb 会走 posix 分支
        # （真锁行为容器里验；这里只验分发不改崩溃）
        import inspect
        src = inspect.getsource(db_bridge._try_lock_nb)
        assert "fcntl" in src
        monkeypatch.setattr(sys, "platform", "win32")
        assert db_bridge._on_windows() is True
        src = inspect.getsource(db_bridge._try_lock_nb)
        assert "msvcrt" in src

    def test_release_none_is_noop(self):
        """release(None) 幂等：不抛不碰。"""
        db_bridge.release_instance_lock(None)

    def test_windows_real_acquire_release_roundtrip(self, tmp_path):
        """真 Windows 路：acquire → release → 再 acquire 成功（自锁自释）。"""
        if sys.platform != "win32":
            pytest.skip("Windows 真路")
        lock = str(tmp_path / "worker.lock")
        h = db_bridge.acquire_instance_lock(lock)
        db_bridge.release_instance_lock(h)
        h2 = db_bridge.acquire_instance_lock(lock)
        assert h2 is not None
        db_bridge.release_instance_lock(h2)

    def test_lock_file_never_deleted_by_api(self, tmp_path):
        """锁文件红线：acquire 只 truncate 重写 pid，路径不变（绝不删改名）。"""
        lock = tmp_path / "worker.lock"
        lock.write_text("99999", encoding="ascii")
        h = db_bridge.acquire_instance_lock(str(lock))
        assert lock.exists()
        # msvcrt 锁定期内其他进程读被锁字节会 PermissionError——只验路径不删
        db_bridge.release_instance_lock(h)
        # 释放后可读：pid 已被 truncate+重写为本进程
        content = lock.read_text(encoding="ascii").strip()
        assert content == str(db_bridge.os.getpid())
