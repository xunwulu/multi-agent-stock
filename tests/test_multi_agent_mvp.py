"""
2+1 多智能体 MVP 端到端测试

验证: 输入股票代码 -> 编排者调技术分析师 + 基本面分析师 -> 输出综合报告

运行方式:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    set TUSHARE_TOKEN=你的token
    python tests/test_multi_agent_mvp.py
"""

import json
import sys
import os
import logging

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 尝试从 .env 文件加载 TUSHARE_TOKEN
_env_file = os.path.join(project_root, ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as f:
        for _line in f:
            _line = _line.strip()
            if _line.startswith("TUSHARE_TOKEN="):
                os.environ["TUSHARE_TOKEN"] = _line.split("=", 1)[1].strip()

# Windows 终端 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_multi_agent_mvp")


def main():
    # 1. 加载模型配置
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info(f"Model config loaded: {config['model']} @ {config['base_url']}")

    # 2. 创建编排者
    from src.agents.orchestrator import MultiAgentOrchestrator

    orchestrator = MultiAgentOrchestrator(config)
    logger.info("Orchestrator created")

    # 3. 运行完整分析
    stock_code = "300033.SZ"
    logger.info(f"Starting full analysis for {stock_code}...")
    result = orchestrator.run_analysis(stock_code, max_iterations=10)

    # 4. 输出结果
    print("\n" + "=" * 60)
    print("MULTI-AGENT MVP TEST RESULT")
    print("=" * 60)
    print(f"Stock:      {result['stock_code']}")
    print(f"Success:    {result['success']}")
    print(f"Duration:   {result['duration_ms']}ms ({result['duration_ms']/1000:.1f}s)")
    if result.get("error"):
        print(f"Error:      {result['error']}")

    # 技术分析师结果
    tech = result["tech_report"]
    print(f"\n--- Technical Analyst ---")
    print(f"  Success:    {tech['success']}")
    print(f"  Iterations: {tech['iterations']}")
    print(f"  Tool calls: {tech['tool_calls']}")
    print(f"  Duration:   {tech['duration_ms']}ms")
    if tech.get("json_data"):
        jd = tech["json_data"]
        print(f"  Score:      {jd.get('score')}")
        print(f"  Direction:  {jd.get('direction')}")
    if tech.get("validation"):
        print(f"  Valid:      {tech['validation']['valid']}")
        if tech["validation"]["warnings"]:
            print(f"  Warnings:   {tech['validation']['warnings']}")

    # 基本面分析师结果
    fund = result["fund_report"]
    print(f"\n--- Fundamentals Analyst ---")
    print(f"  Success:    {fund['success']}")
    print(f"  Iterations: {fund['iterations']}")
    print(f"  Tool calls: {fund['tool_calls']}")
    print(f"  Duration:   {fund['duration_ms']}ms")
    if fund.get("json_data"):
        jd = fund["json_data"]
        print(f"  Score:      {jd.get('score')}")
        print(f"  Verdict:    {jd.get('verdict')}")
    if fund.get("validation"):
        print(f"  Valid:      {fund['validation']['valid']}")
        if fund["validation"]["warnings"]:
            print(f"  Warnings:   {fund['validation']['warnings']}")

    # 综合报告
    combined = result["combined_report"]
    print(f"\n--- Combined Report ---")
    print(f"  Combined Score:  {combined['combined_score']}")
    print(f"  Direction:       {combined['combined_direction']}")
    print(f"  Tech Score:      {combined['tech_score']} ({combined['tech_direction']})")
    print(f"  Fund Score:      {combined['fund_score']} ({combined['fund_direction']})")
    print(f"  Alignment:       {combined['alignment']}")
    print(f"  Recommendation:  {combined['recommendation']}")
    print(f"  Summary:         {combined['summary']}")

    # 5. 断言检查
    print(f"\n--- Assertions ---")
    checks = []

    # Check 1: 整体成功
    check1 = result["success"]
    checks.append(("Overall success", check1))
    print(f"  Overall success:        {'PASS' if check1 else 'FAIL'}")

    # Check 2: 技术分析师成功
    check2 = tech["success"]
    checks.append(("Tech analyst success", check2))
    print(f"  Tech analyst success:   {'PASS' if check2 else 'FAIL'}")

    # Check 3: 基本面分析师成功
    check3 = fund["success"]
    checks.append(("Fund analyst success", check3))
    print(f"  Fund analyst success:   {'PASS' if check3 else 'FAIL'}")

    # Check 4: 综合评分在 0-100
    check4 = 0 <= combined["combined_score"] <= 100
    checks.append(("Combined score range", check4))
    print(f"  Combined score 0-100:   {'PASS' if check4 else 'FAIL'} (got {combined['combined_score']})")

    # Check 5: 方向有效
    valid_dirs = [
        "strong_bullish", "bullish", "neutral", "bearish", "strong_bearish",
    ]
    check5 = combined["combined_direction"] in valid_dirs
    checks.append(("Direction valid", check5))
    print(f"  Direction valid:        {'PASS' if check5 else 'FAIL'} (got {combined['combined_direction']})")

    # Check 6: 一致性不为空
    check6 = combined["alignment"] in ["aligned", "divergent"]
    checks.append(("Alignment valid", check6))
    print(f"  Alignment valid:        {'PASS' if check6 else 'FAIL'} (got {combined['alignment']})")

    # Check 7: 技术面 JSON 解析成功
    check7 = tech.get("json_data") is not None and tech["json_data"].get("score") is not None
    checks.append(("Tech JSON parsed", check7))
    print(f"  Tech JSON parsed:       {'PASS' if check7 else 'FAIL'}")

    # Check 8: 基本面 JSON 解析成功
    check8 = fund.get("json_data") is not None and fund["json_data"].get("score") is not None
    checks.append(("Fund JSON parsed", check8))
    print(f"  Fund JSON parsed:       {'PASS' if check8 else 'FAIL'}")

    # Check 9: 技术面 tool_calls >= 5 (5 个工具)
    check9 = tech["tool_calls"] >= 5
    checks.append(("Tech tool_calls >= 5", check9))
    print(f"  Tech tool_calls >= 5:   {'PASS' if check9 else 'FAIL'} (got {tech['tool_calls']})")

    # Check 10: 基本面 tool_calls >= 4 (4 个工具)
    check10 = fund["tool_calls"] >= 4
    checks.append(("Fund tool_calls >= 4", check10))
    print(f"  Fund tool_calls >= 4:   {'PASS' if check10 else 'FAIL'} (got {fund['tool_calls']})")

    # Check 11: 综合评分 = 技术评分*50% + 基本面评分*50%
    expected_combined = round(combined["tech_score"] * 0.5 + combined["fund_score"] * 0.5, 1)
    check11 = combined["combined_score"] == expected_combined
    checks.append(("Combined score math", check11))
    print(f"  Combined score math:    {'PASS' if check11 else 'FAIL'} "
          f"(expected {expected_combined}, got {combined['combined_score']})")

    all_passed = all(c[1] for c in checks)
    print(f"\n  Result: {sum(1 for c in checks if c[1])}/{len(checks)} checks passed")

    # 6. 保存结果
    output_dir = os.path.join(project_root, "output", "test_multi_agent_mvp")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Result saved to {output_file}")

    print("\n" + "=" * 60)

    return {
        "all_passed": all_passed,
        "checks": checks,
        "result": result,
    }


if __name__ == "__main__":
    output = main()
    if output["all_passed"]:
        print("\nMULTI-AGENT MVP TEST PASSED!")
    else:
        failed = [c[0] for c in output["checks"] if not c[1]]
        print(f"\nMULTI-AGENT MVP TEST FAILED: {failed}")
        sys.exit(1)
