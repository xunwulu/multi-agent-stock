"""
Tool Registry - 工具注册表

用装饰器模式注册工具。每个工具 = 一个处理函数 + 一个 Anthropic 格式的工具定义。

使用方式:
    from src.core.tool_registry import ToolRegistry

    registry = ToolRegistry()

    @registry.tool(
        name="get_kline",
        description="Get stock K-line data",
        parameters={
            "code": {"type": "string", "description": "Stock code like 300033.SZ"},
            "start_date": {"type": "string", "description": "Start date YYYYMMDD"},
            "end_date": {"type": "string", "description": "End date YYYYMMDD"},
        },
        required=["code", "start_date", "end_date"],
    )
    def get_kline(code, start_date, end_date):
        # ... 实际获取数据的代码
        return {"ok": True, "data": [...]}

    # 获取 Anthropic 格式的工具定义
    tools = registry.get_tools()

    # 获取工具名 -> 处理函数的映射
    dispatch_map = registry.get_dispatch_map()
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._handlers: dict[str, Callable] = {}

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, dict],
        required: list[str] | None = None,
    ):
        """
        装饰器：注册一个工具

        Args:
            name: 工具名称（LLM 调用时用的名字）
            description: 工具描述（告诉 LLM 这个工具做什么）
            parameters: 参数定义 {"param_name": {"type": "string", "description": "..."}}
            required: 必填参数列表

        Usage:
            @registry.tool(name="get_kline", description="...", parameters={...})
            def get_kline(code, start_date, end_date):
                ...
        """

        def decorator(func: Callable):
            # 构建 Anthropic 格式的工具定义
            tool_def = {
                "name": name,
                "description": description,
                "input_schema": {
                    "type": "object",
                    "properties": parameters,
                },
            }
            if required:
                tool_def["input_schema"]["required"] = required

            self._tools[name] = tool_def
            self._handlers[name] = func
            logger.info(f"[ToolRegistry] Registered tool: {name}")

            return func

        return decorator

    def register(
        self,
        name: str,
        handler: Callable,
        description: str,
        parameters: dict[str, dict],
        required: list[str] | None = None,
    ):
        """
        直接注册一个工具（不用装饰器）

        Args:
            name: 工具名称
            handler: 处理函数
            description: 工具描述
            parameters: 参数定义
            required: 必填参数列表
        """
        tool_def = {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": parameters,
            },
        }
        if required:
            tool_def["input_schema"]["required"] = required

        self._tools[name] = tool_def
        self._handlers[name] = handler
        logger.info(f"[ToolRegistry] Registered tool: {name}")

    def get_tools(self) -> list[dict]:
        """获取 Anthropic 格式的工具定义列表"""
        return list(self._tools.values())

    def get_dispatch_map(self) -> dict[str, Callable]:
        """获取工具名 -> 处理函数的映射"""
        return dict(self._handlers)

    def get_tool_names(self) -> list[str]:
        """获取所有已注册的工具名"""
        return list(self._tools.keys())

    def has_tool(self, name: str) -> bool:
        """检查某个工具是否已注册"""
        return name in self._tools
