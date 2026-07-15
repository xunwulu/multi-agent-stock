"""
test_tool_cache - 验证第3刀请求级缓存

验证点:
  1. 命中: 同参数第二次走缓存, requests.post 只调1次
  2. 未命中: 参数不同(如 fields) -> 两次都真调
  3. 浅拷贝: 业务 .sort() 不污染缓存
  4. disable 清空: disable 后再调 -> 真调
  5. 默认关闭: 未 enable 时不缓存, 两次都真调

Usage: python -m pytest tests/test_tool_cache.py -v
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.tools.tushare_utils import (
    DirectTushareClient,
    enable_cache,
    disable_cache,
    _tushare_limiter,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前后确保缓存关闭+清空，避免互相污染"""
    disable_cache()
    yield
    disable_cache()


def _ok_response(items=None, fields=None):
    fields = fields or ["ts_code", "trade_date", "close"]
    items = items or [["300033.SZ", "20251231", 30.0]]
    mock = MagicMock()
    mock.status_code = 200
    mock.headers = {}
    mock.json.return_value = {"code": 0, "data": {"fields": fields, "items": items}}
    return mock


def _patched_client(token="fake"):
    """构造 client + 计数 post + 关闭限速阻塞"""
    client = DirectTushareClient(token=token)
    call_count = {"n": 0}

    def post_side(*a, **k):
        call_count["n"] += 1
        return _ok_response()

    return client, call_count, post_side


def test_cache_hit_skips_second_call():
    """同参数第二次命中缓存, requests.post 只调1次"""
    enable_cache()
    client, call_count, post_side = _patched_client()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        r1 = client._call("daily", {"ts_code": "300033.SZ"})
        r2 = client._call("daily", {"ts_code": "300033.SZ"})
    assert call_count["n"] == 1  # 第二次命中
    assert r1 == r2


def test_cache_miss_on_different_params():
    """参数不同(fields) -> 两次都真调"""
    enable_cache()
    client, call_count, post_side = _patched_client()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        client._call("daily", {"ts_code": "300033.SZ", "fields": "A"})
        client._call("daily", {"ts_code": "300033.SZ", "fields": "B"})
    assert call_count["n"] == 2  # params 不同, 都 miss


def test_cache_returns_copy_not_reference():
    """缓存命中返回浅拷贝: 业务 .sort() 不污染缓存"""
    enable_cache()
    client = DirectTushareClient(token="fake")
    items = [["300033.SZ", "20251231", 30.0], ["300033.SZ", "20251230", 25.0]]
    with patch("src.tools.tushare_utils.requests.post",
               return_value=_ok_response(items=items)), \
         patch.object(_tushare_limiter, "acquire"):
        r1 = client._call("daily", {"ts_code": "300033.SZ"})
        r1.sort(key=lambda x: x["trade_date"])  # 升序原地改: 20251230 在前
        r2 = client._call("daily", {"ts_code": "300033.SZ"})  # 命中缓存
    # r2 应是原始顺序(20251231 在前), 不被 r1.sort() 污染
    assert r2[0]["trade_date"] == "20251231"


def test_disable_cache_clears_store():
    """disable 后缓存清空, 再调 -> 真调"""
    enable_cache()
    client, call_count, post_side = _patched_client()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        client._call("daily", {"ts_code": "300033.SZ"})  # miss
        assert call_count["n"] == 1
        client._call("daily", {"ts_code": "300033.SZ"})  # hit
        assert call_count["n"] == 1
        disable_cache()
        client._call("daily", {"ts_code": "300033.SZ"})  # 清空后再真调
        assert call_count["n"] == 2


def test_cache_disabled_by_default():
    """默认(未 enable)不缓存, 两次都真调"""
    client, call_count, post_side = _patched_client()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        client._call("daily", {"ts_code": "300033.SZ"})
        client._call("daily", {"ts_code": "300033.SZ"})
    assert call_count["n"] == 2  # 未开启, 都真调


def test_permanent_error_not_cached():
    """永久错误(权限不足)不写缓存: 两次调用都真调 post"""
    from src.tools.tushare_utils import TusharePermanentError
    enable_cache()
    client = DirectTushareClient(token="fake")
    perm_resp = MagicMock()
    perm_resp.status_code = 200
    perm_resp.headers = {}
    perm_resp.json.return_value = {"code": 1, "msg": "抱歉，您没有权限访问该接口"}
    call_count = {"n": 0}

    def post_side(*a, **k):
        call_count["n"] += 1
        return perm_resp

    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        with pytest.raises(TusharePermanentError):
            client._call("daily", {"ts_code": "300033.SZ"})
        with pytest.raises(TusharePermanentError):
            client._call("daily", {"ts_code": "300033.SZ"})
    assert call_count["n"] == 2  # 永久错误不缓存, 两次都真调


def test_cache_stats_counted_correctly():
    """get_cache_stats: 1 miss + 2 hit 后 = {hit:2, miss:1}"""
    from src.tools.tushare_utils import get_cache_stats
    enable_cache()
    client, call_count, post_side = _patched_client()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        client._call("daily", {"ts_code": "300033.SZ"})  # miss
        client._call("daily", {"ts_code": "300033.SZ"})  # hit
        client._call("daily", {"ts_code": "300033.SZ"})  # hit
        stats = get_cache_stats()
    assert stats == {"hit": 2, "miss": 1}


def test_cache_key_order_invariant():
    """_cache_key: 参数顺序不同但内容相同 -> 命中同 key"""
    enable_cache()
    client, call_count, post_side = _patched_client()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        client._call("daily", {"ts_code": "300033.SZ", "fields": "A", "start_date": "20260101"})
        client._call("daily", {"start_date": "20260101", "fields": "A", "ts_code": "300033.SZ"})
    assert call_count["n"] == 1  # 顺序不同同 key, 第二次命中


def test_enable_cache_clears_stale():
    """enable_cache 清空残留: enable→调A→enable→调A, 第二次真调"""
    enable_cache()
    client, call_count, post_side = _patched_client()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch.object(_tushare_limiter, "acquire"):
        client._call("daily", {"ts_code": "300033.SZ"})  # miss
        assert call_count["n"] == 1
        enable_cache()  # 清空残留
        client._call("daily", {"ts_code": "300033.SZ"})  # 残留被清, 又 miss
        assert call_count["n"] == 2


def test_cache_hit_skips_limiter():
    """命中跳过 _tushare_limiter.acquire: 第二次 acquire 不调用"""
    enable_cache()
    client, call_count, post_side = _patched_client()
    limiter_spy = MagicMock()
    with patch("src.tools.tushare_utils.requests.post", side_effect=post_side), \
         patch("src.tools.tushare_utils._tushare_limiter.acquire", limiter_spy):
        client._call("daily", {"ts_code": "300033.SZ"})  # miss: acquire 1次
        client._call("daily", {"ts_code": "300033.SZ"})  # hit: acquire 0次
    assert limiter_spy.call_count == 1  # 只 miss 时调 acquire


def test_dict_mutation_does_not_pollute_cache():
    """命中返回 dict 副本: 改 dict 字段不污染缓存"""
    enable_cache()
    client = DirectTushareClient(token="fake")
    with patch("src.tools.tushare_utils.requests.post",
               return_value=_ok_response(items=[["300033.SZ", "20251231", 30.0]])), \
         patch.object(_tushare_limiter, "acquire"):
        r1 = client._call("daily", {"ts_code": "300033.SZ"})
        r1[0]["close"] = 999  # 改返回的 dict(副本)
        r2 = client._call("daily", {"ts_code": "300033.SZ"})  # 命中
    assert r2[0]["close"] == 30.0  # 缓存未被污染
