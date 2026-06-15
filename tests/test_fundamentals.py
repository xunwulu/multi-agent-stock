"""
基本面分析师独立测试

验证: 输入股票代码 -> 基本面分析师调用4个工具 -> 输出完整分析报告

运行方式:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    set TUSHARE_TOKEN=你的token
    python tests/test_fundamentals.py
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
logger = logging.getLogger("test_fundamentals")


def main():
    # 1. 加载模型配置
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info(f"Model config loaded: {config['model']} @ {config['base_url']}")

    # 2. 加载 Skill
    from src.core.skill_loader import load_skill

    skill_content = load_skill("fundamentals-analyst")
    logger.info(f"Skill loaded: {len(skill_content)} chars")

    # 3. 注册工具
    from src.core.tool_registry import ToolRegistry
    from src.tools.get_financials import get_financials
    from src.tools.get_institutional import get_institutional
    from src.tools.get_daily_basic import get_daily_basic
    from src.tools.get_index import get_index
    from src.tools.get_peers import get_peers
    from src.tools.get_dcf import get_dcf_valuation

    registry = ToolRegistry()

    registry.register(
        name="get_financials",
        handler=get_financials,
        description=(
            "获取股票财务报表数据，包含利润表、资产负债表、现金流量表、财务指标。"
            "返回数据包含 summary 字段（预计算关键指标）和 scoring_hints 字段（预计算评分建议）。"
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
            "report_type": {
                "type": "string",
                "description": "报表类型: all(全部), income, balancesheet, cashflow, indicators",
            },
        },
        required=["code"],
    )

    registry.register(
        name="get_institutional",
        handler=get_institutional,
        description=(
            "获取股东结构数据，包含前十大股东、前十大流通股东、股东户数变化。"
            "返回数据包含 summary（筹码集中度、机构持仓统计）和 scoring_hints。"
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

    registry.register(
        name="get_daily_basic",
        handler=get_daily_basic,
        description=(
            "获取每日基本面数据: 换手率、量比、PE(TTM)、PB、总市值、流通市值。"
            "返回 valuation 字段包含 PE/PB 历史百分位。"
        ),
        parameters={
            "code": {
                "type": "string",
                "description": "股票代码，如 300033.SZ 或 300033",
            },
        },
        required=["code"],
    )

    registry.register(
        name="get_index",
        handler=get_index,
        description=(
            "获取大盘指数和行业指数数据。"
            "传入 stock_code 参数会自动查询该股票所属行业指数。"
        ),
        parameters={
            "index_code": {
                "type": "string",
                "description": "指数代码或简写，默认 sh（上证指数）",
            },
            "stock_code": {
                "type": "string",
                "description": "股票代码，传入后自动查询所属行业指数",
            },
        },
        required=[],
    )

    registry.register(
        name="get_peers",
        handler=get_peers,
        description=(
            "获取同行业可比公司对标数据（同行PE/PB/ROE/毛利率对比+行业中位数）。"
            "返回 peers（对标表）、industry_median（行业中位数）、target_vs_median（对比差异）、scoring_hints。"
        ),
        parameters={
            "code": {
                "type": "string",
                "description": "股票代码，如 300033.SZ 或 300033",
            },
        },
        required=["code"],
    )

    registry.register(
        name="get_dcf_valuation",
        handler=get_dcf_valuation,
        description=(
            "DCF绝对估值分析（2阶段DCF模型+敏感性分析+PE交叉验证）。"
            "返回内在价值、上涨空间、WACC/增速敏感性表。"
        ),
        parameters={
            "code": {
                "type": "string",
                "description": "股票代码，如 300033.SZ 或 300033",
            },
        },
        required=["code"],
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
            "content": (
                f"请分析股票 {stock_code} 的基本面。"
                f"按照工作流程依次调用6个工具: "
                f"1) get_financials 获取财务报表数据，"
                f"2) get_institutional 获取股东结构数据，"
                f"3) get_daily_basic 获取估值数据（PE/PB百分位），"
                f"4) get_index 获取行业信息（传入stock_code），"
                f"5) get_peers 获取同行业可比公司对标数据，"
                f"6) get_dcf_valuation 获取DCF绝对估值（内在价值+敏感性分析），"
                f"然后按评分锚定表逐项打分，输出完整的基本面分析报告。"
            ),
        }
    ]

    # 6. 运行 Agent Loop
    logger.info(f"Starting Agent Loop for {stock_code} (fundamentals analyst)...")
    result = loop.run(
        system_prompt=skill_content,
        messages=messages,
        tools=tools,
        dispatch_map=dispatch_map,
        max_iterations=10,
    )

    # 7. 输出结果
    print("\n" + "=" * 60)
    print("FUNDAMENTALS ANALYST TEST RESULT")
    print("=" * 60)
    print(f"Success:    {result['success']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Tool calls: {result['tool_calls']}")
    print(f"Duration:   {result['duration_ms']}ms")
    if result.get("error"):
        print(f"Error:      {result['error']}")

    # 8. 质量校验
    from src.infra.quality import validate_analyst_output

    if result["content"]:
        validation = validate_analyst_output(result["content"], schema_type="fundamentals")
        print(f"\nValidation: valid={validation['valid']}")
        if validation["errors"]:
            print(f"Errors: {validation['errors']}")
        if validation["warnings"]:
            print(f"Warnings: {validation['warnings']}")

        # 提取关键信息
        if validation.get("json_data"):
            jd = validation["json_data"]
            print(f"\nScore: {jd.get('score')}")
            print(f"Verdict: {jd.get('verdict')}")
            bd = jd.get("scoring_breakdown", {})
            total = sum(bd.values())
            print(f"Breakdown sum: {total}")
            print(f"Match: {total == jd.get('score')}")
            if bd:
                print("\nScoring breakdown:")
                for k, v in bd.items():
                    print(f"  {k}: {v}")

    print("\n" + "=" * 60)

    # 9. 保存结果
    output_dir = os.path.join(project_root, "output", "test_fundamentals")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Result saved to {output_file}")

    return result


if __name__ == "__main__":
    result = main()
    if result["success"]:
        print("\nFUNDAMENTALS ANALYST TEST PASSED!")
    else:
        print(f"\nFUNDAMENTALS ANALYST TEST FAILED: {result.get('error')}")
        sys.exit(1)
