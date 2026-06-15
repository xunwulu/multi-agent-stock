# 素材获取策略 — 怎么高效准备好所有材料

> **日期**: 2026-04-22 | **核心发现**: 约60%素材已有基础，只需"包装"和"改写"
> **关联文档**: [准备清单](2026-04-22-agent-preparation-guide.md) | [子智能体架构](2026-04-21-sub-agent-architecture.md)

---

## 一、总体策略: 三种获取方式

```
获取方式A: 包装已有代码
  把 ai-investment-tool 项目已有的37个Tushare方法、3种成本测算算法
  包装成Agent可调用的工具（加一层标准接口）
  工作量: 小（主要是写包装函数）

获取方式B: 改写已有提示词
  把从 TradingAgents-CN 提取的12份提示词作为"原材料"
  用"正确的高度"原则改写成Skill文件
  去掉emoji轰炸，保留有用的角色定义和工作流程
  工作量: 中（需要理解每份提示词的意图并重写）

获取方式C: 参考开源代码新写
  Agent Loop、子智能体管理、消息总线等基础设施
  参考 learn-claude-code 的开源实现
  换成 GLM-5.1 API，加入熔断和质检
  工作量: 大（但参考代码清晰，逻辑可直接搬）
```

---

## 二、工具层获取明细

### 2.1 数据获取工具（包装已有代码）

| Agent工具名 | 包装的已有方法 | 已有文件位置 | 包装工作量 |
|------------|-------------|------------|----------|
| `get_kline` | get_stock_daily, get_stock_weekly, get_stock_monthly, get_stock_mins | tushare_service.py | 小 |
| `get_financials` | get_income, get_balancesheet, get_cashflow, get_financial_indicator, get_forecast | tushare_service.py | 小 |
| `get_stock_basic` | get_stock_company, get_stock_basic, get_stock_managers, get_stock_namechange, get_stock_st | tushare_service.py | 小 |
| `get_institutional` | get_top10_holders, get_top10_floatholders, get_repurchase | tushare_service.py | 小 |
| `get_money_flow` | get_moneyflow, get_moneyflow_hsgt | tushare_service.py | 小 |
| `get_chip` | get_chip_distribution, get_chip_performance | tushare_service.py | 小 |
| `get_index` | get_index_daily, get_index_basic, get_index_weight | tushare_service.py | 小 |
| `get_macro` | get_shibor, get_cpi, get_gdp | tushare_service.py | 小 |

**包装要做的事:**
```python
# 包装前: 直接调用 TushareService
service = TushareService()
df = service.get_stock_daily("300033.SZ", "2026-01-01", "2026-04-22")

# 包装后: Agent工具标准接口
def tool_get_kline(code, start_date, end_date, period="daily"):
    """Agent工具: 获取K线数据"""
    try:
        service = get_tushare_service()
        if period == "daily":
            df = service.get_stock_daily(code, start_date, end_date)
        elif period == "weekly":
            df = service.get_stock_weekly(code, start_date, end_date)
        # ... 其他周期
        return {"ok": True, "data": df.to_dict("records"), "error": None,
                "meta": {"count": len(df), "duration_ms": ...}}
    except Exception as e:
        return {"ok": False, "data": None, "error": str(e), "meta": {}}
```

### 2.2 计算工具（部分包装，部分新写）

| Agent工具名 | 来源 | 工作量 |
|------------|------|-------|
| `calc_cost` | 已有 CostCalculator (cost_calculator.py) | 小（包装） |
| `calc_chip` | 已有 ChipDistributionCalculator (chip_calculator.py) | 小（包装） |
| `calc_technical` | **需新写** MACD/RSI/BOLL/均线计算 | 中（标准算法） |
| `calc_valuation` | **需新写** PE/PB/PEG估值区间计算 | 中（标准公式） |
| `calc_risk_score` | **需新写** 综合风险评分 | 中（需设计评分规则） |

### 2.3 通信工具（参考 learn-claude-code 新写）

| Agent工具名 | 参考来源 | 工作量 |
|------------|---------|-------|
| `send_message` | learn-claude-code s09 MessageBus.send() | 小 |
| `read_inbox` | learn-claude-code s09 MessageBus.read_inbox() | 小 |
| `broadcast` | learn-claude-code s09 MessageBus.broadcast() | 小 |

### 2.4 知识工具（参考 learn-claude-code 新写）

| Agent工具名 | 参考来源 | 工作量 |
|------------|---------|-------|
| `load_skill` | learn-claude-code s05 SkillLoader | 小 |
| `save_note` | 新写，简单文件写入 | 小 |

### 2.5 工具层总结

```
总共15个工具:
  直接包装已有代码: 9个 (get_kline, get_financials, get_stock_basic,
                        get_institutional, get_money_flow, get_chip,
                        get_index, get_macro, calc_cost)
  需新写（标准算法）: 3个 (calc_technical, calc_valuation, calc_risk_score)
  参考开源代码写:     3个 (send_message, read_inbox, broadcast)
  不计工作量:         1个 (load_skill, save_note)
```

---

## 三、技能层获取明细

### 3.1 原材料评估

从 TradingAgents-CN 提取的12份提示词质量评估:

```
高质量（可直接改写）:
  ✅ 看多研究员 — 干净的单提示词，辩论结构清晰
  ✅ 看空研究员 — 与看多结构一致
  ✅ 3个风控辩论者 — 结构完全相同
  ✅ 研究经理 — 决策框架好

中等质量（需要大改）:
  ⚠️ 技术分析师 — 双阶段设计好，但emoji不一致，800字最低要求太死板
  ⚠️ 情绪分析师 — 平台列表好，但通用开场白浪费token
  ⚠️ 交易员 — 5字段输出格式好，但中英混杂
  ⚠️ 风控经理 — 重试/降级好，但缺输出格式模板

低质量（需要重写）:
  ❌ 基本面分析师 — 4个子提示词过度工程化
  ❌ 新闻分析师 — 5个子提示词，"绝对禁止"语气太强
```

### 3.2 合并机会

```
原12份提示词 → 合并后10个Skill文件:

  提示词 05 (看多) + 提示词 06 (看空)
    → 合并为 1个 debater.md (参数: side=bull/bear)

  提示词 09 (激进) + 提示词 10 (保守) + 提示词 11 (中性)
    → 合并为 1个 risk-debater.md (参数: stance=aggressive/conservative/neutral)

  节省: 3个文件 → 维护成本降低，一致性提升
```

### 3.3 改写策略

每份提示词的改写步骤:

```
步骤1: 提取精华
  - 保留角色定义（你是谁）
  - 保留工作流程（怎么做）
  - 保留输出格式要求
  - 保留有用的约束（不编造数据等）

步骤2: 删除噪音
  - 删除所有 emoji (🚨⚠️🔴✅等)
  - 删除防御性提示词（"绝对禁止"、"现在立即"等）
  - 删除多阶段fallback逻辑（由代码层面的熔断机制负责）
  - 删除与 LangGraph 状态机的耦合

步骤3: 调整到"正确的高度"
  - 清晰指引: "先用get_kline获取数据，然后分析"
  - 不微观管理: 不规定"必须800字"、"必须用这个标题"
  - 给灵活空间: LLM自己决定分析深度和重点

步骤4: 加入标准格式
  - YAML前置元数据 (name, description, tools, output_to, max_iterations, timeout)
  - 统一输出模板 (JSON格式，包含score/summary/report等字段)
```

### 3.4 10个Skill文件清单

```
skills/
├── analyst/
│   ├── technical-analyst.md    # 改写自提示词01 (中等难度)
│   ├── fundamentals-analyst.md # 改写自提示词02 (较难，需重写)
│   ├── news-analyst.md         # 改写自提示词03 (较难，需重写)
│   └── sentiment-analyst.md    # 改写自提示词04 (中等难度)
│
├── researcher/
│   ├── debater.md              # 合并自提示词05+06 (容易，参数化)
│   └── research-manager.md     # 改写自提示词07 (中等难度)
│
├── trader/
│   └── trader.md               # 改写自提示词08 (中等难度)
│
├── risk/
│   ├── risk-debater.md         # 合并自提示词09+10+11 (容易，参数化)
│   └── risk-manager.md         # 改写自提示词12 (中等难度)
│
└── orchestrator/
    └── orchestrator.md         # 新写 (编排者角色)
```

---

## 四、约束层获取明细

### 4.1 从已有提示词中可提取的约束

```
硬约束（代码实现）:
  ✅ 工具调用上限3次 — 提示词01中已有，可直接用代码实现
  ✅ 辩论轮次上限 — 提示词05/06中已有
  ✅ 超时限制 — 需要新设计，但概念清晰

软约束（写入Skill）:
  ✅ 不编造数据 — 提示词02/03中强调，值得保留
  ✅ 不越权决策 — 提示词01/04中有，分析师不给最终建议
  ✅ 用中文输出 — 多个提示词中都有
  ✅ 引用具体数据 — 提示词05/06中辩论要求引用数据
```

### 4.2 需要新设计的约束

```
token预算: 根据GLM-5.1的定价设计单股分析预算
输出格式校验: 每个角色设计具体的JSON schema
```

---

## 五、基础设施获取明细

### 5.1 参考 learn-claude-code 的组件

| 组件 | 参考文件 | 参考代码量 | 改动点 |
|------|---------|-----------|-------|
| Agent Loop | s01_agent_loop.py | ~80行 | API换成GLM-5.1 |
| 子智能体 | s04_subagent.py | ~120行 | 加入超时+熔断 |
| 技能加载 | s05_skill_loading.py | ~130行 | 几乎照搬 |
| 消息总线 | s09_agent_teams.py | ~280行 | 几乎照搬 |

### 5.2 需要新写的组件

| 组件 | 功能 | 预估代码量 |
|------|------|----------|
| 质检模块 | 输出校验、JSON schema检查 | ~100行 |
| 追踪日志 | 记录每一步操作 | ~80行 |
| 调度员 | 批量分析的并发控制 | ~150行 |

---

## 六、推荐获取顺序

```
Phase 1: 先搞定"能跑"的最小集 (3-5天)
  1. 写Agent Loop (~80行，参考learn-claude-code s01)
  2. 包装3个最核心的数据工具 (get_kline, get_financials, get_money_flow)
  3. 写1个Skill样例 (technical-analyst.md)
  → 目标: 一个技术分析师智能体能跑起来

Phase 2: 扩展到"全角色" (5-7天)
  4. 包装剩余的数据工具
  5. 改写全部10个Skill文件
  6. 写子智能体管理器 (~120行)
  → 目标: 12个角色都能独立跑

Phase 3: 加入"协作"能力 (3-5天)
  7. 写消息总线 (~280行，参考learn-claude-code s09)
  8. 写编排者智能体
  9. 连通全流程: 分析师→辩论→裁决→风控→决策
  → 目标: 完整的单股分析流程

Phase 4: 加入"质量和批量" (3-5天)
  10. 写约束系统（超时、熔断、token预算）
  11. 写质检模块（输出校验）
  12. 写追踪日志
  13. 写调度员（批量分析）
  → 目标: 生产级质量
```

---

## 七、风险和注意事项

```
风险1: GLM-5.1 的工具调用能力
  → learn-claude-code 基于 Anthropic API，我们的 GLM-5.1 可能接口不同
  → 缓解: Phase 1 先验证 GLM-5.1 的工具调用是否正常
  → 如果不行: 考虑换成 DeepSeek 或其他支持工具调用的模型

风险2: 新闻数据源
  → Tushare 没有新闻接口，需要用 AKShare 或其他源
  → 缓解: Phase 2 再处理新闻数据，先跑通其他3个分析师

风险3: 成本控制
  → 12个角色 × 1只股票 = 12次LLM调用（最少）
  → 辩论环节可能翻倍
  → 缓解: 设定 token 预算，超出自动熔断
```

---

## 八、类比总结

```
这就像开一家餐厅:

  已有的（ai-investment-tool）:
    食材采购渠道（Tushare数据接口）✅
    招牌菜配方（3种成本测算算法）✅
    厨房设备（数据库、前端）✅

  需要准备的:
    厨师工作手册（Skill文件）— 有参考（提示词），需要改写
    厨房规章制度（约束层）— 部分有参考，需要补充
    传菜系统（消息总线）— 有参考代码
    质检流程（质检层）— 需要新设计

  不需要从零开始的部分:
    不需要重新找食材供应商（Tushare接口）
    不需要重新设计菜品（成本测算算法）
    不需要重新装修厨房（数据库和前端）
```

---

**文档结束** | 船长可以指出想先从哪个 Phase 开始，或者对获取策略有疑问。
