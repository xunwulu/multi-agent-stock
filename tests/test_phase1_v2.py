"""
Phase 1 升级测试 - 4工具完整喂养

验证: 输入股票代码 -> 技术分析师调用4个工具 -> 输出完整分析报告

对比 v1: 只有 get_kline (60天)
升级 v2: get_kline(250天) + calc_technical + get_daily_basic + get_index

运行方式:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    set TUSHARE_TOKEN=你的token
    python tests/test_phase1_v2.py
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
logger = logging.getLogger("test_phase1_v2")


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

    # 3. 注册所有4个工具
    from src.core.tool_registry import ToolRegistry
    from src.tools.get_kline import get_kline
    from src.tools.calc_technical import calc_technical
    from src.tools.get_daily_basic import get_daily_basic
    from src.tools.get_moneyflow import get_moneyflow
    from src.tools.get_index import get_index

    registry = ToolRegistry()

    # 工具 1: get_kline - K线数据
    registry.register(
        name="get_kline",
        handler=get_kline,
        description=(
            "获取股票K线数据，包含开盘价、收盘价、最高价、最低价、成交量、成交额。"
            "支持日K线(默认)、周K线、月K线。"
            "默认返回最近250个交易日的日K线数据（已做前复权处理）。"
            "start_date 和 end_date 可以省略，会自动计算。"
        ),
        parameters={
            "code": {
                "type": "string",
                "description": "股票代码，如 300033.SZ 或 300033",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYYMMDD（可省略，自动计算为250天前）",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYYMMDD（可省略，默认今天）",
            },
            "period": {
                "type": "string",
                "description": "K线周期: daily(日线)/weekly(周线)/monthly(月线)，默认 daily",
            },
        },
        required=["code"],
    )

    # 工具 2: calc_technical - 预计算技术指标
    registry.register(
        name="calc_technical",
        handler=calc_technical,
        description=(
            "获取股票的预计算技术指标，包含: "
            "均线(MA5/MA10/MA20/MA60/MA120)、"
            "MACD(DIF/DEA/柱状图)、"
            "KDJ(K/D/J)、"
            "RSI(RSI6/RSI12/RSI24)、"
            "布林带(上轨/中轨/下轨)、"
            "背离检测(MACD/KDJ/RSI的顶背离和底背离)、"
            "K线形态识别(锤子线/十字星/吞没形态等)。"
            "返回数据包含 summary 字段，提供最新信号摘要和K线形态列表。"
            "start_date 和 end_date 可以省略。"
        ),
        parameters={
            "code": {
                "type": "string",
                "description": "股票代码，如 300033.SZ 或 300033",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYYMMDD（可省略，自动计算）",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYYMMDD（可省略，默认今天）",
            },
            "indicators": {
                "type": "string",
                "description":
                    "需要计算的指标: 'all'(全部，默认), 'ma'(均线), 'macd', 'kdj', 'rsi', 'boll'(布林带)。"
                    "可用逗号组合，如 'ma,macd'",
            },
        },
        required=["code"],
    )

    # 工具 3: get_daily_basic - 换手率/量比/PE/PB/市值
    registry.register(
        name="get_daily_basic",
        handler=get_daily_basic,
        description=(
            "获取每日基本面数据: 换手率、量比、PE(TTM)、PB、总市值、流通市值。"
            "用于量价关系分析和估值参考。"
        ),
        parameters={
            "code": {
                "type": "string",
                "description": "股票代码，如 300033.SZ 或 300033",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYYMMDD（可省略，自动计算）",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYYMMDD（可省略，默认今天）",
            },
        },
        required=["code"],
    )

    # 工具 4: get_moneyflow - 资金流向
    registry.register(
        name="get_moneyflow",
        handler=get_moneyflow,
        description=(
            "获取个股资金流向数据，包含大单/特大单/中单/小单的买卖金额和净流入。"
            "返回 summary 包含主力信号判断（持续流入/持续流出/反转等）。"
            "用于判断主力资金真实意图。"
        ),
        parameters={
            "code": {
                "type": "string",
                "description": "股票代码，如 300033.SZ 或 300033",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYYMMDD（可省略，默认近30天）",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYYMMDD（可省略，默认今天）",
            },
        },
        required=["code"],
    )

    # 工具 5: get_index - 大盘指数+行业指数
    registry.register(
        name="get_index",
        handler=get_index,
        description=(
            "获取大盘指数和行业指数数据，用于判断个股是否跑赢/跑输大盘和行业。"
            "传入 stock_code 参数会自动查询该股票所属申万行业指数。"
            "返回指数走势、涨跌幅统计、行业信息。"
        ),
        parameters={
            "index_code": {
                "type": "string",
                "description":
                    "指数代码或简写: 'sh'(上证指数), 'sz'(深证成指), "
                    "'cyb'(创业板指), 'hs300'(沪深300), 'zz500'(中证500)。默认 'sh'",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYYMMDD（可省略，自动计算）",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYYMMDD（可省略，默认今天）",
            },
            "stock_code": {
                "type": "string",
                "description": "股票代码（如 300033.SZ）。传入后自动查询该股票所属行业指数",
            },
        },
        required=[],
    )

    tools = registry.get_tools()
    dispatch_map = registry.get_dispatch_map()
    logger.info(f"Tools registered: {registry.get_tool_names()}")

    # 4. 创建 Agent Loop
    from src.core.agent_loop import AgentLoop

    loop = AgentLoop(config)

    # 5. 准备用户消息 - 引导 LLM 使用全部4个工具
    stock_code = "300033.SZ"
    messages = [
        {
            "role": "user",
            "content": (
                f"请分析股票 {stock_code} 的技术面。"
                f"按照工作流程依次调用5个工具: "
                f"1) get_kline 获取K线数据，"
                f"2) calc_technical 获取预计算技术指标（含背离检测和K线形态），"
                f"3) get_daily_basic 获取换手率/PE/PB数据，"
                f"4) get_moneyflow 获取资金流向数据（判断主力动向），"
                f"5) get_index 获取上证指数对比（传入stock_code获取行业指数），"
                f"然后按评分锚定表逐项打分，输出完整的技术分析报告（包含短中长期趋势、"
                f"多层支撑压力位、止损价/目标价、风险收益比、背离信号、评分明细）。"
            ),
        }
    ]

    # 6. 运行 Agent Loop (增加迭代次数，因为需要调用4个工具)
    logger.info(f"Starting Agent Loop for {stock_code} with 4 tools...")
    result = loop.run(
        system_prompt=skill_content,
        messages=messages,
        tools=tools,
        dispatch_map=dispatch_map,
        max_iterations=10,
    )

    # 7. 输出结果
    print("\n" + "=" * 60)
    print("PHASE 1 V2 TEST RESULT (4 Tools)")
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
            print("(Report saved to output/test_phase1_v2/result.json)")

    print("\n" + "=" * 60)

    # 8. 保存结果
    output_dir = os.path.join(project_root, "output", "test_phase1_v2")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Result saved to {output_file}")

    return result


if __name__ == "__main__":
    result = main()
    if result["success"]:
        print("\nPhase 1 V2 TEST PASSED!")
    else:
        print(f"\nPhase 1 V2 TEST FAILED: {result.get('error')}")
        sys.exit(1)
