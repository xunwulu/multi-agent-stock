# v8 全文展示升级 — 设计文档

> 日期: 2026-09-10 | 状态: 船长已拍板 6 项，全部实施完成；第二阶段后端直播化 2026-09-14 完成并真跑验收（见 §七）
> 范围: docs/mockups/agent-analysis-demo-v8.html（纯前端）+ 第二阶段后端三件套

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

## 七、第二阶段后端备忘（2026-09-14 已全部完成）

1. orchestrator merge 白名单捡回：RM 的 summary → `combined.rm_summary`；
   风险经理的 risk_rationale/scoring_breakdown → `combined.risk_rationale`/`risk_scoring_breakdown`
   （summary 与 RM 撞名故不入 combined；前端 KEY_CN 已补 3 个中文名）
2. 三个 _run_* 经理 stash 叙述全文（`self._*_narrative`）→ agent_done.content 带回；
   实测三位经理只交表格不写作文（content=None 属诚实结果），管道留作未来 prompt 升级
3. RiskLoop 接 MessageBus/persist_dir：听证发言落 JSONL（msg_type=risk）
4. 直播三件套落地：
   - `src/infra/progress_emitter.py`：契约信封（seq/ts/run_id）+ progress.jsonl 追加 + 快照重写 + normalize_result
   - agent_loop.on_event → 心跳（迭代/工具计时/重试通知）；orchestrator.on_event → 六阶段事件全发射
   - `scripts/worker_server.py`（FastAPI:8766）：POST /analyze 起线程 + GET /progress 轮询 + 起飞页
5. 真跑验收（2026-09-14 工商银行）：283s / 47 事件 / 六阶段全绿零降级；
   契约重放深度==run_done 终态；live 页面 10/10、mock 回放 7/7、pytest 140/140
6. 遗留观察：分析师叙述全文长度随模型当次行为波动（本轮仅 28 字，9 月 8 日跑批为 500-4000 字）；
   若要稳定全文，可后续在分析师 skill 里加一句「提交前先写一段结论文字」（产品决策，未动）

## 八、追加拍板（2026-09-14 第三轮：经理也要写作文）

船长拍板「作文也要写」→ 三位经理 skill（research-manager / risk-manager / trader）
各加两条：
1. **推理文字要求（必写）**: 调用 submit_analysis 的同一条回复中，先写 200~300 字
   推理（评判/裁决/决策，各按职责定制题目），再交表格 → agent_done.content 自动带回，
   前端「分析推理」段零改动自动出现
2. **防漏填保险**: 作文不能替代表格——表格所有字段仍须完整填写
   （验证时发现副作用苗头：模型把论点写进作文后表格漏填 2 字段，加保险后消除）

真 LLM 验证（tests/_tmp_verify_narrative.py，一句话假辩论输入）：三经理均交作文
（88~414 字，输入薄则作文短，真实跑批数据丰满时更长），表格字段齐全。

## 九、追加拍板（2026-09-14 第四轮：分析师全文稳定化，D 方案两步走）

三方会审（架构师/代码审查员/产品顾问）一致推荐 D = B(管道保全) + A(试卷要求)：

**B 步：agent_loop 跨轮累积（~30 行）**
- 旧缺陷：`text_parts` 每轮清零——模型边查数据边写的推理被丢弃（token 已付费却倒掉）
- 改法：`all_text_parts` 跨轮累积 → `content`（轮间空行分隔、跳空块、2 万字封顶保尾）；
  另存 `last_round_text`（仅末轮）专供 JSON 兜底解析——**护栏**：早轮草稿 JSON
  片段永远污染不到 `_extract_json`（审查员查实的中低频高害风险，此护栏完全消除）
- orchestrator 四处文本兜底（分析师×2/RM/trader）改喂 `last_round_text or content`
- 影响面：经理（≤2轮）与辩手（单轮）语义不变；分析师 content 从"末轮文字"变"全程叙述"

**A 步：试卷要求（3 个 skill + 3 条用户消息）**
- skill 输出方式段：各加 200~300 字结论要求（技术/基本面/新闻各按职责定题）+ 防漏填保险
- **关键教训**：只改 skill 时真调一次技术分析师仍 0 字——工具循环模式下系统提示词的
  作文要求被工具惯性稀释；把作文要求同时写进**用户消息**（最靠近交表时刻、权重最高）
  后，真调 609 字成文 + 35 字段表格齐全 ✓

验证：pytest 142/142（含 2 条新护栏单测：早轮草稿 JSON 隔离、累积封顶保尾）；
真调技术分析师 609 字成文。回滚：B 删累积列表即可，A 删提示词两行。
