# 13 - 状态结构与默认配置

> **源文件**: `tradingagents/agents/utils/agent_states.py` + `tradingagents/default_config.py`

---

## AgentState — 全局状态（所有Agent共享的"会议记录本"）

```python
class AgentState(MessagesState):
    # 基本信息
    company_of_interest: str       # 分析的股票代码
    trade_date: str                # 分析日期
    sender: str                    # 当前发送消息的Agent

    # 4份分析报告（分析师团队产出）
    market_report: str             # 市场分析师报告
    sentiment_report: str          # 社交媒体分析师报告
    news_report: str               # 新闻分析师报告
    fundamentals_report: str       # 基本面分析师报告

    # 工具调用计数器（防止死循环）
    market_tool_call_count: int    # 市场分析师工具调用次数（上限3）
    news_tool_call_count: int      # 新闻分析师工具调用次数（上限3）
    sentiment_tool_call_count: int # 社交媒体分析师工具调用次数（上限3）
    fundamentals_tool_call_count: int  # 基本面分析师工具调用次数（上限1）

    # 研究团队辩论状态
    investment_debate_state: InvestDebateState
    investment_plan: str           # 研究经理的投资计划

    # 交易员产出
    trader_investment_plan: str    # 交易员的交易计划

    # 风控团队辩论状态
    risk_debate_state: RiskDebateState

    # 最终决策
    final_trade_decision: str      # 风控经理的最终决策
```

---

## InvestDebateState — 多空辩论状态

```python
class InvestDebateState(TypedDict):
    bull_history: str      # 看多研究员的发言历史
    bear_history: str      # 看空研究员的发言历史
    history: str           # 完整辩论历史
    current_response: str  # 最新一条回应
    judge_decision: str    # 研究经理的裁决
    count: int             # 当前对话轮次计数
```

---

## RiskDebateState — 风控辩论状态

```python
class RiskDebateState(TypedDict):
    risky_history: str             # 激进分析师发言历史
    safe_history: str              # 保守分析师发言历史
    neutral_history: str           # 中性分析师发言历史
    history: str                   # 完整辩论历史
    latest_speaker: str            # 最后发言者标识
    current_risky_response: str    # 激进分析师最新回应
    current_safe_response: str     # 保守分析师最新回应
    current_neutral_response: str  # 中性分析师最新回应
    judge_decision: str            # 风控经理的裁决
    count: int                     # 当前对话轮次计数
```

---

## 默认配置 (default_config.py)

```python
DEFAULT_CONFIG = {
    # 目录配置
    "project_dir": "./",
    "results_dir": "./results",
    "data_dir": "~/Documents/TradingAgents/data",
    "data_cache_dir": "./dataflows/data_cache",

    # LLM 配置
    "llm_provider": "openai",          # 默认LLM提供商
    "deep_think_llm": "o4-mini",       # 深度思考模型
    "quick_think_llm": "gpt-4o-mini",  # 快速思考模型
    "backend_url": "https://api.openai.com/v1",

    # 辩论配置
    "max_debate_rounds": 1,            # 多空辩论轮数（1轮=各发言1次）
    "max_risk_discuss_rounds": 1,      # 风控辩论轮数（1轮=各发言1次）
    "max_recur_limit": 100,            # LangGraph最大递归深度

    # 工具开关
    "online_tools": False,             # 是否使用在线工具
    "online_news": True,               # 是否使用在线新闻
    "realtime_data": False,            # 是否使用实时数据
}
```

---

## 数据流总图

```
初始状态 (AgentState)
  |
  +-- [市场分析师] --quick_llm + 工具--> market_report
  +-- [基本面分析师] --quick_llm + 工具--> fundamentals_report
  +-- [新闻分析师] --quick_llm + 工具--> news_report
  +-- [社交分析师] --quick_llm + 工具--> sentiment_report
  |
  v
InvestDebateState（多空辩论）
  +-- [看多研究员] --quick_llm--> 看多论点  -+
  +-- [看空研究员] --quick_llm--> 看空论点  -+ 重复 max_debate_rounds 轮
  +-- [研究经理] --deep_llm--> investment_plan
  |
  v
  +-- [交易员] --quick_llm--> trader_investment_plan
  |
  v
RiskDebateState（风控辩论）
  +-- [激进风控] --quick_llm--> 激进论点  -+
  +-- [保守风控] --quick_llm--> 保守论点  -+ 重复 max_risk_discuss_rounds 轮
  +-- [中性风控] --quick_llm--> 中性论点  -+
  |
  v
  +-- [风控经理] --deep_llm--> final_trade_decision（最终决策）
```
