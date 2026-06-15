"""
Shared State - 共享状态字典

所有智能体的分析结果统一存储在一个 State 字典中。
每个角色读取需要的字段，写入自己负责的字段。

参考: LangGraph 的 State 设计
"""

import json
import time
from typing import Any


class SharedState:
    """共享状态管理器"""

    def __init__(self, stock_code: str):
        """
        初始化共享状态

        Args:
            stock_code: 要分析的股票代码（如 300033.SZ）
        """
        self.data = {
            "stock_code": stock_code,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            # Phase 1: 分析师产出
            "tech_report": None,
            "fund_report": None,
            "news_report": None,
            "sentiment_report": None,
            # Phase 2: 辩论产出
            "bull_args": None,
            "bear_args": None,
            "debate_rounds": 0,
            # Phase 3: 研究经理综合
            "research_summary": None,
            # Phase 4: 风控产出
            "risk_views": None,
            # Phase 5: 最终决策
            "decision": None,
            "target_price": None,
            "confidence": None,
            "risk_score": None,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """读取字段"""
        return self.data.get(key, default)

    def set(self, key: str, value: Any):
        """写入字段"""
        self.data[key] = value

    def update(self, values: dict):
        """批量更新"""
        self.data.update(values)

    def to_dict(self) -> dict:
        """返回完整状态字典"""
        return dict(self.data)

    def to_json(self) -> str:
        """导出为 JSON"""
        return json.dumps(self.data, ensure_ascii=False, indent=2, default=str)
