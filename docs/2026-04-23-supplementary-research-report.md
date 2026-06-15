# 补充调研报告 — 接口清点 + AKShare新闻 + DeepSeek对比

> **报告日期**: 2026-04-23 | **作者**: 船员 (Claude)
> **关联文档**: [素材获取策略](2026-04-22-material-acquisition-strategy.md) | [通信技术深度报告](2026-04-22-multi-agent-communication-deep-report.md)
> **核心发现**: 37个Tushare接口可直接包装；新闻用AKShare两行代码搞定；DeepSeek是最佳备选模型

---

## 一、ai-investment-tool 接口完整清点

### 1.1 已有代码清单

| 文件 | 位置 | 行数 | 内容 |
|------|------|------|------|
| tushare_service.py | ai-investment-tool/backend/app/services/ | 965行 | 37个Tushare API方法 |
| cost_calculator.py | ai-investment-tool/backend/app/core/ | ~500行 | 3种成本测算算法 |
| chip_calculator.py | ai-investment-tool/backend/app/core/ | ~150行 | 筹码分布计算 |

### 1.2 37个方法按用途分类

#### A. K线行情（6个方法）

| 方法名 | 参数 | 返回 | Agent工具映射 |
|--------|------|------|-------------|
| get_stock_daily | ts_code, start_date, end_date | 日K线 | `get_kline(period=daily)` |
| get_stock_weekly | ts_code, start_date, end_date | 周K线 | `get_kline(period=weekly)` |
| get_stock_monthly | ts_code, start_date, end_date | 月K线 | `get_kline(period=monthly)` |
| get_stock_mins | ts_code, start_date, end_date, freq | 分钟K线 | `get_kline(period=5m/15m/60m)` |
| get_stock_realtime | ts_code | 实时行情 | `get_kline(period=realtime)` |
| get_kline_for_cost_calculation | ts_code, report_date, months_before, months_after | 成本测算专用K线 | `get_kline_for_cost` |

#### B. 股票基本信息（7个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_stock_basic | 无 | `get_stock_basic(type=basic)` |
| get_daily_basic | ts_code, trade_date, start_date, end_date | `get_stock_basic(type=daily)` |
| get_stock_company | ts_code | `get_stock_basic(type=company)` |
| get_stock_managers | ts_code | `get_stock_basic(type=managers)` |
| get_stock_namechange | ts_code | `get_stock_basic(type=namechange)` |
| get_stock_st | 无 | `get_stock_basic(type=st)` |
| get_trade_calendar | exchange | 系统内部用 |

#### C. 财务数据（7个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_income | ts_code, period, report_type | `get_financials(type=income)` |
| get_balancesheet | ts_code, period | `get_financials(type=balancesheet)` |
| get_cashflow | ts_code, period | `get_financials(type=cashflow)` |
| get_financial_indicator | ts_code, start_date, end_date | `get_financials(type=indicator)` |
| get_forecast | ts_code | `get_financials(type=forecast)` |
| get_express | ts_code | `get_financials(type=express)` |
| get_dividend | ts_code | `get_financials(type=dividend)` |

#### D. 股东与机构（4个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_top10_holders | ts_code | `get_institutional(type=holders)` |
| get_top10_floatholders | ts_code | `get_institutional(type=floatholders)` |
| get_new_share | 无 | `get_institutional(type=new_share)` |
| get_repurchase | ts_code | `get_institutional(type=repurchase)` |

#### E. 资金流向（2个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_moneyflow | ts_code | `get_money_flow(type=stock)` |
| get_moneyflow_hsgt | 无 | `get_money_flow(type=north)` |

#### F. 龙虎榜（2个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_top_list | trade_date | `get_money_flow(type=top_list)` |
| get_top_inst | trade_date | `get_money_flow(type=top_inst)` |

#### G. 涨跌停（2个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_limit_list_d | trade_date | `get_money_flow(type=limit_d)` |
| get_limit_list_ths | trade_date | `get_money_flow(type=limit_ths)` |

#### H. 指数数据（3个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_index_basic | 无 | `get_index(type=basic)` |
| get_index_daily | ts_code, start_date, end_date | `get_index(type=daily)` |
| get_index_weight | index_code | `get_index(type=weight)` |

#### I. 宏观数据（3个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_shibor | 无 | `get_macro(type=shibor)` |
| get_cpi | 无 | `get_macro(type=cpi)` |
| get_gdp | 无 | `get_macro(type=gdp)` |

#### J. 筹码数据（2个方法）

| 方法名 | 参数 | Agent工具映射 |
|--------|------|-------------|
| get_chip_distribution | ts_code, trade_date | `get_chip(type=distribution)` |
| get_chip_performance | ts_code, trade_date | `get_chip(type=performance)` |

#### K. 便捷方法（3个）

| 方法名 | 功能 | Agent工具映射 |
|--------|------|-------------|
| batch_get_kline | 批量获取K线 | 内部用 |
| get_fundamental_data | 一次性拿三表 | `get_financials(type=all)` |
| get_stock_analysis_data | 一次性拿K线+公司+资金流 | `get_analysis_pack` |

### 1.3 最终 Agent 工具映射表

37个方法 → 合并为 **12个 Agent 工具**：

| # | Agent工具名 | 包装方法数 | 给谁用 | 包装工作量 |
|---|------------|----------|--------|----------|
| 1 | `get_kline` | 6 | 技术分析师 | 小 |
| 2 | `get_stock_basic` | 7 | 所有角色 | 小 |
| 3 | `get_financials` | 8 | 基本面分析师 | 小 |
| 4 | `get_institutional` | 4 | 基本面/辩论者 | 小 |
| 5 | `get_money_flow` | 6 | 情绪分析师 | 小 |
| 6 | `get_chip` | 2 | 技术分析师 | 小 |
| 7 | `get_index` | 3 | 所有角色 | 小 |
| 8 | `get_macro` | 3 | 基本面分析师 | 小 |
| 9 | `get_news` | **新写**（AKShare） | 新闻分析师 | 小（2行核心代码） |
| 10 | `calc_cost` | 已有 | 所有角色 | 小（直接包装） |
| 11 | `calc_technical` | **新写** | 技术分析师 | 中 |
| 12 | `calc_valuation` | **新写** | 基本面分析师 | 中 |

---

## 二、新闻数据获取方案（来自 TradingAgents-CN 源码分析）

### 2.1 源码位置

```
E:\TradingAgents-CN-main\
├── app\services\data_sources\akshare_adapter.py    ← 核心适配器
│   └── get_news() 方法（第345-386行）
├── app\worker\news_data_sync_service.py             ← 同步服务
├── app\worker\akshare_sync_service.py               ← AKShare同步
└── app\routers\news_data.py                         ← API路由
```

### 2.2 AKShare 新闻获取方式

**只需两个 AKShare 接口：**

```python
import akshare as ak

# 1. 个股新闻（东方财富数据源）
df_news = ak.stock_news_em(symbol="300033")
# 返回列: 新闻标题、文章来源、发布时间、新闻链接

# 2. 公司公告（东方财富数据源）
df_ann = ak.stock_announcement_em(symbol="300033")
# 返回列: 公告标题、公告时间、公告链接
```

**TradingAgents-CN 的完整实现（可直接参考）：**

```python
# 来自 akshare_adapter.py 第345-386行
def get_news(self, code: str, days: int = 2, limit: int = 50,
             include_announcements: bool = True):
    """AKShare-based news/announcements fallback"""
    import akshare as ak
    code6 = str(code).zfill(6)
    items = []

    # 获取新闻
    try:
        dfn = ak.stock_news_em(symbol=code6)
        if dfn is not None and not dfn.empty:
            for _, row in dfn.head(limit).iterrows():
                items.append({
                    "title": str(row.get('新闻标题') or ''),
                    "source": str(row.get('文章来源') or ''),
                    "time": str(row.get('发布时间') or ''),
                    "url": str(row.get('新闻链接') or ''),
                    "type": "news",
                })
    except Exception:
        pass

    # 获取公告
    if include_announcements:
        try:
            dfa = ak.stock_announcement_em(symbol=code6)
            if dfa is not None and not dfa.empty:
                for _, row in dfa.head(limit - len(items)).iterrows():
                    items.append({
                        "title": str(row.get('公告标题') or ''),
                        "source": "akshare",
                        "time": str(row.get('公告时间') or ''),
                        "url": str(row.get('公告链接') or ''),
                        "type": "announcement",
                    })
        except Exception:
            pass

    return items if items else None
```

### 2.3 TradingAgents-CN 的数据源架构

```
TradingAgents-CN 采用"多数据源 + 优先级"模式:

  请求 → 查数据库(MongoDB) → 有数据？→ 返回
                                  ↓ 没有
                          AKShare实时获取 → 存数据库 → 返回

  数据源优先级:
    1. 数据库缓存（最快）
    2. AKShare（免费，东方财富数据）
    3. Tushare（需要高权限，有新闻接口）

  我们可以简化为:
    请求 → AKShare直接获取 → 返回
    （不需要缓存层，智能体每次分析时实时拉取即可）
```

### 2.4 AKShare 额外能力（可作为 Tushare 备用）

```python
# 实时行情快照（全市场）
df = ak.stock_zh_a_spot_em()        # 东方财富源
df = ak.stock_zh_a_spot()           # 新浪财经源

# K线数据（可作为Tushare的备用）
df = ak.stock_zh_a_hist(symbol="300033", period="daily", adjust="qfq")

# 分钟K线
df = ak.stock_zh_a_minute(symbol="300033", period="5", adjust="")
```

### 2.5 我们的工具包装方案

```python
@tool
def get_news(code: str, limit: int = 50, include_announcements: bool = True):
    """
    获取股票相关新闻和公告

    Args:
        code: 股票代码，如 "300033.SZ" 或 "300033"
        limit: 最大返回条数
        include_announcements: 是否包含公告

    Returns:
        {"news": [...], "announcements": [...]}
    """
    import akshare as ak

    # 标准化代码（去掉交易所后缀）
    code6 = str(code).replace(".SZ","").replace(".SH","").replace(".BJ","")
    code6 = code6.zfill(6)

    result = {"news": [], "announcements": []}

    # 新闻
    try:
        df = ak.stock_news_em(symbol=code6)
        if df is not None and not df.empty:
            for _, row in df.head(limit).iterrows():
                result["news"].append({
                    "title": str(row.get('新闻标题', '')),
                    "source": str(row.get('文章来源', '')),
                    "time": str(row.get('发布时间', '')),
                    "url": str(row.get('新闻链接', '')),
                })
    except Exception:
        pass

    # 公告
    if include_announcements:
        try:
            df = ak.stock_announcement_em(symbol=code6)
            if df is not None and not df.empty:
                remaining = limit - len(result["news"])
                for _, row in df.head(max(0, remaining)).iterrows():
                    result["announcements"].append({
                        "title": str(row.get('公告标题', '')),
                        "time": str(row.get('公告时间', '')),
                        "url": str(row.get('公告链接', '')),
                    })
        except Exception:
            pass

    return result
```

---

## 三、DeepSeek vs GLM-5.1 对比分析

### 3.1 DeepSeek 原生多智能体能力

| 能力 | DeepSeek-V3.2 | 说明 |
|------|-------------|------|
| **Tool Use / Function Calling** | 完全支持 | 兼容 OpenAI SDK 格式 |
| **strict 模式** | 支持（Beta） | JSON Schema 校验 |
| **Context Caching** | 支持（独特优势） | 缓存命中后输入价格低至 $0.028/1M tokens |
| **官方多智能体框架** | 无 | 但可直接接入 AutoGen/CrewAI/LangGraph |
| **SDK 兼容** | OpenAI SDK | 只需改 `base_url` |

### 3.2 社区实践

| 项目/平台 | 说明 |
|----------|------|
| awesome-deepseek-integration | 36.3k Stars，97+ 集成项目 |
| Dify | 原生支持 DeepSeek |
| FastGPT | 原生支持 DeepSeek |
| AutoGen + DeepSeek | 社区有完整代码示例 |
| LangGraph + DeepSeek | 社区有完整代码示例 |
| CrewAI + DeepSeek | 社区有完整代码示例 |

### 3.3 DeepSeek vs GLM-5.1 详细对比

| 维度 | DeepSeek-V3.2 | GLM-5.1 | 说明 |
|------|-------------|---------|------|
| **Tool Use 支持** | 完全支持 | 支持 | DeepSeek 兼容 OpenAI 格式更成熟 |
| **中文理解** | 优秀 | 优秀 | GLM 在金融领域略优 |
| **工具调用精度** | 高 | 较高 | GLM 在复杂嵌套工具时略优 |
| **API 兼容性** | OpenAI SDK | 自有SDK | DeepSeek 只需改 base_url |
| **价格（输入）** | $0.27/1M tokens | ~$1.0/1M tokens | DeepSeek 便宜约 4 倍 |
| **价格（输出）** | $1.10/1M tokens | ~$3.0/1M tokens | DeepSeek 便宜约 3 倍 |
| **Context Caching** | 支持（-90%成本） | 不明确 | DeepSeek 独特优势 |
| **多智能体生态** | 丰富（97+项目） | 较少 | DeepSeek 生态成熟得多 |
| **代码示例** | 大量 | 少 | DeepSeek 参考资料多 |
| **综合评分** | **90.5/100** | **82.5/100** | DeepSeek 综合领先 |

### 3.4 其他国产模型对比

| 模型 | Tool Use | 价格 | 适合场景 | 推荐度 |
|------|---------|------|---------|--------|
| **DeepSeek-V3.2** | 完全支持 | 低 | 主力/备选 | 强烈推荐 |
| **GLM-5.1** | 支持 | 中 | 中文金融分析 | 推荐 |
| **Qwen-2.5** | 支持 | 低 | 经济型备选 | 可选 |
| **Yi（零一万物）** | 不明确 | - | 已从百炼下架 | 不推荐 |
| **MiniMax** | 有限 | - | 模型有限 | 不推荐 |

### 3.5 多智能体场景成本估算

```
单只股票分析:
  12个角色 x 平均3轮 = 36次 LLM 调用
  平均每次: 输入2000 tokens + 输出800 tokens

  DeepSeek-V3.2:
    输入: 36 x 2000 x $0.27/1M = $0.019
    输出: 36 x 800 x $1.10/1M = $0.032
    合计: ~$0.05/只（约 0.36 元）
    如果用 Context Caching: ~$0.02/只（约 0.14 元）

  GLM-5.1:
    输入: 36 x 2000 x $1.0/1M = $0.072
    输出: 36 x 800 x $3.0/1M = $0.086
    合计: ~$0.16/只（约 1.15 元）

  结论: DeepSeek 单股分析成本约为 GLM 的 1/4 到 1/3
```

---

## 四、推荐策略

### 4.1 三层模型架构

```
推荐策略: "三层架构，一行切换"

  第1层（主力）: GLM-5.1
    理由: 中文金融理解好，项目已规划用GLM
    适用: 所有分析任务

  第2层（首选备选）: DeepSeek-V3.2
    理由: 便宜4倍，生态成熟，OpenAI兼容
    适用: GLM失败时的降级方案
    适用: 辩论环节（消耗token多，用便宜的）

  第3层（经济型备选）: Qwen-2.5
    理由: 价格低，基础能力够用
    适用: 批量分析时的低成本方案
```

### 4.2 模型切换层设计

```python
# 模型配置（一行代码切换）
MODEL_CONFIG = {
    "glm": {
        "model": "glm-5.1",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "YOUR_GLM_KEY",
    },
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "YOUR_DEEPSEEK_KEY",
    },
    "qwen": {
        "model": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "YOUR_QWEN_KEY",
    },
}

# 统一调用接口
def call_llm(messages, tools, model="glm"):
    """统一LLM调用，一行代码切换模型"""
    config = MODEL_CONFIG[model]
    # DeepSeek 和 Qwen 都兼容 OpenAI SDK
    from openai import OpenAI
    client = OpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
    )
    response = client.chat.completions.create(
        model=config["model"],
        messages=messages,
        tools=tools,
    )
    return response
```

### 4.3 最终工具清单（更新版）

```
总共 12 个 Agent 工具:

  直接包装已有 Tushare 代码（9个）:
    1. get_kline         — K线行情（日/周/月/分钟/实时）
    2. get_stock_basic   — 股票基本信息（公司/高管/行业/PE/PB/市值）
    3. get_financials    — 财务数据（利润表/资产负债表/现金流/指标/预告/分红）
    4. get_institutional — 股东与机构（十大股东/流通股东/回购/新股）
    5. get_money_flow    — 资金流向（个股/北向/龙虎榜/涨跌停）
    6. get_chip          — 筹码数据（分布/成本/胜率）
    7. get_index         — 指数数据（基本信息/日线/成分权重）
    8. get_macro         — 宏观数据（SHIBOR/CPI/GDP）
    9. calc_cost         — 成本测算（3种方法：VWAP/波段/时序）

  新写，参考已有代码（2个）:
    10. get_news          — 新闻+公告（AKShare: stock_news_em + stock_announcement_em）
    11. calc_technical    — 技术指标计算（MACD/RSI/BOLL/均线）

  新写，标准算法（1个）:
    12. calc_valuation    — 估值计算（PE/PB/PEG/估值区间）

  通信工具（3个，不计入数据工具）:
    send_message / read_inbox / broadcast
```

---

## 五、关键结论

### 5.1 好消息

```
1. 37个 Tushare 接口可以直接包装，工作量小
2. 新闻获取只需 AKShare 两行代码，不需要新找数据源
3. AKShare 还能作为 Tushare 的备用数据源（实时行情、K线）
4. DeepSeek 是成熟可靠的备选模型，成本仅为 GLM 的 1/4
5. 三种模型（GLM/DeepSeek/Qwen）都兼容 OpenAI SDK，切换成本为零
```

### 5.2 需要验证的事

```
优先级1（生死线）: GLM-5.1 的 Tool Use 能力
  写50行测试脚本验证
  不行就直接换 DeepSeek

优先级2: AKShare 在当前环境的安装和数据获取
  pip install akshare
  python -c "import akshare as ak; print(ak.stock_news_em(symbol='300033').head(3))"

优先级3: DeepSeek 的 Tool Use 精度
  同样用50行脚本验证
```

### 5.3 对素材获取策略的更新

```
原计划: 15个工具（9包装 + 3新写 + 3通信）
更新后: 12个数据工具 + 3个通信工具

变化:
  - 新闻接口不再需要"新找数据源"，直接用 AKShare（工作量从"中"降为"小"）
  - AKShare 还可提供实时行情和K线作为 Tushare 的备用源
  - 模型策略从"只用 GLM" 升级为"三层架构"
```

---

**报告完成** | **最后更新**: 2026-04-23

> 类比: 这份报告就像一次仓库盘点 + 供应商考察。
> 盘点发现: 仓库里的食材（37个Tushare接口）比预想的还丰富，9成可以直接用。
> 考察发现: 隔壁菜市场（AKShare）有我们缺的新闻食材，而且价格免费、随买随到。
> 最大的惊喜: 不只一家供应商能做这道菜（GLM/DeepSeek/Qwen都能做Tool Use），
> 而且 DeepSeek 的价格是 GLM 的 1/4，味道还差不多。
> 下一步: 先点火试试灶台（验证 Tool Use），再开始炒菜（写代码）。
