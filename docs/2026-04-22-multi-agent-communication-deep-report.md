# 多智能体通信技术深度研究报告

> **报告日期**: 2026-04-22 | **作者**: 船员 (Claude) | **目标读者**: 船长
> **核心问题**: 我们的多子智能体股票分析系统，应该用什么技术让12个AI角色互相通信？

---

## 〇、报告导航

```
第一章  为什么这个问题很重要         → 问题的本质
第二章  六种技术的全景对比表         → 一页看完全貌
第三章  AG2 (AutoGen)              → 对话式多智能体
第四章  Google A2A Protocol         → 跨框架通信标准
第五章  Laddr Framework            → 微服务架构智能体
第六章  LangGraph                  → 图式状态机
第七章  CrewAI                     → 角色扮演式团队
第八章  DIY (learn-claude-code)    → 从零手搓
第九章  通信机制横向对比            → 消息怎么传递的
第十章  可借鉴的设计模式            → 每种技术我们学什么
第十一章 最终推荐方案               → 船长该怎么选
第十二章 行动路线图                 → 下一步做什么
```

---

## 一、为什么这个问题很重要

### 1.1 我们的系统长什么样

```
我们要建的是这样一个系统:

  用户输入 "分析 300033"
      |
      v
  [编排者 Orchestrator]  ← 总指挥
      |
      +-- [技术分析师]  → 分析K线、MACD、RSI
      +-- [基本面分析师] → 分析营收、利润、估值
      +-- [新闻分析师]   → 分析近期新闻和公告
      +-- [情绪分析师]   → 分析市场情绪和资金面
      |
      v
  [看多辩论者] vs [看空辩论者]  ← 正反方辩论
      |
      v
  [研究经理]  ← 综合辩论，给出初步判断
      |
      v
  [激进风控] vs [保守风控] vs [中性风控]  ← 三种风险视角
      |
      v
  [风控经理]  ← 最终决策: 买入/持有/卖出
      |
      v
  [交易员]    ← 输出完整交易建议
```

**核心挑战**: 这12个角色怎么互相传递信息？

- 技术分析师的结论，看多辩论者怎么读到？
- 辩论过程中，看多和看空怎么一来一回地争论？
- 风控经理怎么汇总三个风控视角的意见？
- 交易员怎么拿到所有角色的最终结论？

**类比**: 这就像一家投资公司的12个分析师要写一份联合报告。
- 他们怎么交流？开会？发邮件？用Slack？
- 谁先发言？谁最后总结？
- 中间有人生病（崩溃）了怎么办？

### 1.2 通信机制的本质差异

六种技术对"智能体之间怎么通信"这个问题，给出了截然不同的回答:

| 技术 | 通信本质 | 类比 |
|------|---------|------|
| AG2 | 对话 (LLM消息列表) | 开会讨论 |
| A2A | 协议 (JSON-RPC/HTTP) | 公司间合同 |
| Laddr | 微服务 (REST API) | 公司部门间邮件 |
| LangGraph | 图节点 (共享State字典) | 流水线传送带 |
| CrewAI | 任务队列 (顺序/并行) | 项目管理工具 |
| DIY | 文件邮箱 (JSONL追加) | 每人一个信箱 |

---

## 二、六种技术全景对比表

### 2.1 一页看完全貌

| 维度 | AG2 | A2A | Laddr | LangGraph | CrewAI | DIY |
|------|-----|-----|-------|-----------|--------|-----|
| **通信方式** | LLM对话 | HTTP/JSON-RPC | REST API | 共享State | 任务传递 | JSONL邮箱 |
| **编排方式** | 群聊模式 | 去中心化 | 微服务 | 有向图 | Crew流程 | 代码循环 |
| **上手难度** | 低 | 中 | 高 | 中 | 低 | 中 |
| **灵活性** | 极高 | 高 | 高 | 中高 | 中 | 极高 |
| **可控性** | 低 | 中 | 高 | 高 | 中高 | 极高 |
| **可观测性** | 低 | 中 | 极高 | 高 | 中 | 自定义 |
| **生产就绪** | 中 | 低(新) | 高 | 高 | 中 | 自定义 |
| **适合场景** | 探索/辩论 | 跨平台集成 | 后端服务 | 结构化流程 | 快速原型 | 完全定制 |
| **依赖数量** | ~10 | ~5 | ~20+ | ~15 | ~10 | 2 |
| **代码量** | ~200 | ~300 | ~2000+ | ~500 | ~300 | ~500 |

### 2.2 一句话总结每种技术

```
AG2:      "让多个AI坐在一起开会讨论"
A2A:      "让不同框架的AI用统一语言沟通"
Laddr:    "每个AI是一个独立的微服务容器"
LangGraph:"用流程图定义AI的工作步骤"
CrewAI:   "给AI分配角色和任务，让它们组队干活"
DIY:      "从零手搓，想怎么通信就怎么通信"
```

---

## 三、AG2 (AutoGen) — 对话式多智能体

### 3.1 核心理念

```
核心理念: AI之间的协作，本质就是"对话"

  智能体A说话 → 智能体B听到 → 智能体B回应 → 智能体A听到 → ...

  就像人类开会:
    张三: "我认为这只股票值得买入"
    李四: "我不同意，因为PE太高了"
    张三: "但它的增长速度可以支撑高PE"
    主持人: "双方都有道理，我来总结..."
```

### 3.2 核心架构

```
AG2 架构三层:

  第1层: ConversableAgent（基础智能体）
    每个智能体 = 一个LLM客户端 + 工具注册 + 消息收发
    可以发送消息、接收消息、调用工具、自主决定是否继续

  第2层: GroupChat（群聊管理器）
    管理多个智能体的发言顺序
    支持自动选择下一个发言者（由LLM决定）
    支持轮询、随机、自定义选择策略

  第3层: Run Methods（运行模式）
    run_group_chat(): 群聊模式（多智能体自由讨论）
    initiate_chat():  一对一对话
    run():            单智能体执行
```

### 3.3 代码示例（伪代码）

```python
from ag2 import ConversableAgent

# 创建两个辩论者
bull = ConversableAgent(
    name="看多分析师",
    system_message="你是一位看多分析师，从积极角度分析股票",
    llm_config={"model": "glm-5.1"}
)

bear = ConversableAgent(
    name="看空分析师",
    system_message="你是一位看空分析师，从风险角度分析股票",
    llm_config={"model": "glm-5.1"}
)

# 注册工具
@bull.register_function("get_kline")
def get_kline(code, start, end):
    """获取K线数据"""
    ...

# 让两个辩论者互相对话
result = bull.initiate_chat(
    bear,
    message="300033.SZ 的技术面支持买入，MACD金叉，RSI=55",
    max_turns=4  # 最多4轮
)
# bull说 → bear回 → bull反驳 → bear反驳 → 结束
```

### 3.4 通信机制详解

```
消息格式（LLM原生格式）:
  {
    "role": "assistant",     ← 发送者
    "content": "我认为...",   ← 消息内容
    "name": "看多分析师"      ← 智能体名称
  }

传递方式:
  每个智能体维护一个 messages 列表
  发送消息 = 把消息追加到对方的 messages 列表
  接收消息 = 从自己的 messages 列表读取新消息

特点:
  ✅ 最自然的通信方式（人类就是这样沟通的）
  ✅ 灵活，不需要预定义消息格式
  ❌ 不可控（LLM可能跑题）
  ❌ 难以调试（对话历史太长时难以追踪）
  ❌ 消耗大量token（每次都要带完整对话历史）
```

### 3.5 对我们项目的启发

```
可借鉴:
  ✅ "群聊"模式非常适合辩论场景
     看多 vs 看空 → GroupChat(max_turns=4)
     三种风控辩论 → GroupChat(max_turns=3)

  ✅ register_function 工具注册方式很简洁
     我们可以采用类似的方式注册数据工具

需要注意:
  ⚠️ AG2的通信依赖LLM理解对话上下文
     如果对话轮次多，上下文会溢出
     需要加一层摘要机制

  ⚠️ AG2的可控性较差
     无法精确控制"第3步必须做什么"
     需要外部编排器来控制流程
```

---

## 四、Google A2A Protocol — 跨框架通信标准

### 4.1 核心理念

```
核心理念: 不同框架的AI智能体，应该用统一的语言沟通

  现状:
    AG2的AI说 "方言A"
    CrewAI的AI说 "方言B"
    LangGraph的AI说 "方言C"
    → 互相听不懂！

  A2A的目标:
    所有AI都说 "普通话"
    不管底层用什么框架，通信协议统一

  类比:
    就像HTTP协议 — 不管你用什么浏览器(Chrome/Safari/Firefox)，
    都能访问同一个网站，因为大家都说HTTP
```

### 4.2 核心架构

```
A2A 三层架构:

  第1层: Agent Card（名片）
    每个智能体有一张JSON格式的"名片"
    包含: 名字、能力描述、通信端点、认证方式
    类比: 员工的工牌

  第2层: A2A Server（通信服务器）
    支持三种传输层:
    - JSON-RPC over HTTP  ← 推荐默认
    - REST API            ← 兼容Web
    - gRPC                ← 高性能场景

  第3层: Task Protocol（任务协议）
    客户端发送 Task → 服务端处理 → 返回 TaskResult
    支持流式返回（任务进行中可以发中间结果）
    支持任务取消和状态查询
```

### 4.3 代码示例

```python
# A2A 服务端（一个智能体暴露自己的能力）
from a2a.server import A2AServer, AgentCard, Skill

card = AgentCard(
    name="技术分析师",
    description="分析股票技术面",
    skills=[
        Skill(id="tech_analysis", name="技术分析",
              description="K线、MACD、RSI等技术指标分析")
    ]
)

server = A2AServer(agent_card=card, host="0.0.0.0", port=8001)
server.start()
# 现在其他智能体可以通过 HTTP 调用这个分析师

# A2A 客户端（调用其他智能体）
from a2a.client import A2AClient

client = A2AClient(base_url="http://localhost:8001")
result = await client.send_task({
    "task": "分析 300033.SZ 的技术面",
    "data": {"code": "300033.SZ", "period": "2026Q1"}
})
```

### 4.4 通信机制详解

```
消息格式（标准化协议）:
  请求:
  {
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "params": {
      "task_id": "xxx",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "分析300033"}]
      }
    }
  }

  响应:
  {
    "jsonrpc": "2.0",
    "result": {
      "task_id": "xxx",
      "status": "completed",
      "artifacts": [
        {"type": "text", "text": "技术面分析: MACD金叉..."}
      ]
    }
  }

特点:
  ✅ 标准化，跨框架兼容
  ✅ 支持流式返回（长时间任务）
  ✅ 有安全模型（认证/授权）
  ✅ Linux Foundation 治理（长期维护有保障）
  ❌ 协议较重（HTTP开销）
  ❌ 实时性不如直接内存通信
  ❌ 太新（2025年才发布），生态不成熟
```

### 4.5 对我们项目的启发

```
可借鉴:
  ✅ Agent Card（名片）概念
     每个智能体注册时声明自己的能力和接口
     编排者可以动态发现可用的智能体

  ✅ 标准化的任务协议
     发送任务 → 返回结果 → 支持中间状态
     可以作为我们内部通信的参考格式

  ✅ 安全模型设计
     认证/授权机制
     防止未经授权的智能体加入

需要注意:
  ⚠️ A2A是跨框架协议，我们不需要跨框架
     我们的所有智能体都在同一个Python进程里
     用HTTP通信太重了，内存通信更快

  ⚠️ 太新，文档和示例较少
     学习成本高，坑多
```

---

## 五、Laddr Framework — 微服务架构智能体

### 5.1 核心理念

```
核心理念: 每个智能体是一个独立的微服务容器

  不是 "一群AI在开会"
  而是 "一群专业AI员工，每人一个工位，通过邮件沟通"

  类比:
    传统多智能体 = 一群人在一个房间里喊话
    Laddr = 一栋写字楼，每家公司（智能体）有自己的办公室
            公司之间通过正式邮件（REST API）沟通
```

### 5.2 核心架构

```
Laddr 四层架构:

  第1层: Agent Definition（智能体定义）
    每个智能体 = 独立的Python进程
    通过 agent.yaml 配置文件定义:
      - 使用什么LLM
      - 有哪些工具
      - 通信端点
      - 超时和重试策略

  第2层: Tool System（工具系统）
    @tool 装饰器注册工具
    工具之间松耦合
    每个智能体只暴露自己需要的工具

  第3层: REST API（通信接口）
    每个智能体暴露 HTTP 端点
    /chat   → 发送消息
    /status → 查询状态
    /tools  → 列出可用工具

  第4层: Observability（可观测性）
    Langfuse 集成 → 追踪每一次LLM调用
    React Dashboard → 实时监控面板
    结构化日志 → 每一步操作都记录
```

### 5.3 代码示例

```python
from laddr import Agent, tool

# 定义一个技术分析师智能体
class TechAnalyst(Agent):
    name = "technical-analyst"
    model = "glm-5.1"

    @tool
    def get_kline(self, code: str, start: str, end: str) -> dict:
        """获取K线数据"""
        return self.tushare.get_stock_daily(code, start, end)

    @tool
    def calc_macd(self, kline_data: list) -> dict:
        """计算MACD指标"""
        return calculate_macd(kline_data)

# 启动智能体服务
agent = TechAnalyst()
agent.serve(host="0.0.0.0", port=8001)

# 其他智能体通过 REST API 调用
# POST http://localhost:8001/chat
# {"message": "分析 300033.SZ 技术面"}
```

### 5.4 通信机制详解

```
通信方式: REST API（HTTP请求/响应）

  技术分析师 ──POST /chat──→ 编排者
  编排者     ──POST /chat──→ 看多辩论者
  编排者     ──POST /chat──→ 看空辩论者
  看多       ──POST /chat──→ 看空（直接对话）

特点:
  ✅ 生产级架构，可独立部署、扩缩容
  ✅ 极强的可观测性（Langfuse + React面板）
  ✅ 松耦合，增减智能体不影响其他
  ✅ 每个智能体有独立的上下文空间
  ❌ HTTP通信延迟（每次请求~50ms开销）
  ❌ 部署复杂（需要容器化、网络配置）
  ❌ 开发成本高（每个智能体都是独立服务）
  ❌ 对我们的场景过度工程化
```

### 5.5 对我们项目的启发

```
可借鉴:
  ✅ @tool 装饰器模式
     工具注册非常清晰，代码可读性高
     我们可以直接采用这种模式

  ✅ 可观测性设计（最重要！）
     Langfuse追踪 → 我们可以用更简单的方式实现
     React Dashboard → 我们可以做一个分析过程可视化面板
     结构化日志 → 每步记录到JSONL文件

  ✅ 独立上下文空间
     每个智能体只看自己的数据
     避免上下文污染

需要注意:
  ⚠️ 微服务架构对我们太重了
     我们只有12个角色，不需要容器化
     单进程多线程就够了

  ⚠️ REST API通信延迟
     本地通信用HTTP太浪费
     内存直接调用更快
```

---

## 六、LangGraph — 图式状态机

### 6.1 核心理念

```
核心理念: 用有向图定义智能体的工作流程

  节点(Node) = 一个处理步骤（可以是LLM调用或代码）
  边(Edge) = 步骤之间的转移条件
  状态(State) = 在节点之间传递的共享数据

  类比:
    工厂流水线 — 原材料(股票代码)进去
    经过一道道工序(分析/辩论/裁决)
    最后产出成品(投资建议)

    每道工序只看传送带(共享State)上的信息
    加工完放回传送带，传给下一道工序
```

### 6.2 核心架构

```
LangGraph 三要素:

  第1层: StateGraph（状态图）
    用代码定义节点和边
    state = {"code": "300033", "tech_report": None, ...}

    graph = StateGraph(AgentState)
    graph.add_node("tech_analysis", tech_analyst_fn)
    graph.add_node("fundamental_analysis", fundamental_fn)
    graph.add_node("debate", debate_fn)
    graph.add_node("risk_assessment", risk_fn)

    graph.add_edge("tech_analysis", "fundamental_analysis")
    graph.add_conditional_edges("debate", should_continue,
        {"continue": "debate", "end": "risk_assessment"})

  第2层: Durable Execution（持久化执行）
    工作流状态自动持久化到数据库
    崩溃后可以从中断点恢复
    适合长时间运行的分析任务

  第3层: Human-in-the-Loop（人机协同）
    在关键节点暂停，等待人类审核
    审核通过后继续执行
    适合需要人工确认的投资决策
```

### 6.3 代码示例

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

# 定义共享状态
class AgentState(TypedDict):
    code: str
    tech_report: str | None
    fund_report: str | None
    bull_args: str | None
    bear_args: str | None
    decision: str | None
    debate_round: int

# 定义节点函数
def tech_analysis(state: AgentState) -> AgentState:
    """技术分析节点"""
    kline = get_kline(state["code"])
    report = llm_analyze("你是技术分析师", kline)
    state["tech_report"] = report
    return state

def bull_debater(state: AgentState) -> AgentState:
    """看多辩论节点"""
    response = llm_analyze(
        "你是看多分析师，反驳看空观点",
        state["bear_args"]
    )
    state["bull_args"] = response
    state["debate_round"] += 1
    return state

# 构建图
graph = StateGraph(AgentState)
graph.add_node("tech", tech_analysis)
graph.add_node("bull", bull_debater)
graph.add_node("bear", bear_debater)
graph.add_node("risk", risk_assessment)

graph.add_edge("tech", "bull")
graph.add_edge("bull", "bear")
graph.add_conditional_edges("bear", check_debate_limit,
    {"continue": "bull", "done": "risk"})
graph.add_edge("risk", END)

# 运行
app = graph.compile()
result = app.invoke({"code": "300033.SZ", "debate_round": 0})
```

### 6.4 通信机制详解

```
通信方式: 共享State字典（Python dict）

  State = {
    "code": "300033.SZ",
    "tech_report": "MACD金叉，RSI=55...",
    "fund_report": "营收增长20%...",
    "bull_args": "技术面+基本面都支持...",
    "bear_args": "PE偏高，注意风险...",
    "decision": "买入",
    "debate_round": 3
  }

  每个节点:
    读取 State 中自己需要的字段
    处理完后，更新 State 中自己负责的字段
    传给下一个节点

特点:
  ✅ 流程极其清晰（看图就知道每一步做什么）
  ✅ 状态可持久化（崩溃可恢复）
  ✅ 条件分支灵活（根据结果决定下一步）
  ✅ 可观测性好（LangSmith追踪）
  ✅ Human-in-the-Loop 支持
  ❌ 流程一旦定义，运行时不可更改
  ❌ 共享State可能导致字段冲突
  ❌ 学习曲线较陡（需要理解图的概念）
  ❌ 调试困难（图太复杂时难以定位问题）
```

### 6.5 对我们项目的启发

```
可借鉴:
  ✅ 共享State的设计
     所有分析结果放在一个统一的字典中
     每个角色读取需要的，写入自己负责的

  ✅ 条件边（conditional_edges）
     辩论轮次 < 3 → 继续辩论
     辩论轮次 >= 3 → 进入裁决
     这种条件控制非常符合我们的需求

  ✅ 持久化执行
     长时间分析任务可以中断恢复
     批量分析10只股票时特别有用

需要注意:
  ⚠️ 图是静态定义的，运行时不能改
     我们的流程可能需要动态调整
     比如"如果新闻分析师发现重大利好，增加一轮辩论"

  ⚠️ LangGraph依赖LangChain生态
     我们用GLM-5.1，可能需要适配
     LangSmith需要付费
```

---

## 七、CrewAI — 角色扮演式团队

### 7.1 核心理念

```
核心理念: 给AI分配角色和任务，让它们像人类团队一样协作

  你不需要设计复杂的通信协议
  只需要告诉每个AI:
    - 你是谁（角色）
    - 你要做什么（目标）
    - 你的背景（故事）
    - 你有什么工具

  然后AI们自己决定怎么协作

  类比:
    你是一个项目经理，招聘了一组员工
    你给每个员工写了职位描述(JD)
    告诉他们团队的目标
    然后让他们自己去协作完成

    你不需要告诉他们"先做什么再做什么"
    他们自己会协调
```

### 7.2 核心架构

```
CrewAI 四层架构:

  第1层: Agent（智能体）
    Agent(role="技术分析师",
          goal="分析股票技术面",
          backstory="你是一位经验丰富的技术分析师...",
          tools=[get_kline, calc_macd])

  第2层: Task（任务）
    Task(description="分析 {stock_code} 的技术面",
         agent=tech_analyst,
         expected_output="JSON格式的技术分析报告")

  第3层: Crew（团队）
    Crew(agents=[tech, fund, news, ...],
         tasks=[task1, task2, ...],
         process=Process.sequential  # 或 hierarchical)

  第4层: Flow（流程）— 新增
    @start          → 流程起点
    @listen("xxx")  → 监听某步骤完成
    @router         → 根据条件路由到不同分支
```

### 7.3 代码示例

```python
from crewai import Agent, Task, Crew, Process

# 定义智能体
tech_analyst = Agent(
    role="技术分析师",
    goal="分析股票的技术面，提供技术指标和趋势判断",
    backstory="你是一位有15年经验的技术分析师...",
    tools=[get_kline_tool, calc_macd_tool],
    llm="glm-5.1"
)

bull_debater = Agent(
    role="看多辩论者",
    goal="从积极角度论证投资价值",
    backstory="你总是能发现被低估的投资机会...",
    llm="glm-5.1"
)

# 定义任务
tech_task = Task(
    description="分析 {stock_code} 的技术面",
    agent=tech_analyst,
    expected_output="JSON: {score, direction, signals, summary}"
)

debate_task = Task(
    description="基于技术分析结果，论证看多观点",
    agent=bull_debater,
    expected_output="结构化的看多论证"
)

# 组建团队
crew = Crew(
    agents=[tech_analyst, bull_debater, ...],
    tasks=[tech_task, debate_task, ...],
    process=Process.sequential
)

# 运行
result = crew.kickoff(inputs={"stock_code": "300033.SZ"})
```

### 7.4 通信机制详解

```
通信方式: 任务传递（Task Output → 下一个 Task Context）

  Task1(技术分析) 产出:
    "MACD金叉，RSI=55，趋势向上..."

  Task2(看多辩论) 接收:
    上下文自动包含 Task1 的输出
    基于技术分析结果进行看多论证

  Task3(看空辩论) 接收:
    上下文自动包含 Task1 和 Task2 的输出
    同时看到技术分析和看多论证

特点:
  ✅ 上手最简单（声明式API）
  ✅ 角色定义自然（role/goal/backstory）
  ✅ 支持YAML配置（代码和配置分离）
  ✅ 内建记忆系统（短期+长期）
  ❌ 控制粒度粗（很难精确控制每一步）
  ❌ 任务顺序相对固定
  ❌ 调试困难（黑盒运行）
  ❌ 辩论场景支持有限（不支持真正的来回对话）
```

### 7.5 对我们项目的启发

```
可借鉴:
  ✅ Agent/Task/Crew 三层抽象
     Agent = 角色 + 工具
     Task = 任务描述 + 期望输出
     Crew = 团队配置
     这种分层非常清晰

  ✅ YAML配置方式
     把角色定义和代码分开
     方便船长（非技术人员）调整角色描述

  ✅ expected_output 设计
     每个任务明确期望的输出格式
     方便后续质检

需要注意:
  ⚠️ CrewAI的辩论能力有限
     它的 process=sequential 是线性流程
     不支持真正的"一来一回"辩论
     辩论场景需要自己扩展

  ⚠️ 内部通信不透明
     Task之间怎么传数据的？自动拼接context
     我们无法精确控制传了什么
     可能导致上下文膨胀
```

---

## 八、DIY (learn-claude-code) — 从零手搓

### 8.1 核心理念

```
核心理念: Agent的智能来自模型训练，不是代码编排

  不要花时间设计复杂的通信协议
  先做好最基础的事:
    1. Agent Loop（一个while循环）
    2. 工具注册（一个字典映射）
    3. Skill加载（读一个Markdown文件）

  通信？用最简单的方式:
    每个智能体一个JSONL文件当"邮箱"
    发消息 = 往对方邮箱追加一行JSON
    收消息 = 读取自己的邮箱然后清空

  类比:
    不要一上来就建一栋摩天大楼
    先搭一个帐篷能住人
    然后逐步升级: 帐篷 → 平房 → 楼房 → 大厦
```

### 8.2 核心架构

```
DIY 分层架构（从简到繁，12课渐进式构建）:

  s01 Agent Loop (~80行)
    while True:
      response = llm.chat(messages, tools)
      if response.stop_reason != "tool_use": break
      result = execute_tool(response.tool_call)
      messages.append(result)

  s02 Tool Use (~100行)
    dispatch_map = {
      "get_kline": handle_get_kline,
      "calc_macd": handle_calc_macd,
    }
    每个工具 = 一个handler函数 + 注册到map

  s04 Subagents (~100行)
    父智能体创建子智能体
    子智能体用全新messages启动
    完成后只返回摘要给父智能体

  s05 Skill Loading (~130行)
    SKILL.md = 角色定义文件
    按需加载（用到时才读，不塞进system prompt）

  s09 Agent Teams (~280行)
    MessageBus = JSONL文件邮箱
    send(to, message)    → 追加一行到 to.jsonl
    read_inbox(agent_id) → 读取 + 清空 agent_id.jsonl
    broadcast(message)   → 给所有队友发消息
```

### 8.3 代码示例

```python
# 核心循环（s01，~80行）
def agent_loop(system_prompt, messages, tools, dispatch_map):
    while True:
        response = glm_client.chat(
            model="glm-5.1",
            system=system_prompt,
            messages=messages,
            tools=tools,
        )
        messages.append(response)

        if response.stop_reason != "tool_use":
            return messages[-1].content  # 结束，返回最终回答

        # 执行工具调用
        tool_name = response.tool_calls[0].name
        tool_args = response.tool_calls[0].arguments
        handler = dispatch_map[tool_name]
        result = handler(**tool_args)
        messages.append({"role": "tool_result", "content": result})

# 消息总线（s09，~50行）
class MessageBus:
    def __init__(self, base_dir="mailboxes/"):
        self.base_dir = base_dir

    def send(self, from_id, to_id, message):
        """给指定智能体发消息"""
        filepath = os.path.join(self.base_dir, f"{to_id}.jsonl")
        entry = {"from": from_id, "message": message,
                 "timestamp": datetime.now().isoformat()}
        with open(filepath, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def read_inbox(self, agent_id):
        """读取并清空收件箱"""
        filepath = os.path.join(self.base_dir, f"{agent_id}.jsonl")
        if not os.path.exists(filepath):
            return []
        with open(filepath, "r") as f:
            lines = f.readlines()
        # 清空
        with open(filepath, "w") as f:
            pass
        return [json.loads(line) for line in lines]

# 子智能体创建（s04，~30行）
def spawn_subagent(skill_file, task, tools):
    """创建一个子智能体执行任务"""
    skill = load_skill(skill_file)  # 读取SKILL.md
    messages = [{"role": "user", "content": task}]
    result = agent_loop(
        system_prompt=skill,
        messages=messages,
        tools=tools,
        dispatch_map=build_dispatch_map(tools),
    )
    return summarize(result)  # 只返回摘要，不返回完整对话
```

### 8.4 通信机制详解

```
通信方式: JSONL文件邮箱

  目录结构:
    mailboxes/
    ├── technical-analyst.jsonl   ← 技术分析师的邮箱
    ├── bull-debater.jsonl        ← 看多辩论者的邮箱
    ├── bear-debater.jsonl        ← 看空辩论者的邮箱
    └── orchestrator.jsonl        ← 编排者的邮箱

  每个文件内容（一行一条消息）:
    {"from":"orchestrator","message":"分析300033技术面","ts":"..."}
    {"from":"bull-debater","message":"看多论据：MACD金叉","ts":"..."}

  操作:
    发送 → open("bull.jsonl", "a") 写入一行
    接收 → open("bull.jsonl", "r") 读取全部 → 清空文件

特点:
  ✅ 极简，总共不到50行代码
  ✅ 文件系统天然持久化（断电不丢数据）
  ✅ 易于调试（打开JSONL文件就能看到所有消息）
  ✅ 零外部依赖（不需要Redis、数据库、消息队列）
  ✅ 天然支持并发（每个文件独立）
  ❌ 没有事务保证（极端情况可能丢消息）
  ❌ 没有类型校验（消息格式靠约定）
  ❌ 扩展到大规模时性能有限（文件IO）
```

### 8.5 对我们项目的启发

```
可借鉴:
  ✅ 极简主义（最重要！）
     80行代码就能跑起来
     不要过度设计

  ✅ 渐进式复杂度
     先做好 Agent Loop + 3个工具
     跑通了再加 Skill + 子智能体
     再加 MessageBus + 团队协作

  ✅ Harness 哲学
     智能来自模型（GLM-5.1），不来自代码
     代码只提供: 工具、知识、通信、约束

  ✅ Skill.md 按需加载
     不把所有知识塞进system prompt
     需要时才加载，节省上下文空间

需要注意:
  ⚠️ learn-claude-code 基于 Anthropic API
     我们用 GLM-5.1，需要适配API接口
     GLM-5.1的工具调用能力需要验证

  ⚠️ 缺少生产级特性
     没有内置的熔断、质检、追踪
     需要自己加（但代码量不大）
```

---

## 九、通信机制横向对比

### 9.1 消息传递方式对比

```
┌──────────────────────────────────────────────────────────────┐
│                    六种通信方式对比                             │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ 技术     │ 传输层   │ 消息格式 │ 实时性   │ 持久化          │
├──────────┼──────────┼──────────┼──────────┼─────────────────┤
│ AG2      │ 内存     │ LLM原生  │ 实时     │ 无（内存）       │
│ A2A      │ HTTP     │ JSON-RPC │ 延迟~50ms│ 需自建           │
│ Laddr    │ HTTP/REST│ JSON     │ 延迟~50ms│ 数据库           │
│ LangGraph│ 内存     │ State字典│ 实时     │ 内建持久化       │
│ CrewAI   │ 内存     │ 任务文本 │ 实时     │ 可选             │
│ DIY      │ 文件系统 │ JSONL    │ 近实时   │ 天然持久化       │
└──────────┴──────────┴──────────┴──────────┴─────────────────┘
```

### 9.2 辩论场景适配度对比

```
辩论场景: 看多 vs 看空，一来一回，最多4轮

  AG2:      ★★★★★
    天生适合！GroupChat(max_turns=4) 直接搞定
    看多说 → 看空回 → 看多反驳 → 看空反驳

  LangGraph: ★★★★
    用条件边实现: bear → check_round → bull (循环)
    可控性强，但定义图需要写更多代码

  DIY:      ★★★★
    MessageBus.send() + read_inbox() 循环
    需要自己写循环控制，但很灵活

  CrewAI:   ★★★
    process=sequential 是线性的
    要实现辩论需要用 Flow 的 @listen/@router
    不是天然支持

  Laddr:    ★★
    REST API一来一回可以，但延迟高
    需要自己管理辩论状态

  A2A:      ★★
    协议层面支持请求/响应
    但太重了，辩论场景不需要HTTP
```

### 9.3 可控性对比

```
问题: 能否精确控制"第3步必须做什么"？

  LangGraph: ★★★★★
    图定义每一步，精确控制
    conditional_edges 可以根据条件分支

  DIY:       ★★★★★
    代码控制一切，想怎么控制就怎么控制

  Laddr:     ★★★★
    REST API编排，精确控制调用顺序

  CrewAI:    ★★★
    顺序流程可控，但内部细节不可控

  AG2:       ★★
    群聊模式不可控（LLM决定谁发言）
    需要自定义 speaker_selection

  A2A:       ★★
    协议本身不编排，需要外部编排器
```

---

## 十、可借鉴的设计模式

### 10.1 从每种技术学到什么

```
从 AG2 学:
  ✅ GroupChat 群聊模式
     直接用于看多 vs 看空辩论
     直接用于三种风控辩论

  ✅ register_function 工具注册
     简洁的工具注册方式

  ✅ max_turns 对话轮次控制
     防止辩论无限循环

从 A2A 学:
  ✅ Agent Card（名片）
     每个智能体注册时声明能力
     编排者可以动态发现可用角色

  ✅ 标准化任务协议
     请求/响应/中间状态的统一格式
     可以简化为我们自己的内部协议

  ✅ 安全模型
     工具权限白名单（每个角色只能调指定工具）

从 Laddr 学:
  ✅ @tool 装饰器
     工具定义最清晰的方式

  ✅ 可观测性设计
     每步记录到结构化日志
     可以做一个分析过程可视化面板

  ✅ 独立上下文空间
     每个智能体的消息独立管理
     避免上下文污染

从 LangGraph 学:
  ✅ 共享 State 字典
     所有分析结果统一存储
     每个角色读取需要的，写入自己负责的

  ✅ conditional_edges（条件边）
     根据结果决定下一步
     辩论轮次控制

  ✅ 持久化执行
     长任务可以中断恢复

从 CrewAI 学:
  ✅ Agent/Task/Crew 三层抽象
     角色定义非常自然
     任务期望输出明确

  ✅ YAML 配置
     角色定义和代码分离
     非技术人员可以调整

  ✅ expected_output
     明确每个任务的输出格式
     方便质检

从 DIY 学:
  ✅ 极简主义（最重要！）
     80行代码就能跑
     不要过度设计

  ✅ 渐进式复杂度
     先做最小可用，再逐步增强

  ✅ Harness 哲学
     智能来自模型，不来自代码
     代码只提供环境

  ✅ JSONL 邮箱通信
     最简单的持久化通信方式
```

### 10.2 融合设计方案

```
我们的系统将融合各技术的精华:

  基础架构: DIY 的 Agent Loop + 工具注册（~80行）
    ↓ 这是最核心的部分，保证系统简洁可控

  角色定义: CrewAI 的 Agent(role, goal, tools) + YAML配置
    ↓ 让角色定义清晰、可调整

  辩论机制: AG2 的 GroupChat(max_turns) 思想
    ↓ 用代码实现辩论循环控制

  状态管理: LangGraph 的共享State字典思想
    ↓ 所有分析结果存在统一的state中

  工具注册: Laddr 的 @tool 装饰器模式
    ↓ 工具定义清晰，可读性高

  可观测性: Laddr 的结构化日志思想
    ↓ 每步记录到JSONL，方便调试

  通信方式: DIY 的 JSONL邮箱
    ↓ 最简单、最可靠、最易调试
```

---

## 十一、最终推荐方案

### 11.1 推荐结论

```
推荐方案: DIY 为主，借鉴五种技术的精华

  不是"选一个框架"
  而是"站在六种技术的肩膀上，构建最适合自己的系统"

  为什么不选单一框架？

    AG2:    可控性差，不适合需要精确控制的分析流程
    A2A:    太新太重，我们不需要跨框架
    Laddr:  微服务过度工程化，12个角色不需要容器化
    LangGraph: 流程太静态，我们的辩论需要动态控制
    CrewAI: 辩论支持有限，内部通信不透明

  为什么选 DIY 为主？

    1. 完全可控 — 我们决定每一步做什么
    2. 极简主义 — 80行代码就能跑
    3. 渐进式 — 先跑通再逐步增强
    4. 无外部依赖 — 不需要学新框架
    5. 最适合我们的场景 — 12个角色的股票分析

  但不是"闭门造车" — 借鉴每种技术的精华:
    AG2 的辩论模式
    A2A 的名片和安全设计
    Laddr 的可观测性和工具注册
    LangGraph 的状态管理和条件控制
    CrewAI 的角色抽象和YAML配置
```

### 11.2 推荐架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    推荐系统架构                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │               Orchestrator (编排者)                    │  │
│  │  职责: 创建子智能体、管理流程、汇总结果               │  │
│  │  通信: MessageBus (JSONL邮箱)                         │  │
│  │  控制: 共享State字典 + 条件分支                        │  │
│  └─────────────┬─────────────────────────────────────────┘  │
│                |                                            │
│     ┌──────────┼──────────┐                                │
│     v          v          v                                │
│  ┌──────┐  ┌──────┐  ┌──────┐                             │
│  │技术  │  │基本面│  │新闻  │  ← 第一层: 4个分析师        │
│  │分析师│  │分析师│  │分析师│    各自独立运行              │
│  └──┬───┘  └──┬───┘  └──┬───┘    通过 @tool 注册工具      │
│     |         |         │                                  │
│     └─────────┼─────────┘                                  │
│               v                                            │
│  ┌──────────────────────────────┐                          │
│  │    DebateLoop (辩论循环)      │  ← 第二层: 辩论          │
│  │  看多 vs 看空 (max 4轮)      │    借鉴AG2的GroupChat     │
│  │  → 研究经理综合              │    用条件边控制轮次        │
│  └──────────────┬───────────────┘                          │
│                 v                                          │
│  ┌──────────────────────────────┐                          │
│  │    RiskLoop (风控循环)        │  ← 第三层: 风控          │
│  │  激进 vs 保守 vs 中性 (3轮)  │    三种视角辩论           │
│  │  → 风控经理最终裁决          │    → 输出决策             │
│  └──────────────┬───────────────┘                          │
│                 v                                          │
│  ┌──────────────────────────────┐                          │
│  │    Trader (交易员)            │  ← 第四层: 输出          │
│  │  整合所有分析，输出最终建议    │    买入/持有/卖出         │
│  └──────────────────────────────┘                          │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                 基础设施层                              │  │
│  │  MessageBus (JSONL邮箱)  — 智能体间通信                │  │
│  │  SharedState (字典)      — 共享分析结果                │  │
│  │  SkillLoader (读MD文件)  — 按需加载角色定义            │  │
│  │  TraceLogger (JSONL)     — 记录每一步操作             │  │
│  │  CircuitBreaker          — 熔断保护                   │  │
│  │  QualityChecker          — 输出质检                   │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                 工具层                                 │  │
│  │  @tool get_kline(code, start, end)                    │  │
│  │  @tool get_financials(code, period)                   │  │
│  │  @tool calc_technical(kline_data)                     │  │
│  │  @tool calc_cost(code, report_date)                   │  │
│  │  ... 15个工具                                         │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 11.3 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 通信方式 | JSONL邮箱 | 最简单、可调试、天然持久化 |
| 状态管理 | 共享State字典 | 所有分析结果统一存储 |
| 辩论控制 | 条件循环 | max_turns限制 + 条件退出 |
| 工具注册 | @tool装饰器 | 清晰、可读、易维护 |
| 角色定义 | YAML/MD配置 | 非技术人员可调整 |
| 可观测性 | JSONL追踪日志 | 每步记录、可回放 |
| 熔断机制 | 代码层强制 | 超时、最大轮次、token预算 |
| 质检 | 后置校验 | JSON schema检查输出格式 |
| LLM | GLM-5.1 | 中文能力好，价格低 |
| 数据源 | Tushare | 已有37个方法封装 |

---

## 十二、行动路线图

### 12.1 Phase 1: 能跑起来（第1周）

```
目标: 一个技术分析师智能体能独立分析一只股票

  [1.1] Agent Loop 核心循环 (~80行)
    参考: learn-claude-code s01
    改动: API换成GLM-5.1

  [1.2] @tool 装饰器 + 工具注册 (~50行)
    参考: Laddr 的工具系统
    实现: get_kline, get_financials, calc_cost 3个核心工具

  [1.3] SkillLoader (~30行)
    参考: learn-claude-code s05
    实现: 读取 technical-analyst.md

  [1.4] 验证GLM-5.1的工具调用能力
    如果不支持 → 切换到DeepSeek或其他模型

  产出:
    - agent_loop.py (~80行)
    - tool_registry.py (~50行)
    - tools/get_kline.py (~30行)
    - tools/get_financials.py (~30行)
    - skills/technical-analyst.md
    - 验证结果: GLM-5.1 能否正确调用工具
```

### 12.2 Phase 2: 全角色（第2周）

```
目标: 12个角色都能独立运行

  [2.1] 子智能体管理器 (~120行)
    参考: learn-claude-code s04
    实现: spawn_subagent() 创建和销毁

  [2.2] 编排者 Orchestrator
    参考: LangGraph 的图式编排
    实现: 顺序创建子智能体，汇总结果

  [2.3] 全部10个Skill文件
    参考: CrewAI的Agent(role,goal) + TradingAgents-CN提示词
    实现: 改写12份提示词 → 10个Skill.md

  [2.4] 共享State字典
    参考: LangGraph 的State设计
    实现: 统一的分析结果存储

  产出:
    - subagent.py (~120行)
    - orchestrator.py (~200行)
    - shared_state.py (~50行)
    - skills/ 目录下10个MD文件
    - 验证结果: 12个角色各跑一次
```

### 12.3 Phase 3: 协作+辩论（第3周）

```
目标: 完整的单股分析流程

  [3.1] MessageBus 消息总线 (~50行)
    参考: learn-claude-code s09
    实现: send/read_inbox/broadcast

  [3.2] DebateLoop 辩论循环 (~100行)
    参考: AG2 的GroupChat思想
    实现: 看多vs看空辩论，max_turns=4

  [3.3] RiskLoop 风控循环 (~80行)
    参考: AG2 的多角色辩论
    实现: 三种风控视角辩论

  [3.4] 完整流程联调
    编排者 → 4分析师 → 辩论 → 风控 → 交易员

  产出:
    - message_bus.py (~50行)
    - debate_loop.py (~100行)
    - risk_loop.py (~80行)
    - 验证结果: 完整分析300033.SZ
```

### 12.4 Phase 4: 质量+扩展（第4周）

```
目标: 生产级质量

  [4.1] 熔断机制 (~60行)
    超时、最大轮次、token预算

  [4.2] 质检模块 (~80行)
    输出JSON schema校验
    数据引用验证

  [4.3] 追踪日志 (~50行)
    每步记录到JSONL
    成本统计

  [4.4] 调度员 (~150行)
    批量分析多只股票
    并发窗口控制

  产出:
    - circuit_breaker.py (~60行)
    - quality_checker.py (~80行)
    - trace_logger.py (~50行)
    - dispatcher.py (~150行)
    - 验证结果: 10只股票批量分析
```

---

## 十三、总结

### 13.1 核心洞察

```
洞察1: 不要选框架，要选设计模式

  每种技术都有值得借鉴的设计模式:
    AG2 → 群聊辩论
    A2A → 名片发现 + 安全协议
    Laddr → 可观测性 + 微服务解耦
    LangGraph → 图式编排 + 持久化
    CrewAI → 角色抽象 + 配置分离
    DIY → 极简主义 + 渐进构建

  我们要做的是"融合"，不是"选边"
```

```
洞察2: 通信方式的选择取决于场景

  分析师 → 编排者: 共享State（直接写入字典）
  看多 ↔ 看空: JSONL邮箱（一来一回）
  风控 → 交易员: 共享State（汇总结果）
  全局追踪: JSONL日志（每步记录）

  不需要统一的通信方式
  不同场景用不同的通信方式
```

```
洞察3: 极简主义是最大的竞争力

  learn-claude-code 用 80行代码实现了 Agent Loop
  我们的系统核心也不会超过 500行

  复杂度是敌人，简洁是朋友
  先跑起来，再逐步增强
  不要一上来就设计一个"完美的架构"
```

### 13.2 风险提示

```
风险1: GLM-5.1的工具调用能力未验证
  → Phase 1 第一件事就是验证
  → 如果不行，切换到DeepSeek或Claude

风险2: 辩论可能消耗大量token
  → 12个角色 × 平均3轮 = 36次LLM调用
  → 设定token预算，超出熔断

风险3: 角色之间的信息传递可能不准确
  → JSON schema校验输出格式
  → 追踪日志帮助调试

风险4: 分析结果可能不一致（同只股票分析两次结果不同）
  → 设定随机种子
  → 关键参数固定（温度=0.1）
```

---

**报告完成** | **最后更新**: 2026-04-22

> 类比总结: 选多智能体通信技术，就像给一家投资公司选沟通工具。
> - AG2 = 让所有人坐一个会议室讨论（自然但混乱）
> - A2A = 给每家公司统一格式的传真机（标准化但太正式）
> - Laddr = 给每个人独立的办公室和邮件系统（专业但成本高）
> - LangGraph = 给每个人编号，按编号顺序传文件（有序但死板）
> - CrewAI = 写好职位描述，让大家自己协调（灵活但不可控）
> - DIY = 先用最简单的方式（微信群里发消息），够用就行
>
> 我们的选择: **先建微信群（DIY极简），再逐步升级为OA系统（借鉴各种技术精华）。**
> 不需要一上来就建一栋写字楼（Laddr），也不需要标准化传真协议（A2A）。
> 先让团队能沟通起来，再逐步优化沟通方式。
