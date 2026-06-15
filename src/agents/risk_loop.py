"""
risk_loop - 三方风险辩论循环

激进/保守/中性三方风险辩手交替发言，从不同风险偏好展开辩论。

流程:
  Round 1: Aggressive -> Conservative -> Neutral (三方依次发言)
  Round 2+: 每方看到前一轮所有人的发言，继续辩论
  达到 max_rounds 后结束

设计原则:
  - 与 debate_loop.py 模式一致（AgentLoop + skill + 纯文本输出）
  - 三方轮流发言，每方都能看到所有历史
  - 输入：研究经理结论 + 分析师原始数据
  - 输出：风险辩论纪要（传给风险经理评估）
"""

import time
import logging

from src.core.agent_loop import AgentLoop
from src.core.skill_loader import load_skill

logger = logging.getLogger(__name__)

# 三方辩论者定义: (skill_name, display_name, position)
RISK_DEBATERS = [
    ("risk-aggressive", "Aggressive", "激进"),
    ("risk-conservative", "Conservative", "保守"),
    ("risk-neutral", "Neutral", "中性"),
]


class RiskLoop:
    """
    三方风险辩论循环

    用法:
        risk_loop = RiskLoop(config)
        result = risk_loop.run(
            stock_code="300033.SZ",
            research_manager_output=rm_json,
            reports_summary="...",
            max_rounds=1,
        )
    """

    def __init__(self, config: dict):
        self.config = config
        self.loop = AgentLoop(config)
        # 辩论历史: list of (debater_name, content)
        self._history: list[tuple[str, str]] = []

    def run(
        self,
        stock_code: str,
        research_manager_output: dict,
        reports_summary: str,
        max_rounds: int = 1,
    ) -> dict:
        """
        运行三方风险辩论

        Args:
            stock_code: 股票代码
            research_manager_output: 研究经理的 JSON 输出
            reports_summary: 分析师报告摘要（来自 debate_loop._format_reports）
            max_rounds: 辩论轮数（默认1轮，三方各发言一次）

        Returns:
            {
                "success": True/False,
                "rounds_completed": N,
                "total_messages": N,
                "aggressive_arguments": "...",
                "conservative_arguments": "...",
                "neutral_arguments": "...",
                "transcript": "完整辩论记录",
                "duration_ms": ...,
                "rounds": [...],
            }
        """
        start_time = time.time()
        self._history = []
        rounds_detail = []

        # 格式化研究经理结论
        rm_summary = self._format_rm_output(research_manager_output)

        logger.info(
            f"[RiskLoop] Starting risk debate for {stock_code}, "
            f"max_rounds={max_rounds}"
        )

        for round_num in range(1, max_rounds + 1):
            round_detail = {"round": round_num}
            logger.info(f"[RiskLoop] === Round {round_num}/{max_rounds} ===")

            for skill_name, display_name, cn_name in RISK_DEBATERS:
                logger.info(
                    f"[RiskLoop] Round {round_num}: "
                    f"{display_name} ({cn_name}) speaking..."
                )

                skill_content = load_skill(skill_name)
                messages = self._build_messages(
                    stock_code, rm_summary, reports_summary,
                    round_num, display_name,
                )

                result = self.loop.run(
                    system_prompt=skill_content,
                    messages=messages,
                    tools=None,
                    max_iterations=1,
                )

                content = result.get("content", f"({display_name} failed)")
                if not result["success"]:
                    logger.warning(
                        f"[RiskLoop] {display_name} failed: "
                        f"{result.get('error')}"
                    )
                    # Retry once
                    result = self.loop.run(
                        system_prompt=skill_content,
                        messages=messages,
                        tools=None,
                        max_iterations=1,
                    )
                    content = result.get("content", f"({display_name} failed)")

                round_detail[display_name.lower()] = {
                    "success": result["success"],
                    "content": content,
                    "duration_ms": result["duration_ms"],
                }

                # 记录到历史
                self._history.append((display_name, content))

            rounds_detail.append(round_detail)

        duration_ms = int((time.time() - start_time) * 1000)

        # 提取每方最后发言
        last_by = {}
        for name, content in self._history:
            last_by[name] = content

        logger.info(
            f"[RiskLoop] Risk debate complete: "
            f"{len(rounds_detail)} rounds, "
            f"{len(self._history)} messages, {duration_ms}ms"
        )

        return {
            "success": any(
                r.get(d.lower(), {}).get("success", False)
                for r in rounds_detail
                for _, d, _ in RISK_DEBATERS
            ),
            "rounds_completed": len(rounds_detail),
            "total_messages": len(self._history),
            "aggressive_arguments": last_by.get("Aggressive", ""),
            "conservative_arguments": last_by.get("Conservative", ""),
            "neutral_arguments": last_by.get("Neutral", ""),
            "transcript": self._format_transcript(),
            "duration_ms": duration_ms,
            "rounds": rounds_detail,
        }

    def _format_rm_output(self, rm: dict) -> str:
        """格式化研究经理输出"""
        if not rm:
            return "无研究经理结论"

        parts = [
            "## 研究经理综合研判",
            f"- 综合评分: {rm.get('adjusted_score', rm.get('score', 'N/A'))}",
            f"- 综合方向: {rm.get('adjusted_direction', 'N/A')}",
            f"- 辩论胜方: {rm.get('debate_winner', 'N/A')}",
            f"- 辩论理由: {rm.get('debate_rationale', 'N/A')}",
            f"- 看多最强论点: {rm.get('strongest_bull_point', 'N/A')}",
            f"- 看空最强论点: {rm.get('strongest_bear_point', 'N/A')}",
            f"- 投资建议: {rm.get('recommendation', 'N/A')}",
        ]

        risk_warnings = rm.get("risk_warnings", [])
        if risk_warnings:
            parts.append("- 风险提示:")
            for w in risk_warnings[:5]:
                parts.append(f"  - {w}")

        summary = rm.get("summary", "")
        if summary:
            parts.append(f"- 总结: {summary}")

        return "\n".join(parts)

    def _build_messages(
        self,
        stock_code: str,
        rm_summary: str,
        reports_summary: str,
        round_num: int,
        debater_name: str,
    ) -> list[dict]:
        """构建辩手输入消息"""
        history_text = self._format_transcript()

        if round_num == 1 and not history_text.strip():
            # 第一轮: 看到研究经理结论 + 分析师报告
            content = (
                f"请为股票 {stock_code} 从{self._get_position(debater_name)}视角进行风险分析。\n\n"
                f"以下是研究经理综合研判:\n\n{rm_summary}\n\n"
                f"以下是分析师报告摘要:\n\n{reports_summary}\n\n"
                f"请基于以上数据，构建你的风险论证。"
            )
        else:
            # 后续轮次: 看到历史辩论 + 继续论证
            content = (
                f"请为股票 {stock_code} 继续风险辩论。\n\n"
                f"以下是研究经理综合研判:\n\n{rm_summary}\n\n"
                f"以下是分析师报告摘要:\n\n{reports_summary}\n\n"
                f"以下是之前的辩论记录:\n\n{history_text}\n\n"
                f"请回应其他辩手的论点，补充新的论证。"
            )

        return [{"role": "user", "content": content}]

    def _get_position(self, debater_name: str) -> str:
        """获取辩手立场描述"""
        positions = {
            "Aggressive": "激进（机会优先）",
            "Conservative": "保守（风控优先）",
            "Neutral": "中性（平衡视角）",
        }
        return positions.get(debater_name, "")

    def _format_transcript(self) -> str:
        """格式化辩论记录"""
        if not self._history:
            return ""
        lines = []
        for name, content in self._history:
            lines.append(f"--- {name} ---")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)
