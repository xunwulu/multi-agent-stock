"""
公共工具模块 - Tushare 客户端和股票代码标准化

消除 get_kline / calc_technical / get_daily_basic / get_moneyflow / get_index
中的重复代码，统一维护。
"""

import os
import sys
import time
import random
import logging
import threading
import json
import requests
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_env_token() -> str:
    """从环境变量或 .env 文件读取 TUSHARE_TOKEN"""
    token = os.getenv("TUSHARE_TOKEN", "")
    if token:
        return token
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TUSHARE_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


_TUSHARE_TOKEN = _load_env_token()
_USE_PROXY = os.getenv("TUSHARE_USE_PROXY", "false").lower() == "true"


# === 限流容错配置（第2刀）===
_MAX_RETRIES = 4          # 重试次数（总尝试 5 次）
_BASE_DELAY = 1.0         # 指数退避基础间隔(秒)
_RETRY_CAP = 20.0         # 单次退避上限(秒)
_TS_RATE = 2.0            # 令牌桶: 平均 2 次/秒（Tushare 500次/分≈8.3/s，留余量）
_TS_BURST = 5             # 令牌桶: 突发上限


# === 异常类（失败分级，供上游按 error_type 决策）===
class TushareError(Exception):
    """Tushare 调用异常基类。kind: transient_rate_limit / network / permanent"""

    def __init__(self, kind: str, msg: str):
        self.kind = kind
        super().__init__(msg)


class TushareRateLimitError(TushareError):
    """限流（可重试，耗尽后抛出）"""

    def __init__(self, msg: str):
        super().__init__("transient_rate_limit", msg)


class TushareNetworkError(TushareError):
    """网络错误（可重试，耗尽后抛出）"""

    def __init__(self, msg: str):
        super().__init__("network", msg)


class TusharePermanentError(TushareError):
    """永久错误（参数/权限/无数据，不重试）"""

    def __init__(self, msg: str):
        super().__init__("permanent", msg)


class _TushareRateLimiter:
    """Tushare 专用令牌桶（模块级单例，跨分析师线程共享，防并发放大触发限流）"""

    def __init__(self, rate: float = _TS_RATE, burst: int = _TS_BURST):
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        """阻塞直到拿到一个令牌"""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.burst,
                    self._tokens + (now - self._last_refill) * self.rate,
                )
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(0.05)


_tushare_limiter = _TushareRateLimiter()


# === 请求级缓存（第3刀）===
# 一次 run_analysis 内共享、跨分析清空。命中跳过限流/重试/网络，是 Tushare 调用量翻倍的根因解药。
_cache_store: dict = {}
_cache_lock = threading.Lock()
_cache_enabled = False
_cache_stats = {"hit": 0, "miss": 0}


def enable_cache() -> None:
    """开启请求级缓存(清空旧数据)。run_analysis 开头调用。"""
    global _cache_enabled, _cache_stats
    with _cache_lock:
        _cache_store.clear()
        _cache_stats = {"hit": 0, "miss": 0}
        _cache_enabled = True
    logger.info("[Tushare Cache] enabled (request-scoped)")


def disable_cache() -> None:
    """关闭并清空缓存。run_analysis 结束调用，保证跨股票隔离。"""
    global _cache_enabled
    with _cache_lock:
        cleared = len(_cache_store)
        _cache_store.clear()
        _cache_enabled = False
    logger.info(
        f"[Tushare Cache] disabled: hit={_cache_stats['hit']}, "
        f"miss={_cache_stats['miss']}, cleared={cleared}"
    )


def get_cache_stats() -> dict:
    """返回缓存命中统计(供观测/调试)"""
    return dict(_cache_stats)


def _cache_key(api_name: str, params: dict) -> str:
    """生成缓存 key: api_name + 排序后的 params(含 fields)，避免参数顺序差异导致 miss。"""
    stable = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return f"{api_name}|{stable}"


def _parse_retry_after(resp) -> float | None:
    """从响应头解析 Retry-After（秒），无效返回 None"""
    val = resp.headers.get("Retry-After")
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _is_rate_limit_msg(msg: str) -> bool:
    """判断 Tushare 业务错误信息是否为限流（可重试）。
    注意: 用"频率/超限"等精准词, 避免误匹配"权限"里的"限"字。
    """
    if not msg:
        return False
    low = msg.lower()
    return any(
        k in low
        for k in (
            "频率", "超限", "频次", "过于频繁", "每天最多",
            "frequency", "too many", "rate limit",
        )
    )


def normalize_code(code: str) -> str:
    """
    标准化股票代码

    "300033"    -> "300033.SZ"
    "600519"    -> "600519.SH"
    "300033.SZ" -> "300033.SZ" (不变)
    """
    if "." in code:
        return code
    code = code.strip()
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    elif code.startswith(("0", "3", "2")):
        return f"{code}.SZ"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"


class DirectTushareClient:
    """直接调用 Tushare API 的客户端"""

    def __init__(self, token: str = ""):
        self.token = token or _TUSHARE_TOKEN
        self.api_url = "http://api.tushare.pro"

    def _call(self, api_name: str, params: dict) -> list[dict]:
        """
        调用 Tushare API，带令牌桶限速 + 指数退避重试 + 失败分级。

        - 限流(HTTP 429/5xx 或业务层"频率超限")/网络错误: 重试(指数退避+full jitter)
        - 永久错误(权限/参数/非JSON): 立即抛 TusharePermanentError，不重试
        - 重试耗尽: 抛 TushareRateLimitError / TushareNetworkError
        - Retry-After header: 若返回则优先使用其值
        """
        # 请求级缓存: 命中直接返回浅拷贝(防业务 .sort() 污染缓存), 跳过限流/重试
        key = _cache_key(api_name, params)
        if _cache_enabled:
            with _cache_lock:
                if key in _cache_store:
                    _cache_stats["hit"] += 1
                    return [dict(r) for r in _cache_store[key]]

        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params,
        }
        last_err = None

        for attempt in range(_MAX_RETRIES + 1):
            _tushare_limiter.acquire()
            try:
                resp = requests.post(self.api_url, json=payload, timeout=15)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = TushareNetworkError(str(e))
            except Exception as e:
                raise TusharePermanentError(f"request error: {e}")
            else:
                http_err = self._classify_http(resp)
                if http_err is None:
                    # HTTP 正常，解析业务层
                    try:
                        data = resp.json()
                    except Exception as e:
                        raise TusharePermanentError(f"non-JSON response: {e}")
                    if data.get("code") == 0:
                        fields = data["data"]["fields"]
                        items = data["data"]["items"]
                        result_list = [dict(zip(fields, item)) for item in items]
                        if _cache_enabled:
                            with _cache_lock:
                                _cache_stats["miss"] += 1
                                _cache_store[key] = [dict(r) for r in result_list]
                        return result_list
                    msg = data.get("msg", "") or f"unknown tushare error (code={data.get('code')})"
                    if _is_rate_limit_msg(msg):
                        last_err = TushareRateLimitError(msg)
                    else:
                        raise TusharePermanentError(msg)
                else:
                    last_err = http_err
                    retry_after = _parse_retry_after(resp)
                    if retry_after is not None and attempt < _MAX_RETRIES:
                        logger.warning(
                            f"[Tushare] {api_name} 限流, "
                            f"Retry-After={retry_after}s, "
                            f"retry {attempt + 1}/{_MAX_RETRIES}"
                        )
                        time.sleep(min(retry_after, _RETRY_CAP))
                        continue

            # 退避（仅限流/网络错误；full jitter 防 thundering herd，AWS 标准）
            if attempt < _MAX_RETRIES and isinstance(
                last_err, (TushareRateLimitError, TushareNetworkError)
            ):
                delay = min(_BASE_DELAY * (2 ** attempt), _RETRY_CAP)
                sleep_time = random.uniform(0, delay)
                logger.warning(
                    f"[Tushare] {api_name} {last_err.kind}: {last_err}, "
                    f"retry {attempt + 1}/{_MAX_RETRIES} in {sleep_time:.1f}s"
                )
                time.sleep(sleep_time)

        if last_err is None:
            last_err = TusharePermanentError(f"unknown failure for {api_name}")
        logger.error(
            f"[Tushare] {api_name} 重试耗尽: {last_err.kind}: {last_err}"
        )
        raise last_err

    @staticmethod
    def _classify_http(resp):
        """HTTP 层分级: 429=限流; 5xx=服务端/网关故障(归网络,可重试); 其余 None"""
        if resp.status_code == 429:
            return TushareRateLimitError(f"HTTP {resp.status_code}")
        if resp.status_code in (500, 502, 503, 504):
            return TushareNetworkError(f"HTTP {resp.status_code}")
        return None

    # 通用方法
    def get_stock_daily(self, ts_code, start_date, end_date):
        return self._call("daily", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
        })

    def get_adj_factor(self, ts_code, start_date, end_date):
        return self._call("adj_factor", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
        })

    def get_daily_basic(self, ts_code, start_date, end_date):
        return self._call("daily_basic", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
            "fields": "trade_date,close,turnover_rate,volume_ratio,pe_ttm,pb,total_mv,circ_mv",
        })

    def get_index_daily(self, ts_code, start_date, end_date):
        return self._call("index_daily", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
        })

    def get_sw_daily(self, ts_code, start_date, end_date):
        return self._call("sw_daily", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
        })

    def get_stock_basic(self, ts_code):
        return self._call("stock_basic", {
            "ts_code": ts_code, "fields": "ts_code,name,industry",
        })

    def get_moneyflow(self, ts_code, start_date, end_date):
        return self._call("moneyflow", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
        })

    def get_stock_weekly(self, ts_code, start_date, end_date):
        return self._call("weekly", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
        })

    def get_stock_monthly(self, ts_code, start_date, end_date):
        return self._call("monthly", {
            "ts_code": ts_code, "start_date": start_date, "end_date": end_date,
        })


def get_tushare_client() -> DirectTushareClient:
    """
    获取 Tushare 客户端。

    优先尝试从 ai-investment-tool 导入 TushareService，
    如果不可用则使用内置的 DirectTushareClient。
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        backend_path = project_root.parent / "ai-investment-tool" / "backend"
        if backend_path.exists():
            sys.path.insert(0, str(backend_path))
            from app.services.tushare_service import TushareService
            return TushareService(_TUSHARE_TOKEN, use_codebuddy_proxy=_USE_PROXY)
    except Exception as e:
        logger.warning(f"Cannot import TushareService: {e}")

    return DirectTushareClient(_TUSHARE_TOKEN)
