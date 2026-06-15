"""
Phase 1 端到端测试

验证: 输入股票代码 -> 技术分析师 -> 输出分析报告

运行方式:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    python tests/test_phase1.py
"""

import json
import sys
import os
import logging

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_phase1")


def main():
    # 1. 加载模型配置
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info(f"Model config loaded: {config['model']} @ {config['base_url']}")

    # 2. 加载 Skill
    from src.core.skill_loader import load_skill

    skill_content = load_skill("technical-analyst")
    logger.info(f"Skill loaded: {len(skill_content)} chars")

    # 3. 注册工具
    from src.core.tool_registry import ToolRegistry
    from src.tools.get_kline import get_kline

    registry = ToolRegistry()

    registry.register(
        name="get_kline",
        handler=get_kline,
        description="Get stock K-line (candlestick) data. Returns OHLCV data for analysis.",
        parameters={
            "code": {
                "type": "string",
                "description": "Stock code like 300033.SZ or 300033",
            },
            "start_date": {
                "type": "string",
                "description": "Start date, format YYYYMMDD",
            },
            "end_date": {
                "type": "string",
                "description": "End date, format YYYYMMDD",
            },
            "period": {
                "type": "string",
                "description": "K-line period: daily/weekly/monthly (default: daily)",
            },
        },
        required=["code", "start_date", "end_date"],
    )

    tools = registry.get_tools()
    dispatch_map = registry.get_dispatch_map()
    logger.info(f"Tools registered: {registry.get_tool_names()}")

    # 4. 创建 Agent Loop
    from src.core.agent_loop import AgentLoop

    loop = AgentLoop(config)

    # 5. 准备用户消息
    stock_code = "300033.SZ"
    messages = [
        {
            "role": "user",
            "content": f"Analyze stock {stock_code}. Get the last 60 trading days of daily K-line data, then provide a complete technical analysis in the required JSON format.",
        }
    ]

    # 6. 运行 Agent Loop
    logger.info(f"Starting Agent Loop for {stock_code}...")
    result = loop.run(
        system_prompt=skill_content,
        messages=messages,
        tools=tools,
        dispatch_map=dispatch_map,
        max_iterations=5,
    )

    # 7. 输出结果
    print("\n" + "=" * 60)
    print("PHASE 1 TEST RESULT")
    print("=" * 60)
    print(f"Success:    {result['success']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Tool calls: {result['tool_calls']}")
    print(f"Duration:   {result['duration_ms']}ms")
    if result.get("error"):
        print(f"Error:      {result['error']}")

    if result["content"]:
        print("\n--- Analysis Report ---")
        try:
            print(result["content"])
        except UnicodeEncodeError:
            # Windows console encoding issue - save to file instead
            print("(Report contains characters that cannot display in console)")
            print("Full report saved to output/test_phase1/result.json")

    print("\n" + "=" * 60)

    # 8. 保存结果到 output/
    output_dir = os.path.join(project_root, "output", "test_phase1")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Result saved to {output_file}")

    return result


if __name__ == "__main__":
    result = main()
    if result["success"]:
        print("\nPhase 1 TEST PASSED!")
    else:
        print(f"\nPhase 1 TEST FAILED: {result.get('error')}")
        sys.exit(1)
