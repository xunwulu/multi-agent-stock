# 业界调研：多智能体股票系统「评分保守偏置」的处理方法

> 日期 2026-06-17 | 方法：4 方向并行联网调研（TradingAgents / LLM 打分校准 / 辩论偏置 / 信号阈值）
> 配套根因：[2026-06-16-root-cause-conservative.md](2026-06-16-root-cause-conservative.md)

## 一句话定论

我们的「6 环分数平均 → 向 50 收敛 → 从不喊买」，是业界早研究透的 **Central Tendency Bias（中庸偏置）+ 辩论举证不对称 + 阈值校准错误** 的教科书组合。最讽刺的是：我们抄的 TradingAgents **原版根本不用分数**——它让 LLM 直接判档（Buy/Hold/Sell），所以天然不中值收敛。我们抄架构时改成「6 环打分平均」，反而引入了这个病。

## 根因的业界映射

| 我们的 6 环现象 | 业界叫法 | 成熟度 |
|---|---|---|
| 分数向 50 收敛、回避极端 | Central Tendency Bias / Regression to the Mean | 教科书级，多篇 arXiv |
| 看空方 8/8 全赢辩论 | 举证门槛不对称（affirmative vs negative burden） | 辩论理论 + MAD 研究 |
| 绝对分 ≥60 永不触发 buy | 阈值未校准（该用分位数/排名） | 量化交易常识 |

## 五个核心建议（按 ROI 排序）

### 建议 1【治本·最高 ROI】档位制替代「连续分数聚合」
**做法**：最终决策由一个 agent 直接判 Buy/Hold/Sell 离散档位，而不是 6 环数字平均。
**依据**：TradingAgents 原版就这么做（research_manager / portfolio_manager 输出 5 档枚举，无数值阈值）；学术上「把复杂 rubric 分解为离散检查」是中值坍缩空间最小的形态。
**对应我们**：根治环①②③（打分表/加权平均/delta 太小导致的向 50 收敛）。
**成本**：高（要重构决策链）。

### 建议 2【治本】辩论改「对称举证 + 盲判」
**做法**：① 裁判（研究经理）判据从「哪方论证更有力」改成对称标准——要求看空方也给出「可证伪的看空主张 + 证据」，不能只挑漏洞；② 匿名化（隐藏 bull/bear 标签）或角色对调，消除身份偏置。
**依据**：竞赛辩论理论（affirmative 承担举证重担）；MAD 匿名化去偏（arXiv:2510.07517）；LLM 评委 position bias（ACL-IJCNLP 2025）。
**对应我们**：根治环⑤（看空方总赢）。
**成本**：中（改 research-manager.md + 判定逻辑）。

### 建议 3【治标·最快】prompt 显式「反保守施压」
**做法**：照搬 TradingAgents 措辞，在每个判档环节加：「Commit to a clear stance whenever the strongest arguments warrant one; reserve Hold/中性 only for genuinely balanced evidence. Be decisive.」
**依据**：TradingAgents 每个经理 prompt 都有这句；GitHub 几乎无「从不喊 buy」issue，反证有效。
**对应我们**：缓解环⑥（trader「30-50 就 watch」）+ 整体保守倾向。
**成本**：低（改 prompt 文字）。

### 建议 4【治本】用「分位数/排名」替代「绝对分阈值」
**做法**：把「综合分 ≥60 才 buy」改成「当前批次排名前 20% 即进入 buy 候选」。阈值随每批分数分布自适应，永不「永不触发」。
**依据**：量化交易常识——市场非正态，分位数优于绝对分；MDPI 滚动 ECDF 归一化框架。
**对应我们**：根治「天花板 60 vs 门槛 60」的死结。
**成本**：中（改阈值逻辑）。

### 建议 5【治本·逻辑】拆「左侧/右侧」双轨门槛
**做法**：价值股走「安全边际」门槛（价格低于内在价值 30-50%），趋势股走「突破信号」门槛，两套并行、任一触发即候选。
**依据**：价值投资（安全边际）vs 趋势跟踪（突破+高盈亏比）的入场逻辑根本不同；强制用统一右侧门槛套价值股是「逻辑错配」。盈亏比 2:1 是趋势派基准，价值派靠安全边际不靠盈亏比硬门槛。
**对应我们**：解决「长江电力这种价值股被右侧门槛卡死」。
**成本**：高（要新增左侧分支逻辑）。

### 建议 6【辅助】rubric 锚点 + 校准
**做法**：① 打分表每个档位（尤其极端档）加「操作化锚点示例」（few-shot 展示 1 分和 5 分长什么样）；② 用 isotonic regression 把原始分映射到「真实跑赢概率」再设阈值。
**依据**：「调 rubric 不调 judge」；锚定示例是对抗回归中值最有效的 prompt 级手段；isotonic regression 实测优于 Platt scaling。
**对应我们**：缓解环①（打分表中位档=5 分）。
**成本**：中。

## 推荐实施路径（分 3 阶段，由低到高）

| 阶段 | 做什么 | 成本 | 预期效果 |
|------|--------|------|---------|
| **阶段 1·快赢** | 建议 3（反保守 prompt）+ 建议 4 的分位数版 | 低 | 立竿见影缓解，看 buy 能否出现 |
| **阶段 2·治本** | 建议 2（辩论对称）+ 建议 1 局部（最终环改拍板） | 中 | 看空不再总赢、分数不再卡 50 |
| **阶段 3·根治** | 建议 1 全面档位制 + 建议 5 双轨门槛 | 高 | 从架构上消除保守偏置 |

## 交叉印证：两个方向指向同一个结论

- 方向 ①（TradingAgents）说：用**离散档位**不用连续分数
- 方向 ②（LLM 校准）说：**分解 rubric 为离散检查**，中值坍缩空间骤降
- **两者独立得出同一结论：离散判档 > 连续打分**。这是治本之道。

---

## 参考资料汇总

### 方向① TradingAgents（一手源码）
- [TradingAgents GitHub (86.8K stars)](https://github.com/TauricResearch/TradingAgents)
- [schemas.py（档位枚举）](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/schemas.py)
- [research_manager.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/managers/research_manager.py) · [portfolio_manager.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/managers/portfolio_manager.py) · [trader.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/trader/trader.py)
- [TradingAgents 论文 arXiv:2412.20138](https://arxiv.org/abs/2412.20138) · [项目站](https://tradingagents-ai.github.io/)
- [Issue #479 风险约束漂移](https://github.com/TauricResearch/TradingAgents/issues/479)

### 方向② LLM 打分中庸偏置与校准
- [Central Tendency Bias in Clinical Ordinal Scoring (arXiv:2605.16386)](https://arxiv.org/pdf/2605.16386)
- [LLMs Judging LLMs: Simplex Perspective (arXiv:2505.21972)](https://arxiv.org/html/2505.21972v3)
- [How to Correctly Report LLM-as-a-Judge (arXiv:2511.21140)](https://arxiv.org/abs/2511.21140) · [代码](https://github.com/UW-Madison-Lee-Lab/LLM-judge-reporting)
- [Calibrate, Don't Curate (arXiv:2605.09702)](https://arxiv.org/html/2605.09702v1)
- [CalibJudge 多语言温度校准 (preprints 202603.1324)](https://www.preprints.org/manuscript/202603.1324)
- [Before You Tune Your Judge, Tune Your Rubric](https://pub.towardsai.net/before-you-tune-your-judge-tune-your-rubric-4dd3206d36aa)
- [5 Methods for Calibrating LLM Confidence](https://latitude.so/blog/5-methods-for-calibrating-llm-confidence-scores)
- [Galileo: 人工标注校准](https://galileo.ai/blog/calibrate-llm-judge-human-annotations) · [Deepchecks 校准概述](https://deepchecks.com/llm-judge-calibration-automated-issues/)

### 方向③ 多智能体辩论偏置与去偏
- [匿名化去偏 MAD (arXiv:2510.07517)](https://arxiv.org/html/2510.07517v1)
- [Sycophancy in MAD (arXiv:2509.23055)](https://arxiv.org/html/2509.23055v1)
- [Confidence Calibration in MAD (EMNLP 2025)](https://aclanthology.org/2025.findings-emnlp.343.pdf)
- [DEBATE: Devil's Advocate (arXiv:2405.09935)](https://arxiv.org/html/2405.09935v2) · [LLM Devil's Advocate (IUI'24)](https://mingyin.org/papers/IUI-24/devil.pdf)
- [Position Bias in LLM Judge (ACL-IJCNLP 2025)](https://aclanthology.org/2025.ijcnlp-long.18.pdf) · [CALM: 12 种 judge 偏置](https://llm-judge-bias.github.io/)
- [举证负担不对称 — DSDC](https://dsdc.ca/glossary/affirmative-negative) · [Ethos Debate](https://www.ethosdebate.com/a-crushing-weight-the-lost-potential-of-the-burden-of-proof/)

### 方向④ 量化信号阈值校准
- [分位数归一化框架 (MDPI)](https://www.mdpi.com/2227-7072/14/1/4) · [衡量交易信号质量 (Macrosynergy)](https://macrosynergy.com/research/how-to-measure-the-quality-of-a-trading-signal/)
- [Classifier Calibration & 阈值选择](https://valeman.medium.com/classifier-calibration-and-the-end-of-roc-based-threshold-selection-d8e52086cb12) · [ROC vs PR (ML Mastery)](https://www.machinelearningmastery.com/roc-curves-and-precision-recall-curves-for-classification-in-python/)
- [Profit Factor (QuantifiedStrategies)](https://www.quantifiedstrategies.com/profit-factor-trading/) · [胜率与盈亏比成对 (TradeZella)](https://www.tradezella.com/blog/win-rate)
- [Kelly Criterion (Wikipedia)](https://en.wikipedia.org/wiki/Kelly_criterion) · [Fractional Kelly](https://harrycrane.substack.com/p/two-arguments-for-fractional-kelly)
- [趋势跟踪肥右尾 (CFM)](https://www.cfm.com/wp-content/uploads/2022/12/188-2018-Making-fat-right-tails-fatter-with-trend-following-most-of-the-time.pdf)
- [Margin of Safety (Investopedia)](https://www.investopedia.com/terms/m/margin_of_safety.asp) · [30% 安全边际门槛 (Quartr)](https://quartr.com/insights/investing/margin-of-safety-protecting-your-investments-for-uncertainty)
- [左侧靠估值、右侧靠确认 (广发基金)](http://www.gffunds.com.cn/jjkt/tzjhl/202305/t20230509_383537.shtml) · [左右侧交易 (新浪)](https://finance.sina.com.cn/roll/2025-01-12/doc-ineeseki3706946.shtml)

---

**记录人**：船员（Claude）
**状态**：业界调研完成，6 条建议已分级排序。是否实施、从哪阶段起，待船长定夺。
