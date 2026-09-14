"""
debate_loop - 看多/看空辩论循环

让看多辩论者和看空辩论者交替发言，形成结构化辩论记录。

流程:
  Round 1: Bull 发言 (看到分析师报告) -> Bear 反驳 (看到报告 + Bull 论点)
  Round 2: Bull 反驳 (看到 Bear 论点) -> Bear 再反驳 (看到 Bull 反驳)
  ...
  达到 max_rounds 后结束

参考: TradingAgents 的 bull_researcher <-> bear_researcher 辩论模式
"""

import time
import json
import logging

from src.core.agent_loop import AgentLoop
from src.core.skill_loader import load_skill
from src.infra.message_bus import MessageBus

logger = logging.getLogger(__name__)


class DebateLoop:
    """
    看多/看空辩论循环

    用法:
        debate = DebateLoop(config, persist_dir="output/debate_logs")
        result = debate.run(
            stock_code="300033.SZ",
            tech_report=tech_json,
            fund_report=fund_json,
            max_rounds=2,
        )
    """

    def __init__(self, config: dict, persist_dir: str | None = None):
        """
        Args:
            config: 模型配置 (同 AgentLoop)
            persist_dir: JSONL 日志输出目录 (可选)
        """
        self.config = config
        self.loop = AgentLoop(config)
        self.bus = MessageBus(persist_dir=persist_dir)
        # 信息增益追踪: 记录辩论中已出现的数字，用于分析每轮新增论据
        self._seen_numbers: set[str] = set()

    def run(
        self,
        stock_code: str,
        tech_report: dict,
        fund_report: dict,
        max_rounds: int = 2,
        news_report: dict | None = None,
    ) -> dict:
        """
        运行完整辩论循环

        Args:
            stock_code: 股票代码
            tech_report: 技术分析师 JSON 输出
            fund_report: 基本面分析师 JSON 输出
            max_rounds: 辩论轮数 (每轮 Bull + Bear 各发言一次)
            news_report: 新闻分析师 JSON 输出（可选）

        Returns:
            {
                "success": True/False,
                "rounds_completed": 2,
                "total_messages": 4,
                "bull_arguments": "...",
                "bear_arguments": "...",
                "transcript": "完整辩论记录",
                "duration_ms": ...,
                "rounds": [
                    {
                        "round": 1,
                        "bull": {"success": True, "content": "...", "duration_ms": ...},
                        "bear": {"success": True, "content": "...", "duration_ms": ...},
                    },
                    ...
                ],
            }
        """
        start_time = time.time()
        rounds_detail = []

        # 格式化分析师报告摘要 (控制长度，避免 token 爆炸)
        reports_summary = self._format_reports(tech_report, fund_report, news_report)

        # 加载 Skill
        bull_skill = load_skill("bull-debater")
        bear_skill = load_skill("bear-debater")

        logger.info(
            f"[Debate] Starting debate for {stock_code}, "
            f"max_rounds={max_rounds}"
        )

        for round_num in range(1, max_rounds + 1):
            round_detail = {"round": round_num}
            logger.info(f"[Debate] === Round {round_num}/{max_rounds} ===")

            # --- Bull 发言 ---
            logger.info(f"[Debate] Round {round_num}: Bull debater speaking...")
            bull_messages = self._build_bull_messages(
                stock_code, reports_summary, round_num,
            )
            bull_result = self.loop.run(
                system_prompt=bull_skill,
                messages=bull_messages,
                tools=None,       # 辩论者不需要工具
                max_iterations=1,  # 一次回复即可
            )
            round_detail["bull"] = {
                "success": bull_result["success"],
                "content": bull_result.get("content", ""),
                "duration_ms": bull_result["duration_ms"],
                "error": bull_result.get("error"),
            }

            if not bull_result["success"]:
                logger.error(
                    f"[Debate] Bull debater failed: {bull_result.get('error')}"
                )
                # B1 fix: retry once on single-side failure
                logger.info("[Debate] Retrying Bull debater...")
                bull_result = self.loop.run(
                    system_prompt=bull_skill,
                    messages=bull_messages,
                    tools=None,
                    max_iterations=1,
                )
                round_detail["bull_retry"] = {
                    "success": bull_result["success"],
                    "duration_ms": bull_result["duration_ms"],
                }

            # Bull 的发言发到消息总线
            bull_content = bull_result.get("content", "(Bull debater failed)")
            self.bus.send(
                from_agent="bull-debater",
                to_agent="bear-debater",
                content=bull_content,
                round_num=round_num,
            )

            # --- Bear 发言 ---
            logger.info(f"[Debate] Round {round_num}: Bear debater speaking...")
            bear_messages = self._build_bear_messages(
                stock_code, reports_summary, round_num, bull_content,
            )
            bear_result = self.loop.run(
                system_prompt=bear_skill,
                messages=bear_messages,
                tools=None,
                max_iterations=1,
            )
            round_detail["bear"] = {
                "success": bear_result["success"],
                "content": bear_result.get("content", ""),
                "duration_ms": bear_result["duration_ms"],
                "error": bear_result.get("error"),
            }

            if not bear_result["success"]:
                logger.error(
                    f"[Debate] Bear debater failed: {bear_result.get('error')}"
                )
                # B1 fix: retry once on single-side failure
                logger.info("[Debate] Retrying Bear debater...")
                bear_result = self.loop.run(
                    system_prompt=bear_skill,
                    messages=bear_messages,
                    tools=None,
                    max_iterations=1,
                )
                round_detail["bear_retry"] = {
                    "success": bear_result["success"],
                    "duration_ms": bear_result["duration_ms"],
                }

            # Bear 的发言发到消息总线
            bear_content = bear_result.get("content", "(Bear debater failed)")
            self.bus.send(
                from_agent="bear-debater",
                to_agent="bull-debater",
                content=bear_content,
                round_num=round_num,
            )

            rounds_detail.append(round_detail)

            # 信息增益日志: 记录每轮新增数字数量
            self._log_info_gain(round_detail, round_num)

            # 检查是否有失败，决定是否继续
            if not bull_result["success"] and not bear_result["success"]:
                logger.warning("[Debate] Both debaters failed, stopping early")
                break

        duration_ms = int((time.time() - start_time) * 1000)
        debate_summary = self.bus.get_debate_summary()

        logger.info(
            f"[Debate] Debate complete: "
            f"{debate_summary['rounds_completed']} rounds, "
            f"{debate_summary['total_messages']} messages, "
            f"{duration_ms}ms"
        )

        return {
            "success": any(
                r.get("bull", {}).get("success") or r.get("bear", {}).get("success")
                for r in rounds_detail
            ),
            "rounds_completed": len(rounds_detail),
            "total_messages": debate_summary["total_messages"],
            "bull_arguments": self._get_last_from("bull-debater"),
            "bear_arguments": self._get_last_from("bear-debater"),
            "transcript": self.bus.format_debate_history(),
            "duration_ms": duration_ms,
            "rounds": rounds_detail,
            "summary": debate_summary,
        }

    def _format_reports(self, tech_report: dict, fund_report: dict, news_report: dict | None = None) -> str:
        """
        将两份分析师报告格式化为完整摘要，传递给辩论者。

        设计原则: 给够数据，减少 AI 脑补/幻觉的动机。
        技术面保留率: ~100%，基本面保留率: ~100%。
        """
        parts = []

        # ===== 技术面报告 =====
        if tech_report:
            parts.append("## 技术分析报告摘要")
            parts.append(f"- 综合评分: {tech_report.get('score', 'N/A')}/100")
            parts.append(f"- 方向: {tech_report.get('direction', 'N/A')}")

            # 趋势
            parts.append(f"- 短期趋势: {tech_report.get('short_term_trend', 'N/A')}")
            parts.append(f"- 中期趋势: {tech_report.get('mid_term_trend', 'N/A')}")
            parts.append(f"- 长期趋势: {tech_report.get('long_term_trend', 'N/A')}")
            parts.append(f"- 趋势综合: {tech_report.get('trend', 'N/A')}")

            # 技术指标信号
            parts.append(f"- MACD信号: {tech_report.get('macd_signal', 'N/A')}")
            parts.append(f"- MACD背离: {tech_report.get('macd_divergence', 'N/A')}")
            parts.append(f"- KDJ信号: {tech_report.get('kdj_signal', 'N/A')}")
            parts.append(f"- KDJ背离: {tech_report.get('kdj_divergence', 'N/A')}")
            parts.append(f"- RSI信号: {tech_report.get('rsi_signal', 'N/A')}")
            parts.append(f"- RSI背离: {tech_report.get('rsi_divergence', 'N/A')}")
            parts.append(f"- 均线形态: {tech_report.get('ma_pattern', 'N/A')}")

            # 量价信号
            parts.append(f"- 成交量信号: {tech_report.get('volume_signal', 'N/A')}")
            parts.append(f"- 换手率信号: {tech_report.get('turnover_signal', 'N/A')}")
            parts.append(f"- 资金流向: {tech_report.get('money_flow_signal', 'N/A')}")
            parts.append(f"- 资金流向详情: {tech_report.get('money_flow_summary', 'N/A')}")
            parts.append(f"- 相对强度: {tech_report.get('relative_strength', 'N/A')}")
            parts.append(f"- 行业对比: {tech_report.get('industry_comparison', 'N/A')}")

            # 共振与周期信号
            parts.append(f"- 多指标共振: {tech_report.get('resonance', 'N/A')}")
            parts.append(f"- 周线/日线信号: {tech_report.get('weekly_signal', 'N/A')}")

            # 关键价位
            parts.append(f"- 强支撑: {tech_report.get('strong_support', 'N/A')}")
            parts.append(f"- 弱支撑: {tech_report.get('weak_support', 'N/A')}")
            parts.append(f"- 弱压力: {tech_report.get('weak_resistance', 'N/A')}")
            parts.append(f"- 强压力: {tech_report.get('strong_resistance', 'N/A')}")
            parts.append(f"- 止损价: {tech_report.get('stop_loss_price', 'N/A')}")
            parts.append(f"- 目标价: {tech_report.get('target_price', 'N/A')}")
            parts.append(f"- 风险收益比: {tech_report.get('risk_reward_ratio', 'N/A')}")

            # K线形态
            kline_patterns = tech_report.get("kline_patterns", [])
            if kline_patterns:
                parts.append(f"- K线形态: {', '.join(str(p) for p in kline_patterns[:10])}")

            # 评分明细
            breakdown = tech_report.get("scoring_breakdown", {})
            if breakdown:
                parts.append("- 评分明细:")
                for k, v in breakdown.items():
                    parts.append(f"  - {k}: {v}")

            # 关键观察 (分析师提炼的 Top 观点)
            observations = tech_report.get("key_observations", [])
            if observations:
                parts.append("- 关键观察:")
                for o in observations[:5]:
                    parts.append(f"  - {o}")

            # 情景分析 (完整版: 目标价+触发条件+关键驱动)
            scenario = tech_report.get("scenario_analysis", {})
            if scenario:
                parts.append("- 情景分析:")
                for key in ["bull", "base", "bear"]:
                    s = scenario.get(key, {})
                    if s:
                        parts.append(
                            f"  - {key}: 目标价={s.get('target_price', 'N/A')}, "
                            f"概率={s.get('probability', 'N/A')}, "
                            f"触发条件={s.get('trigger', 'N/A')}, "
                            f"关键驱动={s.get('key_driver', 'N/A')}"
                        )

            # 失败条件 (看空分析师的核心弹药)
            failure = tech_report.get("failure_conditions", [])
            if failure:
                parts.append("- 失败条件:")
                for f in failure[:5]:
                    parts.append(f"  - {f}")

            # 最新收盘价 (辩论/RM 需要知道当前价位)
            latest_close = tech_report.get("latest_close")
            if latest_close:
                parts.append(f"- 最新收盘价: {latest_close}")

            # 总结 (不截断)
            summary = tech_report.get("summary", "")
            if summary:
                parts.append(f"- 总结: {summary}")

        # ===== 基本面报告 =====
        if fund_report:
            parts.append("")
            parts.append("## 基本面分析报告摘要")
            parts.append(f"- 综合评分: {fund_report.get('score', 'N/A')}/100")
            parts.append(f"- 判定: {fund_report.get('verdict', 'N/A')}")
            parts.append(f"- 盈利等级: {fund_report.get('profitability_grade', 'N/A')}")
            parts.append(f"- 成长等级: {fund_report.get('growth_grade', 'N/A')}")
            parts.append(f"- 安全等级: {fund_report.get('safety_grade', 'N/A')}")
            parts.append(f"- 估值等级: {fund_report.get('valuation_grade', 'N/A')}")

            # 盈利能力
            parts.append(f"- ROE(最新): {fund_report.get('roe_latest', 'N/A')}")
            parts.append(f"- ROE(年均): {fund_report.get('roe_annual', 'N/A')}")
            parts.append(f"- ROE趋势: {fund_report.get('roe_trend', 'N/A')}")
            parts.append(f"- 毛利率: {fund_report.get('gross_margin', 'N/A')}")
            parts.append(f"- 净利率: {fund_report.get('net_margin', 'N/A')}")
            parts.append(f"- 费用泄漏: {fund_report.get('expense_leakage', 'N/A')}")

            # 成长性
            parts.append(f"- 营收增速: {fund_report.get('revenue_yoy', 'N/A')}")
            parts.append(f"- 营收趋势: {fund_report.get('revenue_trend', 'N/A')}")
            parts.append(f"- 净利增速: {fund_report.get('net_profit_yoy', 'N/A')}")
            parts.append(f"- 利润趋势: {fund_report.get('profit_trend', 'N/A')}")
            parts.append(f"- 扣非占比: {fund_report.get('deducted_profit_ratio', 'N/A')}")
            parts.append(f"- 增长归因: {fund_report.get('growth_attribution', 'N/A')}")

            # 安全性
            parts.append(f"- 负债率: {fund_report.get('debt_ratio', 'N/A')}")
            parts.append(f"- 负债结构: {fund_report.get('debt_structure', 'N/A')}")
            parts.append(f"- 流动比率: {fund_report.get('current_ratio', 'N/A')}")
            parts.append(f"- 经营现金流/净利润: {fund_report.get('ocf_to_np_ratio', 'N/A')}")
            parts.append(f"- 自由现金流: {fund_report.get('free_cash_flow', 'N/A')}")
            parts.append(f"- FCF利润率: {fund_report.get('fcf_margin', 'N/A')}")
            parts.append(f"- 现金流类型: {fund_report.get('cashflow_type', 'N/A')}")
            parts.append(f"- 营收现金比: {fund_report.get('revenue_cash_ratio', 'N/A')}")

            # 估值
            parts.append(f"- PE(TTM): {fund_report.get('pe_ttm', 'N/A')}")
            parts.append(f"- PB: {fund_report.get('pb', 'N/A')}")
            parts.append(f"- PE百分位: {fund_report.get('pe_percentile', 'N/A')}")
            parts.append(f"- PB百分位: {fund_report.get('pb_percentile', 'N/A')}")
            parts.append(f"- PEG: {fund_report.get('peg', 'N/A')}")
            parts.append(f"- 估值概述: {fund_report.get('valuation_summary', 'N/A')}")

            # 股东结构
            parts.append(f"- 股东户数变化: {fund_report.get('holder_num_change_pct', 'N/A')}")
            parts.append(f"- 股东趋势: {fund_report.get('holder_trend', 'N/A')}")
            parts.append(f"- 机构比例: {fund_report.get('institutional_ratio', 'N/A')}")
            parts.append(f"- 内部人信号: {fund_report.get('insider_signal', 'N/A')}")
            parts.append(f"- 内部人详情: {fund_report.get('insider_note', 'N/A')}")
            parts.append(f"- 质押风险: {fund_report.get('pledge_risk', 'N/A')}")
            parts.append(f"- 质押详情: {fund_report.get('pledge_note', 'N/A')}")

            # 治理风险 + ST状态 + 机构持仓数 + 年均ROE (之前部分丢弃, 现补全)
            gov_events = fund_report.get("governance_events")
            if gov_events:
                parts.append(f"- 治理事件: {gov_events}")
            st_status = fund_report.get("st_status")
            if st_status and st_status != "normal":
                parts.append(f"- ST状态: {st_status} ({fund_report.get('st_reason', '')})")
            inst_holders = fund_report.get("institutional_holders")
            if inst_holders is not None:
                parts.append(f"- 机构持仓数: {inst_holders}")
            roe_annual = fund_report.get("roe_annual")
            if roe_annual is not None:
                parts.append(f"- 年均ROE: {roe_annual}")

            # 行业分析 (完整嵌套对象)
            industry = fund_report.get("industry_analysis", {})
            if industry:
                parts.append("- 行业分析:")
                if isinstance(industry, dict):
                    for ik, iv in industry.items():
                        parts.append(f"  - {ik}: {iv}")
                else:
                    parts.append(f"  - {industry}")

            # 股息政策
            dividend = fund_report.get("dividend", {})
            if dividend:
                parts.append("- 股息政策:")
                if isinstance(dividend, dict):
                    for dk, dv in dividend.items():
                        parts.append(f"  - {dk}: {dv}")
                else:
                    parts.append(f"  - {dividend}")

            # 盈利预测
            forecast = fund_report.get("earnings_forecast", {})
            if forecast:
                parts.append("- 盈利预测:")
                if isinstance(forecast, dict):
                    for fk, fv in forecast.items():
                        parts.append(f"  - {fk}: {fv}")
                else:
                    parts.append(f"  - {forecast}")

            # 关键优势和风险 (不限制数量)
            strengths = fund_report.get("key_strengths", [])
            if strengths:
                parts.append("- 核心优势:")
                for s in strengths:
                    parts.append(f"  - {s}")

            risks = fund_report.get("key_risks", [])
            if risks:
                parts.append("- 核心风险:")
                for r in risks:
                    parts.append(f"  - {r}")

            # 情景分析 (完整版: 目标价+概率+关键驱动+EPS预测)
            scenario = fund_report.get("scenario_analysis", {})
            if scenario:
                parts.append("- 情景分析:")
                for key in ["bull", "base", "bear"]:
                    s = scenario.get(key, {})
                    if s:
                        parts.append(
                            f"  - {key}: 目标价={s.get('target_price', 'N/A')}, "
                            f"概率={s.get('probability', 'N/A')}, "
                            f"关键驱动={s.get('key_driver', 'N/A')}, "
                            f"EPS预测={s.get('eps_estimate', 'N/A')}"
                        )

            # 概率加权目标价 (完整嵌套对象)
            target = fund_report.get("target_price", {})
            if target:
                parts.append("- 概率加权目标价:")
                if isinstance(target, dict):
                    for tk, tv in target.items():
                        parts.append(f"  - {tk}: {tv}")
                else:
                    parts.append(f"  - {target}")

            # DCF 交叉验证 (完整版)
            dcf = fund_report.get("dcf_cross_check", {})
            if dcf:
                parts.append("- DCF估值:")
                if isinstance(dcf, dict):
                    for dk, dv in dcf.items():
                        parts.append(f"  - {dk}: {dv}")
                else:
                    parts.append(f"  - {dcf}")

            # 跨层矛盾 (重要辩论弹药)
            cross_notes = fund_report.get("cross_layer_notes", "")
            if cross_notes:
                parts.append(f"- 跨层矛盾: {cross_notes}")

            # 商业模式
            biz_model = fund_report.get("business_model", "")
            if biz_model:
                parts.append(f"- 商业模式: {biz_model}")

            # 杜邦分析
            dupont = fund_report.get("dupont_analysis", "")
            if dupont:
                parts.append(f"- 杜邦分析: {dupont}")

            # 营运资金
            wc = fund_report.get("working_capital", "")
            if wc:
                parts.append(f"- 营运资金: {wc}")

            # 评分明细
            breakdown = fund_report.get("scoring_breakdown", {})
            if breakdown:
                parts.append("- 评分明细:")
                for k, v in breakdown.items():
                    parts.append(f"  - {k}: {v}")

            # 关键观察 (分析师提炼的 Top 观点)
            observations = fund_report.get("key_observations", [])
            if observations:
                parts.append("- 关键观察:")
                for o in observations[:5]:
                    parts.append(f"  - {o}")

            # 总结 (不截断)
            summary = fund_report.get("summary", "")
            if summary:
                parts.append(f"- 总结: {summary}")

            # 跟踪指标 (未来3个月关注)
            tracking = fund_report.get("tracking_indicators", [])
            if tracking:
                parts.append("- 跟踪指标:")
                for t in tracking[:5]:
                    parts.append(f"  - {t}")

        # ===== 新闻面报告 =====
        if news_report:
            parts.append("")
            parts.append("## 新闻面分析报告摘要")
            parts.append(f"- 综合评分: {news_report.get('score', 'N/A')}/100")
            parts.append(f"- 方向: {news_report.get('direction', 'N/A')}")
            parts.append(f"- 市场情绪: {news_report.get('sentiment', 'N/A')}")
            parts.append(f"- 情绪置信度: {news_report.get('sentiment_confidence', 'N/A')}")
            parts.append(f"- 市场关注度: {news_report.get('market_attention', 'N/A')}")

            # 关键事件
            key_events = news_report.get("key_events", [])
            if key_events:
                parts.append("- 关键事件:")
                for e in key_events[:5]:
                    if isinstance(e, dict):
                        parts.append(
                            f"  - {e.get('event', 'N/A')} "
                            f"(方向={e.get('direction', 'N/A')}, "
                            f"冲击={e.get('impact', 'N/A')}, "
                            f"持续={e.get('duration', 'N/A')})"
                        )
                    else:
                        parts.append(f"  - {e}")

            # 风险事件
            risk_events = news_report.get("risk_events", [])
            if risk_events:
                parts.append("- 风险事件:")
                for r in risk_events[:5]:
                    if isinstance(r, dict):
                        parts.append(
                            f"  - {r.get('event', 'N/A')} "
                            f"(严重={r.get('severity', 'N/A')}, "
                            f"概率={r.get('probability', 'N/A')})"
                        )
                    else:
                        parts.append(f"  - {r}")

            # 利好/利空因素
            pos = news_report.get("positive_factors", [])
            if pos:
                parts.append(f"- 利好因素: {'; '.join(str(p) for p in pos[:5])}")
            neg = news_report.get("negative_factors", [])
            if neg:
                parts.append(f"- 利空因素: {'; '.join(str(n) for n in neg[:5])}")

            # 评分明细
            breakdown = news_report.get("scoring_breakdown", {})
            if breakdown:
                parts.append("- 评分明细:")
                for k, v in breakdown.items():
                    parts.append(f"  - {k}: {v}")

            # 数据时效
            fresh = news_report.get("data_freshness", {})
            if fresh:
                parts.append(
                    f"- 数据时效: 最新新闻{fresh.get('latest_news_date', 'N/A')}, "
                    f"新闻总数{fresh.get('news_count', 'N/A')}"
                )

            # 关键观察 + 失效条件 (之前部分丢弃, 现补全)
            news_obs = news_report.get("key_observations", [])
            if news_obs:
                parts.append("- 关键观察:")
                for o in news_obs[:5]:
                    parts.append(f"  - {o}")
            news_fail = news_report.get("failure_conditions", [])
            if news_fail:
                parts.append("- 失效条件:")
                for fc in news_fail[:4]:
                    parts.append(f"  - {fc}")

            # 总结
            news_summary = news_report.get("summary", "")
            if news_summary:
                parts.append(f"- 总结: {news_summary}")

        return "\n".join(parts)

    def _build_bull_messages(
        self, stock_code: str, reports_summary: str, round_num: int,
    ) -> list[dict]:
        """构建看多辩论者的输入消息"""
        if round_num == 1:
            # 第一轮: 看到完整报告，构建初始看多案例
            content = (
                f"请为股票 {stock_code} 构建看多论证。\n\n"
                f"以下是分析师报告摘要:\n\n"
                f"{reports_summary}\n\n"
                f"请基于以上数据，构建有力的看多案例。"
            )
        else:
            # P2 fix: 后续轮次也用完整报告，保持辩手信息对称
            last_bear = self._get_last_from("bear-debater") or ""
            history = self.bus.format_debate_history()

            content = (
                f"请为股票 {stock_code} 继续看多辩论。\n\n"
                f"以下是分析师报告摘要:\n\n"
                f"{reports_summary}\n\n"
                f"以下是之前的辩论记录:\n\n"
                f"{history}\n\n"
                f"看空分析师的最新反驳:\n{last_bear}\n\n"
                f"请回应看空分析师的反驳，补充新的看多论据。"
            )

        return [{"role": "user", "content": content}]

    def _build_bear_messages(
        self, stock_code: str, reports_summary: str, round_num: int,
        last_bull_content: str,
    ) -> list[dict]:
        """构建看空辩论者的输入消息"""
        # 看空分析师每轮都能看到看多论点
        history = self.bus.format_debate_history()

        if round_num == 1 and not history.strip():
            # 第一轮: 看到完整报告 + Bull 的论点
            content = (
                f"请为股票 {stock_code} 构建看空论证。\n\n"
                f"以下是分析师报告摘要:\n\n"
                f"{reports_summary}\n\n"
                f"看多分析师的论点:\n{last_bull_content}\n\n"
                f"请基于以上数据，构建有力的看空案例，并反驳看多观点。"
            )
        else:
            # 后续轮次: 看到完整历史 + Bull 最新论点
            content = (
                f"请为股票 {stock_code} 继续看空辩论。\n\n"
                f"以下是分析师报告摘要:\n\n"
                f"{reports_summary}\n\n"
                f"以下是之前的辩论记录:\n\n"
                f"{history}\n\n"
                f"看多分析师的最新论点:\n{last_bull_content}\n\n"
                f"请回应看多分析师的论点，补充新的看空论据。"
            )

        return [{"role": "user", "content": content}]

    def _get_last_from(self, agent_name: str) -> str:
        """获取某个辩论者的最后发言"""
        msg = self.bus.get_last_from(agent_name)
        return msg.content if msg else ""

    def _log_info_gain(self, round_detail: dict, round_num: int) -> None:
        """
        记录每轮信息增益 (纯正则，零LLM成本)

        追踪辩论中出现的数字，计算每轮新增数字数量。
        仅用于日志记录和未来优化分析，不影响辩论流程。
        """
        import re

        num_pattern = re.compile(r"\d+\.?\d*")

        for side in ["bull", "bear"]:
            content = round_detail.get(side, {}).get("content", "")
            if not content:
                continue

            # 提取所有数字
            numbers = set(num_pattern.findall(content))
            # 计算新增数字
            new_numbers = numbers - self._seen_numbers
            # 更新已见数字集合
            self._seen_numbers.update(numbers)

            logger.info(
                f"[Debate] Info gain: round={round_num}, side={side}, "
                f"total_numbers={len(numbers)}, "
                f"new_numbers={len(new_numbers)}, "
                f"cumulative_seen={len(self._seen_numbers)}"
            )

            if new_numbers and len(new_numbers) <= 10:
                logger.info(
                    f"[Debate] New data points: {new_numbers}"
                )
