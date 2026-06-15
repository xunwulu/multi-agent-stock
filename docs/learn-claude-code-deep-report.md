# learn-claude-code 深度分析报告

> **报告日期**: 2026-04-20 | **分析对象**: [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) | **作者**: Claude (船员)

---

## 一、项目概览

### 1.1 基本信息

| 项目 | 内容 |
|------|------|
| **仓库地址** | https://github.com/shareAI-lab/learn-claude-code |
| **Fork地址** | https://github.com/xunwulu/learn-claude-code (船长个人Fork) |
| **许可证** | MIT |
| **语言** | Python (后端) + Next.js (Web平台) |
| **依赖** | 仅2个: `anthropic>=0.25.0` + `python-dotenv>=1.0.0` |
| **文档语言** | 英语 / 中文 / 日语 (三语支持) |
| **口号** | "Bash is all you need" |

### 1.2 一句话总结

**这个仓库教你从零开始，用12个渐进式课程，手工搭建一个 Claude Code 级别的 Agent 驾驶舱（Harness）。**

### 1.3 比喻理解

如果把 Claude Code 比作一辆智能汽车：
- **模型（Claude）** = 司机，负责看路、判断、决策
- **Harness（代码）** = 汽车，给司机提供方向盘、油门、仪表盘
- 这个仓库 = 一本从"造方向盘"到"造整车"的汽车制造手册
- s01 = 只有一个方向盘的底盘（能跑）
- s_full = 配备导航、自动驾驶、车队通信的旗舰轿车

---

## 二、核心哲学 -- "Agent 是模型，不是代码"

### 2.1 颠覆性观点

这个仓库提出了一个非常鲜明（甚至有些激进）的观点：

> **Agent 的智能（Agency）来自模型训练，不是来自代码编排。**

他们用历史案例来论证：
- **2013 DeepMind DQN** -- 一个模型从像素学会玩7款Atari游戏，没有游戏专属规则
- **2019 OpenAI Five** -- 5个模型自我对弈45,000年Dota 2，打败世界冠军OG
- **2019 AlphaStar** -- 一个模型打到星际2宗师段位（前0.15%）
- **2019 腾讯绝悟** -- 一天训练等于440人类年，全面超越KPL职业选手
- **2024-2025 LLM Agent** -- Claude/GPT/Gemini 部署为编程Agent

**所有这些案例的共同点**：智能来自模型训练，代码只提供环境。

### 2.2 痛批"提示词水管工"

仓库对市场上的"拖拽式Agent平台"、"无代码AI Agent"、"提示词链编排库"进行了尖锐批评：

> "它们做出来的东西是鲁布·戈德堡机械 -- 一个过度工程化的、脆弱的过程式规则流水线，LLM被楔在里面当一个美化了的文本补全节点。那不是Agent。那是一个有着宏大妄想的shell脚本。"

核心论点：你不可能通过堆叠if-else和规则树来工程化出智能。Agency是学出来的，不是编出来的。

### 2.3 心智转换：从"开发Agent"到"开发Harness"

仓库提出了一个关键的思维转变：

| 传统思维 | Harness思维 |
|----------|-------------|
| "我要开发一个Agent" | "我要为模型搭建一个工作环境" |
| "怎么让系统做X？" | "怎么让模型能够做X？" |
| "这个任务的工作流是什么？" | "模型需要什么能力才能完成这个任务？" |
| 智能来自代码 | 智能来自模型，代码提供能力 |

**Harness的五大要素**：
```
Harness = Tools（工具） + Knowledge（知识） + Observation（观察）
        + Action Interfaces（行动接口） + Permissions（权限）
```

---

## 三、12个课程的完整架构

### 3.1 学习路径总览

```
第一阶段: THE LOOP（循环基础）         第二阶段: PLANNING & KNOWLEDGE（规划与知识）
================================     ====================================
s01  Agent Loop        [1个工具]      s03  TodoWrite              [5个工具]
     while + stop_reason                  计划管理 + 超时提醒
     |                                    |
     +-> s02 Tool Use    [4个工具]        s04  Subagents            [5个工具]
         dispatch map注册                  子代理，独立上下文
                                              |
                                         s05  Skills               [5个工具]
                                              SKILL.md按需加载
                                              |
                                         s06  Context Compact      [5个工具]
                                              三层压缩策略

第三阶段: PERSISTENCE（持久化）         第四阶段: TEAMS（团队协作）
================================     ====================================
s07  Tasks             [8个工具]      s09  Agent Teams            [9个工具]
     文件持久化任务 + 依赖图              队友 + JSONL邮箱
     |                                    |
s08  Background Tasks  [6个工具]      s10  Team Protocols         [12个工具]
     后台线程 + 通知队列                   关机协议 + 计划审批
                                          |
                                     s11  Autonomous Agents     [14个工具]
                                          空闲轮询 + 自动认领
                                          |
                                     s12  Worktree Isolation    [16个工具]
                                          Git Worktree任务隔离
```

### 3.2 每个课程详解

#### s01: Agent Loop（智能体循环） -- ~80行代码
**格言**: "One loop & Bash is all you need"

核心模式，整个仓库的基础：
```python
def agent_loop(messages):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages, tools=TOOLS,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":  # 模型说停就停
            return
        # 执行工具调用，追加结果，继续循环
```

**比喻**: 就像给司机一个方向盘（bash工具）和一条跑道（while循环），司机自己决定往哪开、什么时候停。

#### s02: Tool Use（工具注册） -- ~100行代码
**格言**: "加一个工具，只加一个handler"

- 核心设计：dispatch map（名字 -> 函数映射）
- 新增工具只需：写handler函数 + 注册到map
- 循环代码完全不用改

**比喻**: 汽车加新功能就像插U盘一样 -- 不用改发动机，加个接口就行。

#### s03: TodoWrite（任务清单） -- ~120行代码
**格言**: "没有计划的agent走哪算哪"

- TodoManager: 最多20项任务，同一时间只能有1个in_progress
- 超过3轮未更新自动提醒（nag机制）
- 效果：完成率翻倍

**比喻**: 给司机一个导航仪，不然开着开着就忘了要去哪。

#### s04: Subagents（子代理） -- ~100行代码
**格言**: "大任务拆小，每个小任务干净的上下文"

- 父代理有个`task`工具，可以派活给子代理
- 子代理用全新的`messages=[]`启动，运行自己的循环
- 子代理可能跑了30+次工具调用，但父代理只收到一段摘要
- 子代理不能递归生成子代理（防止无限套娃）

**比喻**: 老板把调研任务派给实习生，实习生跑了30个地方查资料，最后只给老板交一份一页纸的摘要报告。老板的桌子上不会堆满30份原始资料。

#### s05: Skill Loading（技能加载） -- ~130行代码
**格言**: "用到什么知识，临时加载什么知识"

- 知识以SKILL.md文件形式存在磁盘上
- 模型需要时才加载，通过tool_result注入
- 不塞进system prompt（节省上下文空间）
- 支持YAML前置元数据

**比喻**: 就像考试不是把整本教科书背进去，而是开卷考试 -- 需要查什么翻什么。

#### s06: Context Compact（上下文压缩） -- ~160行代码
**格言**: "上下文总会满，要有办法腾地方"

三层压缩策略：
1. **Layer 1 - micro_compact**: 每轮静默执行，旧工具结果替换为占位符
2. **Layer 2 - auto_compact**: token超过50,000自动触发，LLM做摘要+保存到.transcripts/
3. **Layer 3 - manual compact**: 模型主动调用compact工具

**关键**: 完整历史保存在磁盘上，信息没有真正丢失。

**比喻**: 就像人脑的工作记忆 -- 你不需要记住每一顿饭吃了什么，但真需要时可以翻日记本。大脑保持清醒，记忆存放在笔记本里。

#### s07: Task System（任务系统） -- ~200行代码
**格言**: "大目标要拆成小任务，排好序，记在磁盘上"

- 文件持久化的任务管理（.tasks/目录）
- 支持`blockedBy`依赖关系（任务A完成才能开始任务B）
- 支持`claim`认领机制
- 为多Agent协作打基础

**比喻**: 从"脑袋记事"进化到"写在项目管理软件里"，电脑关机重启也不丢。

#### s08: Background Tasks（后台任务） -- ~180行代码
**格言**: "慢操作丢后台，agent继续想下一步"

- 守护线程跑耗时命令
- 完成后通过通知队列注入结果
- Agent不会因为等一个命令而"卡住"

**比喻**: 就像你一边炖汤（后台任务），一边继续切菜炒菜（主线程），汤炖好了电饭煲会"叮"一声提醒你。

#### s09: Agent Teams（代理团队） -- ~280行代码
**格言**: "任务太大一个人干不完，要能分给队友"

- **TeammateManager**: 通过config.json维护团队名册
- **spawn()**: 创建队友并在线程中启动agent loop
- **MessageBus**: 基于JSONL文件的append-only收件箱
  - `send()` 写入一行
  - `read_inbox()` 读取全部并清空
  - `broadcast()` 广播给所有队友
- 生命周期: spawn -> WORKING -> IDLE -> WORKING -> ... -> SHUTDOWN

**比喻**: 从"个体户"进化到"公司" -- 每个员工有工牌（身份）、有邮箱（通信）、有考勤（生命周期管理）。

#### s10: Team Protocols（团队协议） -- ~320行代码
**格言**: "队友之间要有统一的沟通规矩"

- 关机握手协议（shutdown request/response）
- 计划审批机制（plan approval FSM）
- 统一的请求-响应模式驱动所有协商

**比喻**: 团队不能各说各话，需要统一的"会议规则" -- 谁先发言、怎么表决、怎么宣布散会。

#### s11: Autonomous Agents（自主代理） -- ~420行代码
**格言**: "队友自己看看板，有活就认领"

- 空闲时自动轮询任务板（每5秒一次，最长60秒）
- 发现未认领任务自动claim
- 上下文压缩后的身份重新注入（identity re-injection）
- 不需要领导逐个分配任务，自组织

**比喻**: 从"老板指派工作"进化到"员工自己看任务板找活干" -- 真正的自我驱动。

#### s12: Worktree Isolation（目录隔离） -- ~350行代码
**格言**: "各干各的目录，互不干扰"

- **控制面**（.tasks/）: 管理任务状态
- **执行面**（.worktrees/）: 每个任务独立的git worktree目录
- 任务ID绑定两边状态
- EventBus: 追加写入的事件日志（events.jsonl）
- 收尾选项: keep（保留）或 remove + complete_task（删除并完成）

**比喻**: 给每个员工分配独立的工位，工位之间互不干扰。做完可以选择保留工位或收拾走人。

### 3.3 终极版: s_full.py -- ~500行代码

将s01-s11的所有机制整合为一个可运行的全功能Agent：
- **22个工具**: bash/read/write/edit + TodoWrite + task(子代理) + load_skill + compact + background_run/check + task_create/get/update/list + spawn_teammate/list_teammates + send_message/read_inbox/broadcast + shutdown_request + plan_approval
- **REPL命令**: /compact, /tasks, /team, /inbox
- 每轮循环自动执行: 压缩管道 -> 后台通知排空 -> 收件箱检查 -> todo nag提醒

---

## 四、代码架构分析

### 4.1 文件结构

```
learn-claude-code/
|-- agents/                        # 14个Python文件
|   |-- s01_agent_loop.py          # ~80行, 1个工具
|   |-- s02_tool_use.py            # ~100行, 4个工具
|   |-- s03_todo_write.py          # ~120行, 5个工具
|   |-- s04_subagent.py            # ~100行, 5个工具
|   |-- s05_skill_loading.py       # ~130行, 5个工具
|   |-- s06_context_compact.py     # ~160行, 5个工具
|   |-- s07_task_system.py         # ~200行, 8个工具
|   |-- s08_background_tasks.py    # ~180行, 6个工具
|   |-- s09_agent_teams.py         # ~280行, 9个工具
|   |-- s10_team_protocols.py      # ~320行, 12个工具
|   |-- s11_autonomous_agents.py   # ~420行, 14个工具
|   |-- s12_worktree_task_isolation.py  # ~350行, 16个工具
|   |-- s_full.py                  # ~500行, 22个工具 (总成)
|   +-- __init__.py
|-- docs/{en,zh,ja}/               # 36个文档文件 (3语言 x 12课)
|-- web/                           # Next.js交互式学习平台
|-- skills/                        # Skill定义文件
|   |-- agent-builder/             # Agent构建技能
|   |-- code-review/               # 代码审查技能
|   |-- mcp-builder/               # MCP构建技能
|   +-- pdf/                       # PDF阅读技能
|-- tests/                         # 测试文件
+-- requirements.txt               # 仅2个依赖!
```

### 4.2 代码量分析

| 阶段 | 累计代码行数 | 累计工具数 | 新增能力 |
|------|-------------|-----------|---------|
| s01 | ~80行 | 1 | 基础循环 |
| s02 | ~100行 | 4 | 多工具注册 |
| s03 | ~120行 | 5 | 任务计划 |
| s04 | ~100行 | 5 | 子代理 |
| s05 | ~130行 | 5 | 技能加载 |
| s06 | ~160行 | 6 | 上下文压缩 |
| s07 | ~200行 | 8 | 任务持久化 |
| s08 | ~180行 | 6 | 后台任务 |
| s09 | ~280行 | 9 | 团队通信 |
| s10 | ~320行 | 12 | 团队协议 |
| s11 | ~420行 | 14 | 自主认领 |
| s12 | ~350行 | 16 | 目录隔离 |
| s_full | ~500行 | 22 | 全部合一 |

**关键洞察**: 从80行到500行，6倍代码量增长，但核心循环从未改变。所有复杂度都在循环之外的"装饰"上。

### 4.3 依赖极简主义

整个项目只依赖2个Python包：
- `anthropic>=0.25.0` -- Anthropic官方SDK
- `python-dotenv>=1.0.0` -- 环境变量管理

**比喻**: 就像盖一栋大楼，只用两种基础材料 -- 水泥和钢筋。其余全是设计。

---

## 五、核心设计模式总结

### 5.1 七大Harness机制

| 机制 | 解决的问题 | 对应课程 |
|------|-----------|---------|
| **工具注册** | 给Agent一双"手" | s01, s02 |
| **任务计划** | 让Agent有"方向感" | s03 |
| **上下文隔离** | 让Agent的"大脑"不混乱 | s04, s06 |
| **按需知识** | 让Agent有"查字典"的能力 | s05 |
| **持久化** | 让Agent的工作"不丢失" | s07, s08 |
| **团队协作** | 让多个Agent"分工合作" | s09, s10, s11 |
| **执行隔离** | 让多个Agent"各干各的" | s12 |

### 5.2 五大关键设计原则

1. **信任模型** -- 不替模型做决策，给它能力和边界就好
2. **原子化工具** -- 每个工具做一件事，可组合
3. **按需加载** -- 知识不前置，用的时候才拉取
4. **上下文是宝贵资源** -- 隔离、压缩、保护
5. **渐进式复杂度** -- 从简单开始，按需增加

### 5.3 反模式（Anti-Patterns）警告

| 反模式 | 问题 | 正确做法 |
|--------|------|---------|
| 过度工程 | 还没跑就先设计复杂架构 | 从3-5个工具开始 |
| 工具太多 | 模型反而不知道用哪个 | 精简工具集 |
| 僵化工作流 | 模型无法适应变化 | 让模型自己决定流程 |
| 前置加载知识 | 浪费上下文空间 | 按需加载 |
| 微观管理 | 限制了模型的智能 | 信任模型 |

---

## 六、延伸产品生态

### 6.1 Kode Agent CLI
- 开源编程Agent命令行工具
- 支持Skill & LSP
- Windows兼容
- 可接入GLM/MiniMax/DeepSeek等开放模型
- 安装: `npm i -g @shareai-lab/kode`

### 6.2 Kode Agent SDK
- 独立库，无per-user进程开销
- 可嵌入后端、浏览器插件、嵌入式设备
- 对比: 官方Claude Code SDK每个并发用户=一个终端进程

### 6.3 姊妹仓库 claw0
从"被动临时会话"到"主动常驻助手"：
- **心跳 (Heartbeat)**: 每30秒检查有没有事可做
- **定时任务 (Cron)**: 自己安排未来要做的事
- **IM多通道**: WhatsApp/Telegram/Slack/Discord等13+平台
- **记忆系统**: 不清空的上下文记忆
- **Soul人格**: 个性化AI助手

---

## 七、对船长的AI投资工具项目的启示

### 7.1 可以借鉴的设计思想

1. **Harness思维**: 你的AI投资工具本质上也是一个Harness -- 给模型提供数据工具（Tushare API）、分析工具（成本计算）、展示工具（K线图），模型负责分析和推理
2. **按需加载**: 不需要一次性加载所有股票数据，按需获取
3. **渐进式复杂度**: 先做好核心功能（成本测算），再逐步添加维度分析
4. **上下文管理**: 前端展示要注意信息密度，不是越多越好

### 7.2 与Claude Code的关系

你正在使用的Claude Code本身就是这套哲学的最佳实践。当你说"帮我分析300033的成本"，Claude Code的Harness提供了：
- bash工具: 执行Python脚本
- read/write工具: 读取和保存数据
- edit工具: 修改代码
- 子代理: 并行分析多只股票
- 上下文压缩: 长时间工作不崩溃

---

## 八、总体评价

### 8.1 优点

- **教学设计极佳**: 12个课程从简到繁，每课只加一个概念
- **哲学深刻**: "Agency来自训练，不是代码"的观点非常值得深思
- **代码极简**: 依赖仅2个，从80行到500行的渐进路径清晰
- **文档完善**: 三语支持，心智模型优先的教学法
- **实用性强**: 直接拆解Claude Code的生产级架构

### 8.2 适用人群

- 想理解Agent内部原理的开发者
- 想构建自己Agent产品的创业者
- 想深入理解Claude Code架构的深度用户
- 对AI Agent哲学感兴趣的思考者

### 8.3 一句话评价

> **这不是一个"如何使用Claude Code"的教程，而是一个"如何理解Agent本质"的哲学课 + "如何建造Agent环境"的工程课的合体。**

---

## 九、快速开始指南

```bash
# 1. 克隆仓库
git clone https://github.com/shareAI-lab/learn-claude-code
cd learn-claude-code

# 2. 安装依赖（仅2个！）
pip install -r requirements.txt

# 3. 配置API密钥
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY=你的密钥

# 4. 从第一课开始
python agents/s01_agent_loop.py

# 5. 交互式Web平台
cd web && npm install && npm run dev
# 打开 http://localhost:3000
```

---

**报告完成** | **最后更新**: 2026-04-20

> 类比总结：这个仓库就像一本《汽车制造手册》，从教你拧第一颗螺丝（s01），到组装整车（s_full），最后还告诉你怎么建一个车队（s09-s12）。更重要的是，它一直在强调一个道理 -- **发动机（模型）是别人造的，你的工作是造好底盘和方向盘（Harness），让发动机的力量能真正发挥出来。**
