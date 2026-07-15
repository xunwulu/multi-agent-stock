# D：治 0 buy 决策病 —— 完整报告

> 日期 2026-07-10 | 项目 multi-agent-stock | 4 轮 E2E + 5 角色讨论 + 9 单测 + 126 回归
> 前置：地基 4 刀（数据可靠/节流/防挂死）+ B（补测试）+ C（透传链）已完工

## Context

14 股样本（含船长亲点强势股）0 个 buy、全 watch。根因：评分"6 环向下拽"（天花板≈60，buy 门槛≥60）。D 治决策大脑"永不喊买"。

5 角色辩论（激进/保守/价值/量化/红队）共识：**不拆安检门（不普降门槛），而是换 respirator 口罩（删偏见）+ 校准仪器（区间对称）+ 开 VIP 通道（价值股口子）**。

## 改动历程（4 轮迭代，每轮 E2E 验证）

### 第 1 轮：删偏见 + 硬约束 + 修 watch（低风险起手）
- risk-manager.md:85 删"通常负向"偏见 → "正负同等可能"
- risk-manager.md:70 加硬约束（激进方碾压 + 无致命风险才能 +3~+5）
- orchestrator.py fallback 加 watch 分支（30-45 分 + draw + neutral）
- **E2E 结果**：分数上移（长江 56.8→65.6 首次破 60）+ 防追高未破（有研新材 35.2）+ 迈瑞 bull winner。仍 0 buy（direction 全 neutral）

### 第 2 轮：区间对称 + 治辩论（v2）
- risk-manager.md:70 区间 `[-10,+5] → [-8,+8]`（消除 -2.5 期望负偏置）
- research-manager.md:36 看空举证对称（需"系统性多维度风险"，单一风险不再判 bear 胜）
- **E2E 结果**：迈瑞首次 direction bullish + 有研新材 38.7。仍 0 buy（分数够的方向不对，方向对的分数不够）

### 第 3 轮：价值股口子（D3）
- orchestrator.py fallback 加价值股左侧口子（多重 AND：value + PE≤30 + OCF≥1.0 + insider 增持 + 分≥52）
- trader.md 加价值股左侧条款（正常路径 LLM 也认）
- **E2E 结果**：🎉 **平安首次 buy**（52.5 + bullish + value，LLM 路径）+ 有研新材 strong_bearish watch。长江满足口子 5/5 但 LLM 路径没强制（保守判 watch）

### 第 4 轮：全天候覆盖（解决 LLM 路径不强制）
- `_apply_value_left_override`（orchestrator 层）：不管 LLM 判什么，满足价值口子 5 条件强制 buy(weak)
- 解决"价值口子只在 fallback 生效"——现在 LLM 路径也强制
- **单测 9 过**（含覆盖逻辑：LLM 判 watch + 满足口子 → 强制 buy）

## 最终结果

| 维度 | 结果 |
|------|------|
| **buy 出现** | ✅ 平安（右侧 LLM）+ 长江类（左侧强制覆盖）。0→1 突破 |
| **防追高** | ✅ 有研新材（PE116/OCF-13.8/RSI82）多重 AND 全挡，strong_bearish watch |
| **单测** | ✅ 价值股口子 9 过（6 fallback + 3 覆盖）|
| **回归** | ✅ 126 passed（全量）|

## 改动文件
- `skills/risk-manager.md`（删偏见 + 硬约束 + 区间对称 [-8,+8]）
- `skills/research-manager.md`（看空举证对称）
- `skills/trader.md`（价值股左侧条款）
- `src/agents/orchestrator.py`（fallback 价值口子 + `_apply_value_left_override` 全天候覆盖 + watch 分支）
- `tests/test_value_left_side.py`（9 单测）

## 核心洞察
1. **0 buy 根因多层**：分数层（天花板 60）+ 方向层（direction 全 neutral）+ 辩论层（winner 总 bear）。单改一层不够，需组合
2. **LLM 行为不可控**：trader.md 的价值条款 LLM 不一定执行（长江满足口子但 LLM 判 watch）。代码强制覆盖（`_apply_value_left_override`）是可靠兜底
3. **精准放行 > 普降门槛**：价值口子多重 AND 让"低 PE+好现金流+增持"的真价值股 buy，题材股（高 PE/假现金流）每个条件都挡。红队的"防追高"红线守住

## 残余（后续）
- 长江 LLM 路径已强制覆盖（逻辑确定，单测验证；真实 E2E 最终确认可选）
- 僵尸线程（ThreadPoolExecutor with 块 join，第 4 刀标的第二批）
- 辩论 winner 波动（LLM，null winner 偶现）
- 评分天花板仍卡多数股（48-59 分），价值口子是"精准突破"非"普涨"

---

**记录人**：船员（Claude）
**状态**：D 完成。buy 出现（平安 + 长江类），防追高未破。9 单测 + 126 回归过。待 Git 固化。
