"""
公共工具模块 - Tushare 客户端和股票代码标准化

消除 get_kline / calc_technical / get_daily_basic / get_moneyflow / get_index
中的重复代码，统一维护。
"""

import os
import sys
import logging
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
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params,
        }
        resp = requests.post(self.api_url, json=payload, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"Tushare API error: {data.get('msg')}")
        fields = data["data"]["fields"]
        items = data["data"]["items"]
        return [dict(zip(fields, item)) for item in items]

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
