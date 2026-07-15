# 全面完成度审计：multi-agent-stock

> 日期 2026-06-18 | 方法：6 维度并行审计（7 agent / 48 万 token / 164 次工具调用）
> 范围：代码 vs 计划，逐条核对「做了 / 没做 / 半成品 / 待解决」
> 铁律：只认代码与文档证据，不臆想，每条带文件:行号
> 配套：[根因诊断](2026-06-16-root-cause-conservative.md) · [业界调研](2026-06-17-industry-research-recommendations.md)

## 一、总体评价

**好消息——骨架已建成**：6 阶段编排流程全部接通、12 个设计角色中 11 个已实现并被实际调用、13 个数据工具全部接入、核心循环与质检层主体完整、5 月审计的 F1-F9 修复项绝大多数已落地。这是真正的「能力已建成」，不是空壳。

**坏消息——卡在一个致命设计缺陷 + 若干工程缺口**：
1. **致命**：评分机制「层层向下拽」导致 14 只样本（含船长亲点强势股）**0 个 buy、全部 watch**。评分天花板 ≈60 恰好压在 buy 门槛 ≥60 之下——整套辩论+风控链路虽跑通，却产不出有效买入决策。
2. **工程缺口**：工具层零缓存（Tushare 调用翻倍）、无阶段级超时围栏、MessageBus 被降级为辩论记录器（广播/主动通信从未实现）、幻觉/跨报告校验缺失。

**结论**：「能跑但效果失真 + 静默丢数据风险」，**尚未达到可面客标准**。

## 二、完整缺口清单（16 项，按类别 + 严重性）

### A. 没做（7 项）

| # | 缺口 | 严重性 | 证据 |
|---|------|--------|------|
| 1 | 工具层零缓存→单只股票 Tushare 调用翻倍 | 高 | tools/ grep lru_cache 零命中；calc_technical 内部再取 kline；get_dcf 内部取 financials+daily_basic 重复；get_peers N+1（8 同行=16 次 API） |
| 2 | Tushare 限流(429/529)工具层零容错 | 高 | tushare_utils.py:69-75 `_call` 无重试；各工具 except 返回 ok:False/空数据；限流规避仅靠测试间 30 秒冷却 |
| 3 | 超时防御 Batch2（阶段边界/协作截止/总预算）未实现 | 高 | orchestrator.py:130-155 future.result() 无 timeout；agent_loop 仅 per-call 超时；test_timeout_defense 注释明确仅 Batch1 |
| 4 | broadcast 广播 + agent 主动通信工具未实现 | 高 | message_bus.py 全文无 broadcast；send_message/read_inbox 在 src/ 零匹配；设计见 sub-agent-architecture.md:124,267 |
| 5 | 7 个高价值 API（机构持仓/解禁/北向/融资融券/回购等）+ 筹码/VWAP 工具未实现 | 中 | grep fund_portfolio/share_float/margin_detail 等零结果；无 cyq_chips |
| 6 | LLM 数值幻觉校验(P9) + 跨报告指标校验(P11) | 中 | quality.py validate_tool_output 仅结构检查；无 tech/fund 跨报告一致性比对 |
| 7 | Phase2 上下文瘦身待办（50K→16K） | 低 | plans/2026-04-27-phase2-optimization-plan.md:334-338 标「待办，触发条件未达」 |

### B. 半成品（6 项）

| # | 缺口 | 严重性 | 证据 |
|---|------|--------|------|
| 8 | RiskLoop 未接 MessageBus，用 self._history 绕过总线 | 高 | risk_loop.py:21-24 无 import、:52 self._history 全程用；vs debate_loop.py:48 接总线。receive/peek/get_history 三方法零调用（dead capability） |
| 9 | 辩论/风险经理失败无确定性回退，核心环节静默缺失 | 中 | orchestrator.py:276-301 辩论失败→None 臺 Phase3-5 全跳过；360 门控致 RM 降级时风控层旁路；409-411 风险经理 None 仅记日志 |
| 10 | DirectTushareClient 字段与 get_daily_basic 不一致 | 中 | tushare_utils.py:91 只请求 8 字段，get_daily_basic.py:90-95 期望 14 字段；内置 client 下 ps_ttm/dv_ratio 恒 null |
| 11 | cninfo 公告正文实际仍为空（5 月 CRITICAL 未真修） | 中 | get_stock_news.py:142 自承「正文多为标题兜底」 |
| 12 | 情绪分析师设计了但从未创建独立 skill | 中 | project-design.md:78,152 + sub-agent-architecture.md:53 规划 sentiment-analyst；skills/ 无此文件，并入 news-analyst；state.py:32 残留占位字段 |
| 13 | P10 置信度校准未按学术方案实现 | 低 | quality.py:1142-1158 仅按 risk_level 硬封顶，未实现「初始 50%+数据点+5%+上限 80%」校准 |

### C. 待解决问题（3 项）

| # | 问题 | 严重性 | 证据 |
|---|------|--------|------|
| 14 | **保守偏置导致系统从不喊 buy（14 股 0 buy）** | 高 | 评分天花板≈60 < buy 门槛≥60；6 环向下拽（中位档 5 分/加权平均/研究经理±5/风险经理[-10,+5]/辩论举证不对称/trader 30-50 即 watch） |
| 15 | E2E 批量验证样本不足（仅 14 只，缺多类型）+ 测试断言过时 | 中 | validation 文档仅 14 只；test_full_e2e.py:182 断言遗漏 watch 与实际全 watch 矛盾 |
| 16 | 技术分析师 LLM 偶尔输出 score=0 依赖 auto-correct | 低 | memory project-pending-issues A 类；依赖 quality.py:341-369 自动重算 |

## 三、优先级建议（按「影响大 × 易实施」排序）

| 序 | 建议先做 | 理由 |
|----|---------|------|
| 1 | **修复保守偏置**（方案已就绪：档位制/分位数排名/双轨门槛） | 影响最大、方案已成型，只待船长拍板选 1-2 条。这是项目能否产出有效决策的根本问题 |
| 2 | 分析师层 + 辩论层加确定性回退 | 易实施、消除静默退化（辩论失败时系统悄悄退化为纯加权，用户无感） |
| 3 | 工具层加请求级缓存（lru_cache/TTLCache） | 投入产出比高，直接砍掉重复调用，减半 Tushare 调用，缓解限流根因 |
| 4 | Tushare 限流加指数退避重试 | 防静默丢数据，改动集中单一文件，风险低 |
| 5 | orchestrator 各阶段加超时围栏 + 总预算 | 防系统挂死，Batch1 已就绪，补阶段级超时即可 |
| 6 | 补 broadcast + 统一 RiskLoop 到 MessageBus | 消除通信碎片化，让设计要求的「全公司通信」落地 |
| 7 | LLM 幻觉校验(P9) + 跨报告校验(P11) | 提升决策准确性，复用现有 validate 框架扩展 |
| 8 | 扩展 E2E 多类型批量验证 + 更新断言 | 验证修复效果（保守偏置修完后确认 buy 不再稀有） |

## 四、方法学说明

6 维度并行扫描，互不重叠：① Agent 角色 ② 编排流程 ③ 通信机制 ④ 核心基础设施 ⑤ 工具与数据层 ⑥ 计划文档 + 已知问题。每个维度由独立 agent 穷尽扫描、带行号取证，最后综合 agent 合并去重。

---

**记录人**：船员（Claude，7-agent 审计编队）
**状态**：全面审计完成。16 项缺口已定位、分级、排序。下一步动哪项，待船长定夺。
