"""
test_tushare_retry - 验证第2刀 Tushare 限流容错

验证点:
  1. 业务层限流 -> 重试后成功
  2. 重试耗尽 -> 抛 TushareRateLimitError
  3. HTTP 429 -> 视为限流重试
  4. 永久错误(权限不足) -> 不重试，立即抛 TusharePermanentError
  5. 网络错误 -> 重试后成功
  6. 令牌桶 burst 内不阻塞

Usage: python -m pytest tests/test_tushare_retry.py -v
"""
import sys
import os
import time as _time
import pytest
import requests
from unittest.mock import patch, MagicMock

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.tools.tushare_utils import (
    DirectTushareClient,
    TushareRateLimitError,
    TusharePermanentError,
    _tushare_limiter,
    _TushareRateLimiter,
)


def _ok_response():
    """构造成功响应"""
    mock = MagicMock()
    mock.status_code = 200
    mock.headers = {}
    mock.json.return_value = {
        "code": 0,
        "data": {"fields": ["ts_code", "trade_date"], "items": [["300033.SZ", "20251231"]]},
    }
    return mock


def _rate_limit_response():
    """业务层限流响应(code!=0, msg 含'频率超限')"""
    mock = MagicMock()
    mock.status_code = 200
    mock.headers = {}
    mock.json.return_value = {"code": 1, "msg": "抱歉，您访问接口频率超限(500次/分钟)"}
    return mock


def _http_429_response():
    mock = MagicMock()
    mock.status_code = 429
    mock.headers = {}
    return mock


def _permanent_error_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.headers = {}
    mock.json.return_value = {"code": 1, "msg": "抱歉，您没有权限访问该接口"}
    return mock


def _run_call(responses):
    """用一组 mock 响应运行 _call，返回 (result, call_count)。跳过真实 sleep/限速"""
    client = DirectTushareClient(token="fake_token")
    call_count = {"n": 0}

    def post_side_effect(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        r = responses[idx] if idx < len(responses) else responses[-1]
        if isinstance(r, Exception):
            raise r
        return r

    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side_effect), \
         patch("src.tools.tushare_utils.time.sleep"), \
         patch("src.tools.tushare_utils.random.uniform", return_value=0.01), \
         patch.object(_tushare_limiter, "acquire"):
        result = client._call("daily", {"ts_code": "300033.SZ"})
    return result, call_count["n"]


def test_retry_on_rate_limit_then_success():
    """前2次业务层限流，第3次成功 -> 拿到数据，调了3次"""
    result, n = _run_call([_rate_limit_response(), _rate_limit_response(), _ok_response()])
    assert n == 3
    assert result == [{"ts_code": "300033.SZ", "trade_date": "20251231"}]


def test_exhaust_retries_raises_rate_limit():
    """永远限流 -> 重试耗尽，抛 TushareRateLimitError"""
    client = DirectTushareClient(token="fake")
    with patch("src.tools.tushare_utils.requests.post", return_value=_rate_limit_response()), \
         patch("src.tools.tushare_utils.time.sleep"), \
         patch("src.tools.tushare_utils.random.uniform", return_value=0.01), \
         patch.object(_tushare_limiter, "acquire"):
        with pytest.raises(TushareRateLimitError):
            client._call("daily", {"ts_code": "300033.SZ"})


def test_http_429_treated_as_rate_limit():
    """HTTP 429 -> 视为限流重试，最终成功"""
    result, n = _run_call([_http_429_response(), _ok_response()])
    assert n == 2
    assert result == [{"ts_code": "300033.SZ", "trade_date": "20251231"}]


def test_permanent_error_no_retry():
    """权限不足(永久错误) -> 立即抛 TusharePermanentError，只调1次"""
    client = DirectTushareClient(token="fake")
    call_count = {"n": 0}

    def post_side(*a, **k):
        call_count["n"] += 1
        return _permanent_error_response()

    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        with pytest.raises(TusharePermanentError):
            client._call("daily", {"ts_code": "300033.SZ"})
    assert call_count["n"] == 1  # 永久错误不重试


def test_network_error_retries_then_succeeds():
    """第1次网络错误，第2次成功 -> 重试后拿到数据"""
    conn_err = requests.ConnectionError("network down")
    result, n = _run_call([conn_err, _ok_response()])
    assert n == 2
    assert result == [{"ts_code": "300033.SZ", "trade_date": "20251231"}]


def test_token_bucket_burst_no_block():
    """令牌桶 burst 次调用立即返回(不阻塞)，验证限速器可正常工作"""
    limiter = _TushareRateLimiter(rate=1.0, burst=3)
    t0 = _time.monotonic()
    for _ in range(3):
        limiter.acquire()
    elapsed = _time.monotonic() - t0
    assert elapsed < 0.5  # burst 内快速返回


def test_http_429_with_retry_after_header():
    """HTTP 429 + Retry-After header -> 优先用 Retry-After 退避，重试成功"""
    resp1 = MagicMock()
    resp1.status_code = 429
    resp1.headers = {"Retry-After": "0.1"}
    result, n = _run_call([resp1, _ok_response()])
    assert n == 2
    assert result == [{"ts_code": "300033.SZ", "trade_date": "20251231"}]


def test_http_5xx_treated_as_network_retry():
    """HTTP 500/502/503/504 -> 归 NetworkError 重试，最终成功"""
    for code in (500, 502, 503, 504):
        resp = MagicMock()
        resp.status_code = code
        resp.headers = {}
        result, n = _run_call([resp, _ok_response()])
        assert n == 2, f"HTTP {code} 应触发重试"


def test_timeout_retries_then_succeeds():
    """requests.Timeout -> 重试后成功"""
    timeout_err = requests.Timeout("read timed out")
    result, n = _run_call([timeout_err, _ok_response()])
    assert n == 2
    assert result == [{"ts_code": "300033.SZ", "trade_date": "20251231"}]


def test_last_attempt_succeeds():
    """前4次限流，第5次(attempt=4,最后一次)成功 -> 验证 off-by-one"""
    rl = _rate_limit_response()
    result, n = _run_call([rl, rl, rl, rl, _ok_response()])
    assert n == 5
    assert result == [{"ts_code": "300033.SZ", "trade_date": "20251231"}]


def test_token_bucket_limits_after_burst():
    """令牌桶 burst+1 会真阻塞(真限速): burst=2, 第3次必须等令牌补充"""
    limiter = _TushareRateLimiter(rate=4.0, burst=2)
    limiter.acquire()
    limiter.acquire()
    t0 = _time.monotonic()
    limiter.acquire()  # 第3次: 令牌空, 需等
    elapsed = _time.monotonic() - t0
    assert elapsed >= 0.1, f"第3次应阻塞等令牌, 实际 {elapsed:.3f}s"
