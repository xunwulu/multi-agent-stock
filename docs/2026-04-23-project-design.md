# 项目总设计文档

> **日期**: 2026-04-23 | **状态**: 设计完成，待开发
> **作者**: 船员 (Claude) | **目标读者**: 船长

---

## 一、一句话说明

基于 learn-claude-code 的 Harness 哲学，用 GLM-5.1 模型，构建一个 12角色多智能体股票分析系统。

---

## 二、关键决策记录

### 2.1 模型选择

| 决策 | 选择 | 理由 |
|------|------|------|
| **主模型** | GLM-5.1 | 中文金融分析能力强 |
| **SDK** | anthropic（Python包） | 走通道1，覆盖在 Coding Plan Max 内 |
| **API端点** | https://open.bigmodel.cn/api/anthropic | Anthropic协议兼容端点 |
| **备选模型** | DeepSeek-V3.2 | 成本为GLM的1/4，OpenAI兼容 |
| **经济型** | glm-4-flash | 免费，工具调用已验证可用 |

### 2.2 通道选择（2026-04-23 验证）

```
通道1（Anthropic协议）— 我们的选择 ✅
  地址: https://open.bigmodel.cn/api/anthropic
  SDK:  anthropic 包
  计费: Coding Plan Max 月费覆盖
  验证: Tool Use ✅ | 多轮对话 ✅ | 并发4路 ✅ | 串行10次 ✅

通道2（OpenAI协议）— 备用
  地址: https://open.bigmodel.cn/api/paas/v4/
  SDK:  openai 包
  计费: 需要智谱平台单独充值
  验证: glm-4-flash ✅ | glm-5.1 余额不足 ❌
```

### 2.3 速率限制测试结果（2026-04-23）

| 测试 | 请求数 | 结果 | 耗时 | 说明 |
|------|--------|------|------|------|
| 串行10次 | 10 | 10/10 通过 | 117秒 | 平均11.7秒/次，无限制 |
| 并发4路 | 4 | 4/4 通过 | 24秒 | 无并发限制 |
| 并发4路+工具 | 4 | 4/4 通过 | 36秒 | 工具调用+并发无问题 |

**结论**: Coding Plan Max 在通道1上没有严格的并发或速率限制。4个分析师可以放心并行。

### 2.4 架构选择

| 决策 | 选择 | 理由 |
|------|------|------|
| **整体架构** | DIY（learn-claude-code风格） | 完全可控、极简、渐进式 |
| **通信方式** | JSONL邮箱 | 最简单、可调试、天然持久化 |
| **状态管理** | 共享State字典 | 所有分析结果统一存储 |
| **辩论控制** | 条件循环 | max_turns限制 + 条件退出 |
| **工具注册** | @tool装饰器模式 | 清晰、可读 |
| **角色定义** | Markdown Skill文件 | 非技术人员可调整 |
| **可观测性** | JSONL追踪日志 | 每步记录、可回放 |
| **数据源** | Tushare + AKShare | 37个Tushare方法 + AKShare新闻 |

---

## 三、系统架构

### 3.1 流程图

```
用户输入 "分析 300033"
    |
    v
[编排者 Orchestrator]
    |
    +-- Phase 1: 4个分析师并行
    |   [技术分析师]  [基本面分析师]  [新闻分析师]  [情绪分析师]
    |        |              |              |             |
    |        +--------------+--------------+-------------+
    |                       |
    +-- Phase 2: 辩论       v
    |   [看多辩论者] <---> [看空辩论者]  (max 4轮)
    |                       |
    +-- Phase 3: 综合       v
    |   [研究经理]  综合辩论，给出初步判断
    |                       |
    +-- Phase 4: 风控       v
    |   [激进] <---> [保守] <---> [中性]  (max 3轮)
    |                       |
    +-- Phase 5: 决策       v
    |   [风控经理]  最终决策: 买入/持有/卖出
    |                       |
    +-- Phase 6: 输出       v
        [交易员]  输出完整交易建议
```

### 3.2 核心代码调用方式

```python
import anthropic

# 通道1：Anthropic协议（Coding Plan Max 覆盖）
client = anthropic.Anthropic(
    api_key="7d0c60e2535e4deea91cd4e85472d65c.AZHB5wbt0wCOVl6o",
    base_url="https://open.bigmodel.cn/api/anthropic",
)

# Agent Loop 核心
response = client.messages.create(
    model="glm-5.1",
    max_tokens=2048,
    system=skill_content,        # 从 Skill 文件加载
    messages=messages,           # 对话历史
    tools=agent_tools,           # 该角色可用的工具
)

# 处理响应
for block in response.content:
    if block.type == "tool_use":
        result = execute_tool(block.name, block.input)
        messages.append({"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(result),
        }]})
    elif block.type == "text":
        # 模型的文字回复
        ...
```

---

## 四、项目目录结构（方案A）

```
multi-agent-stock/
│
│  ── 船长直接看的内容 ──────────────────────────────
│
├── README.md                   项目说明（船长看的第一眼）
├── docs/                       所有文档（已有的8份调研 + 本文件）
│   ├── 2026-04-23-project-design.md   ← 本文件（总设计）
│   ├── 2026-04-23-channel1-verification.md  ← 通道验证记录
│   ├── ...（已有8份文档）
│   └── tradingagents-prompts/  原始12份提示词（原材料）
│
├── skills/                     角色定义（船长可直接打开看！）
│   ├── technical-analyst.md    技术分析师的工作手册
│   ├── fundamentals-analyst.md 基本面分析师的工作手册
│   ├── news-analyst.md         新闻分析师的工作手册
│   ├── sentiment-analyst.md    情绪分析师的工作手册
│   ├── debater.md              辩论者（看多/看空，参数化）
│   ├── research-manager.md     研究经理的工作手册
│   ├── risk-debater.md         风控辩论者（激进/保守/中性）
│   ├── risk-manager.md         风控经理的工作手册
│   └── trader.md               交易员的工作手册
│
├── output/                     分析结果（船长最关心的！）
│   └── 300033_20260423/        按股票+日期组织
│       ├── final_report.md     最终投资建议报告
│       └── traces.jsonl        完整分析过程日志
│
│  ── 我写的代码 ──────────────────────────────────
│
├── src/
│   ├── core/                   核心引擎
│   │   ├── agent_loop.py       Agent Loop 核心（~80行）
│   │   ├── tool_registry.py    工具注册表（@tool装饰器）
│   │   ├── skill_loader.py     Skill文件加载器
│   │   └── state.py            共享State字典
│   │
│   ├── tools/                  12个数据工具
│   │   ├── get_kline.py        K线数据（包装Tushare 6个方法）
│   │   ├── get_stock_basic.py  股票基本信息（包装7个方法）
│   │   ├── get_financials.py   财务数据（包装8个方法）
│   │   ├── get_institutional.py 股东机构（包装4个方法）
│   │   ├── get_money_flow.py   资金流向（包装6个方法）
│   │   ├── get_chip.py         筹码数据（包装2个方法）
│   │   ├── get_index.py        指数数据（包装3个方法）
│   │   ├── get_macro.py        宏观数据（包装3个方法）
│   │   ├── get_news.py         新闻公告（AKShare 2个接口）
│   │   ├── calc_cost.py        成本测算（已有3种算法）
│   │   ├── calc_technical.py   技术指标计算（新写）
│   │   └── calc_valuation.py   估值计算（新写）
│   │
│   ├── agents/                 智能体实现
│   │   ├── orchestrator.py     编排者（总指挥）
│   │   ├── debate_loop.py      辩论循环控制
│   │   └── risk_loop.py        风控循环控制
│   │
│   └── infra/                  基础设施
│       ├── message_bus.py      JSONL邮箱通信
│       ├── tracer.py           追踪日志
│       ├── circuit_breaker.py  熔断保护
│       └── quality.py          输出质检
│
├── config/
│   └── model.json              模型配置（API地址、token、模型名）
│
│  ── 自动生成 ──────────────────────────────────
│
├── mailboxes/                  智能体邮箱（JSONL文件，运行时自动创建）
└── requirements.txt            Python依赖（anthropic, akshare, tushare, pandas）
```

### 4.1 设计原则

```
1. 船长能看懂的部分在顶层
   README.md / skills/ / output/ → 船长直接打开看
   不需要懂代码就能理解每个角色的定义和每次分析的结果

2. 代码分层清晰
   core/    → 最核心的循环（改最少）
   tools/   → 数据工具（改最多，一个工具一个文件）
   agents/  → 智能体逻辑（编排和流程控制）
   infra/   → 基础设施（通信、日志、保护）

3. 每个文件职责单一
   一个工具 = 一个文件
   一个Skill = 一个文件
   改一个不影响其他

4. 输出和代码分离
   output/  和代码完全分离
   分析结果可以独立查看、分享、归档
```

---

## 五、12个Agent工具清单

| # | 工具名 | 数据源 | 包装方法数 | 工作量 |
|---|--------|--------|----------|--------|
| 1 | get_kline | Tushare | 6 | 小 |
| 2 | get_stock_basic | Tushare | 7 | 小 |
| 3 | get_financials | Tushare | 8 | 小 |
| 4 | get_institutional | Tushare | 4 | 小 |
| 5 | get_money_flow | Tushare | 6 | 小 |
| 6 | get_chip | Tushare | 2 | 小 |
| 7 | get_index | Tushare | 3 | 小 |
| 8 | get_macro | Tushare | 3 | 小 |
| 9 | get_news | AKShare | 2 | 小 |
| 10 | calc_cost | 已有代码 | 3种算法 | 小 |
| 11 | calc_technical | 新写 | MACD/RSI/BOLL | 中 |
| 12 | calc_valuation | 新写 | PE/PB/PEG | 中 |

---

## 六、开发路线图

### Phase 1: 最小可运行（第1周）

```
目标: 一个技术分析师能独立分析一只股票

  [1.1] 创建项目目录结构
  [1.2] 实现 agent_loop.py（~80行，核心循环）
  [1.3] 实现 tool_registry.py（~50行，工具注册）
  [1.4] 实现 get_kline.py（第1个工具）
  [1.5] 实现 skill_loader.py（加载Skill文件）
  [1.6] 编写 technical-analyst.md（第1个Skill）
  [1.7] 跑通: 输入股票代码 → 技术分析报告

  代码量: ~200行 + 1个Skill文件
```

### Phase 2: 全角色（第2周）

```
目标: 完整的单股分析流程

  [2.1] 包装剩余11个工具
  [2.2] 编写剩余9个Skill文件
  [2.3] 实现 orchestrator.py（编排者）
  [2.4] 实现 state.py（共享状态）
  [2.5] 12个角色各自独立跑通
```

### Phase 3: 协作+辩论（第3周）

```
目标: 完整的多角色协作流程

  [3.1] 实现 message_bus.py（JSONL邮箱）
  [3.2] 实现 debate_loop.py（辩论循环）
  [3.3] 实现 risk_loop.py（风控循环）
  [3.4] 连通全流程: 分析师 → 辩论 → 风控 → 交易员
```

### Phase 4: 质量+扩展（第4周）

```
目标: 生产级质量

  [4.1] 实现熔断保护
  [4.2] 实现输出质检
  [4.3] 实现追踪日志
  [4.4] 实现批量分析（调度员）
```

---

## 七、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| Coding Plan 有隐藏的月度用量上限 | 可能无法批量分析 | 监控用量，必要时切DeepSeek |
| GLM-5.1 输出格式不稳定 | 质检失败率高 | 加后置校验 + 重试 |
| 12角色总token消耗超预期 | 单股分析太贵 | 估算约0.05-0.2元/只（取决于套餐） |
| 辩论进入死循环 | 分析卡住 | max_turns=4 强制结束 |
| AKShare 接口不稳定 | 新闻分析无数据 | Tushare备用 + 降级提示 |

---

## 八、依赖清单

```
Python 依赖:
  anthropic>=0.96.0    ← Anthropic SDK（通道1）
  akshare              ← 新闻数据
  tushare              ← 行情/财务数据
  pandas               ← 数据处理
  numpy                ← 数值计算
```

---

**文档完成** | **最后更新**: 2026-04-23
**状态**: 设计完成，材料充分，准备进入 Phase 1 开发

> 类比: 这份文档就是我们的"施工蓝图"。从现在开始，不再是"研究菜谱"阶段，
> 而是"照着蓝图炒菜"阶段。第一道菜（技术分析师）本周就可以出锅。
