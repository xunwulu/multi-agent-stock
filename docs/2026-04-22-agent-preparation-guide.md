# 智能体准备清单 — 打造高质量 Agent 的完整指南

> **日期**: 2026-04-22 | **基于**: Anthropic 上下文工程指南 + 2026 Agent 最佳实践 + learn-claude-code 哲学
> **目标**: 为多子智能体股票分析系统设计完整的工具、技能、约束和质检体系

---

## 一、核心原则（来自前沿研究）

### 1.1 Anthropic 的"上下文工程"三原则

> 来源: [Anthropic - Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

```
原则1: 找到"最小高信号token集"
  → 不是塞更多信息，而是给最有用的信息
  → 类比: 给分析师一份精简摘要，不是把整个数据库倒给他

原则2: 系统提示词要在"正确的高度"
  → 太具体 = 脆弱（像 TradingAgents-CN 用大量🚨⚠️🔴逼LLM调工具）
  → 太模糊 = 无效（"分析这只股票"没有具体指引）
  → 正确高度 = 清晰指引 + 灵活空间

原则3: 工具要"精简、不重叠、自描述"
  → 如果一个人类都搞不清该用哪个工具，LLM也搞不清
  → 工具数量越少越好，每个工具职责清晰
```

### 1.2 2026 Agent 生产架构五要素

> 来源: [AI Agents 2026: Practical Architecture](https://andriifurmanets.com/blogs/ai-agents-2026-practical-architecture-tools-memory-evals-guardrails)

```
要素1: 工具 = API契约（有类型校验、有超时、有结构化输出）
要素2: 状态 = 确定性状态机（LLM做决策，代码管状态转换）
要素3: 记忆 = 分层记忆（工作记忆 + 摘要 + 持久化）
要素4: 护栏 = 失败安全（前置检查 + 后置检查 + 预算限制）
要素5: 可观测 = 追踪日志（每一步都记录，可回溯调试）
```

### 1.3 learn-claude-code 的 Harness 五要素

```
工具(Tools)    → 给智能体一双"手"（查数据的能力）
知识(Knowledge) → 给智能体一个"脑"（SKILL.md 按需加载）
观察(Observation) → 给智能体一双"眼"（看到执行结果）
行动接口(Action)  → 给智能体一双"脚"（能输出报告、做决策）
权限(Permission)  → 给智能体一条"边界"（不能做的事）
```

---

## 二、我们需要准备的六样东西

```
┌────────────────────────────────────────────────────────┐
│                                                          │
│  1. 工具层（Tools）     → 智能体能做什么                  │
│  2. 技能层（Skills）     → 智能体知道怎么做               │
│  3. 约束层（Constraints）→ 智能体不能做什么               │
│  4. 状态层（State）      → 智能体记住什么                  │
│  5. 质检层（Quality）    → 输出质量怎么保证               │
│  6. 可观测层（Tracing）  → 出了问题怎么排查               │
│                                                          │
└────────────────────────────────────────────────────────┘
```

---

## 三、工具层设计（智能体能做什么）

### 3.1 工具设计原则

```
原则1: 每个工具只做一件事
  ✅ get_kline(code, start_date, end_date)     → 只拿K线
  ✅ calculate_macd(kline_data)                → 只算MACD
  ❌ get_all_data_and_analyze(code)            → 做太多，模糊

原则2: 工具之间不重叠
  ✅ get_kline 专拿K线，get_financials 专拿财务
  ❌ get_stock_data 既拿K线又拿财务 → 智能体不知道该调哪个

原则3: 输入输出结构化
  输入: 有类型校验（股票代码必须是6位数字）
  输出: 标准格式 {ok: true, data: {...}, error: null, meta: {耗时}}

原则4: 有超时和重试
  超时: 10秒内必须返回
  重试: 最多重试2次
  降级: 主数据源失败自动切备用源
```

### 3.2 我们需要准备的具体工具

```
数据获取工具（给分析师用）:
  ┌─────────────────────────────────────────────────┐
  │ 工具名              │ 功能          │ 数据源     │
  ├─────────────────────┼──────────────┼───────────┤
  │ get_kline           │ K线数据       │ Tushare   │
  │ get_financials      │ 财务数据      │ Tushare   │
  │ get_news            │ 新闻数据      │ AKShare   │
  │ get_institutional   │ 机构持仓      │ Tushare   │
  │ get_money_flow      │ 资金流向      │ Tushare   │
  │ get_stock_basic     │ 股票基本信息  │ Tushare   │
  └─────────────────────────────────────────────────┘

计算工具（给分析师用）:
  ┌─────────────────────────────────────────────────┐
  │ 工具名              │ 功能                       │
  ├─────────────────────┼───────────────────────────┤
  │ calc_technical      │ 计算MACD/RSI/布林带/均线   │
  │ calc_valuation      │ 计算PE/PB/PEG/估值区间     │
  │ calc_cost           │ 计算机构成本（我们已有3种方法）│
  │ calc_risk_score     │ 计算风险评分               │
  └─────────────────────────────────────────────────┘

通信工具（给辩论者用）:
  ┌─────────────────────────────────────────────────┐
  │ 工具名              │ 功能                       │
  ├─────────────────────┼───────────────────────────┤
  │ send_message        │ 给指定智能体发消息          │
  │ read_inbox          │ 读取自己的收件箱            │
  │ broadcast           │ 广播消息给所有智能体        │
  └─────────────────────────────────────────────────┘

知识工具（所有智能体用）:
  ┌─────────────────────────────────────────────────┐
  │ 工具名              │ 功能                       │
  ├─────────────────────┼───────────────────────────┤
  │ load_skill          │ 按需加载角色技能文件        │
  │ save_note           │ 保存笔记到持久化存储        │
  │ read_note           │ 读取之前的笔记              │
  └─────────────────────────────────────────────────┘
```

---

## 四、技能层设计（智能体知道怎么做）

### 4.1 什么是 Skill

```
Skill = 一个 Markdown 文件，描述:
  - 你是谁（角色定义）
  - 你能做什么（工作范围）
  - 你应该怎么工作（工作流程）
  - 你的输出应该长什么样（输出模板）
  - 你不应该做什么（约束边界）

类比: Skill = 员工入职时收到的工作手册
  不是每句话都规定死，而是给出方向和边界
  员工（LLM）根据手册自己决定具体怎么做
```

### 4.2 我们需要准备的 Skill 文件

```
skills/
├── analyst/
│   ├── technical-analyst.md      # 技术分析师工作手册
│   ├── fundamentals-analyst.md   # 基本面分析师工作手册
│   ├── news-analyst.md           # 新闻分析师工作手册
│   └── sentiment-analyst.md      # 情绪分析师工作手册
│
├── researcher/
│   ├── bull-debater.md           # 看多辩论者工作手册
│   ├── bear-debater.md           # 看空辩论者工作手册
│   └── research-manager.md       # 研究经理工作手册
│
├── trader/
│   └── trader.md                 # 交易员工作手册
│
├── risk/
│   ├── aggressive.md             # 激进风控工作手册
│   ├── conservative.md           # 保守风控工作手册
│   ├── neutral.md                # 中性风控工作手册
│   └── risk-manager.md           # 风控经理工作手册
│
└── orchestrator/
    └── orchestrator.md           # 父智能体（编排者）工作手册
```

### 4.3 Skill 文件的统一格式

```markdown
---
name: 技术分析师
description: 分析股票技术面，包括K线形态、技术指标、趋势判断
tools: [get_kline, calc_technical]
output_to: [orchestrator]           # 结果发给谁
max_iterations: 5                    # 最多循环5次
timeout_seconds: 60                  # 超时60秒
---

# 你的角色

你是一位专业的股票技术分析师。

# 你的工具

- get_kline: 获取K线数据（调用一次即可）
- calc_technical: 计算MACD、RSI、布林带等技术指标

# 工作流程

1. 调用 get_kline 获取K线数据
2. 调用 calc_technical 计算技术指标
3. 综合分析，输出报告

# 输出格式

必须输出 JSON 格式:
{
  "score": 0-100的评分,
  "direction": "bullish/bearish/neutral",
  "signals": ["信号1", "信号2", ...],
  "summary": "一段话总结",
  "report": "详细分析报告（Markdown）"
}

# 约束

- 必须基于真实数据分析，不允许编造
- 每个技术指标必须给出具体数值
- 不允许给出最终交易建议（最终建议由风控经理定）
- 如果数据获取失败，输出错误信息，不要编造分析
```

### 4.4 Skill 设计的关键: "正确的高度"

```
TradingAgents-CN 的提示词问题（太低/太死板）:
  "🚨 绝对禁止在没有调用工具的情况下直接回答"
  "🚨 绝对禁止基于推测或假设生成任何分析内容"
  "现在立即开始调用工具！不要说任何其他话！"
  → 像在逼一个不愿意干活的员工，用大量感叹号和emoji
  → 说明提示词写得不好，需要靠"逼"来让LLM执行

我们 Skill 应该的高度（清晰+灵活）:
  "你负责技术面分析。先用 get_kline 获取数据，然后分析。"
  "分析完成后输出 JSON 格式报告。"
  → 清晰指引，但不过度控制
  → LLM 自己决定分析深度和重点
```

---

## 五、约束层设计（智能体不能做什么）

### 5.1 三层约束体系

```
第1层: 硬约束（代码层面强制执行，智能体无法违反）
  ┌────────────────────────────────────────────┐
  │ 约束                  │ 实现方式            │
  ├──────────────────────┼─────────────────────┤
  │ 超时限制              │ timeout参数          │
  │ 最大循环次数          │ max_iterations参数   │
  │ 最大token消耗         │ token预算            │
  │ 最大工具调用次数      │ 每个工具上限3次      │
  │ 辩论轮次上限          │ max_debate_rounds    │
  │ 工具权限白名单        │ 每个角色只能调指定工具│
  └──────────────────────┴─────────────────────┘
  → 类比: 公司门禁卡，员工只能在有权限的区域活动

第2层: 软约束（写在Skill里，LLM应遵守但不是100%保证）
  ┌────────────────────────────────────────────┐
  │ 约束                  │ 写在Skill中          │
  ├──────────────────────┼─────────────────────┤
  │ 不编造数据            │ "必须基于真实数据"    │
  │ 不越权决策            │ "不给出最终交易建议"  │
  │ 不重复劳动            │ "数据只需获取一次"    │
  │ 用中文输出            │ "所有输出使用中文"    │
  │ 不使用英文建议        │ "用买入/持有/卖出"    │
  └──────────────────────┴─────────────────────┘
  → 类比: 员工手册上的规章制度

第3层: 后置检查（输出后校验，不符合就拒绝）
  ┌────────────────────────────────────────────┐
  │ 检查项                │ 处理方式            │
  ├──────────────────────┼─────────────────────┤
  │ 报告是否包含数据      │ 无数据则重试         │
  │ 决策是否明确          │ 不明确则追问         │
  │ JSON格式是否正确      │ 格式错误则重新解析   │
  │ 是否有矛盾结论        │ 有矛盾则标记警告     │
  └──────────────────────┴─────────────────────┘
  → 类比: 质检部门，产品出厂前最后检查
```

### 5.2 熔断机制（Circuit Breaker）

```
来源: 2026 Agent最佳实践中的关键设计

什么是熔断?
  当一个智能体反复失败时，不是让它无限重试，而是"断电"保护

场景1: 分析师反复调用工具拿不到数据
  第1次失败 → 重试
  第2次失败 → 重试
  第3次失败 → 熔断！返回错误信息，让父智能体决定下一步

场景2: 辩论者进入死循环
  看多说"买" → 看空说"不买" → 看多说"买" → ...
  达到 max_debate_rounds → 熔断！强制结束辩论，进入裁决

场景3: 总token消耗超预算
  单只股票分析 token 预算 = 50000
  消耗达到 45000 → 警告
  消耗达到 50000 → 熔断！强制结束，返回已有结果
```

---

## 六、状态层设计（智能体记住什么）

### 6.1 四层记忆体系

```
Layer 1: 工作记忆（当前分析任务的临时状态）
  存储位置: 内存中的 AgentState 字典
  内容: 当前分析到哪一步了、拿到了什么数据、还没做什么
  生命周期: 一只股票分析完毕后清除
  类比: 分析师办公桌上的便签纸

Layer 2: 摘要记忆（对话压缩）
  存储位置: 每个子智能体内部
  内容: 自己分析过程的摘要（不保留原始数据，只保留结论）
  触发: 当消息超过一定长度时自动压缩
  类比: 分析师写的工作日志

Layer 3: 任务产出（分析报告）
  存储位置: 文件系统或数据库
  内容: 每个子智能体产出的正式报告
  特点: 结构化JSON，可被其他智能体引用
  类比: 分析师提交的正式文件

Layer 4: 长期记忆（历史经验，可选）
  存储位置: 向量数据库（ChromaDB）或文件
  内容: 历史分析的成功/失败教训
  用途: 新分析时检索相似案例参考
  类比: 分析师的工作经验积累
```

### 6.2 状态转换: 确定性 vs 概率性

```
关键设计原则（来自2026最佳实践）:

  LLM做决策 = 概率性（可能每次不同）
  代码管状态 = 确定性（每次相同输入相同输出）

举例:
  LLM决策: "我要查K线"（概率性，可能查可能不查）
  状态转换: 收到K线数据 → 存入state.kline_data（确定性，代码执行）

  LLM决策: "我建议买入"（概率性）
  状态转换: 收到建议 → 检查格式 → 存入state.decision（确定性）

这样设计的好处:
  - LLM 的不确定性被限制在"决策"环节
  - 状态转换由代码保证，不会出错
  - 出问题只查决策环节，不查状态管理
```

---

## 七、质检层设计（输出质量怎么保证）

### 7.1 每个智能体的输出校验

```
分析师输出校验:
  ✅ 是否包含具体数值（MACD=? RSI=? PE=?）
  ✅ 是否有明确的评分（0-100）
  ✅ 是否有总结段落
  ✅ 报告长度是否合理（>200字，<3000字）
  ❌ 是否编造了数据（对比工具返回的原始数据）

辩论者输出校验:
  ✅ 是否引用了具体数据
  ✅ 是否回应了对方的观点
  ✅ 论点长度是否合理（>50字，<1000字）
  ❌ 是否只是在重复（与上一轮相似度<70%）

经理输出校验:
  ✅ 是否有明确的决策（买入/持有/卖出）
  ✅ 是否有目标价（必须是具体数字）
  ✅ 是否有置信度（0-1之间）
  ✅ 是否有风险评分（0-1之间）
  ❌ 是否说"无法确定"（不允许）
```

### 7.2 系统级质检

```
最终输出质检（在返回给用户之前）:
  ✅ 所有分析师都产出了报告
  ✅ 辩论至少进行了1轮
  ✅ 最终决策是明确的买入/持有/卖出
  ✅ 目标价与当前价差距合理（不超过±50%）
  ✅ 置信度和风险评分在0-1范围内
  ✅ 所有引用的数据与原始数据一致
```

---

## 八、可观测层设计（出了问题怎么排查）

### 8.1 追踪日志（Tracing）

```
每一步都记录:
  {
    "trace_id": "分析任务唯一ID",
    "step": 5,
    "agent": "technical-analyst",
    "action": "tool_call",
    "tool": "get_kline",
    "tool_input": {"code": "300033", "start": "2026-01-01"},
    "tool_output": "ok, 120条K线数据",
    "duration_ms": 823,
    "tokens_used": 450,
    "timestamp": "2026-04-22T10:30:15"
  }

好处:
  - 知道哪个智能体卡住了
  - 知道哪一步花时间最长
  - 知道总共消耗了多少token
  - 可以回放整个分析过程
```

### 8.2 成本追踪

```
每只股票分析完成后记录:
  - 总LLM调用次数
  - 总token消耗（输入/输出）
  - 总耗时
  - 各智能体的耗时分布
  - 各智能体的token消耗分布

用途:
  - 优化成本（哪个智能体最耗token？）
  - 优化速度（哪个环节最慢？）
  - 设定预算（单股分析不超过X元）
```

---

## 九、推荐的建造顺序（参考2026最佳实践）

```
Phase 1: 基础设施（第1周）
  ├─ [1.1] Agent Loop 核心循环（~80行代码）
  ├─ [1.2] 工具注册系统（~50行代码）
  ├─ [1.3] 2-3个数据工具（get_kline, get_financials）
  └─ [1.4] 第一个Skill（technical-analyst.md）

  验证目标: 一个技术分析师智能体能独立跑通

Phase 2: 多角色协作（第2周）
  ├─ [2.1] 父智能体（Orchestrator）
  ├─ [2.2] 子智能体创建和销毁
  ├─ [2.3] 更多Skill（fundamentals, news, bull, bear...）
  ├─ [2.4] 消息总线（MessageBus）
  └─ [2.5] 状态管理系统

  验证目标: 完整的单股分析流程（12个角色全部跑通）

Phase 3: 质量和约束（第3周）
  ├─ [3.1] 输出校验系统
  ├─ [3.2] 熔断机制
  ├─ [3.3] 追踪日志
  ├─ [3.4] 成本追踪
  └─ [3.5] 优化Skill提示词

  验证目标: 分析结果稳定、可复现、可调试

Phase 4: 批量扩展（第4周）
  ├─ [4.1] 调度员（Dispatcher）
  ├─ [4.2] 并发窗口控制
  ├─ [4.3] 结果对比排名
  └─ [4.4] 前端界面接入

  验证目标: 10只股票并行分析，出对比排名
```

---

## 十、总清单汇总

```
我们要准备的所有东西:

工具层（~15个工具）:
  ☐ get_kline          ☐ get_financials
  ☐ get_news           ☐ get_institutional
  ☐ get_money_flow     ☐ get_stock_basic
  ☐ calc_technical     ☐ calc_valuation
  ☐ calc_cost          ☐ calc_risk_score
  ☐ send_message       ☐ read_inbox
  ☐ broadcast          ☐ load_skill
  ☐ save_note

技能层（~13个Skill文件）:
  ☐ technical-analyst   ☐ fundamentals-analyst
  ☐ news-analyst        ☐ sentiment-analyst
  ☐ bull-debater        ☐ bear-debater
  ☐ research-manager    ☐ trader
  ☐ aggressive          ☐ conservative
  ☐ neutral             ☐ risk-manager
  ☐ orchestrator

约束层:
  ☐ 超时限制            ☐ 最大循环次数
  ☐ token预算           ☐ 工具调用上限
  ☐ 辩论轮次上限        ☐ 工具权限白名单
  ☐ 熔断机制            ☐ 输出格式校验

质检层:
  ☐ 分析师输出校验      ☐ 辩论者输出校验
  ☐ 经理输出校验        ☐ 系统级质检

基础设施:
  ☐ Agent Loop          ☐ 子智能体管理器
  ☐ MessageBus          ☐ 追踪日志系统
  ☐ 成本追踪系统        ☐ 调度员（批量时加）
```

---

## 参考来源

- [Anthropic - Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [AI Agents 2026: Practical Architecture](https://andriifurmanets.com/blogs/ai-agents-2026-practical-architecture-tools-memory-evals-guardrails)
- [Designing Autonomous Multi-Agent Systems with Guardrails](https://medium.com/@dewasheesh.rana/agentic-ai-in-production-designing-autonomous-multi-agent-systems-with-guardrails-2026-guide-a5a1c8461772)
- [Designing Production-Ready AI Agents](https://medium.com/@mamidipaka2003/designing-production-ready-ai-agents-architecture-guardrails-and-failure-handling-c250dc3fc0fe)
- [Six Core Design Principles for Multi-AI Agent Systems](https://cobusgreyling.medium.com/six-core-design-principles-for-multi-ai-agent-systems-857f5c32ec33)
- [Google ADK - Efficient Context-Aware Multi-Agent Framework](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/)

---

**文档结束** | 船长看完后可以指出想深入讨论或调整的部分。
