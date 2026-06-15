"""
message_bus - 智能体间消息传递

轻量级消息总线，支持:
  1. 邮箱模式: send(to, msg) / receive(agent)
  2. 辩论历史: 自动记录所有消息，可格式化为对话记录
  3. JSONL 持久化: 每条消息追加写入日志文件

参考: learn-claude-code s09 的 JSONL 邮箱模式
"""

import json
import time
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class Message:
    """一条消息"""

    def __init__(self, from_agent: str, to_agent: str, content: str,
                 round_num: int = 0, msg_type: str = "debate"):
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.content = content
        self.round_num = round_num
        self.msg_type = msg_type
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "content": self.content,
            "round": self.round_num,
            "type": self.msg_type,
            "timestamp": self.timestamp,
        }

    def __repr__(self):
        return f"Message({self.from_agent} -> {self.to_agent}, round={self.round_num})"


class MessageBus:
    """
    轻量级消息总线

    用法:
        bus = MessageBus(persist_dir="output/debate_logs")

        # 发送消息
        bus.send("bull-debater", "bear-debater", "看多理由...", round_num=1)

        # 接收消息
        msgs = bus.receive("bear-debater")

        # 获取完整辩论记录
        transcript = bus.format_debate_history()
    """

    def __init__(self, persist_dir: Optional[str] = None):
        self.history: list[Message] = []
        self.mailboxes: dict[str, list[Message]] = {}
        self.persist_dir = persist_dir
        self.log_file: Optional[str] = None

        if persist_dir:
            os.makedirs(persist_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self.log_file = os.path.join(persist_dir, f"debate_{timestamp}.jsonl")
            logger.info(f"[MessageBus] Logging to {self.log_file}")

    def send(self, from_agent: str, to_agent: str, content: str,
             round_num: int = 0, msg_type: str = "debate") -> Message:
        """
        发送一条消息

        Args:
            from_agent: 发送者名称
            to_agent: 接收者名称
            content: 消息内容
            round_num: 当前轮次
            msg_type: 消息类型 (debate/analysis/decision)
        """
        msg = Message(from_agent, to_agent, content, round_num, msg_type)
        self.history.append(msg)

        # 写入邮箱
        if to_agent not in self.mailboxes:
            self.mailboxes[to_agent] = []
        self.mailboxes[to_agent].append(msg)

        # JSONL 持久化
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning(f"[MessageBus] Failed to persist message: {e}")

        logger.info(
            f"[MessageBus] {from_agent} -> {to_agent} "
            f"(round={round_num}, {len(content)} chars)"
        )
        return msg

    def receive(self, agent_name: str) -> list[Message]:
        """
        接收并清空该智能体的邮箱

        Returns:
            该智能体的所有未读消息（读取后清空）
        """
        msgs = self.mailboxes.get(agent_name, [])
        self.mailboxes[agent_name] = []
        return msgs

    def peek(self, agent_name: str) -> list[Message]:
        """查看邮箱内容但不清空"""
        return list(self.mailboxes.get(agent_name, []))

    def get_history(self, msg_type: Optional[str] = None) -> list[Message]:
        """获取所有历史消息，可按类型过滤"""
        if msg_type:
            return [m for m in self.history if m.msg_type == msg_type]
        return list(self.history)

    def get_last_from(self, agent_name: str) -> Optional[Message]:
        """获取某个智能体发送的最后一条消息"""
        for msg in reversed(self.history):
            if msg.from_agent == agent_name:
                return msg
        return None

    def format_debate_history(self) -> str:
        """
        将辩论历史格式化为可读的对话记录

        Returns:
            格式化的对话文本，如:
            [Round 1] 看多分析师:
            xxx

            [Round 1] 看空分析师:
            yyy
        """
        if not self.history:
            return "(暂无辩论记录)"

        lines = []
        agent_labels = {
            "bull-debater": "看多分析师",
            "bear-debater": "看空分析师",
            "research-manager": "研究经理",
        }

        for msg in self.history:
            if msg.msg_type != "debate":
                continue
            label = agent_labels.get(msg.from_agent, msg.from_agent)
            lines.append(f"[Round {msg.round_num}] {label}:")
            lines.append(msg.content)
            lines.append("")  # 空行分隔

        return "\n".join(lines)

    def get_debate_summary(self) -> dict:
        """获取辩论统计摘要"""
        debate_msgs = [m for m in self.history if m.msg_type == "debate"]
        bull_msgs = [m for m in debate_msgs if m.from_agent == "bull-debater"]
        bear_msgs = [m for m in debate_msgs if m.from_agent == "bear-debater"]

        max_round = max((m.round_num for m in debate_msgs), default=0)

        return {
            "total_messages": len(debate_msgs),
            "bull_messages": len(bull_msgs),
            "bear_messages": len(bear_msgs),
            "rounds_completed": max_round,
            "total_chars": sum(len(m.content) for m in debate_msgs),
        }

    def clear(self):
        """清空所有消息（保留日志文件）"""
        self.history.clear()
        self.mailboxes.clear()
