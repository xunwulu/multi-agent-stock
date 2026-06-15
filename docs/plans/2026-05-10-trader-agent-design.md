# Phase 5: Trader 交易员智能体设计计划

> 日期: 2026-05-10 | 目标: 从"分析报告"到"可执行交易决策"的最后一公里
> 前置条件: Phase 1-3 已完成（分析师 + 辩论 + Research Manager）

---

## Context: 为什么需要 Trader

### 现状

```
技术分析师 (76.4分, neutral, 目标价252)
    ↓
基本面分析师 (75.0分, strong_bullish, 目标价303)
    ↓
看多/看空辩论 (3轮, bear胜)
    ↓
Research Manager (综合68.8分, neutral, 观望建议)
    ↓
??? → state.decision = None ← 这里断了
```

**问题**: Research Manager 输出了"综合研判"（评分 + 方向 + 建议），但没有输出**可执行的交易决策**。

- 评分 68.8 是什么意思？买入？观望？
- 目标价 252 vs 303，到底听谁的？
- 止损应该设在哪里？
- 仓位应该多大？

**类比**: Research Manager 就像军医诊断病情，Trader 就像外科医生决定怎么开刀。诊断再精确，不落地成手术方案就没用。

---

## 设计思路

### 核心原则

1. **不是简单的"评分→决策"映射** — 不是"分数>70就买，<30就卖"
2. **综合研判** — 把分析师的分歧（252 vs 303）作为关键输入，不是简单平均
3. **置信度评分组件化** — 避免 LLM 的"7/10 偏差"（无论什么情况 LLM 都倾向于给出 70% 置信度）
4. **可执行输出** — 决策 + 目标价 + 止损 + 仓位建议 + 入场条件，缺一不可
5. **有退路** — LLM 失败时降级到确定性方案

### 与 TradingAgents 的对比

| 方面 | TradingAgents Trader | 我们的 Trader |
|------|---------------------|--------------|
| 输入 | 投资计划 + 4份报告 + 历史记忆 | Research Manager综合 + 2份分析师报告 + 辩论记录 |
| 输出 | 自由文本 + "最终交易建议: **买入**" | 结构化 JSON（action + target_price + ...） |
| 模型 | quick_thinking_llm | 同一个模型 (glm-5.1) |
| 记忆 | ChromaDB 向量检索 | 无（可未来加） |
| 下游 | → 风控辩论(3人) → 风控经理 | 直接输出（风控层可未来加） |
| 置信度 | 单一 0-1 分数 | 组件化评分（5个维度分别打分） |

### 关键设计决策

**决策 1: Trader 什么时候运行？**

在 Research Manager 之后、输出结果之前。

```
Step 6a: Research Manager → combined_score, direction, debate_winner
Step 6b: Trader → decision, target_price, confidence, risk_score  ← 新增
Step 7: 组装结果
```

**决策 2: 目标价怎么定？**

技术面给了 252，基本面给了 303，差距 20%。

方案: **加权倾向法**
- 基础 = 技术面目标价 × 权重_a + 基本面目标价 × 权重_b
- 权重由 Trader 根据以下因素动态调整:
  - 辩论胜方（bear 胜 → 倾向技术面更低的目标价）
  - 综合方向（neutral → 取中间偏低）
  - risk_reward_ratio（技术面的盈亏比）
- Trader 不是简单算术，而是理解两个目标价背后的逻辑，做出判断

**决策 3: 置信度怎么算？**

TradingAgents 用单一 0-1 分数，但 LLM 有"7/10 偏差"——无论输入质量如何，LLM 都倾向于给出 ~70% 置信度。

**解决方案: 组件化置信度**

让 LLM 分别评估 5 个独立维度（每个 0-20 分），再加总:

| 组件 | 满分 | 评估什么 |
|------|------|---------|
| 信号一致性 | 20 | 技术面和基本面方向是否一致？(neutral vs strong_bullish = 低一致性) |
| 数据充分度 | 20 | 分析师获得的数据是否完整？有无关键缺失？ |
| 辩论确定性 | 20 | 辩论是否有明确胜方？还是势均力敌？(bear胜 = 较高确定性) |
| 风险可控性 | 20 | 止损是否明确？盈亏比是否合理？(1:0.54 = 低可控性) |
| 估值合理性 | 20 | 目标价是否有充分支撑？是否偏高/偏低？ |

**总分 = 5个维度之和（0-100）**

为什么组件化好？
- 每个 0-20 分的小区间里，LLM 倾向于给出 10-14（偏差被分散）
- 加总后的范围更广（不会都集中在 70）
- 可以看出哪个维度拖了后腿

**决策 4: 仓位建议怎么给？**

没有投资组合上下文（不知道用户总资产、已有持仓），无法精确算仓位。

**方案: 相对建议**

| 置信度区间 | 仓位建议 | 说明 |
|-----------|---------|------|
| 80-100 | 重仓 (70-100%) | 高置信度，可大仓位 |
| 60-79 | 标准仓 (40-70%) | 中等置信度，正常仓位 |
| 40-59 | 轻仓 (20-40%) | 低置信度，试探性建仓 |
| 0-39 | 观望 (0%) | 信号不明，不建议操作 |

**决策 5: 是否做风控辩论层？**

TradingAgents 在 Trader 之后还有: 激进风控 → 保守风控 → 中性风控 → 风控经理，4个智能体。

**本期不做**。理由:
- 我们系统定位是"研究辅助工具"，不是自动交易系统
- Trader 输出已包含 risk_score + risk_warnings
- 风控层留作 Phase 6 未来优化

---

## 改动清单

### 文件 1: `skills/trader.md`（新建, ~100 行）

**Skill 内容**:

```yaml
---
name: trader
description: 交易员 - 基于综合研判做出可执行交易决策
tools: []
---
```

角色定义: 专业交易员，负责将研究成果转化为可执行决策

输入:
- `stock_code` — 股票代码
- `research_summary` — Research Manager 的综合研判（JSON）
- `tech_report` — 技术面分析（JSON）
- `fund_report` — 基本面分析（JSON）
- `debate_summary` — 辩论记录（文本）

输出 JSON schema:
```json
{
    "action": "buy/hold/sell",
    "action_strength": "strong/normal/weak",
    "target_price": 280.5,
    "target_price_rationale": "为什么是这个目标价（引用分析师数据）",
    "stop_loss": 225.0,
    "stop_loss_rationale": "为什么是这个止损价",
    "take_profit_levels": [
        {"price": 290, "portion": "30%", "reason": "第一阻力位"},
        {"price": 310, "portion": "50%", "reason": "基本面目标价"},
        {"price": 330, "portion": "20%", "reason": "乐观情景"}
    ],
    "confidence_components": {
        "signal_consistency": 12,
        "data_sufficiency": 16,
        "debate_certainty": 15,
        "risk_controllability": 8,
        "valuation_reasonableness": 14
    },
    "confidence_total": 65,
    "confidence_label": "medium",
    "position_advice": "standard",
    "position_range": "40-70%",
    "risk_score": 72,
    "risk_level": "high",
    "time_horizon": "1-2周",
    "entry_conditions": [
        "股价回调至240-245区间",
        "成交量缩量至均量以下",
        "MACD金叉确认"
    ],
    "key_catalysts": [
        "AI大模型商业化进展（2026-2027）",
        "A股市场景气度持续"
    ],
    "reasoning": "200字以内的决策推理过程",
    "warnings": ["风险1", "风险2"]
}
```

评判标准:
1. **目标价必须基于分析师数据** — 不是凭感觉猜的
2. **止损必须明确** — 参考技术面的 strong_support 和 stop_loss_price
3. **置信度必须组件化** — 分别打分再汇总，不允许直接给一个总数
4. **禁止默认 hold** — 与 Research Manager 相同规则，不能因为"两边都有道理"就观望
5. **分歧必须解释** — 如果技术面和基本面方向不一致，必须解释为什么选择倾向某一方

### 文件 2: `src/agents/orchestrator.py`（修改, ~50 行）

在 Step 6 Research Manager 之后、Step 7 组装结果之前，插入:

```python
# Step 6b: Trader 交易决策
trader_result = self._run_trader(
    stock_code, tech_json, fund_json,
    debate_result, combined
)
if trader_result:
    state.set("decision", trader_result["action"])
    state.set("target_price", trader_result["target_price"])
    state.set("confidence", trader_result["confidence_total"])
    state.set("risk_score", trader_result["risk_score"])
    combined["trader"] = trader_result
    combined["synthesis_method"] = "llm_research_manager_with_trader"
else:
    # 降级: 用确定性规则做简单决策映射
    fallback = self._deterministic_trader_fallback(combined)
    state.set("decision", fallback["action"])
    state.set("target_price", fallback["target_price"])
    state.set("confidence", fallback["confidence"])
    state.set("risk_score", fallback["risk_score"])
    combined["trader"] = fallback
    combined["synthesis_method"] = "llm_research_manager_with_deterministic_trader"
```

新增方法:
- `_run_trader()` — 类似 `_run_research_manager()`，加载 skill → 格式化输入 → 调用 LLM → 解析 JSON
- `_deterministic_trader_fallback()` — 降级方案，用确定性规则映射

### 文件 3: `src/infra/quality.py`（修改, ~40 行）

新增 `validate_trader_output()` 函数:

```python
TRADER_SCHEMA = {
    "required_fields": [
        "action", "action_strength", "target_price",
        "stop_loss", "confidence_components", "confidence_total",
        "confidence_label", "position_advice", "risk_score",
        "risk_level", "reasoning"
    ],
    "enum_values": {
        "action": ["buy", "hold", "sell"],
        "action_strength": ["strong", "normal", "weak"],
        "confidence_label": ["very_high", "high", "medium", "low", "very_low"],
        "position_advice": ["heavy", "standard", "light", "watch"],
        "risk_level": ["very_low", "low", "medium", "high", "very_high"],
    },
    "numeric_ranges": {
        "target_price": (0, 100000),
        "stop_loss": (0, 100000),
        "confidence_total": (0, 100),
        "risk_score": (0, 100),
    },
    "confidence_components_fields": [
        "signal_consistency", "data_sufficiency",
        "debate_certainty", "risk_controllability",
        "valuation_reasonableness"
    ],
}
```

验证逻辑:
- 所有 required_fields 非空
- action 在合法枚举值中
- target_price > 0, stop_loss > 0, stop_loss < target_price（如果是 buy）
- confidence_total = 5个组件之和
- confidence_total 在 [0, 100] 范围
- risk_score 在 [0, 100] 范围
- confidence_label 与 confidence_total 一致（>80=very_high, 60-80=high, ...）

### 文件 4: `src/core/state.py`（无需修改）

已预留字段:
```python
"decision": None,      # Phase 5: Reserved for Trader
"target_price": None,  # Reserved for Trader
"confidence": None,    # Reserved for Trader
"risk_score": None,    # Reserved for Trader
```

只需在 orchestrator 中填充这些字段即可。

---

## 确定性降级方案

如果 LLM 调用失败，用确定性规则生成 Trader 输出:

```python
def _deterministic_trader_fallback(self, combined):
    score = combined.get("combined_score", 50)
    direction = combined.get("combined_direction", "neutral")
    tech_json = combined.get("tech_json", {})
    fund_json = combined.get("fund_json", {})

    # 1. action 决策
    if score >= 75 and "bullish" in direction:
        action = "buy"
    elif score <= 30 and "bearish" in direction:
        action = "sell"
    else:
        action = "hold"

    # 2. 目标价: 技术面和基本面的加权平均（辩论胜方影响权重）
    tech_target = tech_json.get("target_price", 0)
    fund_target = fund_json.get("target_price", 0)
    winner = combined.get("debate_winner", "draw")

    if winner == "bull":
        # 看多胜 → 倾向更高的基本面目标价
        target_price = tech_target * 0.4 + fund_target * 0.6
    elif winner == "bear":
        # 看空胜 → 倾向更低的技术面目标价
        target_price = tech_target * 0.6 + fund_target * 0.4
    else:
        target_price = (tech_target + fund_target) / 2

    # 3. 止损: 用技术面的止损价
    stop_loss = tech_json.get("stop_loss_price", target_price * 0.9)

    # 4. 置信度: 基于综合评分映射
    confidence = score  # 直接用综合评分

    # 5. 风险评分: 100 - 置信度
    risk_score = 100 - confidence

    return {
        "action": action,
        "target_price": round(target_price, 2),
        "stop_loss": round(stop_loss, 2),
        "confidence_total": confidence,
        "risk_score": risk_score,
        "synthesis_method": "deterministic_fallback",
    }
```

---

## 文件改动清单

| 文件 | 改动 | 类型 |
|------|------|------|
| `skills/trader.md` | Trader Skill 定义 | 新建 |
| `src/agents/orchestrator.py` | `_run_trader()` + `_deterministic_trader_fallback()` + Step 6b | 修改 |
| `src/infra/quality.py` | `TRADER_SCHEMA` + `validate_trader_output()` | 修改 |

注意: `src/core/state.py` **不需要修改**，字段已预留。

---

## 验证方案

### E2E 测试验证

运行完整 E2E 测试，检查 result.json:

1. **state 字段填充**:
   - `state.decision` 不再是 None，是 "buy"/"hold"/"sell"
   - `state.target_price` 不再是 None，是一个合理数字
   - `state.confidence` 不再是 None，是 0-100 的数字
   - `state.risk_score` 不再是 None，是 0-100 的数字

2. **Trader 输出质量**:
   - `confidence_total` = 5个组件之和（数学一致性）
   - `target_price` 在 tech_target 和 fund_target 之间（不超出范围）
   - `stop_loss` < `target_price`（如果是 buy）
   - `action` 与 `combined_direction` 方向一致
   - `reasoning` 引用了分析师的具体数据

3. **降级测试**:
   - 模拟 LLM 失败，确认降级到确定性方案
   - 确认降级输出也填充了所有 state 字段

---

## 风险和取舍

1. **单次 LLM 调用成本**: ~5000 input + ~1500 output tokens
   - 取舍: 可接受。交易决策是整个流程的"收口"，值得多一次调用

2. **Trader 与 RM 可能矛盾**: RM 说"观望"，Trader 可能说"buy"
   - 处理: 这是设计意图！RM 是"研究层面的判断"，Trader 是"交易层面的决策"，角度不同
   - Trader 必须解释为什么做出了与 RM 不同的决策

3. **组件化置信度的 LLM 遵从度**: LLM 可能不严格按 5 维度打分
   - 缓解: quality.py 会校验 confidence_total = sum(components)，不一致则触发修正

4. **不做的事**:
   - 不做风控辩论层（Phase 6）
   - 不做 ChromaDB 记忆（未来）
   - 不做精确仓位计算（无投资组合上下文）
   - 不做自动交易信号发送（定位是研究辅助）

---

## 类比

船长，Trader 智能体就像医院的**治疗方案制定会诊**:

- **技术分析师** = 检验科（验血、CT，给数据）
- **基本面分析师** = 内科医生（看病史、体检，给诊断）
- **辩论** = 会诊讨论（两个医生争论治疗方案）
- **Research Manager** = 会诊结论（"患者目前病情中性，但有X风险"）
- **Trader** = 主治医生的**处方**（"用药A，剂量X，停药条件Y，复查时间Z"）

Research Manager 说"病情中性"，但 Trader 要回答: "那到底治不治？怎么治？治多久？什么时候停？"

**现在的系统**只有到会诊结论就停了，患者拿着诊断书但不知道该吃什么药。Trader 就是把诊断书变成处方单。

---

*等待船长确认后开始执行*
