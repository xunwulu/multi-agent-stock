# 多智能体系统全面审计报告

> 日期: 2026-05-24 | 触发: 船长审阅利欧股份(002131.SZ)报告后认为质量严重不足
> 方法: 5个专业agent分别审计技术分析师、辩论/RM、质量校验、数据工具、整体pipeline

---

## 一、问题总览

| 模块 | CRITICAL | HIGH | MEDIUM | LOW | 总计 |
|------|----------|------|--------|-----|------|
| Pipeline信息流 | 2 | 3 | 2 | 0 | 7 |
| Trader决策逻辑 | 2 | 2 | 1 | 0 | 5 |
| 基本面分析师 | 0 | 4 | 4 | 1 | 9 |
| 技术分析师 | 2 | 5 | 5 | 4 | 16 |
| 新闻分析师 | 1 | 3 | 2 | 0 | 6 |
| 辩论系统 | 2 | 5 | 5 | 3 | 15 |
| 研究经理 | 1 | 2 | 3 | 0 | 6 |
| 质量校验 | 2 | 11 | 5 | 3 | 21 |
| 数据工具层 | 8 | 12 | 10 | 7 | 37 |
| **总计** | **20** | **47** | **37** | **18** | **122** |

---

## 二、最严重的问题（影响整体输出质量）

### P0: Pipeline信息漏斗 —— 分析师产出的数据80%被丢弃

**位置**: `src/agents/orchestrator.py:984-1054`

```
分析师产出 (~160字段, 100%)
    ↓ _format_reports() 压缩为文本摘要
辩论Round1 (~100数据点, 60-70%)
    ↓ Round2用压缩报告
辩论Round2 (~12数据点, 10-15%)
    ↓ _synthesize_reports() 算术平均
综合报告 (~6个数值, 5%)
    ↓ 手工挑选字段拼接文本
Trader (~42行文本, 15-20%)
```

**丢失的关键数据**:
- `business_model`（商业模式）
- `scenario_analysis`细节（概率、触发条件、EPS预测）
- `failure_conditions`（什么信号证明分析错误）
- `tracking_indicators`（未来3个月跟踪指标）
- `dcf_cross_check`（DCF内在价值与敏感性）
- `scoring_breakdown`（14个子维度得分）
- `key_observations`（5个关键观察）

**修复**: 给Trader传完整JSON，不手工挑选字段。

---

### P0: Trader强制二元决策，没有"观望"选项

**位置**: `skills/trader.md:13,22`

Prompt写: "买入/持有/卖出，必须有明确倾向" + "禁止默认持有"

**影响**: 专业报告建议"观望为主，等待右侧信号"，但系统强制选买/卖。已跌25%的股票应该建议"别急着操作"，系统却输出"强烈卖出"。

**修复**: 添加 `watch`（观望）action选项。

---

### P0: 基本面场景目标价 vs 交易目标价混淆

**位置**: `skills/trader.md:54`, `orchestrator.py:1013-1019`

基本面分析师的 `scenario_analysis` 目标价是**估值价**（DCF/EPS算出），不是**交易价**。
利欧股份：基本面乐观场景=3.5元，但当前市场价=6.65元。Trader直接用3.5当交易目标价。

**类比**: 把房子的建筑成本（30万）当成了合理交易价（市场价60万）。

**修复**: 
1. 场景目标价全部低于/高于当前价时，加警告
2. 添加目标价偏离度校验（>30%警告，>50%拒绝）
3. `_current_price` 注入到validation之前（目前是之后，导致校验是死代码）

---

## 三、数据工具层缺失（巧妇难为无米之炊）

### 利润表缺失的关键字段

**位置**: `src/tools/get_financials.py:22-28`

| 缺失字段 | 影响 | 专业报告用来发现什么 |
|----------|------|---------------------|
| `fin_exp`(财务费用) | 无法发现Q1财务费用暴涨1788.81% | 汇率/利率/地缘三重打击 |
| `invest_income`(投资收益) | 无法识别理想汽车持仓 | 利润"调节器"分析 |
| `fair_value_change` | 无法区分主业vs投资波动 | 公允价值变动导致扭亏 |
| `rd_exp`(研发费用) | 费用分析不完整 | — |
| `asset_impairment` | 无法发现资产减值大洗澡 | Q4单季亏损5.55亿 |

**修复**: 在 INCOME_FIELDS 列表中添加这些字段。**一行代码改动，最高价值修复。**

### 公告正文永远为空

**位置**: `src/tools/get_stock_news.py:133`

cninfo公告只抓标题，`content: ""` 永远为空。"AI收入<0.1%"这种关键事实来自公告正文。

### Tushare文章截断200字符

**位置**: `src/tools/get_stock_news.py:177`

Tushare `major_news` 内容截断到200字符，无法提取具体数字。

### 只有4个报告期财务数据

**位置**: `src/tools/get_financials.py:131-132`

`records = raw[:4]` 只保留最近4期，无法做多年趋势分析。专业分析至少需要3-5年。

### 没有收入结构数据

76%收入来自3.86%毛利率的媒介代理 — 这是核心商业模式问题，但工具只提供公司级汇总。

### Tushare API已有但未使用的工具

| API | 用途 | 优先级 |
|-----|------|--------|
| `fund_portfolio` | 基金持仓变化（最重要机构数据） | CRITICAL |
| `share_float` | 解禁时间表（重大价格事件） | CRITICAL |
| `margin` / `margin_detail` | 融资融券余额（情绪指标） | HIGH |
| `hk_hold` / `moneyflow_hsgt` | 北向资金（最受关注的机构流向） | HIGH |
| `stk_repurchase` | 回购数据 | HIGH |
| `index_dailybasic` | 指数PE/PB | MEDIUM |
| `cyq_chips` / `cyq_perf` | 筹码分布 | MEDIUM |

---

## 四、各Agent具体问题

### A. 技术分析师（16个问题）

**CRITICAL**:
1. **方向与目标价矛盾**: direction=bearish 但 target_price=7.17 > 当前价6.63。Prompt没有强制检查方向与目标价一致性
2. **scoring_hints盲目接受**: 零轴以下MACD金叉给了10/10满分，扭曲评分30%。零轴以上金叉vs以下金叉应该有不同分数

**HIGH**:
3. Prompt中"短期趋势"部分重复了（L88-92）
4. 没有要求识别市场阶段（吸筹/派发/上升趋势/下降趋势）
5. OBV只返回标签不返回数值，无法验证背离
6. 场景分析没有强制概率总和=100%，没有时间范围
7. 资金流单位不明确（万元 vs 亿元混用）

### B. 基本面分析师（9个问题）

**核心问题**: Prompt框架好(10层分析)，但数据不够
1. **无收入结构**: 76%低毛利媒介代理 vs 24%高毛利机械制造 — 不可见
2. **无投资持仓**: 理想汽车股票导致利润波动 — 不可见
3. **无财务费用**: Q1财务费用暴涨1788% — 不可见
4. Prompt要求"收入结构"但没有工具提供分业务线数据
5. 扣非分析只看比例不看来源（投资收益vs补贴vs处置）
6. 同行比较按行业标签而非商业模式（利欧vs游戏公司）
7. 商誉数据有但分析不突出

### C. 新闻分析师（6个问题）

**CRITICAL**:
1. cninfo公告正文永远为空

**HIGH**:
2. Prompt 70%篇幅教打分，几乎没教提取具体数字/产品细节
3. 没有时间线排序或事件因果链分析
4. 没有"叙事vs现实"对比指令

### D. 辩论系统（15个问题）

**CRITICAL**:
1. **信息不对称**: Bear在Round2+收到完整报告，Bull只收到6行压缩版。3只股票全部debate_winner=bear
2. **强化共识而非挑战**: Bull没有独立数据源反驳，只能重新解读bearish数据

**HIGH**:
3. `_synthesize_reports`是纯算术加权平均，没有智能综合
4. Regex fallback统计"独特数字"作为论据质量代理 — 完全错误
5. 辩手无法访问原始数据，只能重读分析师摘要
6. Karl Popper协议只有prompt要求，没有结构化强制执行
7. debate_delta范围[-5,+5]太窄(100分制只占5%)

### E. 研究经理（6个问题）

**HIGH**:
1. 验证失败时丢失全部辩论价值（regex fallback）
2. 收不到辩论质量指标（字数、引用数、协议遵循度）

### F. 质量校验系统（21个问题）

**CRITICAL**:
1. **`_current_price`是死代码**: 在validation之后才注入，导致stop_loss vs current_price校验永远None
2. **target_price偏离度从不校验**: 47%偏离可以无警告通过

**HIGH** (11个):
3. score=0自动修正不标记质量标志
4. 必填字段只检查存在不检查内容（空字符串/空数组/null都通过）
5. 文本字段无最小长度（summary可以是"ok"）
6. 数组字段无最小项数（key_observations可以是[]）
7. Research Manager的adjusted_score vs adjusted_direction不交叉校验
8. PE为负但valuation_grade="undervalued"不校验
9. revenue增长但net_margin崩塌不校验
10. confidence_total=65与risk_score=75不校验矛盾
11. Trader action与Research Manager recommendation不校验一致性
12. 验证失败大多只是warning不是error，orchestrator仍使用数据
13. 15个自动修正掩盖质量问题不标记

---

## 五、修复优先级路线图

### Phase 1: 紧急修复（影响最大，改动最小）

| 编号 | 修复项 | 改动文件 | 改动量 |
|------|--------|---------|--------|
| F1 | 利润表增加6个字段 | `get_financials.py:22-28` | +1行 |
| F2 | 公告获取正文 | `get_stock_news.py:133` | ~20行 |
| F3 | 日基本面增加dv_ratio/ps_ttm | `get_daily_basic.py:80-89` | +1行 |
| F4 | Trader增加watch选项 | `skills/trader.md` | ~10行 |
| F5 | 场景目标价vs当前价警告 | `orchestrator.py:1013` | ~10行 |
| F6 | target_price偏离度校验 | `quality.py` after L835 | ~15行 |
| F7 | _current_price注入前移 | `orchestrator.py:1125` | 移动2行 |
| F8 | 财务数据从4期改8期 | `get_financials.py:131` | 改1个数字 |
| F9 | 资产负债表增加long_equity_invest | `get_financials.py:29-41` | +1行 |

### Phase 2: Pipeline修复（中等改动量）

| 编号 | 修复项 | 改动文件 | 改动量 |
|------|--------|---------|--------|
| P1 | Trader传完整JSON | `orchestrator.py:984-1054` | ~100行重写 |
| P2 | 辩手信息对称（Round2+都用完整数据） | `debate_loop.py:658` | ~20行 |
| P3 | 质量校验增加内容检查 | `quality.py` | ~50行 |
| P4 | 必填字段空值检查 | `quality.py:255` | ~15行 |
| P5 | 跨agent一致性校验 | `orchestrator.py:160` | ~30行 |

### Phase 3: Prompt质量提升（改动量中等）

| 编号 | 修复项 | 改动文件 |
|------|--------|---------|
| Q1 | 基本面Prompt增加"利润质量拆解"层 | `fundamentals-analyst.md` |
| Q2 | 新闻Prompt增加"实质提取"指令 | `news-analyst.md` |
| Q3 | 新闻Prompt增加"叙事vs现实"对比 | `news-analyst.md` |
| Q4 | 技术分析Prompt增加"市场阶段识别" | `technical-analyst.md` |
| Q5 | 技术分析方向与目标价一致性强制检查 | `technical-analyst.md` |
| Q6 | 场景分析强制概率=100%+时间范围 | `technical-analyst.md` |
| Q7 | MACD评分区分零轴以上/以下 | `calc_technical.py` + `technical-analyst.md` |

### Phase 4: 数据工具扩展（新功能）

| 编号 | 修复项 | 涉及Tushare API |
|------|--------|----------------|
| D1 | 基金持仓变化 | `fund_portfolio` |
| D2 | 解禁时间表 | `share_float` |
| D3 | 北向资金 | `hk_hold` / `moneyflow_hsgt` |
| D4 | 融资融券 | `margin` / `margin_detail` |
| D5 | 公司回购 | `stk_repurchase` |
| D6 | 指数PE/PB | `index_dailybasic` |
| D7 | 新闻不截断+增加文章数 | `get_stock_news.py` |

---

## 六、与专业报告的差距对比

### 专业报告有而我们没有的（按重要程度）

1. **收入结构分解**: "76%收入来自3.86%毛利率媒介代理" → 我们只看到6.84%整体毛利率
2. **投资持仓识别**: "持有理想汽车股票，公允价值变动成利润调节器" → 完全不可见
3. **具体催化剂**: "618期间AI日均产出2万套素材，效率提升150倍" → 我们的催化剂是泛泛的"AI赛道热度"
4. **财务异动发现**: "Q1财务费用暴涨1788.81%至3519万" → fin_exp字段不存在
5. **投资者分类建议**: 激进/稳健/长线三种不同建议 → 只有单一buy/hold/sell
6. **商业模式深度**: "四层技术体系"+"液冷泵自主化" → 我们只知道"互联网传媒"
7. **时间线跟踪**: "未来3个月关键跟踪指标" → 有tracking_indicators但没传给Trader
8. **叙事vs现实对比**: "市场炒作AI营销 vs 公司承认AI收入<0.1%" → 新闻分析没有这个维度

---

*报告生成: 2026-05-24 by 5 specialized agents (code-reviewer x3, architect x1, quality auditor x1)*
