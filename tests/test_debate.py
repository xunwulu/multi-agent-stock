"""
辩论循环独立测试

验证: 输入技术+基本面报告 -> 看多/看空辩论 -> 输出辩论记录

运行方式:
    cd C:/Users/ZhangXuesen/Documents/multi-agent-stock
    set TUSHARE_TOKEN=你的token
    python tests/test_debate.py
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
logger = logging.getLogger("test_debate")


def main():
    # 1. 加载模型配置
    config_path = os.path.join(project_root, "config", "model.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info(f"Model config loaded: {config['model']} @ {config['base_url']}")

    # 2. 准备模拟分析师报告 (使用真实的分析报告结构)
    # 如果有之前的测试输出，直接加载
    tech_json_path = os.path.join(
        project_root, "output", "test_technical", "result.json"
    )
    fund_json_path = os.path.join(
        project_root, "output", "test_fundamentals", "result.json"
    )

    tech_json = None
    fund_json = None

    # 尝试加载已有报告
    if os.path.exists(tech_json_path):
        with open(tech_json_path, "r", encoding="utf-8") as f:
            tech_result_data = json.load(f)
        from src.infra.quality import validate_analyst_output
        tech_validation = validate_analyst_output(
            tech_result_data.get("content", ""), "technical"
        )
        tech_json = tech_validation.get("json_data")
        if tech_json:
            logger.info(f"Loaded tech report: score={tech_json.get('score')}")
        else:
            logger.warning("Tech report JSON parse failed")

    if os.path.exists(fund_json_path):
        with open(fund_json_path, "r", encoding="utf-8") as f:
            fund_result_data = json.load(f)
        from src.infra.quality import validate_analyst_output
        fund_validation = validate_analyst_output(
            fund_result_data.get("content", ""), "fundamentals"
        )
        fund_json = fund_validation.get("json_data")
        if fund_json:
            logger.info(f"Loaded fund report: score={fund_json.get('score')}")
        else:
            logger.warning("Fund report JSON parse failed")

    # 如果没有已有报告，使用模拟数据
    if not tech_json:
        logger.info("Using mock tech report")
        tech_json = {
            "score": 72,
            "direction": "bullish",
            "short_term_trend": "上升趋势",
            "mid_term_trend": "上升趋势",
            "long_term_trend": "上升趋势",
            "macd_signal": "golden_cross",
            "macd_divergence": "none",
            "kdj_signal": "neutral",
            "rsi_signal": "neutral",
            "money_flow_signal": "continuous_inflow",
            "relative_strength": "outperform",
            "strong_support": 235.0,
            "weak_support": 250.0,
            "weak_resistance": 280.0,
            "strong_resistance": 310.0,
            "stop_loss_price": 232.0,
            "target_price": 300.0,
            "risk_reward_ratio": "1:2.4",
            "scoring_breakdown": {
                "trend_ma": 8, "trend_macd": 7, "trend_price_position": 8,
                "signal_macd": 7, "signal_kdj": 6, "signal_rsi": 5,
                "volume_price": 7, "volume_turnover": 6,
                "relative_vs_index": 8, "relative_volatility": 7,
            },
            "summary": "技术面整体偏多，短中长期趋势一致向上",
        }

    if not fund_json:
        logger.info("Using mock fund report")
        fund_json = {
            "score": 65,
            "verdict": "bullish",
            "profitability_grade": "A",
            "growth_grade": "A-",
            "safety_grade": "B+",
            "valuation_grade": "overvalued",
            "roe_latest": 36.7,
            "gross_margin": "85.0%",
            "net_margin": "24.3%",
            "revenue_yoy": "40.8%",
            "net_profit_yoy": "30.0%",
            "debt_ratio": "60.8%",
            "pe_ttm": 51.6,
            "pb": 40.6,
            "pe_percentile": 75.0,
            "peg": 1.3,
            "insider_signal": "neutral",
            "pledge_risk": "none",
            "key_strengths": [
                "ROE远高于行业平均",
                "营收增速40%+，高成长",
                "有息负债为0，经营性负债为主",
            ],
            "key_risks": [
                "PE百分位75%偏高",
                "PB 40.6处于历史高位",
                "成长股估值回调风险",
            ],
            "scenario_analysis": {
                "bull": {"target_price": 350, "probability": "30%"},
                "base": {"target_price": 280, "probability": "50%"},
                "bear": {"target_price": 200, "probability": "20%"},
            },
            "dcf_cross_check": {
                "intrinsic_value": 320.5,
                "upside_pct": "+32%",
            },
            "scoring_breakdown": {
                "profitability_roe": 9, "profitability_margin": 8,
                "growth_revenue": 8, "growth_profit": 7,
                "safety_debt": 8, "cashflow_quality": 6,
                "valuation_pe": 3, "valuation_pb": 5,
                "holder_concentration": 6, "institutional_presence": 5,
            },
            "summary": "基本面优质但估值偏高，高ROE+零有息负债是亮点",
        }

    # 3. 运行辩论循环
    from src.agents.debate_loop import DebateLoop

    stock_code = "300033.SZ"
    persist_dir = os.path.join(project_root, "output", "test_debate")

    debate = DebateLoop(config, persist_dir=persist_dir)

    logger.info(f"Starting debate for {stock_code} (2 rounds)...")
    result = debate.run(
        stock_code=stock_code,
        tech_report=tech_json,
        fund_report=fund_json,
        max_rounds=2,
    )

    # 4. 输出结果
    print("\n" + "=" * 60)
    print("DEBATE LOOP TEST RESULT")
    print("=" * 60)
    print(f"Success:    {result['success']}")
    print(f"Rounds:     {result['rounds_completed']}")
    print(f"Messages:   {result['total_messages']}")
    print(f"Duration:   {result['duration_ms']}ms")

    if result.get("rounds"):
        for r in result["rounds"]:
            print(f"\n--- Round {r['round']} ---")
            bull = r.get("bull", {})
            bear = r.get("bear", {})
            print(f"  Bull: success={bull.get('success')}, "
                  f"duration={bull.get('duration_ms')}ms")
            print(f"  Bear: success={bear.get('success')}, "
                  f"duration={bear.get('duration_ms')}ms")

    # 5. 输出辩论记录
    print("\n" + "=" * 60)
    print("DEBATE TRANSCRIPT")
    print("=" * 60)
    transcript = result.get("transcript", "")
    if transcript:
        print(transcript[:3000])
        if len(transcript) > 3000:
            print(f"\n... (truncated, total {len(transcript)} chars)")
    else:
        print("(no transcript)")

    # 6. 保存完整结果
    os.makedirs(persist_dir, exist_ok=True)
    output_file = os.path.join(persist_dir, "result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Result saved to {output_file}")

    # 也保存辩论记录为纯文本
    transcript_file = os.path.join(persist_dir, "transcript.txt")
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(transcript)
    logger.info(f"Transcript saved to {transcript_file}")

    print("\n" + "=" * 60)
    return result


if __name__ == "__main__":
    result = main()
    if result["success"]:
        print("\nDEBATE LOOP TEST PASSED!")
    else:
        print(f"\nDEBATE LOOP TEST FAILED")
        sys.exit(1)
