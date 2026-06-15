# 投研 Skills 深度分析报告

> **报告日期**: 2026-04-22 | **分析对象**: Alpha派 (PaiWork) + 同花顺 iFinD 两个投研 Skills 体系
> **文件位置**: C:\Users\ZhangXuesen\Desktop\ifind\ | **规模**: 658个文件，约71个SKILL.md
> **关联文档**: [准备清单](2026-04-22-agent-preparation-guide.md) | [获取策略](2026-04-22-material-acquisition-strategy.md) | [子智能体架构](2026-04-21-sub-agent-architecture.md)

---

## 一、项目概览

### 1.1 两个独立的投研 Skills 体系

本次分析覆盖了**两个完全不同的公司**的 Claude Code 投研 Skills：

| 来源 | 公司/产品 | 规模 | 定位 | 技术特征 | 邮箱域名 |
|------|----------|------|------|---------|---------|
| **Alpha派 (PaiWork)** | 独立投研平台（具体公司未知） | ~38个Skill | 面向投研从业者的完整工作台 | SKILL.md + references/，使用 search_paipai/data_analyst 等专有工具 | 未知 |
| **iFinD (同花顺)** | Hithink RoyalFlush（同花顺） | ~33个Skill（3个插件） | 金融数据终端 + 研究方法论 | plugin.json + SKILL.md + Python CLI脚本，使用 MCP 服务器 | @myhexin.com |

**关键证据**：iFinD Skills 的 `financial-deep-analysis` 明确将"Alpha派"列为**禁止使用的竞争对手数据源**，确认两家是独立公司。

### 1.2 覆盖的投研工作全链

```
【Alpha派 体系】
  数据层:    cn-stock-data, hk-stock-data, us-stock-data, edb-macro-data, sec-api-pro
  分析层:    financial-models (DCF/三表/LBO/comps等)
  报告层:    company-one-pager (中/港/美), daily-movers-recap, global-market-daily
  辩论层:    fact-debate
  事件层:    announcement-commentary, event-commentary, macro-event-analysis
  行情层:    realtime-market-data
  跟踪层:    marginal-change-tracker, thematic-stock-screening
  情绪层:    alphapai-market-sentiment-data

【iFinD 体系】
  数据层:    ifind-data, ifind-edb, ifind-news, ifind-notice, ifind-report, ifind-stats-report
  分析层:    financial-deep-analysis (五层递进+17行业适配), industry-analysis (9模块+7覆盖层)
  报告层:    company-research-pro-cn (统一入口), earnings-review
  基金层:    fund-analysis, etf-analysis, fund-manager-analysis, fund-comparison, fund-company-analysis, fund-market-analysis
  质检层:    data-accuracy-evaluator
  功能层:    bond-calculate, broker-gold-stocks
  输出层:    xlsx, docx, pptx 模板
```

**一句话总结**: 这是目前我们能找到的、最完整的两套"如何用 Claude Code 做专业投研分析"的实战参考，分别来自两家独立公司。

---

## 二、架构分析

### 2.1 Alpha派 架构：Agent委托链

```
用户请求
  ↓
Claude (主代理/MainAgent) ← 加载匹配的 SKILL.md
  ↓ 数据收集（全部并行）
delegate_to_agent(agent_type="data_analyst") → SQL查询 → 数据库
delegate_to_agent(agent_type="doc_searcher") → 文档检索 → ES索引
search_paipai() → 语义搜索 → 研报/纪要/公告
  ↓ 数据汇总
MainAgent 将原始数据保存到临时文件（不做任何处理）
  ↓ 分析生成
analyst_report(files=[...], model="Gemini 2.5 Pro") → 最终报告
```

**核心设计**: MainAgent 只做"数据搬运工"，不做分析。真正的分析由专门的 analyst 模型完成。

### 2.2 iFinD 架构：插件市场 + Python CLI

```
Marketplace (marketplace.json)
  |
  +-- Plugin A (ifind-plugin) v2.1.10
  |     |-- plugin.json (清单: skills目录, agents列表, hooks配置)
  |     |-- hooks/ (会话生命周期管理, 环境变量注入)
  |     |-- agents/data-collector.md (数据收集编排者)
  |     |-- skills/
  |     |     |-- ifind-data/     (数据浏览器)
  |     |     |-- ifind-edb/      (宏观指标)
  |     |     |-- ifind-news/     (新闻资讯)
  |     |     |-- ifind-notice/   (公告)
  |     |     |-- ifind-report/   (研报)
  |     |     +-- ifind-stats-report/ (统计报表)
  |
  +-- Plugin B (ifind-research) v1.2.1
  |     +-- skills/ (27个研究方法论Skill)
  |
  +-- Plugin C (ifind-functional) v0.0.0
        +-- skills/ (债券计算器, 券商金股)
```

**核心设计**: 数据通过 Python CLI 脚本调用 MCP 服务器获取，研究方法论通过 SKILL.md + references/ 渐进加载。

### 2.3 iFinD Hook 系统（会话生命周期管理）

```bash
# hooks/hooks.json 定义了4种触发器:
startup  → 新会话启动时
resume   → 恢复会话时
clear    → 清除上下文时
compact  → 上下文压缩时

# 每种触发器执行同一个脚本:
bash load_env.sh
  → 将 IFIND_MCP_AUTH_TOKEN 注入到会话环境变量
  → 确保所有Skill脚本能随时访问认证信息
```

### 2.4 两家架构对比

| 维度 | Alpha派 | iFinD |
|------|---------|-------|
| 数据获取 | 内置 Agent 委托（data_analyst/doc_searcher） | Python CLI → MCP 服务器 |
| 分析执行 | analyst_report（调用外部模型） | Claude 自身按 Skill 指令分析 |
| 覆盖范围 | 中/港/美三市场，重"分析" | A股为主，重"数据+研究方法论" |
| 质检方式 | 提示词约束 + "宁可错过不要错误"原则 | Python 校验脚本 + 4层质量控制 |
| 特色优势 | 正反辩论、事件点评、边际变化跟踪 | 五层财务分析、行业适配层、正式交付流程 |

---

## 三、Skill 设计模式分析（八大模式）

### 模式1: "数据搬运工 vs 分析大脑" 分离

**来源: Alpha派** | **出现在**: announcement-commentary, company-one-pager, fact-debate

```
MainAgent 的职责（严格限制）:
  ✅ 确认输入（公司名、股票代码）
  ✅ 调用工具获取原始数据
  ✅ 将原始数据保存到临时文件
  ✅ 把文件路径列表传给 analyst
  ❌ 禁止对数据做任何处理（不总结、不裁剪、不分析）
  ❌ 禁止读取中间文件内容
  ❌ 禁止自行输出分析结论

Analyst 的职责:
  ✅ 接收大量原始数据文件
  ✅ 独立完成深度分析
  ✅ 输出最终报告
```

**为什么好**: 防止"传递损耗"——中间环节不做摘要，保证分析师拿到完整原始材料。

**对我们的启发**: 我们的子智能体之间传递数据时，也应该传递完整原始数据，不压缩。

---

### 模式2: 渐进式文档加载

**来源: 两家共有** | **出现在**: 几乎所有 Skill

```
主 SKILL.md: 只有框架和路由逻辑 (~100-200行)
  ↓ 需要时才加载
references/xxx.md: 具体执行细则 (~500-2000行)
```

示例（iFinD - financial-deep-analysis）:
```
SKILL.md (主文件, ~350行):
  "本层分析涉及商业模式识别，执行本层时读取参考文档获取完整指令：
   → 读取 references/business_model_analysis.md"

references/ (8个文件, 共~5000行):
  business_model_analysis.md  (~800行)
  performance_overview.md     (~600行)
  profitability_analysis.md   (~700行)
  cashflow_analysis.md        (~600行)
  asset_quality_analysis.md   (~700行)
  comprehensive_assessment.md (~400行)
  formatting_guide.md         (~300行)
  financial_industry.md       (~900行)
```

**为什么好**: 不浪费上下文空间。只有执行到某一步时才加载对应的详细指令。

**对我们的启发**: 我们的 Skill 文件也应该采用"主文件 + references/"的渐进式加载。

---

### 模式3: 并行数据收集

**来源: Alpha派** | **出现在**: company-one-pager 等几乎所有 Skill

```python
# company-one-pager 的数据收集（全部并行）:
search_paipai(...)           # 语义搜索
doc_searcher(...)            # 文档检索
quick_fetch_stock_financials(...) # 财务数据
# 三个任务同时发起，不等待
```

**规则**:
- 相互独立的查询必须并行
- 有依赖关系的查询必须串行
- 数据到达后，分析仍按逻辑顺序进行

**对我们的启发**: 4个分析师（技术面/基本面/新闻/情绪）应该并行工作。

---

### 模式4: 正反双路检索

**来源: Alpha派** | **出现在**: fact-debate

```
用户观点: "光伏行业明年将迎来拐点"

Step 1: 拆解为3-5个子命题
Step 2: 每个子命题设计两组检索关键词:
  正向关键词: 产能扩张/新建产线/营收增长
  反向关键词: 产能过剩/开工率下滑/价格战
Step 3: 分别用两组关键词检索
Step 4: 综合正反材料生成质疑报告
```

**为什么好**: 避免"确认偏差"——只找支持自己观点的证据。

**对我们的启发**: 我们的"看多/看空辩论"Skill 也应该强制正反两面都检索数据。

---

### 模式5: 五层递进分析框架

**来源: iFinD** | **出现在**: financial-deep-analysis

```
第一层: 商业模式画像 → "靠什么赚钱？"
  ↓ 产出: "财务特征预期清单"（后续层的对照基准）
第二层: 业绩总览 → "干得怎么样？"
  ↓ 产出: "需要深入解释的关键疑问清单"
第三层: 盈利拆解 → "赚钱效率如何？"
  ↓ 回答第二层的疑问
第四层: 现金流 → "利润变成真金白银了吗？"
  ↓ 用现金流验证利润质量
第五层: 资产质量 → "家底怎么样？"
  ↓ 验证资产是否支撑融资
回填第一章: 综合评估（最后写，不是最先写！）
```

**每一层的特色**:
- 章首必须有"承接段"（上一层揭示了什么）
- 章尾必须有"衔接段"（引出下一层需要验证的问题）
- 风险信号实时识别，不是事后排查
- 行业适配：17个行业各有特殊分析重点

**对我们的启发**: 我们的"基本面分析师"Skill 可以直接采用这个五层框架。

---

### 模式6: 数据准确性核查流水线

**来源: iFinD** | **出现在**: data-accuracy-evaluator

```
6步流水线:
  1. 准备工作 → 创建任务目录
  2. 提取文本 → 文档转纯文本
  3. 抽取数据项 → 识别需要验证的量化数据（13个字段）
  4. 验证数据 → 5级验证优先级链
  5. 计算准确率 → 100%或0%，没有中间值
  6. 输出结果 → Excel报告 + 标注修改的原文

验证优先级链（每个数据项必须按顺序执行）:
  source_url → iFind结构化查询 → iFind公告 → iFind研报 → web搜索
  ↓ 每一步失败才进入下一步
  ↓ 最终仍失败 → 定向搜索（只搜主体+指标名）
  ↓ 仍然失败 → 标记 "无法验证"（不是0%）
```

**对我们的启发**: 我们的质检层可以参考这个5级验证优先级链。

---

### 模式7: 行业覆盖层系统（Overlay System）

**来源: iFinD** | **出现在**: industry-analysis

```
核心9个分析模块:
  政策 → 产业链 → 技术 → 供需 → 规模 → 竞争 → 景气 → 前景 → 估值
  （形成DAG有向无环图，后续模块接收前序模块的输出）

7个行业覆盖层（S1-S7）可以:
  追加（Append）: 在核心模块后添加专有模块
  替换（Replace）: 用行业专属模块替换通用模块
  跳过（Skip）:    跳过不适用的模块
  修改（Override）: 调整通用模块的分析重点
```

**类比**: 核心模块是"通用零件"，覆盖层是"行业定制件"——就像乐高积木，基础框架不变，通过不同的插件适配不同行业。

**对我们的启发**: 我们的 Skill 可以设计"核心分析框架 + 行业适配层"。

---

### 模式8: 明确失败条件（Explicit Failure Conditions）

**来源: Alpha派** | **出现在**: macro-event-analysis

```
六步分析框架:
  Step 1: 关键变量（最多7个，分领先/同步/滞后）
  Step 2: 传导路径（事件→变量→资产，标注时滞）
  Step 3: 历史类似案例（2-4个）
  Step 4: 情景推演（基准/乐观/悲观 + 概率权重）
  Step 5: 交易表达（具体到工具/合约/方向/对冲）
  Step 6: 失败条件 ← 最独特的部分
    → 定义"什么信号出现说明我的分析错了"
    → 列出可观察、可量化的退出规则
    → 迫使分析师保持"知识诚实"
```

**对我们的启发**: 我们的"风控经理"Skill 应该也要求输出"失败条件"。

---

### 八大模式来源汇总

| 模式 | 名称 | 来源 | 具体 Skill |
|------|------|------|-----------|
| 1 | 数据搬运工 vs 分析大脑分离 | **Alpha派** | announcement-commentary, company-one-pager, fact-debate |
| 2 | 渐进式文档加载 | **两家共有** | 几乎所有 Skill |
| 3 | 并行数据收集 | **Alpha派** | company-one-pager |
| 4 | 正反双路检索 | **Alpha派** | fact-debate |
| 5 | 五层递进分析框架 | **iFinD** | financial-deep-analysis |
| 6 | 数据准确性核查流水线 | **iFinD** | data-accuracy-evaluator |
| 7 | 行业覆盖层系统 | **iFinD** | industry-analysis |
| 8 | 明确失败条件 | **Alpha派** | macro-event-analysis |

---

## 四、质量控制机制分析

### 4.1 四层质量控制体系

```
第1层: 提示词级约束（两家共有）
  ┌─────────────────────────────────────────────┐
  │ 时间感知规范:                                 │
  │   - 禁止"时间穿越"（用旧数据解释新情况）       │
  │   - 禁止对已披露数据使用"预计""预测"            │
  │   - 禁止无锚点的时间模糊词                     │
  │                                              │
  │ 写作规范:                                     │
  │   - 先结论后论据（加粗观点句 + 数据支撑）       │
  │   - 禁止空洞定性描述（"大幅增长"必须量化）      │
  │   - 禁止夸张偏激措辞（"暴雷""断崖式暴跌"）     │
  │   - 禁止直接引用券商名（应内化为自身结论）      │
  │                                              │
  │ 事实正确性:                                   │
  │   - 口径一致性（年报对年报，归母对归母）        │
  │   - 图表与正文一致性                          │
  │   - 数值精度（用精确值计算，不用近似值）        │
  └─────────────────────────────────────────────┘

第2层: 数据源优先级（来源: iFinD）
  ┌─────────────────────────────────────────────┐
  │ 用户数据 > iFinD数据 > 网页搜索               │
  │                                              │
  │ 冲突处理: 以高优先级来源为准，标注差异          │
  │                                              │
  │ 权威性排序:                                   │
  │   公告 > 研报 > 纪要 > 点评 > 社媒            │
  └─────────────────────────────────────────────┘

第3层: 校验脚本（来源: iFinD）
  ┌─────────────────────────────────────────────┐
  │ data-accuracy-evaluator:                     │
  │   validate_data_items.py   → 校验13个字段    │
  │   verify_batch.py          → 分组验证进度     │
  │   validate_output.py       → 校验最终输出     │
  │                                              │
  │ company-research-pro-cn:                     │
  │   validate_formal_delivery.py → 校验报告合同   │
  └─────────────────────────────────────────────┘

第4层: 红旗信号系统（来源: iFinD - financial-deep-analysis）
  ┌─────────────────────────────────────────────┐
  │ 财务分析中的红旗信号（示例）:                   │
  │   - Q4收入占比>30% → 年末冲量嫌疑             │
  │   - 毛利率3年连降 → 竞争力恶化                │
  │   - 商誉/净资产>30% → 高减值风险              │
  │   - 核心利润/报表利润<50% → 利润质量堪忧       │
  │   - 净现比2年偏离基线 → 盈利质量警告           │
  │                                              │
  │ 多信号共振自动升级风险等级                     │
  │   （如：收入异常+应收扩张+现金流背离 = 核心风险）│
  └─────────────────────────────────────────────┘
```

### 4.2 准确率判定规则（来源: iFinD - data-accuracy-evaluator）

```
data-accuracy-evaluator 的严格规则:

  | 情况                 | 准确率  |
  |---------------------|--------|
  | 数值和单位都一致      | 100%   |
  | 数值或单位不一致      | 0%     |
  | 无法验证              | 留空    |

  注意: 不存在95%、80%这样的中间值！

  容差规则:
    百分比 ≤ 0.5个百分点
    绝对数值 ≤ 验证值 × 1%
    单位错误 → 直接判定不一致
```

### 4.3 "宁可错过，不要错误"原则（来源: Alpha派 - marginal-change-tracker）

```
marginal-change-tracker 的核心原则:

  弱权威来源（点评、研报、公众号）必须同时满足4个标准:
    1. 有具体数据（不能是模糊描述）
    2. 有增量信息（不是已知信息的重复）
    3. 有显著变化（不是微小的正常波动）
    4. 有可追溯来源（能找到原始出处）

  不满足任何一条 → 不纳入跟踪记录
  "错误的边际变化比没有边际变化更糟糕"
```

---

## 五、具体的 Skill 写作对比

### 5.1 提示词风格对比

```
TradingAgents-CN（我们之前提取的）:
  "绝对禁止在没有调用工具的情况下直接回答"
  "绝对禁止基于推测或假设生成任何分析内容"
  "现在立即开始调用工具！不要说任何其他话！"
  → 风格: 命令式，大量emoji，像在逼一个不听话的员工

Alpha派 Skills:
  "唯一取数路径: delegate_to_agent(agent_type='data_analyst')"
  "禁止对检索数据做任何处理: 所有数据禁止进行过滤、裁剪、摘要、总结"
  "MainAgent的唯一任务是为Analyst提供充实的基础信息，而非自行承担分析工作"
  → 风格: 清晰指引，不带情绪，像在写一份精确的岗位说明书

iFinD Skills:
  "所有外部数据、资料、材料默认先走 iFinD"
  "正文不暴露工具调用名称，只写人类可读来源"
  "每个核心判断都要回答：为什么、关键驱动、持续条件、失效条件、接下来跟什么"
  → 风格: 规范导向，强调决策视角，像在写投研合规手册

我们应该采用的风格:
  "你负责技术面分析。调用 get_kline 获取K线数据，然后分析。"
  "分析完成后，输出 JSON 格式报告。"
  → 清晰指引 + 灵活空间，不微观管理
```

### 5.2 输出格式对比

```
TradingAgents-CN:
  - 要求800字最低长度（导致填充废话）
  - 要求特定标题名（太死板）
  - 没有结构化JSON输出要求

Alpha派 Skills:
  - 报告长度灵活，视分析深度而定
  - 结论前置: 每段第一句必须是加粗的观点判断句
  - 数据支撑: 每个判断必须有具体数字
  - 来源标注: 必须标注数据来源

iFinD Skills:
  - 正式深度报告目标 8,000-12,000 字
  - 正文骨架固定为10章
  - 图表最低标准: 至少4图4表
  - 交付顺序: Markdown → 校验 → xlsx → docx

我们应该采用:
  - JSON结构化输出（方便后续智能体读取）
  - 包含score/summary/report三个层次
  - 每个结论必须有具体数字支撑
  - 来源标注
```

---

## 六、对我们项目的启发（十条具体建议）

### 启发1: Skill文件结构采用"主文件 + references/"模式
**灵感来源: 两家共有**（Alpha派和iFinD均采用此模式）

```
每个角色的Skill目录:
  skills/technical-analyst/
    SKILL.md                    # 主文件（~150行）
    references/
      analysis-framework.md     # 分析框架详细说明
      output-template.md        # 输出模板
      industry-overlays/        # 行业适配层（可选）
        bank.md
        realestate.md
        ...
```

**理由**: 两家公司的最佳实践一致，也和 learn-claude-code 的按需加载理念吻合。主文件控制在150行以内，详细指令按需加载。

---

### 启发2: 采用"数据搬运工 vs 分析大脑"的分离架构
**灵感来源: Alpha派**（announcement-commentary, company-one-pager, fact-debate）

```
我们的子智能体有两种角色:

角色A: 数据收集者（Collector）
  - 只负责调用工具获取原始数据
  - 不做任何分析、总结、裁剪
  - 把完整原始数据传递给下一个智能体

角色B: 分析者（Analyst）
  - 接收完整原始数据
  - 独立完成分析
  - 输出结构化报告
```

**应用**: 4个分析师（技术面/基本面/新闻/情绪）都是"收集者+分析者"一体，但要把"收集原始数据"和"分析结论"两个步骤在Skill里明确分开。

---

### 启发3: 基本面分析师直接采用五层递进框架
**灵感来源: iFinD**（financial-deep-analysis，含8个reference文件共~5000行）

```
基本面分析师 Skill 的工作流程:

  第一步: 加载 references/financial-framework.md
  第二步: 执行五层分析:
    Layer 1: 商业模式画像 → 产出"财务特征预期清单"
    Layer 2: 业绩总览 → 产出"关键疑问清单"
    Layer 3: 盈利拆解 → 回答第二层的疑问
    Layer 4: 现金流 → 验证利润质量
    Layer 5: 资产质量 → 评估家底
  第三步: 输出结构化JSON报告
```

**理由**: iFinD 的 financial-deep-analysis Skill 有~5000行参考文档，覆盖了17个行业的特殊适配规则，我们不需要从零设计，直接借鉴。

---

### 启发4: 辩论环节强制"正反双路检索"
**灵感来源: Alpha派**（fact-debate，含 report-prompt.md 辩论方法论）

```
看多辩论者 Skill:
  第一步: 分析4份报告，识别看多机会
  第二步: 检索"看多证据"（正向关键词）
  第三步: 检索"看空风险"（反向关键词）← 关键！
  第四步: 综合正反材料，构建看多论证
  第五步: 通过消息总线发送给看空辩论者

看空辩论者 Skill:（镜像对称）
  第一步: 分析4份报告，识别看空风险
  第二步: 检索"看空证据"（正向关键词）
  第三步: 检索"看多机会"（反向关键词）← 关键！
  第四步: 综合正反材料，构建看空论证
  第五步: 通过消息总线发送给看多辩论者
```

**理由**: Alpha派 fact-debate Skill 的核心价值在于"不能只找支持自己观点的证据"。

---

### 启发5: 质检层采用"5级验证优先级链"
**灵感来源: iFinD**（data-accuracy-evaluator，含6步流水线和Python校验脚本）

```
我们质检模块的验证优先级:

  Level 1: 原始数据对比（对比工具返回的原始数据）
  Level 2: JSON格式校验（schema检查）
  Level 3: 数值合理性检查（PE是否在0-1000之间）
  Level 4: 逻辑一致性检查（多份报告结论是否矛盾）
  Level 5: 外部数据交叉验证（可选，调用额外数据源）

  准确率规则（参考iFinD）:
    数值和单位都一致 → 100%
    不一致 → 0%
    无法验证 → 留空（不是0%）
```

---

### 启发6: 所有分析师输出必须"结论前置 + 数据支撑"
**灵感来源: 两家共有**（Alpha派和iFinD均有此写作规范）

```
每个分析报告的段落格式:

  **加粗的观点判断句**（结论）
  → 纵向趋势数据（和自己历史比）
  → 横向对比数据（和同行比）
  → 业务归因（为什么这样）
  → 量化支撑（具体数字）

  禁止:
    ❌ 空洞定性描述（"毛利率下降"→ 必须说"从38.2%降至31.5%"）
    ❌ 只有数据没有结论
    ❌ 只有结论没有数据
    ❌ 夸张偏激措辞
```

---

### 启发7: 风控经理必须输出"失败条件"
**灵感来源: Alpha派**（macro-event-analysis 的六步分析框架）

```
风控经理 Skill 的输出格式:
{
  "decision": "买入/持有/卖出",
  "target_price": 38.50,
  "confidence": 0.75,
  "risk_score": 0.35,
  "reasoning": "...",
  "failure_conditions": [       ← 参考 Alpha派 macro-event-analysis
    {
      "signal": "股价跌破35元",
      "meaning": "市场不认可估值逻辑",
      "action": "减仓50%"
    },
    {
      "signal": "Q2营收增速低于10%",
      "meaning": "增长逻辑证伪",
      "action": "全部清仓"
    }
  ],
  "tracking_indicators": [...]  ← 需要持续跟踪的指标
}
```

**理由**: 迫使风控经理保持"知识诚实"，预先定义"什么情况下我的判断会错"。

---

### 启发8: 时间感知规范
**灵感来源: iFinD**（financial-deep-analysis 的 formatting_guide.md）

```
所有智能体必须遵守的时间规则（参考 iFinD financial-deep-analysis）:

  1. 分析开始前先确认当前日期
  2. 禁止"时间穿越"（用2023年数据解释2025年的情况）
  3. 禁止对已披露数据使用"预计""预测"
  4. "目前""最近"等模糊词必须锚定具体日期
  5. 比较必须同口径（年报对年报，季报对季报）
  6. 金额单位统一（不要前半段用亿，后半段用万）
```

---

### 启发9: 行业适配层设计
**灵感来源: iFinD**（industry-analysis，9核心模块 + 7行业覆盖层）

```
我们的分析师 Skill 可以加一个行业适配机制:

  core-analysis.md (通用分析框架)
    ↓ 根据股票所属行业加载
  industry-overlays/
    bank.md         → 金融行业特殊规则
    realestate.md   → 房地产行业特殊规则
    pharma.md       → 医药行业特殊规则
    tech.md         → 科技行业特殊规则
    manufacturing.md → 制造业特殊规则
    ...

  每个覆盖层可以:
    - 替换某些通用分析指标
    - 添加行业专属分析维度
    - 调整红旗信号的阈值
```

**理由**: iFinD 的行业适配系统覆盖了17个行业，证明了"通用框架+行业插件"的模式是可行的。

---

### 启发10: 数据源优先级链
**灵感来源: iFinD**（data-accuracy-evaluator 的验证优先级 + company-research-pro-cn 的数据源规范）

```
我们的数据获取应该遵循的优先级:

  Level 1: 用户提供的持仓数据（机构名称、报告期）
  Level 2: Tushare Pro API（我们已有37个方法）
  Level 3: AKShare（补充新闻数据）
  Level 4: 网页搜索（最后兜底）

  冲突处理规则:
    不同来源数据冲突 → 以高优先级来源为准
    数据获取失败 → 明确标注"数据缺失"，不要编造
    数据过时 → 标注数据截止日期
```

---

### 十条启发来源汇总

| 序号 | 启发 | 来源 | 具体 Skill |
|------|------|------|-----------|
| 1 | 主文件 + references/ 渐进加载 | **两家共有** | 几乎所有 Skill |
| 2 | 数据搬运工 vs 分析大脑分离 | **Alpha派** | announcement-commentary, company-one-pager, fact-debate |
| 3 | 五层递进财务分析框架 | **iFinD** | financial-deep-analysis |
| 4 | 辩论环节正反双路检索 | **Alpha派** | fact-debate |
| 5 | 5级验证优先级链 | **iFinD** | data-accuracy-evaluator |
| 6 | 结论前置 + 数据支撑 | **两家共有** | 两家通用写作规范 |
| 7 | 风控输出失败条件 | **Alpha派** | macro-event-analysis |
| 8 | 时间感知规范 | **iFinD** | financial-deep-analysis |
| 9 | 行业适配层 | **iFinD** | industry-analysis |
| 10 | 数据源优先级链 | **iFinD** | data-accuracy-evaluator + company-research-pro-cn |

---

## 七、可直接复用的参考文档清单

| 我们的Skill | 可参考的文档 | 来源 | 参考内容 |
|------------|------------|------|---------|
| technical-analyst.md | realtime-market-data + daily-movers-recap | **Alpha派** | 数据获取+分析流程 |
| fundamentals-analyst.md | financial-deep-analysis (8个references) | **iFinD** | 五层递进分析框架 |
| news-analyst.md | ifind-news + announcement-commentary | **iFinD + Alpha派** | 新闻获取(iFinD) + 点评流程(Alpha派) |
| sentiment-analyst.md | alphapai-market-sentiment-data | **Alpha派** | 情绪数据获取 |
| debater.md | fact-debate (report-prompt.md) | **Alpha派** | 辩论方法论+正反检索 |
| research-manager.md | company-research-pro-cn | **iFinD** | 投资决策框架 |
| trader.md | event-commentary | **Alpha派** | 交易建议输出格式 |
| risk-debater.md | macro-event-analysis | **Alpha派** | 多角度分析+失败条件 |
| risk-manager.md | data-accuracy-evaluator | **iFinD** | 质检流程+准确率判定 |

---

## 八、类比总结

```
如果把我们的多智能体股票分析系统比作开一家投研公司:

  Alpha派 = 一家敏捷型精品投研公司的"员工培训手册"
  它告诉我们:
    ✅ 怎么做有效的辩论（正反双路检索）
    ✅ 怎么做事件分析（六步框架+失败条件）
    ✅ 怎么做边际变化跟踪（宁可错过不要错误）
    ✅ 怎么组织数据收集和分析（搬运工+分析大脑分离）

  iFinD = 一家大型数据终端公司的"合规分析手册"
  它告诉我们:
    ✅ 怎么写一份好的分析师工作手册（Skill写法）
    ✅ 怎么保证分析报告的质量（四层质量控制）
    ✅ 怎么做财务分析的完整框架（五层递进+17行业适配）
    ✅ 怎么设置合理的约束（时间感知+红旗信号）
    ✅ 怎么做正式交付（docx+xlsx+校验脚本）

  两家的合力 = 我们的设计参考库
  Alpha派 贡献了: 分析方法论、辩论机制、事件响应
  iFinD 贡献了: 数据架构、质量控制、行业适配、交付流程

  我们的系统比两家都简单（我们只有12个角色 vs 两家合计71个Skill）
  但设计原则完全通用。
```

---

## 九、下一步建议

```
1. 把两家最核心的 reference 文档复制到 multi-agent-stock 项目
   Alpha派: fact-debate/references/report-prompt.md（辩论方法论）
   iFinD: financial-deep-analysis/references/（8个文件，五层框架）

2. 基于这些参考开始写我们的10个 Skill 文件
   （优先写 technical-analyst 和 debater 作为样例）

3. 质检模块参考 iFinD 的 data-accuracy-evaluator 6步流程设计
   辩论模块参考 Alpha派 的 fact-debate 正反检索设计
```

---

**报告完成** | **最后更新**: 2026-04-22

> 类比总结: Alpha派和iFinD就像两家顶级投研机构的"内训手册"——Alpha派是敏捷型精品店的手册，教怎么快速分析、怎么辩论；iFinD是大型数据公司的手册，教怎么保证质量、怎么适配行业。我们正在根据这两本手册，为我们的12个"AI分析师"编写属于他们自己的工作手册。
