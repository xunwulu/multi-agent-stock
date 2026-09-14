# v8 全文展示升级 — 设计文档

> 日期: 2026-09-10 | 状态: 船长已拍板 6 项，全部实施完成
> 范围: docs/mockups/agent-analysis-demo-v8.html（纯前端，后端补漏归入第二阶段）

## 〇、追加拍板（2026-09-10 第二轮，验收反馈）

4. 多空对决头像对称：看多头像左 / 看空头像右（含占位泡），镜像对峙
5. 两张裁决卡**居中**（与辩论区同中轴线，"对决→宣判"叙事）
6. 经理裁决卡升级「对阵判词卡」：判词三数字居中 + 最强论点左牛右熊两列 + 评判理由
   风险裁决卡加「风险仪表条」：低—中—高刻度（复用 rbar/rdot 样式，指针按等级 10%/50%/90%）

## 一、问题诊断（三层）

### 展示层
- 风险听证三卡：每人 856~1019 字质证词，卡片硬砍 180 字且无展开
- 研究经理卡：31 字段只露 4 个；风险经理卡：7 字段只露 3 个
- 抽屉 fieldGridAuto 的 fmt() 把 >120 字符的字符串砍到 118+…（总览/风险/决策三页受害）

### 数据层（后端勘察结论，Explore agent 已核实）
- 风险三方全文：一直在 result 的 risk.rounds[].content（纯展示问题）
- 研究经理/风险经理：无长篇"content"（prompt 只要求交表格）；但他们的
  risk_rationale / summary 字段在 orchestrator.py merge 白名单处被丢弃
  （L349-368 丢 RM summary；L418-431 丢风险经理 risk_rationale/summary/scoring_breakdown）
- trader 的结构化输出完整保留（combined_report.trader）
- 结论：本次纯前端；后端补漏（捡回被丢字段 + content 带回）归第二阶段，几行级

### 事件层
- agent_done.content 契约已预留（现为 null），前端预埋 Store.rmContent/riskmgrContent
  后端补数据时零改动自动长出"分析推理"段

## 二、船长拍板（2026-09-10）

1. 听证三卡全文：**预览 + 按钮进抽屉**（不做就地展开——三列等高布局会被撑爆）
2. 经理研判之家：**抽屉新增「裁决」页**（7→8 页），「风险」页重构为裁决区+质证全文
3. 经理不写作文：**摆全字段**（第二阶段后端只捡回被丢字段）

## 三、改动清单（函数级）

| # | 函数/位置 | 改动 |
|---|---|---|
| 1 | fillRiskCard | 去 slice(0,180)；全文进 .rv（CSS 已有 max-height:96px+渐隐预览）；卡尾加「查看全文（N字）」→ openDrawer('risk','rk-anchor-<role>') |
| 2 | renderRM | 卡尾加 vbtn「查看完整研判（N 字段）」→ openDrawer('manager') |
| 3 | renderRiskMgr | 加听证胜方 stat；卡尾加 vbtn「查看完整风险裁决」→ openDrawer('risk','riskmgr-anchor') |
| 4 | TABS/TAB_ORDER | 新增 manager:{title:'裁决'}（在 debate 与 risk 之间） |
| 5 | splitCombined() | 渲染层把 D.combined 按键归属拆 {rm, rsk}：以 Store.riskmgrJson 键为准，fallback RISKMGR_KEYS 常量；**不动 D**（契约对账 D 必须 == result_data.json） |
| 6 | renderTab 'manager' | [未来 content 段] + 评判理由全文 + 最强论点双色块 + 投资建议 + 风险提示列表 + RM 31 字段网格（GROUPS.rm） |
| 7 | renderTab 'risk' | 重构：风险裁决区（等级/评分/胜方 + [未来 content] + 7 字段网格，锚点 riskmgr-anchor）+ 三方质证全文（锚点 rk-anchor-<role>） |
| 8 | renderTab 'overview' | 瘦身为顶层结论（评分/方向/一致性/三面分/建议/方法）+ 决策摘要；完整字段引流到「裁决」「风险」页 |
| 9 | fieldGridAuto | 标量分支加规则：string >120 字 → grid-column:1/-1 跨列 full-text 块（fmt 不动，别处语义不变） |
| 10 | Store._reduce | agent_done rm/riskmgr 存 this.rmContent/riskmgrContent = d.content||null |
| 11 | Store 属性 + resetAll | 初始化置 null；resetAll 清空 + closeDrawer()（修遗留：抽屉开着点重播不重渲染） |
| 12 | tabReady | manager: !!Store.rmJson（独立条件，不与 trader 联合）；risk: liveRounds.risk.length>0 || !!Store.riskmgrJson |
| 13 | pendingBox(txt, stage) | stage 被 skip 时显示「⊘ 该环节已跳过」而非永远"进行中"（诚实原则） |
| 14 | openDrawer(tab, anchor) | anchor 参数：switchTab 渲染后按 getBoundingClientRect 精确定位 dbody 滚动 |
| 15 | run_done 深链 | ?open=<tab>&anchor=<id> 完成后自动开抽屉（顺带成为可分享链接 + headless 验证通道） |

## 四、抽屉最终结构（8 页）

| tab | 就绪 | 内容 |
|---|---|---|
| 总览 | combined && trader | 顶层结论 + 决策摘要 |
| 技术面/基本面/新闻面 | D[x] | 不变（content 全文 + 字段网格） |
| 辩论 | liveRounds.debate | 不变（各轮全文） |
| **裁决（新）** | !!Store.rmJson | [未来content] + 评判理由 + 最强论点 + 建议 + 风险提示 + 31 字段 |
| **风险（重构）** | 质证或裁决任一到达 | 风险经理裁决区（7字段+锚点）+ 三方质证全文（锚点） |
| 决策 | D.trader | 不变 |

## 五、风险清单（四路径）

- 重播 resetAll：清 rmContent/riskmgrContent + closeDrawer；所有渲染从 D/Store 现算
- F5 恢复：事件重放派生重建，锚点由 renderTab 稳定输出
- live 模式：fillRiskCard/renderRM 幂等 innerHTML；退避补发一串事件安全
- 契约对账：D 零改动（content 只进 Store）；assertContract 深度对账不受影响

## 六、验收标准

1. node 语法检查通过
2. headless 终态：三张听证卡各带「查看全文（N字）」；undefined/NaN = 0；六步全绿
3. ?open=manager：裁决页含评判理由全文 + 「全部 31 字段」
4. ?open=risk：风险裁决区 7 字段 + 三方全文（各 >800 字完整呈现）
5. 总览页长文本（如止损建议 158 字）跨列全文块
6. 降级 fixture 重放不报错；v7 页面不受影响

## 七、第二阶段后端备忘（本次不做）

1. orchestrator merge 白名单捡回：RM 的 summary、风险经理的 risk_rationale/summary/scoring_breakdown
2. _run_research_manager/_run_risk_manager/_run_trader 返回时带回 result.content（叙述文本）
3. RiskLoop 接 MessageBus/persist_dir（听证发言进 JSONL，直播信号用）
4. 完成后 agent_done.content 填真值 → 前端「分析推理」段自动出现（零前端改动）
