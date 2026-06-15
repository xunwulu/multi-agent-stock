"""
get_governance - 公司治理风险检测工具

检测内容:
  - ST / *ST 状态 (通过 namechange 更名历史)
  - ST 原因和持续时间 (通过 stk_surv 特别处理)
  - 治理风险等级评估 (clean / watch / critical)

数据源: Tushare namechange + stk_surv 接口
设计: 轻量预检 -- 正常股票只调 1 次 API, ST 股票调 2 次
"""

import time
import logging
from datetime import datetime

from src.tools.tushare_utils import get_tushare_client, normalize_code

logger = logging.getLogger(__name__)


def get_governance(code: str) -> dict:
    """
    检测股票的治理风险

    Args:
        code: 股票代码 (如 600525.SH 或 600525)

    Returns:
        {
            "ok": True,
            "st_status": {"is_st": bool, "st_type": str, "st_reason": str, "st_since": str},
            "governance_risk": "clean" / "watch" / "critical",
            "governance_risk_reason": str,
            "name_changes": [...],
            "duration_ms": int,
            "error": None
        }
    """
    start_ms = time.time()
    ts_code = normalize_code(code)
    code6 = ts_code.split(".")[0]

    try:
        client = get_tushare_client()

        # Step 1: 查更名历史 (最快, 1 次 API 调用)
        st_detected = False
        st_type = ""
        st_since = ""
        name_changes = []

        try:
            raw_names = client._call("namechange", {
                "ts_code": ts_code,
                "fields": "ts_code,name,ann_date,change_reason",
            })
            if isinstance(raw_names, list):
                for item in raw_names:
                    name = str(item.get("name", ""))
                    ann_date = str(item.get("ann_date", ""))
                    reason = str(item.get("change_reason", ""))
                    name_changes.append({
                        "name": name,
                        "ann_date": ann_date,
                        "reason": reason,
                    })
                    # 检测 ST 标记 (ST长园, *ST长园, SST, S*ST etc.)
                    if name.startswith("*ST") or name.startswith("ST") or name.startswith("S*ST") or name.startswith("SST"):
                        st_detected = True
                        # Extract prefix: "ST长园" -> "ST", "*ST长园" -> "*ST"
                        for prefix in ("*ST", "S*ST", "SST", "ST"):
                            if name.startswith(prefix):
                                if not st_type or len(prefix) > len(st_type):
                                    st_type = prefix
                                break
                        if not st_since or ann_date < st_since:
                            st_since = ann_date
        except Exception as e:
            logger.warning(f"[get_governance] namechange failed: {e}")

        # 快速返回: 正常股票
        if not st_detected:
            duration_ms = int((time.time() - start_ms) * 1000)
            return {
                "ok": True,
                "st_status": {
                    "is_st": False,
                    "st_type": "normal",
                    "st_reason": "",
                    "st_since": "",
                },
                "governance_risk": "clean",
                "governance_risk_reason": "No ST history detected",
                "name_changes": name_changes[:10],
                "duration_ms": duration_ms,
                "error": None,
            }

        # Step 2: ST 股票, 查 stk_surv 获取详细信息
        st_reason = ""
        regulatory_events = []

        try:
            raw_surv = client._call("stk_surv", {
                "ts_code": ts_code,
                "fields": "ts_code,trade_date,surv_type,surv_reason",
            })
            if isinstance(raw_surv, list):
                for item in raw_surv[:10]:
                    surv_type = str(item.get("surv_type", ""))
                    surv_reason = str(item.get("surv_reason", ""))
                    trade_date = str(item.get("trade_date", ""))
                    regulatory_events.append({
                        "date": trade_date,
                        "type": surv_type,
                        "detail": surv_reason,
                    })
                    if surv_reason and not st_reason:
                        st_reason = surv_reason
        except Exception as e:
            logger.warning(f"[get_governance] stk_surv failed: {e}")

        # 风险等级判定
        is_star_st = "*" in st_type
        if is_star_st or st_type == "*ST":
            risk_level = "critical"
            risk_reason = f"*ST stock: {st_type}, since {st_since}. {st_reason}"
        elif st_type == "ST":
            risk_level = "critical"
            risk_reason = f"ST stock: {st_type}, since {st_since}. {st_reason}"
        else:
            risk_level = "watch"
            risk_reason = f"ST history detected: {st_type}, since {st_since}"

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[get_governance] {ts_code}: {risk_level}, "
            f"{len(regulatory_events)} events, {duration_ms}ms"
        )

        return {
            "ok": True,
            "st_status": {
                "is_st": True,
                "st_type": st_type,
                "st_reason": st_reason,
                "st_since": st_since,
            },
            "governance_risk": risk_level,
            "governance_risk_reason": risk_reason,
            "regulatory_events": regulatory_events,
            "name_changes": name_changes[:10],
            "duration_ms": duration_ms,
            "error": None,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[get_governance] Error: {e}")
        return {
            "ok": False,
            "st_status": {
                "is_st": False,
                "st_type": "unknown",
                "st_reason": "",
                "st_since": "",
            },
            "governance_risk": "clean",
            "governance_risk_reason": f"Check failed: {e}",
            "name_changes": [],
            "duration_ms": duration_ms,
            "error": str(e),
        }
