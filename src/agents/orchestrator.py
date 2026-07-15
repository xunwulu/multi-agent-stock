"""
orchestrator - 多智能体编排者

实际流程（6 阶段，每阶段都有失败降级，保证 run_analysis 总返回有效 result dict）:
  Phase 1: 三个分析师并行（技术 / 基本面 / 新闻），ThreadPoolExecutor
  Phase 2: 看多/看空辩论（bull/bear debater，自由文本）
  Phase 3: 研究经理（LLM）评判辩论，调整评分与方向；失败降级为正则启发式
  Phase 4: 三方风险辩论（激进 / 中性 / 保守）
  Phase 5: 风险经理（LLM）评估风险等级与仓位；失败降级为确定性规则
  Phase 6: 交易员（LLM）输出可执行决策；失败降级为确定性规则映射

设计选择:
  - 代码编排（非 LLM 编排），确定性 Python 流程
  - 分析师并行 + 辩论循环 + 多层 LLM 研判
  - 每层 LLM 失败都有确定性兜底，run_analysis 永不抛异常
"""

import json
import time
import logging

from src.core.agent_loop import AgentLoop
from src.core.skill_loader import load_skill
from src.core.tool_registry import ToolRegistry
from src.core.state import SharedState
from src.infra.quality import (
    validate_analyst_output,
    validate_structured_output,
    validate_research_manager_output,
    validate_research_manager_structured,
    validate_risk_manager_structured,
    validate_trader_output,
    validate_trader_structured,
)
from src.core.submit_tool import get_submit_tool
from src.agents.debate_loop import DebateLoop
from src.agents.risk_loop import RiskLoop

from src.tools.tushare_utils import enable_cache, disable_cache, get_cache_stats
from src.tools.get_kline import get_kline
from src.tools.calc_technical import calc_technical
from src.tools.get_daily_basic import get_daily_basic
from src.tools.get_moneyflow import get_moneyflow
from src.tools.get_index import get_index
from src.tools.get_financials import get_financials
from src.tools.get_governance import get_governance
from src.tools.get_institutional import get_institutional
from src.tools.get_peers import get_peers
from src.tools.get_dcf import get_dcf_valuation
from src.tools.get_stock_news import get_stock_news

logger = logging.getLogger(__name__)

# Max chars for injected pre-fetched data (prevent context overflow)
_INJECT_DATA_MAX_CHARS = 30000

# Expected scoring_breakdown field counts (must match quality.py schemas)
# tech: 11 (TECHNICAL_ANALYST_SCHEMA.scoring_breakdown_fields)
# fund: 14 (FUNDAMENTALS_ANALYST_SCHEMA.scoring_breakdown_fields)
# news: 6 (NEWS_ANALYST_SCHEMA.scoring_breakdown_fields)
_EXPECTED_BREAKDOWN_COUNTS = {"tech": 11, "fund": 14, "news": 6}

# 第4刀: 阶段超时围栏(防各阶段累积超时挂死)
# ANALYST_TIMEOUT: 单个分析师最长运行时间(秒), 超时走降级
# TOTAL_BUDGET: 单只股票完整分析的总预算(秒), 超时后辩论/交易员跳过 LLM 走确定性兜底
ANALYST_TIMEOUT = 180
TOTAL_BUDGET = 600


def _truncate_inject_data(data: dict) -> str:
    """Serialize pre-fetched data, truncating if too large for context."""
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) > _INJECT_DATA_MAX_CHARS:
        text = text[:_INJECT_DATA_MAX_CHARS] + "\n...(数据已截断)"
    return text


class MultiAgentOrchestrator:
    """多智能体编排者: 分析师 + 辩论 + 综合汇总"""

    def __init__(self, config: dict, persist_dir: str | None = None):
        self.config = config
        self.loop = AgentLoop(config)
        self.persist_dir = persist_dir

    def run_analysis(
        self,
        stock_code: str,
        max_iterations: int = 10,
        debate_rounds: int = 2,
        skip_debate: bool = False,
    ) -> dict:
        """
        运行完整的分析流程

        Args:
            stock_code: 股票代码（如 300033.SZ）
            max_iterations: 每个分析师的最大迭代次数
            debate_rounds: 辩论轮数 (每轮 Bull + Bear 各发言一次)
            skip_debate: 是否跳过辩论阶段（用于快速测试）

        Returns:
            {
                "stock_code": "300033.SZ",
                "tech_report": {...},
                "fund_report": {...},
                "debate_result": {...},    # 辩论结果 (Phase 2)
                "combined_report": {...},
                "success": True/False,
                "duration_ms": ...,
            }
        """
        start_time = time.time()
        # 第3刀: 开启请求级缓存(同次分析内数据不变, 跨股票清空), 减半 Tushare 调用
        enable_cache()
        # 第4刀: 总预算熔断 - 超时后各阶段跳过 LLM 走确定性兜底, 防累积挂死
        deadline = start_time + TOTAL_BUDGET
        state = SharedState(stock_code)

        # Initialize all pipeline variables to safe defaults so that if any
        # stage fails or times out, the result-dict construction still works
        # (no NameError on tech_json/fund_json/news_json, no None dereference).
        tech_json = {}
        fund_json = {}
        news_json = {}
        tech_result = fund_result = news_result = None
        tech_validation = fund_validation = news_validation = None
        debate_result = None
        risk_result = None
        combined = None

        logger.info(f"[Orchestrator] Starting analysis for {stock_code}")

        # Step 1+2: 并行运行技术分析师和基本面分析师
        import concurrent.futures

        logger.info(
            "[Orchestrator] Phase 1: Running technical + fundamentals + news "
            "analysts in parallel..."
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            tech_future = executor.submit(
                self._run_technical_analyst, stock_code, max_iterations
            )
            fund_future = executor.submit(
                self._run_fundamentals_analyst, stock_code, max_iterations
            )
            news_future = executor.submit(
                self._run_news_analyst, stock_code, max_iterations
            )
            results = []
            for future in [tech_future, fund_future, news_future]:
                try:
                    results.append(future.result(timeout=ANALYST_TIMEOUT))
                except concurrent.futures.TimeoutError:
                    logger.error(
                        f"[Orchestrator] Analyst timed out after {ANALYST_TIMEOUT}s, degrading"
                    )
                    results.append({
                        "success": False,
                        "content": "",
                        "structured_output": None,
                        "tool_calls": 0,
                        "iterations": 0,
                        "duration_ms": ANALYST_TIMEOUT * 1000,
                        "error": f"Analyst timeout after {ANALYST_TIMEOUT}s",
                        "error_type": "timeout",
                        "token_usage": None,
                    })
                except Exception as e:
                    logger.error(f"[Orchestrator] Analyst crashed: {e}")
                    results.append({
                        "success": False,
                        "content": "",
                        "structured_output": None,
                        "tool_calls": 0,
                        "iterations": 0,
                        "duration_ms": 0,
                        "error": f"Thread crashed: {e}",
                        "token_usage": None,
                    })
            tech_result, fund_result, news_result = results

        # Retry failed analysts once (API transient errors like 404)
        # Use error_type field (structured) instead of fragile string matching
        for idx, retry_fn in enumerate([
            self._run_technical_analyst,
            self._run_fundamentals_analyst,
            self._run_news_analyst,
        ]):
            result = results[idx]
            error_type = result.get("error_type")
            error_msg = result.get("error") or ""
            is_transient = (
                error_type == "api"
                or "API error" in error_msg
                or "Thread crashed" in error_msg
            )
            if not result["success"] and is_transient:
                label = ["Tech", "Fund", "News"][idx]
                logger.warning(
                    f"[Orchestrator] {label} analyst failed (transient), "
                    f"retrying after 10s cooldown..."
                )
                time.sleep(10)
                try:
                    retried = retry_fn(stock_code, max_iterations)
                    if retried["success"]:
                        logger.info(f"[Orchestrator] {label} analyst retry succeeded")
                        results[idx] = retried
                    else:
                        logger.warning(
                            f"[Orchestrator] {label} analyst retry also failed: "
                            f"{retried.get('error')}"
                        )
                except Exception as e:
                    logger.warning(
                        f"[Orchestrator] {label} analyst retry crashed: {e}"
                    )

        tech_result, fund_result, news_result = results

        state.set("tech_report", tech_result)
        state.set("fund_report", fund_result)
        state.set("news_report", news_result)
        logger.info(
            f"[Orchestrator] All analysts done: "
            f"tech_success={tech_result['success']} "
            f"({tech_result['duration_ms']}ms), "
            f"fund_success={fund_result['success']} "
            f"({fund_result['duration_ms']}ms), "
            f"news_success={news_result['success']} "
            f"({news_result['duration_ms']}ms)"
        )

        # Step 3: 校验报告（优先使用 structured_output，fallback 到文本解析）
        def _validate_report(result: dict, schema_type: str) -> dict:
            structured = result.get("structured_output")
            if structured:
                v = validate_structured_output(structured, schema_type)
                logger.info(f"[Orchestrator] {schema_type}: used structured output (tool submit)")
                return v
            content = result.get("content", "")
            logger.info(f"[Orchestrator] {schema_type}: fell back to text parsing")
            return validate_analyst_output(content, schema_type)

        tech_validation = _validate_report(tech_result, "technical")
        fund_validation = _validate_report(fund_result, "fundamentals")
        news_validation = _validate_report(news_result, "news")

        # Step 4: 提取 JSON 数据
        tech_json = tech_validation.get("json_data") or {}
        fund_json = fund_validation.get("json_data") or {}
        news_json = news_validation.get("json_data") or {}

        # X2 fix: 自动计算 score（LLM 算术容易出错，让 Python 做）
        for _label, _json in [("tech", tech_json), ("fund", fund_json), ("news", news_json)]:
            if _json:
                _breakdown = _json.get("scoring_breakdown", {})
                if _breakdown and (_json.get("score") is None or _json.get("score") == 0):
                    _sum = sum(v for v in _breakdown.values() if isinstance(v, (int, float)))
                    if _label == "news":
                        _json["score"] = max(0, min(100, round(50 + _sum, 1)))
                    else:
                        _n = _EXPECTED_BREAKDOWN_COUNTS.get(_label, len(_breakdown))
                        _max = _n * 10
                        if _max > 0:
                            _json["score"] = round(_sum * 100 / _max, 1)
                    logger.info(
                        f"[Orchestrator] {_label} score auto-calculated: "
                        f"{_json['score']}"
                    )

        # Governance risk score penalty (independent of 14-item scoring_breakdown)
        if fund_json:
            _gov = fund_json.get("governance_risk", "clean")
            if _gov == "critical":
                _orig = fund_json.get("score", 50)
                fund_json["score"] = round(max(0, min(100, _orig * 0.5)), 1)
                logger.warning(
                    f"[Orchestrator] Governance CRITICAL: "
                    f"score {_orig} -> {fund_json['score']}"
                )
            elif _gov == "watch":
                _orig = fund_json.get("score", 50)
                fund_json["score"] = round(max(0, min(100, _orig * 0.75)), 1)
                logger.warning(
                    f"[Orchestrator] Governance WATCH: "
                    f"score {_orig} -> {fund_json['score']}"
                )

        # A3 fix: validate analysis data has actual content (not just empty dict)
        def _is_valid_analysis(json_data: dict) -> bool:
            """Check analysis result has actual content, not just empty shell."""
            if not json_data:
                return False
            score = json_data.get("score")
            if score is None:
                return False
            return bool(json_data.get("scoring_breakdown"))

        # Step 5: 看多/看空辩论 (Phase 2)
        debate_result = None
        if (not skip_debate and time.time() <= deadline
                and _is_valid_analysis(tech_json) and _is_valid_analysis(fund_json)):
            logger.info(
                f"[Orchestrator] Phase 2.5: Starting debate "
                f"(rounds={debate_rounds})..."
            )
            try:
                debate = DebateLoop(self.config, persist_dir=self.persist_dir)
                debate_result = debate.run(
                    stock_code=stock_code,
                    tech_report=tech_json,
                    fund_report=fund_json,
                    max_rounds=debate_rounds,
                    news_report=news_json,
                )
                state.set("bull_args", debate_result.get("bull_arguments", ""))
                state.set("bear_args", debate_result.get("bear_arguments", ""))
                state.set("debate_rounds", debate_result.get("rounds_completed"))
                logger.info(
                    f"[Orchestrator] Debate done: "
                    f"rounds={debate_result.get('rounds_completed')}, "
                    f"duration={debate_result.get('duration_ms')}ms"
                )
            except Exception as e:
                logger.warning(f"[Orchestrator] Debate failed: {e}, continuing without debate")
                debate_result = None
        else:
            logger.info("[Orchestrator] Skipping debate phase")

        # Step 6: 综合汇总
        combined = self._synthesize_reports(tech_json, fund_json, news_json)

        # 如果有辩论结果，附加辩论信息并通过 Research Manager 评估
        if debate_result:
            combined["debate_summary"] = debate_result.get("transcript", "")
            combined["bull_arguments"] = debate_result.get("bull_arguments", "")
            combined["bear_arguments"] = debate_result.get("bear_arguments", "")
            combined["debate_rounds"] = debate_result.get("rounds_completed", 0)

            # 尝试 LLM-based Research Manager
            rm_result = self._run_research_manager(
                stock_code, tech_json, fund_json, debate_result, combined
            )
            if rm_result:
                # 用 LLM 评判结果覆盖确定性评分
                combined["combined_score"] = rm_result.get(
                    "adjusted_score", combined["combined_score"]
                )
                combined["combined_direction"] = rm_result.get(
                    "adjusted_direction", combined["combined_direction"]
                )
                combined["recommendation"] = rm_result.get(
                    "recommendation", combined["recommendation"]
                )
                combined["debate_winner"] = rm_result.get("debate_winner", "draw")
                combined["debate_delta"] = rm_result.get("debate_delta", 0)
                combined["debate_rationale"] = rm_result.get("debate_rationale", "")
                combined["strongest_bull_point"] = rm_result.get(
                    "strongest_bull_point", ""
                )
                combined["strongest_bear_point"] = rm_result.get(
                    "strongest_bear_point", ""
                )
                combined["risk_warnings"] = rm_result.get("risk_warnings", [])
                combined["synthesis_method"] = "llm_research_manager"
                logger.info(
                    f"[Orchestrator] Research Manager: "
                    f"winner={combined['debate_winner']}, "
                    f"delta={combined['debate_delta']}, "
                    f"adjusted_score={combined['combined_score']}"
                )
            else:
                # 降级到 regex 方案
                combined = self._apply_debate_adjustment(combined, debate_result)
                combined["synthesis_method"] = "regex_fallback"
                logger.info("[Orchestrator] Research Manager failed, using regex fallback")
        else:
            combined["synthesis_method"] = "deterministic"

        state.set("research_summary", combined)

        # Step 6a: 风险辩论层 (Phase 4-5)
        risk_result = None
        risk_manager_data = None
        if (debate_result and time.time() <= deadline
                and combined.get("synthesis_method", "") != "deterministic"):
            logger.info("[Orchestrator] Phase 4-5: Running risk debate...")
            try:
                # Phase 4: 三方风险辩论
                debate_formatter = DebateLoop(self.config)
                reports_summary = debate_formatter._format_reports(
                    tech_json, fund_json, news_json
                )
                risk_loop = RiskLoop(self.config)
                risk_result = risk_loop.run(
                    stock_code=stock_code,
                    research_manager_output=combined,
                    reports_summary=reports_summary,
                    max_rounds=1,
                )
                state.set("risk_debate", risk_result)
                logger.info(
                    f"[Orchestrator] Risk debate done: "
                    f"rounds={risk_result.get('rounds_completed')}, "
                    f"duration={risk_result.get('duration_ms')}ms"
                )

                # Phase 5: 风险经理评估
                risk_manager_data = self._run_risk_manager(
                    stock_code, combined, risk_result, reports_summary
                )
                if risk_manager_data:
                    # 用风险经理结果覆盖评分
                    combined["combined_score"] = risk_manager_data.get(
                        "score", combined["combined_score"]
                    )
                    combined["combined_direction"] = risk_manager_data.get(
                        "adjusted_direction", combined["combined_direction"]
                    )
                    combined["risk_level"] = risk_manager_data.get("risk_level", "medium")
                    combined["risk_score"] = risk_manager_data.get("risk_score", 50)
                    combined["risk_winner"] = risk_manager_data.get("risk_winner", "")
                    combined["key_risks"] = risk_manager_data.get("key_risks", [])
                    combined["key_opportunities"] = risk_manager_data.get("key_opportunities", [])
                    combined["position_suggestion"] = risk_manager_data.get("position_suggestion", "")
                    combined["stop_loss_suggestion"] = risk_manager_data.get("stop_loss_suggestion", "")
                    combined["risk_warnings"] = risk_manager_data.get("risk_warnings", [])
                    combined["synthesis_method"] += "_with_risk_manager"
                    logger.info(
                        f"[Orchestrator] Risk Manager: "
                        f"risk_level={combined['risk_level']}, "
                        f"risk_winner={combined['risk_winner']}, "
                        f"adjusted_score={combined['combined_score']}"
                    )
                else:
                    combined["synthesis_method"] += "_risk_manager_failed"
                    logger.info("[Orchestrator] Risk Manager failed, using Research Manager result")
            except Exception as e:
                logger.warning(f"[Orchestrator] Risk layer failed: {e}, continuing without risk adjustment")
                risk_result = None
        else:
            logger.info("[Orchestrator] Skipping risk debate (no Research Manager result)")

        # Update summary with risk-adjusted score
        news_part = ""
        if combined.get("news_score") is not None:
            news_part = f" + 新闻面{combined['news_score']}分({combined.get('news_direction', 'N/A')})"
        combined["summary"] = (
            f"技术面{combined['tech_score']}分({combined['tech_direction']}) + "
            f"基本面{combined['fund_score']}分({combined['fund_direction']})"
            f"{news_part} = "
            f"综合{combined['combined_score']}分({combined['combined_direction']})"
        )

        # Step 6b: Trader 交易决策 (第4刀: 超时跳过 LLM 走确定性兜底)
        if time.time() <= deadline:
            trader_result_data = self._run_trader(
                stock_code, tech_json, fund_json, debate_result, combined,
                news_json=news_json, risk_result=risk_result
            )
        else:
            logger.warning(
                f"[Orchestrator] Total budget {TOTAL_BUDGET}s exceeded before trader "
                f"(elapsed={int(time.time() - start_time)}s), skip to deterministic fallback"
            )
            trader_result_data = None

        # D3: 价值股左侧强制覆盖 - LLM 可能保守漏判, 满足口子强制 buy(全天候生效)
        if trader_result_data:
            trader_result_data, _overridden = self._apply_value_left_override(
                trader_result_data, combined, fund_json
            )
            if _overridden:
                combined["synthesis_method"] = (
                    combined.get("synthesis_method", "") + "_value_left_override"
                )
                logger.info(
                    f"[Orchestrator] 价值股左侧强制覆盖: "
                    f"score={combined.get('combined_score')} + 低PE+好OCF+增持 -> buy(weak)"
                )

        if trader_result_data:
            state.set("decision", trader_result_data["action"])
            state.set("target_price", trader_result_data["target_price"])
            state.set("confidence", trader_result_data["confidence_total"])
            state.set("risk_score", trader_result_data["risk_score"])
            combined["trader"] = trader_result_data
            combined["synthesis_method"] = (
                combined.get("synthesis_method", "unknown") + "_with_trader"
            )
            logger.info(
                f"[Orchestrator] Trader: "
                f"action={trader_result_data['action']}, "
                f"target={trader_result_data['target_price']}, "
                f"confidence={trader_result_data['confidence_total']}, "
                f"risk={trader_result_data['risk_score']}"
            )
        else:
            # 降级: 用确定性规则做简单决策映射
            fallback = self._deterministic_trader_fallback(
                combined, tech_json, fund_json
            )
            state.set("decision", fallback["action"])
            state.set("target_price", fallback["target_price"])
            state.set("confidence", fallback["confidence_total"])
            state.set("risk_score", fallback["risk_score"])
            combined["trader"] = fallback
            combined["synthesis_method"] = (
                combined.get("synthesis_method", "unknown")
                + "_with_deterministic_trader"
            )
            logger.info(
                f"[Orchestrator] Trader fallback: "
                f"action={fallback['action']}, "
                f"target={fallback['target_price']}"
            )

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"[Orchestrator] Analysis complete: "
            f"combined_score={combined.get('combined_score')}, "
            f"direction={combined.get('combined_direction')}, "
            f"decision={state.get('decision')}, "
            f"total_duration={duration_ms}ms"
        )

        # Safe-fallback guards: if any stage was skipped/failed/timed-out,
        # ensure analyst results are dicts (not None) and combined has at least
        # a synthesized report + deterministic trader decision. This guarantees
        # run_analysis always returns a valid result dict.
        if tech_result is None:
            tech_result = {"success": False, "content": "", "tool_calls": 0,
                           "iterations": 0, "duration_ms": 0,
                           "error": "Phase 1 not reached", "token_usage": None}
        if fund_result is None:
            fund_result = {"success": False, "content": "", "tool_calls": 0,
                           "iterations": 0, "duration_ms": 0,
                           "error": "Phase 1 not reached", "token_usage": None}
        if news_result is None:
            news_result = {"success": False, "content": "", "tool_calls": 0,
                           "iterations": 0, "duration_ms": 0,
                           "error": "Phase 1 not reached", "token_usage": None}
        if combined is None:
            combined = self._synthesize_reports(tech_json, fund_json, news_json)
            combined.setdefault("synthesis_method", "deterministic")
            combined["synthesis_method"] = combined["synthesis_method"] + "_timeout_degraded"
        if "trader" not in combined:
            combined["trader"] = self._deterministic_trader_fallback(
                combined, tech_json, fund_json
            )
            combined.setdefault("synthesis_method", "deterministic")
            combined["synthesis_method"] = combined["synthesis_method"] + "_deterministic_trader"

        # C: 诚实降级透传 - 汇总各分析师/阶段降级状态, 让船长在 result.json 一眼看到
        _syn_method = combined.get("synthesis_method") or ""
        degradation_summary = {
            "tech_analyst": tech_result.get("error_type"),
            "fund_analyst": fund_result.get("error_type"),
            "news_analyst": news_result.get("error_type"),
            "synthesis_method": _syn_method,
            "overall_degraded": bool(
                tech_result.get("error_type") or fund_result.get("error_type")
                or news_result.get("error_type")
                or "deterministic" in _syn_method or "regex" in _syn_method
            ),
        }
        result = {
            "stock_code": stock_code,
            "state": state.to_dict(),
            "tech_report": {
                "success": tech_result["success"],
                "content": tech_result.get("content", ""),
                "json_data": tech_json,
                "tool_calls": tech_result["tool_calls"],
                "iterations": tech_result["iterations"],
                "duration_ms": tech_result["duration_ms"],
                "token_usage": tech_result.get("token_usage"),
                "validation": tech_validation,
                "error_type": tech_result.get("error_type"),
            },
            "fund_report": {
                "success": fund_result["success"],
                "content": fund_result.get("content", ""),
                "json_data": fund_json,
                "tool_calls": fund_result["tool_calls"],
                "iterations": fund_result["iterations"],
                "duration_ms": fund_result["duration_ms"],
                "token_usage": fund_result.get("token_usage"),
                "validation": fund_validation,
                "error_type": fund_result.get("error_type"),
            },
            "news_report": {
                "success": news_result["success"],
                "content": news_result.get("content", ""),
                "json_data": news_json,
                "tool_calls": news_result["tool_calls"],
                "iterations": news_result["iterations"],
                "duration_ms": news_result["duration_ms"],
                "token_usage": news_result.get("token_usage"),
                "validation": news_validation,
                "error_type": news_result.get("error_type"),
            },
            "combined_report": combined,
            "degradation_summary": degradation_summary,
            "success": tech_result["success"] and fund_result["success"],
            "duration_ms": duration_ms,
            "error": None,
        }

        if debate_result:
            result["debate_result"] = debate_result

        if risk_result:
            result["risk_result"] = risk_result

        # 第3刀: 关闭缓存(跨股票隔离), 打印命中统计便于验证"调用减半"
        stats = get_cache_stats()
        total = stats["hit"] + stats["miss"]
        hit_rate = (stats["hit"] / total * 100) if total else 0
        logger.info(
            f"[Orchestrator] Cache: hit={stats['hit']}, miss={stats['miss']}, "
            f"hit_rate={hit_rate:.0f}%"
        )
        disable_cache()
        return result

    def _run_technical_analyst(self, stock_code: str, max_iterations: int) -> dict:
        """运行技术分析师"""
        skill_content = load_skill("technical-analyst")
        registry = ToolRegistry()

        registry.register(
            name="get_kline",
            handler=get_kline,
            description="获取股票K线数据，支持多周期（daily/weekly/monthly）",
            parameters={
                "code": {"type": "string", "description": "股票代码"},
                "period": {
                    "type": "string",
                    "description": "K线周期: daily(日线,默认)/weekly(周线)/monthly(月线)",
                },
                "start_date": {
                    "type": "string",
                    "description": "开始日期 YYYYMMDD（可选，默认自动计算约1年）",
                },
                "end_date": {
                    "type": "string",
                    "description": "结束日期 YYYYMMDD（可选，默认今天）",
                },
            },
            required=["code"],
        )
        registry.register(
            name="calc_technical",
            handler=calc_technical,
            description="获取预计算技术指标",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )
        registry.register(
            name="get_daily_basic",
            handler=get_daily_basic,
            description="获取换手率/PE/PB数据",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )
        registry.register(
            name="get_moneyflow",
            handler=get_moneyflow,
            description="获取资金流向数据",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )
        registry.register(
            name="get_index",
            handler=get_index,
            description="获取大盘指数+行业指数对比",
            parameters={
                "index_code": {"type": "string", "description": "指数代码"},
                "stock_code": {"type": "string", "description": "股票代码"},
            },
            required=[],
        )

        messages = [{
            "role": "user",
            "content": (
                f"请分析股票 {stock_code} 的技术面。"
                f"按照工作流程依次调用5个工具获取数据，"
                f"然后按评分锚定表逐项打分，输出完整的技术分析报告。"
            ),
        }]

        submit_tool = get_submit_tool("technical")
        all_tools = registry.get_tools() + [submit_tool]

        # Pre-fetch core data (fallback for hallucination prevention)
        pre_fetched = None
        try:
            pre_fetched = {
                "kline": get_kline(code=stock_code),
                "technical_indicators": calc_technical(code=stock_code),
            }
            logger.info(
                f"[Orchestrator] Technical pre-fetch ready: "
                f"kline={bool(pre_fetched['kline'])}, "
                f"indicators={bool(pre_fetched['technical_indicators'])}"
            )
        except Exception as e:
            logger.warning(f"[Orchestrator] Technical pre-fetch failed: {e}")

        result = self.loop.run(
            system_prompt=skill_content,
            messages=messages,
            tools=all_tools,
            dispatch_map=registry.get_dispatch_map(),
            max_iterations=max_iterations,
            submit_tool_name="submit_analysis",
        )

        # Fallback: inject pre-fetched data if LLM didn't call any tools
        if result.get("tool_calls", 0) == 0 and pre_fetched:
            logger.warning(
                "[Orchestrator] Technical analyst made no tool calls, "
                "injecting pre-fetched data for retry"
            )
            inject_msg = (
                f"以下是预获取的 {stock_code} 技术面数据：\n"
                f"{_truncate_inject_data(pre_fetched)}\n\n"
                f"请基于以上真实数据进行分析，调用 submit_analysis 提交结果。"
            )
            retry_messages = [{"role": "user", "content": inject_msg}]
            result = self.loop.run(
                system_prompt=skill_content,
                messages=retry_messages,
                tools=[submit_tool],
                dispatch_map=None,
                max_iterations=2,
                submit_tool_name="submit_analysis",
            )

        return result

    def _run_fundamentals_analyst(self, stock_code: str, max_iterations: int) -> dict:
        """运行基本面分析师"""
        skill_content = load_skill("fundamentals-analyst")
        registry = ToolRegistry()

        registry.register(
            name="get_financials",
            handler=get_financials,
            description="获取财务报表数据（利润表/资产负债表/现金流量/财务指标）",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )
        registry.register(
            name="get_institutional",
            handler=get_institutional,
            description="获取股东结构数据（前10大股东/股东户数变化）",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )
        registry.register(
            name="get_daily_basic",
            handler=get_daily_basic,
            description="获取估值数据（PE/PB/市值/百分位）",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )
        registry.register(
            name="get_index",
            handler=get_index,
            description="获取行业信息",
            parameters={
                "stock_code": {"type": "string", "description": "股票代码"},
            },
            required=[],
        )
        registry.register(
            name="get_peers",
            handler=get_peers,
            description="获取同行业可比公司对标数据（同行PE/PB/ROE/毛利率对比+行业中位数）",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )
        registry.register(
            name="get_dcf_valuation",
            handler=get_dcf_valuation,
            description=(
                "DCF绝对估值分析（2阶段DCF模型+敏感性分析+PE交叉验证）。"
                "返回内在价值、上涨空间、WACC/增速敏感性表、PEG信号。"
            ),
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )

        messages = [{
            "role": "user",
            "content": (
                f"请分析股票 {stock_code} 的基本面。"
                f"按照工作流程依次调用6个工具获取数据，"
                f"然后按评分锚定表逐项打分，输出完整的基本面分析报告。"
            ),
        }]

        submit_tool = get_submit_tool("fundamentals")
        all_tools = registry.get_tools() + [submit_tool]

        # Pre-fetch core data (fallback for hallucination prevention)
        pre_fetched = None
        try:
            pre_fetched = {
                "financials": get_financials(code=stock_code),
                "governance": get_governance(code=stock_code),
            }
            gov_risk = pre_fetched["governance"].get("governance_risk", "clean")
            logger.info(
                f"[Orchestrator] Fundamentals pre-fetch ready: "
                f"financials={bool(pre_fetched['financials'])}, "
                f"governance={gov_risk}"
            )
        except Exception as e:
            logger.warning(f"[Orchestrator] Fundamentals pre-fetch failed: {e}")

        result = self.loop.run(
            system_prompt=skill_content,
            messages=messages,
            tools=all_tools,
            dispatch_map=registry.get_dispatch_map(),
            max_iterations=max_iterations,
            submit_tool_name="submit_analysis",
        )

        # Fallback: inject pre-fetched data if LLM didn't call any tools
        if result.get("tool_calls", 0) == 0 and pre_fetched:
            logger.warning(
                "[Orchestrator] Fundamentals analyst made no tool calls, "
                "injecting pre-fetched data for retry"
            )
            inject_msg = (
                f"以下是预获取的 {stock_code} 基本面数据：\n"
                f"{_truncate_inject_data(pre_fetched)}\n\n"
                f"请基于以上真实数据进行分析，调用 submit_analysis 提交结果。"
            )
            retry_messages = [{"role": "user", "content": inject_msg}]
            result = self.loop.run(
                system_prompt=skill_content,
                messages=retry_messages,
                tools=[submit_tool],
                dispatch_map=None,
                max_iterations=2,
                submit_tool_name="submit_analysis",
            )

        return result

    def _run_news_analyst(self, stock_code: str, max_iterations: int) -> dict:
        """运行新闻分析师"""
        skill_content = load_skill("news-analyst")
        registry = ToolRegistry()

        registry.register(
            name="get_stock_news",
            handler=get_stock_news,
            description="获取个股新闻资讯 + 市场情绪数据",
            parameters={"code": {"type": "string", "description": "股票代码"}},
            required=["code"],
        )

        messages = [{
            "role": "user",
            "content": (
                f"请分析股票 {stock_code} 的新闻面。"
                f"调用 get_stock_news 获取新闻数据和情绪指标，"
                f"然后按评分锚定表逐条分析，输出完整的新闻分析报告。"
            ),
        }]

        submit_tool = get_submit_tool("news")
        all_tools = registry.get_tools() + [submit_tool]

        # Pre-fetch news data (fallback for hallucination prevention)
        pre_fetched = None
        try:
            pre_fetched = get_stock_news(code=stock_code)
            logger.info(
                f"[Orchestrator] News pre-fetch: "
                f"{pre_fetched.get('count', 0)} articles"
            )
        except Exception as e:
            logger.warning(f"[Orchestrator] News pre-fetch failed: {e}")

        result = self.loop.run(
            system_prompt=skill_content,
            messages=messages,
            tools=all_tools,
            dispatch_map=registry.get_dispatch_map(),
            max_iterations=max_iterations,
            submit_tool_name="submit_analysis",
        )

        # Fallback: inject pre-fetched data if LLM didn't call any tools
        if (
            result.get("tool_calls", 0) == 0
            and pre_fetched
            and pre_fetched.get("ok")
        ):
            logger.warning(
                "[Orchestrator] News analyst made no tool calls, "
                "injecting pre-fetched data for retry"
            )
            inject_msg = (
                f"以下是预获取的 {stock_code} 新闻数据：\n"
                f"{_truncate_inject_data(pre_fetched)}\n\n"
                f"请基于以上真实数据进行分析，调用 submit_analysis 提交结果。"
            )
            retry_messages = [{"role": "user", "content": inject_msg}]
            result = self.loop.run(
                system_prompt=skill_content,
                messages=retry_messages,
                tools=[submit_tool],
                dispatch_map=None,
                max_iterations=2,
                submit_tool_name="submit_analysis",
            )

        return result

    def _synthesize_reports(self, tech_json: dict, fund_json: dict, news_json: dict | None = None) -> dict:
        """
        确定性汇总: 综合技术面 + 基本面 + 新闻评分

        D3: 权重按股票类型动态调整
        新闻分析师权重15%, 从技术/基本面各扣7.5%
        """
        tech_score = tech_json.get("score", 50)
        fund_score = fund_json.get("score", 50)
        news_score = (news_json or {}).get("score", 50) if news_json else 50
        has_news = bool(news_json and news_json.get("score") is not None)

        # D3: 股票类型分类 → 动态权重
        stock_type = _classify_stock(
            industry=_get_industry_from_report(fund_json, tech_json),
            roe=_extract_scoring_value(fund_json, "profitability_roe"),
            net_margin=_extract_scoring_value(fund_json, "profitability_margin"),
            revenue_growth=_extract_scoring_value(fund_json, "growth_revenue"),
        )
        tech_w, fund_w = _get_stock_type_weights(stock_type)

        # 新闻分析师权重15%, 从技术/基本面各扣7.5%
        news_w = 0.15 if has_news else 0
        tech_w_adj = tech_w - (0.075 if has_news else 0)
        fund_w_adj = fund_w - (0.075 if has_news else 0)

        combined_score = round(
            tech_score * tech_w_adj + fund_score * fund_w_adj + news_score * news_w, 1
        )

        # 方向判断 — 统一为 bullish/bearish/neutral 用于对齐检查
        tech_dir = tech_json.get("direction", "neutral")
        fund_dir_raw = fund_json.get("verdict", "neutral")
        # 基本面支持5级，映射到3级用于和技术面比对
        if fund_dir_raw in ("strong_bullish", "bullish"):
            fund_dir = "bullish"
        elif fund_dir_raw in ("strong_bearish", "bearish"):
            fund_dir = "bearish"
        else:
            fund_dir = "neutral"

        if tech_dir == "bullish" and fund_dir == "bullish":
            combined_direction = "strong_bullish"
        elif tech_dir == "bullish" or fund_dir == "bullish":
            combined_direction = "bullish"
        elif tech_dir == "bearish" and fund_dir == "bearish":
            combined_direction = "strong_bearish"
        elif tech_dir == "bearish" or fund_dir == "bearish":
            combined_direction = "bearish"
        else:
            combined_direction = "neutral"

        # 信号一致性
        alignment = "aligned" if tech_dir == fund_dir else "divergent"

        # 建议生成
        recommendation = _generate_recommendation(
            combined_score, combined_direction, alignment
        )

        return {
            "combined_score": combined_score,
            "combined_direction": combined_direction,
            "tech_score": tech_score,
            "tech_direction": tech_dir,
            "fund_score": fund_score,
            "fund_direction": fund_dir,
            "news_score": news_score if has_news else None,
            "news_direction": (news_json or {}).get("direction") if has_news else None,
            "alignment": alignment,
            "tech_scoring_breakdown": tech_json.get("scoring_breakdown", {}),
            "fund_scoring_breakdown": fund_json.get("scoring_breakdown", {}),
            "news_scoring_breakdown": (news_json or {}).get("scoring_breakdown", {}) if has_news else {},
            "tech_data_freshness": tech_json.get("data_freshness", {}),
            "fund_data_freshness": fund_json.get("data_freshness", {}),
            "news_data_freshness": (news_json or {}).get("data_freshness", {}) if has_news else {},
            "tech_key_observations": tech_json.get("key_observations", []),
            "fund_key_strengths": fund_json.get("key_strengths", []),
            "fund_key_risks": fund_json.get("key_risks", []),
            "news_key_events": (news_json or {}).get("key_events", []) if has_news else [],
            "news_risk_events": (news_json or {}).get("risk_events", []) if has_news else [],
            "recommendation": recommendation,
            "stock_type": stock_type,
            "weight_rationale": (
                f"股票类型: {stock_type}, "
                f"技术面权重: {tech_w_adj:.0%}, 基本面权重: {fund_w_adj:.0%}"
                + (f", 新闻面权重: {news_w:.0%}" if has_news else "")
            ),
            "summary": (
                f"技术面{tech_score}分({tech_dir}) + "
                f"基本面{fund_score}分({fund_dir})"
                + (f" + 新闻面{news_score}分({(news_json or {}).get('direction', 'N/A')})" if has_news else "")
                + f" = 综合{combined_score}分({combined_direction})"
            ),
        }

    def _run_research_manager(
        self,
        stock_code: str,
        tech_json: dict,
        fund_json: dict,
        debate_result: dict,
        baseline_combined: dict,
    ) -> dict | None:
        """
        LLM-based Research Manager: 评估辩论质量并调整评分。

        Args:
            stock_code: 股票代码
            tech_json: 技术分析师结构化输出
            fund_json: 基本面分析师结构化输出
            debate_result: 辩论结果
            baseline_combined: 确定性基准综合报告

        Returns:
            Research Manager 的 JSON 输出，失败时返回 None
        """
        try:
            skill_content = load_skill("research-manager")
        except Exception as e:
            logger.warning(f"[Orchestrator] Failed to load research-manager skill: {e}")
            return None

        # 格式化输入数据
        debate_transcript = debate_result.get("transcript", "")
        debate_formatter = DebateLoop(self.config)
        reports_summary = debate_formatter._format_reports(tech_json, fund_json)

        baseline_score = baseline_combined.get("combined_score", 50)
        baseline_dir = baseline_combined.get("combined_direction", "neutral")
        tech_score = baseline_combined.get("tech_score", 50)
        fund_score = baseline_combined.get("fund_score", 50)
        news_score = baseline_combined.get("news_score")

        user_message = (
            f"股票: {stock_code}\n\n"
            f"=== 分析师报告摘要 ===\n{reports_summary}\n\n"
            f"=== 辩论记录 ===\n{debate_transcript}\n\n"
            f"=== 确定性基准评分 ===\n"
            f"技术面评分: {tech_score}\n"
            f"基本面评分: {fund_score}\n"
            + (f"新闻面评分: {news_score}\n" if news_score is not None else "")
            + f"基准综合分: {baseline_score}\n"
            f"基准方向: {baseline_dir}\n\n"
            f"请基于辩论记录评判胜负，调整评分和方向，输出 JSON。"
        )

        messages = [{"role": "user", "content": user_message}]

        submit_tool = get_submit_tool("research_manager")

        result = self.loop.run(
            system_prompt=skill_content,
            messages=messages,
            tools=[submit_tool],
            dispatch_map=None,
            max_iterations=2,
            submit_tool_name="submit_analysis",
        )

        # Retry once on transient API failure
        if not result["success"] and result.get("error_type") == "api":
            logger.warning("[Orchestrator] Research Manager API failed, retrying in 10s...")
            time.sleep(10)
            result = self.loop.run(
                system_prompt=skill_content,
                messages=[{"role": "user", "content": user_message}],
                tools=[submit_tool],
                dispatch_map=None,
                max_iterations=2,
                submit_tool_name="submit_analysis",
            )

        if not result["success"]:
            logger.warning(
                f"[Orchestrator] Research Manager LLM failed: {result.get('error')}"
            )
            return None

        structured = result.get("structured_output")
        if structured:
            validation = validate_research_manager_structured(structured)
            logger.info("[Orchestrator] Research Manager: used structured output")
        else:
            content = result.get("content", "")
            validation = validate_research_manager_output(content)
            logger.info("[Orchestrator] Research Manager: fell back to text parsing")

        if not validation["valid"]:
            logger.warning(
                f"[Orchestrator] Research Manager output invalid: "
                f"{validation['errors']}"
            )
            return None

        return validation["json_data"]

    def _apply_debate_adjustment(
        self, combined: dict, debate_result: dict
    ) -> dict:
        """
        根据辩论强度调整综合评分 (过渡方案)

        启发式: 统计双方引用的独特数据点数量，数量多的一方
        通常论据更充分。调整幅度限制在 [-5, +5] 分。

        注意: 这将在 Research Manager 上线后被替代。
        """
        import re

        bull = debate_result.get("bull_arguments", "")
        bear = debate_result.get("bear_arguments", "")
        if not bull or not bear:
            combined["debate_winner"] = "draw"
            combined["debate_delta"] = 0
            return combined

        # 提取数字型论据 (百分比、倍数、金额等)
        num_pattern = re.compile(r"\d+\.?\d*")

        bull_nums = set(num_pattern.findall(bull))
        bear_nums = set(num_pattern.findall(bear))

        # 独有数据点 = 自有数字 - 对方也引用的数字
        bull_unique = bull_nums - bear_nums
        bear_unique = bear_nums - bull_nums

        # 基于独立论据数量差异计算调整值
        diff = len(bull_unique) - len(bear_unique)
        delta = max(-5, min(5, diff))

        combined["combined_score"] = round(
            max(0, min(100, combined["combined_score"] + delta)), 1
        )
        combined["debate_winner"] = (
            "bull" if delta > 0 else "bear" if delta < 0 else "draw"
        )
        combined["debate_delta"] = delta
        combined["debate_bull_unique_points"] = len(bull_unique)
        combined["debate_bear_unique_points"] = len(bear_unique)

        logger.info(
            f"[Orchestrator] Debate adjustment: "
            f"delta={delta}, winner={combined['debate_winner']}, "
            f"bull_unique={len(bull_unique)}, bear_unique={len(bear_unique)}"
        )
        return combined

    def _run_risk_manager(
        self,
        stock_code: str,
        combined: dict,
        risk_result: dict,
        reports_summary: str,
    ) -> dict | None:
        """
        LLM-based Risk Manager: 评估三方风险辩论，输出风险等级和评分调整。

        Returns:
            Risk Manager 的 JSON 输出，失败时返回 None
        """
        try:
            skill_content = load_skill("risk-manager")
        except Exception as e:
            logger.warning(f"[Orchestrator] Failed to load risk-manager skill: {e}")
            return None

        risk_transcript = risk_result.get("transcript", "")
        baseline_score = combined.get("combined_score", 50)
        baseline_dir = combined.get("combined_direction", "neutral")
        risk_level = combined.get("risk_level", "N/A")

        user_message = (
            f"股票: {stock_code}\n\n"
            f"=== 研究经理综合研判 ===\n"
            f"综合评分: {baseline_score}\n"
            f"综合方向: {baseline_dir}\n"
            f"辩论胜方: {combined.get('debate_winner', 'N/A')}\n"
            f"风险等级(当前): {risk_level}\n\n"
            f"=== 分析师报告摘要 ===\n{reports_summary}\n\n"
            f"=== 风险辩论记录 ===\n{risk_transcript}\n\n"
            f"请评估三方风险辩论，输出风险等级和评分调整建议。"
        )

        messages = [{"role": "user", "content": user_message}]
        submit_tool = get_submit_tool("risk_manager")

        result = self.loop.run(
            system_prompt=skill_content,
            messages=messages,
            tools=[submit_tool],
            dispatch_map=None,
            max_iterations=2,
            submit_tool_name="submit_analysis",
        )

        # Retry once on transient API failure
        if not result["success"] and result.get("error_type") == "api":
            logger.warning("[Orchestrator] Risk Manager API failed, retrying in 10s...")
            time.sleep(10)
            result = self.loop.run(
                system_prompt=skill_content,
                messages=[{"role": "user", "content": user_message}],
                tools=[submit_tool],
                dispatch_map=None,
                max_iterations=2,
                submit_tool_name="submit_analysis",
            )

        if not result["success"]:
            logger.warning(
                f"[Orchestrator] Risk Manager LLM failed: {result.get('error')}"
            )
            return None

        structured = result.get("structured_output")
        if structured:
            validation = validate_risk_manager_structured(structured)
            logger.info("[Orchestrator] Risk Manager: used structured output")
        else:
            logger.warning("[Orchestrator] Risk Manager: no structured output, skipping")
            return None

        if not validation["valid"]:
            logger.warning(
                f"[Orchestrator] Risk Manager output invalid: {validation['errors']}"
            )
            json_data = validation.get("json_data")
            if json_data and json_data.get("risk_level") and json_data.get("risk_score"):
                logger.info("[Orchestrator] Risk Manager has errors but core fields present, using it")
                return json_data
            return None

        return validation["json_data"]

    @staticmethod
    def _extract_target_price(data: dict):
        """提取目标价: 如果是字典取 value，如果是数字直接返回"""
        tp = data.get("target_price")
        if tp is None:
            return 0
        if isinstance(tp, dict):
            return tp.get("value", 0)
        if isinstance(tp, (int, float)):
            return tp
        return 0

    @staticmethod
    def _extract_current_price(fund_json: dict, tech_json: dict):
        """从基本面或技术面提取当前股价"""
        # 1. 优先从基本面提取
        tp = fund_json.get("target_price")
        if isinstance(tp, dict) and tp.get("current_price"):
            return tp["current_price"]
        # 2. 兜底从技术面 latest_close 提取
        lc = tech_json.get("latest_close")
        if isinstance(lc, (int, float)) and lc > 0:
            return lc
        return None

    @staticmethod
    def _format_fund_target_price(fund_json: dict) -> str:
        """格式化基本面目标价: 展开字典，不 dump 原始对象"""
        tp = fund_json.get("target_price", {})
        if isinstance(tp, dict):
            lines = [f"目标价: {tp.get('value', 'N/A')}元"]
            if tp.get("current_price"):
                lines.append(f"当前价: {tp['current_price']}元")
            if tp.get("potential_upside_pct") is not None:
                lines.append(f"上涨空间: {tp['potential_upside_pct']}%")
            if tp.get("weighted_calculation"):
                lines.append(f"推导方法: {tp['weighted_calculation']}")
            return "\n".join(lines)
        return f"目标价: {tp}"

    def _run_trader(
        self,
        stock_code: str,
        tech_json: dict,
        fund_json: dict,
        debate_result: dict | None,
        combined: dict,
        news_json: dict | None = None,
        risk_result: dict | None = None,
    ) -> dict | None:
        """
        LLM-based Trader: 将综合研判转化为可执行交易决策。

        Args:
            stock_code: 股票代码
            tech_json: 技术分析师结构化输出
            fund_json: 基本面分析师结构化输出
            debate_result: 辩论结果（可能为 None）
            combined: 综合报告（含 Research Manager 评判 + 风险经理调整）
            news_json: 新闻分析师结构化输出（可能为 None）
            risk_result: 风险辩论结果（可能为 None）

        Returns:
            Trader 的 JSON 输出，失败时返回 None
        """
        try:
            skill_content = load_skill("trader")
        except Exception as e:
            logger.warning(f"[Orchestrator] Failed to load trader skill: {e}")
            return None

        # 格式化输入数据
        # P1 fix: 传完整 JSON 而非手工挑选字段，避免信息丢失

        # 1. Research Manager 综合研判
        rm_summary = (
            f"综合评分: {combined.get('combined_score', 'N/A')}\n"
            f"综合方向: {combined.get('combined_direction', 'N/A')}\n"
            f"辩论胜方: {combined.get('debate_winner', 'N/A')}\n"
            f"辩论delta: {combined.get('debate_delta', 0)}\n"
            f"辩论理由: {combined.get('debate_rationale', 'N/A')}\n"
            f"看多最强论点: {combined.get('strongest_bull_point', 'N/A')}\n"
            f"看空最强论点: {combined.get('strongest_bear_point', 'N/A')}\n"
            f"投资建议: {combined.get('recommendation', 'N/A')}\n"
            f"风险提示: {combined.get('risk_warnings', [])}"
        )

        # 2. 当前股价（必须在场景分析之前提取）
        current_price = self._extract_current_price(fund_json, tech_json)
        current_price_str = f"{current_price}" if current_price else "N/A"

        # 3. 技术面完整JSON（而非手工挑选字段）
        _safe_json = lambda d: json.dumps(d, ensure_ascii=False, default=str) if d else "{}"
        tech_summary = f"技术面完整分析:\n{_safe_json(tech_json)}"

        # 4. 基本面完整JSON + 场景分析警告
        scenario = fund_json.get("scenario_analysis", {})
        scenario_str = ""
        if scenario:
            bull_tp = scenario.get("bull", {}).get("target_price", "N/A")
            base_tp = scenario.get("base", {}).get("target_price", "N/A")
            bear_tp = scenario.get("bear", {}).get("target_price", "N/A")
            scenario_str = f"\n场景分析: 乐观{bull_tp}元 / 中性{base_tp}元 / 悲观{bear_tp}元"
            if current_price:
                _all_prices = [p for p in [bull_tp, base_tp, bear_tp] if isinstance(p, (int, float))]
                if _all_prices and all(p < current_price for p in _all_prices):
                    scenario_str += (
                        f"\n[警告] 所有场景目标价均低于当前价{current_price}元，"
                        f"基本面认为当前严重高估。交易目标价应结合技术面信号调整，"
                        f"建议考虑watch（观望）"
                    )
                elif _all_prices and all(p > current_price for p in _all_prices):
                    scenario_str += (
                        f"\n[警告] 所有场景目标价均高于当前价{current_price}元，"
                        f"基本面认为当前低估。但需结合技术面确认趋势方向。"
                    )

        fund_summary = f"基本面完整分析:\n{_safe_json(fund_json)}"
        if scenario_str:
            fund_summary += f"\n{scenario_str}"

        # 5. 辩论摘要（传全文，不截断）
        debate_summary = ""
        if debate_result:
            debate_summary = (
                f"看多论点: {debate_result.get('bull_arguments', 'N/A')}\n\n"
                f"看空论点: {debate_result.get('bear_arguments', 'N/A')}"
            )
        else:
            debate_summary = "无辩论数据"

        # 6. 新闻分析完整JSON
        news_summary = f"新闻面完整分析:\n{_safe_json(news_json)}" if news_json else "无新闻数据"

        # 7. 股票类型与权重
        stock_type_info = combined.get("weight_rationale", "未分类，使用默认50/50权重")

        # 8. 风险辩论结果（如果有）
        risk_summary = "无风险辩论数据"
        if risk_result:
            risk_parts = []
            if risk_result.get("aggressive_arguments"):
                risk_parts.append(f"激进方: {risk_result['aggressive_arguments'][:500]}")
            if risk_result.get("conservative_arguments"):
                risk_parts.append(f"保守方: {risk_result['conservative_arguments'][:500]}")
            if risk_result.get("neutral_arguments"):
                risk_parts.append(f"中性方: {risk_result['neutral_arguments'][:500]}")
            risk_summary = "\n".join(risk_parts)
            if combined.get("risk_level"):
                risk_summary += (
                    f"\n\n风险经理结论: 风险等级={combined['risk_level']}, "
                    f"风险评分={combined.get('risk_score', 'N/A')}, "
                    f"仓位建议={combined.get('position_suggestion', 'N/A')}, "
                    f"止损建议={combined.get('stop_loss_suggestion', 'N/A')}"
                )

        user_message = (
            f"股票: {stock_code}\n"
            f"当前股价: {current_price_str}元\n\n"
            f"=== Research Manager 综合研判 ===\n{rm_summary}\n\n"
            f"=== 技术面分析 ===\n{tech_summary}\n\n"
            f"=== 基本面分析 ===\n{fund_summary}\n\n"
            + (f"=== 新闻面分析 ===\n{news_summary}\n\n" if news_summary else "")
            + f"=== 辩论摘要 ===\n{debate_summary}\n\n"
            + (f"=== 风险辩论结论 ===\n{risk_summary}\n\n" if risk_result else "")
            + f"=== 股票类型 ===\n{stock_type_info}\n\n"
            f"请基于以上综合研判，做出可执行的交易决策，输出 JSON。"
        )

        # Governance risk escalation warning for trader
        _gov_risk = fund_json.get("governance_risk", "")
        _st_status = fund_json.get("st_status", "")
        if _gov_risk in ("critical", "watch") or _st_status in ("ST", "*ST"):
            _gov_reason = fund_json.get("governance_risk_reason", "") or fund_json.get("st_reason", "")
            _gov_events = fund_json.get("governance_events", [])
            user_message += (
                f"\n\n=== 治理风险升级警告 ===\n"
                f"治理风险等级: {_gov_risk or 'unknown'}\n"
                f"ST状态: {_st_status or 'unknown'}\n"
                f"风险原因: {_gov_reason}\n"
            )
            if _gov_events:
                user_message += f"风险事件: {', '.join(str(e) for e in _gov_events[:5])}\n"
            user_message += (
                "强烈建议 action=watch 或 action=sell，除非有明确的重组/摘帽预期。"
            )

        messages = [{"role": "user", "content": user_message}]

        submit_tool = get_submit_tool("trader")

        result = self.loop.run(
            system_prompt=skill_content,
            messages=messages,
            tools=[submit_tool],
            dispatch_map=None,
            max_iterations=2,
            submit_tool_name="submit_analysis",
        )

        # Retry once on transient API failure
        if not result["success"] and result.get("error_type") == "api":
            logger.warning("[Orchestrator] Trader API failed, retrying in 10s...")
            time.sleep(10)
            result = self.loop.run(
                system_prompt=skill_content,
                messages=[{"role": "user", "content": user_message}],
                tools=[submit_tool],
                dispatch_map=None,
                max_iterations=2,
                submit_tool_name="submit_analysis",
            )

        if not result["success"]:
            logger.warning(
                f"[Orchestrator] Trader LLM failed: {result.get('error')}"
            )
            return None

        structured = result.get("structured_output")
        if structured:
            # F7 fix: 注入 _current_price 到 validation 之前
            if current_price:
                structured["_current_price"] = current_price
            validation = validate_trader_structured(structured)
            logger.info("[Orchestrator] Trader: used structured output")
        else:
            content = result.get("content", "")
            validation = validate_trader_output(content)
            logger.info("[Orchestrator] Trader: fell back to text parsing")

        if not validation["valid"]:
            logger.warning(
                f"[Orchestrator] Trader output invalid: {validation['errors']}"
            )
            # 即使有 errors，如果 json_data 存在且核心字段在，仍然使用
            json_data = validation.get("json_data")
            if json_data and json_data.get("action") and json_data.get("target_price"):
                logger.info("[Orchestrator] Trader output has errors but core fields present, using it")
                # _current_price 已在 validation 前注入
                return json_data
            return None

        result = validation["json_data"]
        # _current_price 已在 validation 前注入
        return result

    def _apply_value_left_override(self, trader_data, combined, fund_json):
        """D3: 价值股左侧强制覆盖。满足口子5条件(value+低PE+好OCF+增持+够分)则强制 buy(weak)。

        LLM trader 在 direction neutral 时可能保守漏判，此方法确保价值口子全天候生效
        (不只 fallback 路径)。返回 (trader_data, overridden: bool)。
        """
        if not trader_data or trader_data.get("action") == "buy":
            return trader_data, False
        if (
            combined.get("stock_type") == "value"
            and isinstance(fund_json.get("pe_ttm"), (int, float))
            and 0 < fund_json.get("pe_ttm") <= 30
            and isinstance(fund_json.get("ocf_to_np_ratio"), (int, float))
            and fund_json.get("ocf_to_np_ratio") >= 1.0
            and fund_json.get("insider_signal") in ("net_buy", "leaning_buy")
            and combined.get("combined_score", 0) >= 52
        ):
            trader_data["action"] = "buy"
            trader_data["action_strength"] = "weak"
            return trader_data, True
        return trader_data, False

    def _deterministic_trader_fallback(
        self, combined: dict, tech_json: dict, fund_json: dict
    ) -> dict:
        """
        确定性 Trader 降级方案: 用规则映射生成交易决策。

        当 LLM 调用失败时使用。
        """
        score = combined.get("combined_score", 50)
        direction = combined.get("combined_direction", "neutral")
        winner = combined.get("debate_winner", "draw")

        # D3: 价值股左侧口子 - 低PE+好现金流+机构增持+分数够, 不依赖 direction bullish(左侧逆势)
        # 多重AND精准挡题材股: 有研新材PE116/OCF-13.8x 不满足 PE<=30 或 OCF>=1.0
        is_value_left = (
            combined.get("stock_type") == "value"
            and isinstance(fund_json.get("pe_ttm"), (int, float))
            and 0 < fund_json.get("pe_ttm") <= 30
            and isinstance(fund_json.get("ocf_to_np_ratio"), (int, float))
            and fund_json.get("ocf_to_np_ratio") >= 1.0
            and fund_json.get("insider_signal") in ("net_buy", "leaning_buy")
        )

        # 1. action 决策
        if is_value_left and score >= 52:
            action = "buy"
            strength = "weak"
        elif score >= 75 and "bullish" in direction:
            action = "buy"
            strength = "strong" if score >= 85 else "normal"
        elif score >= 60 and "bullish" in direction:
            action = "buy"
            strength = "weak"
        elif score <= 25 and "bearish" in direction:
            action = "sell"
            strength = "strong" if score <= 15 else "normal"
        elif score <= 40 and "bearish" in direction:
            action = "sell"
            strength = "weak"
        elif 30 <= score < 45 and winner == "draw" and "neutral" in direction:
            action = "watch"
            strength = "normal"
        else:
            action = "hold"
            strength = "normal"

        # 2. 目标价: 技术面和基本面的加权（辩论胜方影响权重）
        tech_target = tech_json.get("target_price", 0)
        if not isinstance(tech_target, (int, float)):
            tech_target = 0
        fund_target = self._extract_target_price(fund_json)

        # D3: use dynamic weights based on stock type
        stock_type_fb = _classify_stock(
            industry=_get_industry_from_report(fund_json, tech_json),
            roe=_extract_scoring_value(fund_json, "profitability_roe"),
            net_margin=_extract_scoring_value(fund_json, "profitability_margin"),
            revenue_growth=_extract_scoring_value(fund_json, "growth_revenue"),
        )
        fb_tech_w, fb_fund_w = _get_stock_type_weights(stock_type_fb)

        if tech_target and fund_target:
            if winner == "bull":
                # Bull wins: lean towards higher target (fund side heavier)
                target_price = round(tech_target * fb_fund_w + fund_target * fb_tech_w, 2)
            elif winner == "bear":
                # Bear wins: lean towards lower target (tech side heavier)
                target_price = round(tech_target * fb_tech_w + fund_target * fb_fund_w, 2)
            else:
                target_price = round(tech_target * fb_tech_w + fund_target * fb_fund_w, 2)
        else:
            target_price = tech_target or fund_target or 0

        # 3. 止损: 买入用做多止损/支撑位，卖出用做空止损/阻力位
        if action == "sell":
            # 卖出止损: 价格涨破止损位时止损（止损价 > 当前价）
            stop_loss = (
                tech_json.get("stop_loss_sell")
                or tech_json.get("strong_resistance")
            )
            if stop_loss is None and target_price:
                stop_loss = round(target_price * 1.1, 2)
        else:
            # 买入/持有止损: 价格跌破止损位时止损（止损价 < 当前价）
            stop_loss = (
                tech_json.get("stop_loss_price")
                or tech_json.get("strong_support")
            )
            if stop_loss is None and target_price:
                stop_loss = round(target_price * 0.9, 2)

        # 4. 置信度: 综合评分 + 方向一致性调整
        tech_dir = tech_json.get("direction", "neutral")
        fund_dir_raw = fund_json.get("verdict", "neutral")
        if fund_dir_raw in ("strong_bullish", "bullish"):
            fund_dir = "bullish"
        elif fund_dir_raw in ("strong_bearish", "bearish"):
            fund_dir = "bearish"
        else:
            fund_dir = "neutral"

        # 组件化评分（确定性版本）
        signal_consistency = 16 if tech_dir == fund_dir else 8
        # 根据实际数据是否有效来打分（B6 修复）
        has_tech = bool(tech_json and tech_json.get("score"))
        has_fund = bool(fund_json and fund_json.get("score"))
        if has_tech and has_fund:
            data_sufficiency = 16
        elif has_tech or has_fund:
            data_sufficiency = 8
        else:
            data_sufficiency = 2
        debate_certainty = 16 if winner in ("bull", "bear") else 10
        # 盈亏比检查
        ratio_str = tech_json.get("risk_reward_ratio", "")
        if ":" in str(ratio_str):
            try:
                reward_part = float(str(ratio_str).split(":")[1])
                risk_controllability = 16 if reward_part >= 2.0 else 8
            except (ValueError, IndexError):
                risk_controllability = 10
        else:
            risk_controllability = 10
        # 估值合理性
        valuation_grade = fund_json.get("valuation_grade", "fair")
        valuation_reasonableness = (
            16 if valuation_grade == "undervalued"
            else 12 if valuation_grade == "fair"
            else 6
        )

        confidence_total = (
            signal_consistency + data_sufficiency
            + debate_certainty + risk_controllability
            + valuation_reasonableness
        )

        # 5. 风险评分: 100 - 置信度
        risk_score = 100 - confidence_total

        # 6. 标签映射
        if confidence_total >= 80:
            conf_label, pos_advice, pos_range = "very_high", "heavy", "70-100%"
        elif confidence_total >= 60:
            conf_label, pos_advice, pos_range = "high", "standard", "40-70%"
        elif confidence_total >= 40:
            conf_label, pos_advice, pos_range = "medium", "light", "20-40%"
        elif confidence_total >= 20:
            conf_label, pos_advice, pos_range = "low", "watch", "0%"
        else:
            conf_label, pos_advice, pos_range = "very_low", "watch", "0%"

        if risk_score >= 80:
            risk_level = "very_high"
        elif risk_score >= 60:
            risk_level = "high"
        elif risk_score >= 40:
            risk_level = "medium"
        elif risk_score >= 20:
            risk_level = "low"
        else:
            risk_level = "very_low"

        return {
            "action": action,
            "action_strength": strength,
            "target_price": target_price,
            "target_price_rationale": (
                f"确定性降级方案: 技术面目标价{tech_target} + "
                f"基本面目标价{fund_target}，辩论胜方={winner}"
            ),
            "stop_loss": stop_loss,
            "stop_loss_rationale": (
                f"确定性降级方案: "
                f"{'做空止损(stop_loss_sell)/强阻力位' if action == 'sell' else '做多止损(stop_loss_price)/强支撑位'}"
            ),
            "take_profit_levels": [],
            "confidence_components": {
                "signal_consistency": signal_consistency,
                "data_sufficiency": data_sufficiency,
                "debate_certainty": debate_certainty,
                "risk_controllability": risk_controllability,
                "valuation_reasonableness": valuation_reasonableness,
            },
            "confidence_total": confidence_total,
            "confidence_label": conf_label,
            "position_advice": pos_advice,
            "position_range": pos_range,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "time_horizon": "1-3月",
            "entry_conditions": [],
            "key_catalysts": [],
            "reasoning": (
                f"确定性降级方案: 综合评分{score}分，方向{direction}，"
                f"辩论胜方{winner}。action={action}，目标价={target_price}"
            ),
            "warnings": combined.get("risk_warnings", []),
            "synthesis_method": "deterministic_fallback",
        }


# --- D3: Stock Type Classification and Dynamic Weights ---

CYCLICAL_INDUSTRIES = {
    "钢铁", "有色金属", "采掘", "化工", "基础化工",
    "建筑材料", "建筑装饰", "煤炭", "石油石化", "造纸",
}


def _classify_stock(
    industry: str = "",
    roe: float = 0,
    net_margin: float = 0,
    revenue_growth: float = 0,
) -> str:
    """
    Classify stock into 4 types: growth / value / cyclical / quality.

    Priority: cyclical > quality > growth > value (special to general)

    Note: roe/net_margin/revenue_growth are scoring_breakdown values (0-10 scale).
    Thresholds are adjusted accordingly.
    """
    # 1. Cyclical: industry match
    if industry and industry in CYCLICAL_INDUSTRIES:
        return "cyclical"

    # 2. Quality: high ROE score + high margin score + low growth score
    # scoring_breakdown scale: 0-10, so >=8 is excellent
    if roe >= 8 and net_margin >= 8 and revenue_growth < 7:
        return "quality"

    # 3. Growth: high revenue growth score
    if revenue_growth >= 7:
        return "growth"

    # 4. Value: default
    return "value"


def _get_stock_type_weights(stock_type: str) -> tuple:
    """Return (tech_weight, fund_weight) based on stock type."""
    weights = {
        "growth":   (0.60, 0.40),
        "value":    (0.35, 0.65),
        "cyclical": (0.70, 0.30),
        "quality":  (0.40, 0.60),
    }
    tech_w, fund_w = weights.get(stock_type, (0.50, 0.50))

    # Safety bounds: neither side below 25% or above 75%
    tech_w = max(0.25, min(0.75, tech_w))
    fund_w = 1.0 - tech_w
    return (tech_w, fund_w)


def _get_industry_from_report(fund_json: dict, tech_json: dict) -> str:
    """Extract industry from analyst reports."""
    # Try fund_json first
    industry_analysis = fund_json.get("industry_analysis", {})
    if isinstance(industry_analysis, dict):
        industry = industry_analysis.get("industry", "")
        if industry:
            return str(industry)
    # Try various field names
    for key in ("industry", "sw_industry", "sector"):
        val = fund_json.get(key) or tech_json.get(key)
        if val:
            return str(val)
    return ""


def _extract_scoring_value(fund_json: dict, metric_key: str) -> float:
    """Extract a scoring breakdown value as a numeric score (0-10 scale)."""
    breakdown = fund_json.get("scoring_breakdown", {})
    if isinstance(breakdown, dict):
        val = breakdown.get(metric_key, 0)
        if isinstance(val, (int, float)):
            return float(val)
    return 0.0


def _generate_recommendation(score: float, direction: str, alignment: str) -> str:
    """根据综合评分和方向生成建议"""
    if score >= 70 and "bullish" in direction and alignment == "aligned":
        return "积极关注（技术面和基本面双重看多）"
    elif score >= 60 and "bullish" in direction:
        return "谨慎看多（关注分歧方向的风险）"
    elif score >= 50:
        return "观望偏多（多空力量接近，等待明确信号）"
    elif score >= 40:
        return "观望（多空分歧较大，等待信号明确）"
    elif score <= 30 and "bearish" in direction and alignment == "aligned":
        return "回避（技术面和基本面双重看空）"
    else:
        return "谨慎观望（偏空但存在分歧）"
