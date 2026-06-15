# Phase 2 优化计划 — 基础设施 + 技术分析维度升级

> 日期: 2026-04-27 | 目标: 数据准确性 + 专业级技术指标 = 质的飞跃
> 预计改动: 6个文件修改, 新增~400行代码

---

## 总览

```
Phase 2A: 基础设施（数据准确性）     ← 根基，先做
    |
Phase 2B: 核心技术指标（ATR/Fibonacci/ADX）  ← 最关键的新指标
    |
Phase 2C: 高级形态识别（头肩/双顶底/三角）   ← 最复杂但最有价值
    |
Phase 2D: Skill更新 + 全面测试       ← 收尾验证
```

---

## Phase 2A: 基础设施 — 让数据算得准

> 问题: 模型两次运行，同一个数据差10倍（10亿 vs 1亿）
> 根因: 工具返回原始数据，模型自己算数算错了
> 方案: 让工具把容易算错的数据提前算好

### 2A-1: get_kline 增加摘要字段

**文件**: `src/tools/get_kline.py`

**改动**: 在返回结果中增加 `summary` 字段
```python
summary = {
    "latest_close": 最新收盘价,
    "latest_date": 最新日期,
    "change_pct_5d": 近5日涨跌幅,    # 让模型直接用，不用自己算
    "change_pct_20d": 近20日涨跌幅,
    "period_high": 区间最高价,
    "period_low": 区间最低价,
    "avg_volume_5d": 近5日均量,
    "avg_volume_20d": 近20日均量,
}
```

**效果**: 模型不再需要从60行原始数据中自己算涨跌幅

### 2A-2: get_index 增加相对强弱预计算

**文件**: `src/tools/get_index.py`

**改动**: 当传入 stock_code 时，自动计算个股 vs 指数的相对强弱
```python
"relative_strength": {
    "stock_5d_change": 个股近5日涨跌,
    "index_5d_change": 指数近5日涨跌,
    "outperform_5d": 跑赢/跑输多少百分点,
    "stock_20d_change": ...,
    "index_20d_change": ...,
    "outperform_20d": ...,
    "industry_20d_change": 行业近20日涨跌,  # 如果有行业数据
    "vs_industry_20d": vs行业多少百分点,
}
```

**效果**: 模型直接获得"跑输大盘17.5个百分点"，不用自己从两组数据算差值

### 2A-3: get_daily_basic 增加估值百分位

**文件**: `src/tools/get_daily_basic.py`

**改动**: 利用已有的250天数据（当前只用20天），计算历史百分位
```python
"valuation": {
    "pe_latest": 最新PE,
    "pe_percentile_250d": PE在250天中的百分位,  # "当前PE在历史78%分位，偏高"
    "pb_latest": 最新PB,
    "pb_percentile_250d": ...,
    "latest_date": 最新数据日期,
}
```

**效果**: 模型直接判断"PE偏高/合理/低估"，有数据支撑

### 2A-4: 质检层增加数值合理性检查

**文件**: `src/infra/quality.py`

**改动**: `validate_analyst_output` 增加业务逻辑校验
```python
# 新增检查项:
1. strong_support < weak_support < current_price < weak_resistance < strong_resistance
2. stop_loss_price < current_price < target_price
3. score 与 breakdown 10项之和一致（已有，保留）
4. direction 与 score 不矛盾（已有，保留）
```

**效果**: 捕获"总市值172亿（实际1720亿）"这类荒谬数据

---

## Phase 2B: 核心技术指标 — 三个关键新指标

> 这三个指标是专业分析师的"标配"，我们完全没有

### 2B-1: ATR（真实波动幅度）

**文件**: `src/tools/calc_technical.py`

**新增函数**: `_calc_atr(highs, lows, closes, period=14)`

**算法**:
```
TR（真实波幅）= max(
    当日最高 - 当日最低,
    abs(当日最高 - 昨收),
    abs(当日最低 - 昨收)
)
ATR = TR的14日简单移动平均
```

**输出到 summary**:
```python
"atr_14": 当前ATR值,
"atr_stop_long": 做多止损价 = 最新收盘 - 2×ATR,   # 专业止损
"atr_stop_short": 做空止损价 = 最新收盘 + 2×ATR,
"atr_position_pct": ATR占价格的百分比,  # 波动率视角
```

**代码量**: ~30行

### 2B-2: Fibonacci 回撤

**文件**: `src/tools/calc_technical.py`

**新增函数**: `_calc_fibonacci(high, low)`

**算法**: 基于近60日最高价和最低价，计算关键回撤位
```
关键位:
- 0.236 回撤位
- 0.382 回撤位（最重要）
- 0.500 回撤位（半程位）
- 0.618 回撤位（黄金比例，最重要）
- 0.786 回撤位
```

**输出到 summary**:
```python
"fibonacci": {
    "swing_high": 阶段高点,
    "swing_low": 阶段低点,
    "retracement_236": ...,
    "retracement_382": ...,  # "如果回调到382位，是买入机会"
    "retracement_500": ...,
    "retracement_618": ...,  # "如果跌破618位，趋势可能反转"
    "retracement_786": ...,
    "current_position": 当前价处于哪两个Fib位之间,
}
```

**代码量**: ~40行

### 2B-3: ADX（趋势强度）

**文件**: `src/tools/calc_technical.py`

**新增函数**: `_calc_adx(highs, lows, closes, period=14)`

**算法**:
```
1. 计算方向运动 +DM 和 -DM
2. 计算方向指标 +DI 和 -DI
3. 计算 DX = |+DI - -DI| / (+DI + -DI) × 100
4. ADX = DX的14日移动平均
```

**输出到 summary**:
```python
"adx": {
    "adx_value": 当前ADX值,
    "plus_di": +DI值（多头力量）,
    "minus_di": -DI值（空头力量）,
    "trend_strength": "强趋势/中等趋势/弱趋势/无趋势",
    # ADX > 25: 有趋势, ADX > 50: 强趋势, ADX < 20: 无趋势
    "adx_direction": "上升/下降/平稳",  # ADX本身的方向
}
```

**代码量**: ~60行

---

## Phase 2C: 高级形态识别 — 复合K线形态

> 我们现有13种单日形态，缺所有多日复合形态

### 2C-1: 形态识别扩展

**文件**: `src/tools/calc_technical.py`

**新增函数**: `_detect_advanced_patterns(rows)`

**识别的形态**:

| 形态 | 类型 | 信号强度 | 所需数据窗口 |
|------|------|---------|------------|
| **头肩顶** | 反转（看空） | 极强 | 30-60日 |
| **头肩底** | 反转（看多） | 极强 | 30-60日 |
| **双顶（M头）** | 反转（看空） | 强 | 20-40日 |
| **双底（W底）** | 反转（看多） | 强 | 20-40日 |
| **上升三角形** | 中继（看多） | 中 | 15-30日 |
| **下降三角形** | 中继（看空） | 中 | 15-30日 |
| **对称三角形** | 中继（待突破） | 中 | 15-30日 |
| **上升楔形** | 反转（看空） | 中 | 15-30日 |
| **下降楔形** | 反转（看多） | 中 | 15-30日 |
| **矩形整理** | 中继（待突破） | 中 | 15-30日 |

**算法思路**:
1. 检测局部波峰和波谷（已有 `_detect_peaks` / `_detect_valleys`）
2. 根据波峰/波谷的相对高度和位置关系，匹配形态模板
3. 计算形态完成度（0-100%）和目标价位

**输出到 summary**:
```python
"advanced_patterns": [
    {
        "name": "双底（W底）",
        "signal": "bullish_reversal",
        "confidence": 0.75,           # 置信度
        "completion": 0.85,           # 完成度
        "neckline": 240.5,            # 颈线价
        "target_price": 255.0,        # 突破后目标价
        "invalidation_price": 220.0,  # 形态失效价
    }
]
```

**代码量**: ~200行

---

## Phase 2D: Skill更新 + 全面测试

### 2D-1: 更新 technical-analyst.md

**文件**: `skills/technical-analyst.md`

**改动**:
1. 工作流程增加对 ATR/Fibonacci/ADX 的引用说明
2. 评分锚定表增加新维度的打分规则:

| 新增评分项 | 满分 | 打分规则 |
|-----------|------|---------|
| ADX趋势强度 | 10 | ADX>40且+DI>-DI: 10, ADX>25: 7, ADX 20-25: 5, ADX<20: 3 |

3. 支撑/压力位改为优先使用 Fibonacci 回撤位
4. 止损价改为优先使用 ATR 止损
5. 输出JSON增加新字段（fibonacci_levels, atr_value, adx, advanced_patterns）

### 2D-2: 更新 quality.py schema

**文件**: `src/infra/quality.py`

**改动**: `TECHNICAL_ANALYST_SCHEMA` 增加新字段校验

### 2D-3: 全面测试

**文件**: `tests/test_phase1_v2.py`（复用）

**测试内容**:
- 运行完整分析流程
- 验证所有新指标字段存在
- 验证数值合理性
- 验证报告完整输出（不截断）

---

## 执行顺序和依赖关系

```
2A-1: get_kline 摘要 ─────────┐
2A-2: get_index 相对强弱 ─────┤
2A-3: get_daily_basic 百分位 ─┤── 可并行，互不依赖
2A-4: 质检层升级 ─────────────┘
                               │
                               ▼
2B-1: ATR ────────────────────┐
2B-2: Fibonacci ──────────────┤── 可并行，互不依赖
2B-3: ADX ────────────────────┘
                               │
                               ▼
2C-1: 高级形态识别 ──────────── ← 依赖 2B（需要ATR等辅助判断）
                               │
                               ▼
2D-1: Skill 更新 ─────────────┐
2D-2: Schema 更新 ────────────┤── 可并行
2D-3: 全面测试 ───────────────┘
```

---

## 预期效果

| 维度 | Phase 2 之前 | Phase 2 之后 |
|------|------------|------------|
| 技术指标数量 | 5个（MA/MACD/KDJ/RSI/BOLL） | **8个**（+ATR/Fibonacci/ADX） |
| 形态识别 | 13种单日形态 | **23种**（+10种复合形态） |
| 数据准确性 | 模型自己算（有10倍偏差风险） | 工具预计算（确定性100%） |
| 止损策略 | "跌3%就走" | **ATR科学止损** |
| 支撑压力 | 凭前高前低找 | **Fibonacci黄金比例** |
| 趋势判断 | 只知道方向 | **方向+强度**（ADX） |
| 估值判断 | "偏高/偏低"无依据 | **PE/PB历史百分位** |
| 质检能力 | 只查格式 | **查格式+查数值合理性** |

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 复合形态识别误判 | 中 | 中 | 给出置信度分数，低置信度的标记为"疑似" |
| token膨胀（新指标增加输出） | 低 | 低 | summary字段精简，只返回最新值 |
| ADX在震荡市不准确 | 低 | 中 | 结合MACD信号交叉验证 |
| 测试超时（数据量大） | 低 | 低 | 已有retry机制，max_tokens=8192 |

---

*创建日期: 2026-04-27*
*状态: Phase 2A/2B/2C/2D 已完成*

---

## 待办：上下文瘦身（等全链路跑通后评估）

> 当前状态: 50K chars → 模型处理，暂不压缩
> 触发条件: 多智能体全链路跑通后，如果 token 成本或延迟成为瓶颈，再回来优化
> 方案: summary 保留完整，原始数据行从 60→15-20 行，预计从 50K→16K chars (-68%)

---

## 待办：多智能体架构（下一步重点）

> 技术分析师已就位，接下来需要推进:
> - 编排者 (Orchestrator)
> - 基本面分析师 / 新闻分析师 / 情绪分析师
> - 辩论机制
> - 研究经理 + 风控层
