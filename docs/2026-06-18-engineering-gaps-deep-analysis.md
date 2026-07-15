# 三大工程缺口深度分析（逐行代码 + 方案对比）

> 日期 2026-06-18 | 方法：3 个探员逐行读代码，带行号取证
> 范围：工具缓存 / 限流容错 / 阶段超时（地基三件套）
> 配套：[完成度审计](2026-06-18-completeness-audit.md)

## 〇、附加安全发现（先提醒）

探员发现 `config/model.json` **明文存放真实 GLM API key**（`7d0c60e2...`）。该文件已在 `.gitignore`（不会被提交），但之前曾存在含密钥的 `model.json.bak`（已删）。**建议船长到智谱后台轮换一次 token**，以防历史暴露。

---

## 一、工具缓存：一次分析同数据被取 2-5 次

### 现状（逐行重复点）
- **K 线**：被取 2~5 次。预取 get_kline（orchestrator.py:627）+ calc_technical 内部再取（calc_technical.py:24-36）+ LLM 自主调 + get_index 内部又调（get_index.py:401）
- **daily_basic**：被取 3 次。技术/基本面各调一次 + get_dcf 内部再调（get_dcf.py:84）
- **财务套件**：单次 get_financials = 5 次 API（get_financials.py:122-130），被取 3 轮 = **15 次**
- **同行对标 get_peers**：N+1 重灾区，9 个 code × (fina_indicator + daily_basic 多窗口) ≈ **19~46 次**（审计说的"16 次"是乐观估算）
- **汇总**：单股一次分析 ≈ 20~30 次 Tushare 调用，含 peers 时 40~60 次

### 根因：三层叠加，彼此不感知
1. 编排层"防幻觉预取"无条件拉一遍（orchestrator.py:624-636 等）——LLM 正常调工具时预取数据被白扔，但配额已耗
2. LLM 自主调一遍同一批工具（与预取完全重叠）
3. 工具内部互相再取（calc_technical→get_kline、get_dcf→get_financials+daily_basic、get_peers→循环）
- 放大：3 分析师 `ThreadPoolExecutor(max_workers=3)` 并行，瞬时并发 3 倍，直接触发 500/分钟限流

### 方案对比
| 方案 | 跨分析失效 | 跨股票隔离 | 并发安全 | 实时数据 | 结论 |
|------|-----------|-----------|---------|---------|------|
| `functools.lru_cache` | ❌ 永久（致命） | ❌ | ❌ | ❌ | 出局 |
| `cachetools.TTLCache` | ⚠️ 靠 TTL | ❌ | ⚠️ | ⚠️ | TTL 难调 |
| **请求级上下文缓存** | ✅ run 结束清空 | ✅ 天然 | ✅ 加锁 | ✅ | **推荐** |

### 推荐：请求级上下文缓存，加在 `_call` 层
`_call`（tushare_utils.py:63）是所有 Tushare 请求的**唯一收口**。在这一层加缓存，所有重复点一次性全命中，无需改业务工具。
- 新增 `RequestScopedCache` 类（带 threading.Lock）
- `_call` 走 `_cache.get_or_call(key, miss_fn)`
- `run_analysis` 开头 `_cache.enable()`，finally 里 `_cache.disable()`（**绝不能漏写 finally**）
- **预期降幅 50~60%**，限流压力腰斩

### 风险
1. **可变结果污染（最高危）**：`_call` 返回 list，业务到处 `.sort()`（get_kline.py:88 等）。命中必须返回浅拷贝 `list(result)` 或 `[dict(r) for r in result]`
2. **key 设计**：必须含完整 params（含 fields）——get_daily_basic 全字段 vs get_peers 精简字段 vs get_dcf 只取 close，key 不同
3. **异常不缓存**：失败不写缓存，允许重试

### 决策点
1. 缓存粒度：全量拦截 vs 豁免实时类（moneyflow）？建议全量
2. 浅拷贝 vs 深拷贝？建议浅拷贝（性能）
3. 要不要为 stock_basic 这类"天级慢变"数据加一层跨 run 的 TTL=24h 缓存（把 peers 的 19~46 次再降）？建议后做

---

## 二、限流容错：429 被静默吞成空数据

### 现状：错误处理链（3 环全吞）
1. `_call`（tushare_utils.py:69-72）：裸 requests.post，**零重试、不看 HTTP 状态码、不区分错误类型**，429 一律 raise
2. 工具 except（get_kline.py:144-153 等）：`except Exception` 全吞，转 `ok:False / data:None`
3. **最隐蔽的坑**：`get_financials.py:161-163`——3/4 报表 429 失败，整体仍返回 `ok:True`（第 203 行），quality 层第 51 行"非空检查"被绕过（all_data 是 dict 永远非空）
4. 上层（agent_loop.py:362-373）：不检查 ok 字段，把空数据透传给 LLM 继续打分

### 两套限流：必须分清
| | Tushare 429 | GLM 529 |
|---|---|---|
| 位置 | tushare_utils.py:69 | agent_loop.py:141 |
| 重试 | **零** | ✅ 指数退避（129-176） |
| 限速预防 | **无** | ✅ 令牌桶（22-70） |
| 结论 | **要修** | **好的，不用动** |

### 推荐：把 GLM 那套已验证的三件套移植到 Tushare
- **指数退避+抖动**：重试 4 次，base=1.0s，cap=20s，jitter=30%（比 GLM 短，因 Tushare 恢复更快）
- **令牌桶预防**：复用 `TokenBucketRateLimiter`，模块级全局单例（rate=2.0/s, burst=5）
- **失败类型分级**：transient（限流/网络，可重试）vs permanent（参数错误/无权限，不重试）；耗尽后返回 `failure_type` + `data_degraded:True`，让 quality 层升级处理、决策层降权
- **必须修 get_financials 假成功**：部分报表失败要标记降级

### 风险
- 重试加剧限流（雪崩）→ 靠令牌桶+30%抖动打散
- 延迟增加（最坏单工具 ~15s）→ 退避有界
- 误重试永久错误 → permanent 分支 break

### 决策点
1. 最大重试次数？建议 4 次
2. **耗尽后报错中断 vs 降级继续？**（产品决策）建议降级继续（符合系统"永不抛异常"哲学）
3. 是否加 Tushare 令牌桶？建议加
4. get_financials 假成功要不要改？强烈建议改

---

## 三、阶段超时：只有"门锁"，没有"楼层总闸"

### 现状：超时防御只做了第 1 层
| 层 | 状态 | 行号 |
|---|---|---|
| ① 单次 HTTP 调用（httpx 4 段超时） | ✅ Batch1 已做 | agent_loop.py:110-120 |
| ② 单次循环迭代级 | ❌ | — |
| ③ **阶段级**（分析师并行/辩论/经理） | ❌ | orchestrator.py:143 `future.result()` 无 timeout |
| ④ 总预算 deadline | ❌ | run_analysis 只用 start_time 算耗时，从不熔断 |

### 三种卡死场景
1. **并行分析师某只卡死**：其他两只干等 `future.result()`（:143 无 timeout），最坏拖 8 分钟
2. **串行阶段卡死**：辩论/经理/交易员顺序执行，前一个卡死后面积累无上限
3. **LLM 慢吐字（最危险）**：httpx read timeout 是"两次数据间隔"，模型慢慢吐字每次间隔<120s 就**永不超时**——这是历史上 9424s（2.6 小时）挂死事故的根因

### 方案对比
| 方案 | 改动 | 优点 | 缺点 |
|------|------|------|------|
| A. `future.result(timeout=X)` | 1 行 | 最小，ThreadPoolExecutor 原生支持 | 只罩并行段 |
| B. asyncio 重构 | 巨大 | 优雅 | 面客前不可接受 |
| C. 进程看门狗 | 高 | 唯一能强杀 | 复杂 |
| **D. 总预算 deadline 传递** | 中 | 全链罩，配合已有降级 | 需 6-8 处检查点 |

### 推荐：A + D 组合
- **并行段**：`future.result(timeout=180)`，超时走空结果降级
- **全链**：`run_analysis` 开头算 `deadline = start + 600s`，每阶段入口检查 `time.time() > deadline` 则跳到兜底合成
- **慢吐字**：read_timeout 120→90（缓解），彻底解决需进程级看门狗（第二批）
- **降级链已存在**：超时直接触发已有的确定性回退（orchestrator.py:479-504, 450-468），run_analysis 永不抛异常

### 参数建议（基于实测单股 4-9 分钟）
| 阶段 | 建议超时 |
|------|---------|
| 单分析师 | 180s |
| 辩论单边 | 90s |
| 经理/交易员 | 90s |
| **单股总预算** | **600s（10 分钟）** |

### 风险
- 超时太短误杀 → 初始偏宽（180s），观察日志后收紧
- 降级结果质量下降 → 已带 `synthesis_method` 标记，前端要展示
- `time.sleep(10)` 冷却（orchestrator.py:178/1018/1153/1392）吃 deadline 预算

### 决策点
1. 各阶段超时阈值（见上表）
2. **单股总预算多少？**建议 600s
3. **超时降级 vs 报错？**建议降级（符合系统哲学）
4. read_timeout 120→90？建议降
5. 批量进程级强杀？第二批再做

---

## 四、需船长拍板的关键决策（精选）

技术默认值船员可定，以下是**真正需要船长（产品决策）的点**：

| # | 决策 | 选项 | 船员建议 |
|---|------|------|---------|
| 1 | **限流耗尽后** | 报错中断 / 降级继续 | 降级继续（用户能看到分析，但标注哪部分不可信） |
| 2 | **阶段超时后** | 报错挂起 / 降级收尾 | 降级（run_analysis 永不抛异常，符合设计） |
| 3 | **单股总预算** | 480s / 600s / 900s | 600s（10 分钟，实测上限 9 分钟+1 分钟收尾） |
| 4 | **get_financials 假成功** | 改 / 不改 | 改（最隐蔽的坑，3/4 报表失败不该假装成功） |
| 5 | **stock_basic 跨 run 24h 缓存** | 加 / 后做 | 后做（优化项，先把核心缓存落地） |

---

## 五、实施顺序建议

1. **工具缓存**（独立、收益最大、风险可控）→ 先做，直接缓解限流
2. **限流容错**（依赖缓存落地后效果更明显）→ 紧接，修 get_financials 假成功
3. **阶段超时**（A+D 组合）→ 最后，给整套上保险丝

三件互相独立，可分 3 次提交，每次跑 E2E 验证。

---

**记录人**：船员（Claude，3-agent 逐行分析编队）
**状态**：深度分析完成，方案与决策点已列出。等船长就第四节拍板后，出详细实施计划。
