# 技术分析师智能体优化计划

> 日期: 2026-04-24 | 基于: 三方评估（设计原则 + 专业标准 + TradingAgents-CN源码对比）

## 评估结论

| 维度 | 当前评分 | 目标 |
|------|---------|------|
| 数据层 | A | A（保持） |
| 分析深度 | B- | A- |
| 输出质量 | B | A |
| 专业对齐 | B+ | A |

## 优化计划

### P0: 最高优先级（Skill + JSON 格式，影响最直接）

#### P0-1: 趋势分级（短/中/长期）
- **文件**: `skills/technical-analyst.md`
- **改动**: 将单一 `trend` 字段拆分为:
  - `short_term_trend`: 5-10日趋势（短周期均线+K线形态）
  - `mid_term_trend`: 20-60日趋势（中周期均线+MACD方向）
  - `long_term_trend`: 60-120日趋势（长周期均线+趋势线方向）
- **原因**: 专业分析必须区分不同时间周期的趋势，短期下跌不代表中期看空

#### P0-2: 止损价 + 目标价
- **文件**: `skills/technical-analyst.md`
- **改动**: JSON输出增加:
  - `stop_loss_price`: 止损价（基于关键支撑位下方3-5%）
  - `target_price`: 目标价（基于关键压力位上方空间）
  - `risk_reward_ratio`: 风险收益比
- **原因**: TradingAgents-CN有明确的rating/target/risk输出，这是专业分析标配

#### P0-3: 评分锚定表
- **文件**: `skills/technical-analyst.md`
- **改动**: 添加具体评分锚定规则（每项拆解到分数级别）
- **原因**: 当前评分标准模糊，LLM打分波动大

#### P0-4: 工具描述改中文
- **文件**: `tests/test_phase1_v2.py`
- **改动**: 4个工具的description和parameters全改为中文
- **原因**: 系统提示词是中文，工具描述应该一致

### P1: 高优先级（算法增强，提升分析质量）

#### P1-1: 背离检测
- **文件**: `src/tools/calc_technical.py`
- **改动**: 新增背离检测函数:
  - MACD顶背离 / MACD底背离
  - KDJ顶背离 / KDJ底背离
  - RSI顶背离 / RSI底背离
- **算法**:
  1. 检测价格的峰/谷（N=5窗口）
  2. 检测指标的峰/谷
  3. 比较最近2-3个峰/谷方向是否与价格相反
- **输出**: 在summary中增加 `divergence` 字段

#### P1-2: 多层支撑/压力位
- **文件**: `skills/technical-analyst.md`
- **改动**: JSON输出从单一支撑/压力改为多层:
  - `strong_support` / `weak_support`
  - `strong_resistance` / `weak_resistance`
  - 每个价位附带判断依据

### P2: 中优先级（锦上添花）

#### P2-1: 行业指数对比
- **文件**: `src/tools/get_index.py`
- **改动**: 增加行业指数映射（按stock_basic的行业分类自动选对应行业指数）
- **复杂度**: 需要stock到行业的映射，可能需要新增工具

#### P2-2: K线形态识别
- **文件**: `src/tools/calc_technical.py`
- **改动**: 基础形态识别（十字星、锤子线、吞没形态等）
- **复杂度**: 中等，需要定义形态规则

### P3: 低优先级（后续迭代）

- 筹码分布分析
- 资金流向分析
- 自动画趋势线

## Token 监控策略

每完成一个优化点后检查:
1. `result.json` 中的 `token_usage.per_iteration` — 观察 input_tokens 是否接近上下文窗口
2. `stop_reason` 是否出现 `max_tokens` — 如果出现则说明输出被截断
3. 工具返回数据量 — 确认没有超过合理范围
4. 当前配置: max_tokens=4096, GLM-5.1上下文窗口约205K

## 执行顺序

```
P0-1(趋势分级) → P0-2(止损/目标价) → P0-3(评分锚定表) → P0-4(中文工具描述)
    ↓
P1-1(背离检测算法) → P1-2(多层支撑压力)
    ↓
运行测试 → 检查token用量 → 完成
```
