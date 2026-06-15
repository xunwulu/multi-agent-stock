"""
get_stock_news - 个股新闻资讯 + 市场情绪工具

数据源:
  - 主源: AKShare stock_news_em (东方财富个股新闻10条)
  - 辅助: AKShare 情绪数据 (关注度/综合评分)
  - 补充: Tushare major_news (全市场新闻, 按股票名过滤)
"""

import time
import logging
from datetime import datetime

from src.tools.tushare_utils import get_tushare_client, normalize_code

logger = logging.getLogger(__name__)

# 关键词情绪判断
_POSITIVE_KEYWORDS = [
    "利好", "增长", "扭亏", "摘帽", "获批", "中标", "签约", "合作",
    "增持", "回购", "分红", "业绩超预期", "上调", "突破", "创新高",
    "涨停", "大涨", "预增", "定增", "注入", "投产", "量产",
    "纳入", "扩产", "评级上调", "买入评级",
]
_NEGATIVE_KEYWORDS = [
    "利空", "亏损", "下降", "ST", "退市", "违规", "处罚", "减持",
    "质押", "暴雷", "违约", "风险", "警示", "下调", "跌破",
    "立案调查", "商誉减值", "资金占用", "冻结", "诉讼",
    "财务造假", "降级", "破发", "破净", "解禁",
]
# 关键事件关键词
_EVENT_KEYWORDS = [
    "摘帽", "ST", "退市", "停牌", "复牌", "业绩", "增减持", "回购",
    "并购", "重组", "中标", "签约", "获批", "分红", "质押",
    "定增", "股权激励", "解禁", "举牌", "要约收购",
    "业绩预告", "问询函", "更名",
]


def get_stock_news(code: str) -> dict:
    """
    获取个股新闻资讯 + 市场情绪数据

    Args:
        code: 股票代码 (如 600358.SH 或 600358)

    Returns:
        {
            "ok": True,
            "data": [{title, content, source, datetime, url}, ...],
            "sentiment": {attention_score, composite_score, hot_rank},
            "summary": {sentiment_hint, key_events, latest_news_date, news_count},
            "count": N,
            "duration_ms": N,
            "error": None
        }
    """
    start_ms = time.time()
    all_news = []
    sentiment_data = {}
    errors = []

    # 提取6位纯数字
    code6 = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

    # 0. 提前获取股票名称（用于名称搜索和后续 Tushare 过滤）
    stock_name = ""
    try:
        client = get_tushare_client()
        stock_name = _get_stock_name(client, code)
    except Exception:
        client = None

    # 1. 主源: AKShare stock_news_em（代码搜索）
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=code6)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                all_news.append({
                    "title": str(row.get("新闻标题", "")),
                    "content": str(row.get("新闻内容", "")),
                    "source": str(row.get("文章来源", "")),
                    "datetime": str(row.get("发布时间", "")),
                    "url": str(row.get("新闻链接", "")),
                })
            logger.info(f"[get_stock_news] AKShare stock_news_em: {len(all_news)} articles")
        else:
            logger.info("[get_stock_news] AKShare stock_news_em: no data")
    except Exception as e:
        errors.append(f"akshare_stock_news_em: {e}")
        logger.warning(f"[get_stock_news] AKShare stock_news_em error: {e}")

    # 1.5 补充: AKShare stock_news_em（名称搜索）
    if stock_name:
        try:
            import akshare as ak
            df2 = ak.stock_news_em(symbol=stock_name)
            if df2 is not None and not df2.empty:
                for _, row in df2.iterrows():
                    all_news.append({
                        "title": str(row.get("新闻标题", "")),
                        "content": str(row.get("新闻内容", "")),
                        "source": str(row.get("文章来源", "")),
                        "datetime": str(row.get("发布时间", "")),
                        "url": str(row.get("新闻链接", "")),
                    })
                logger.info(
                    f"[get_stock_news] AKShare stock_news_em (name): "
                    f"{len(all_news)} total articles"
                )
        except Exception as e:
            errors.append(f"akshare_stock_news_em_name: {e}")
            logger.warning(
                f"[get_stock_news] AKShare stock_news_em name search error: {e}"
            )

        # 1.6 补充: 巨潮信息网公告 (cninfo, 科学取样: 分类保底 + MMR 多样性)
    try:
        import akshare as ak
        from datetime import timedelta
        from src.tools.announcement_sampler import sample_announcements
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=730)
        df_cninfo = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=code6,
            start_date=start_dt.strftime('%Y%m%d'),
            end_date=end_dt.strftime('%Y%m%d'),
        )
        if df_cninfo is not None and not df_cninfo.empty:
            rows_list = [row for _, row in df_cninfo.iterrows()]
            _selected = sample_announcements(
                rows_list, stock_name, code6, budget=10
            )
            for row in _selected:
                content_text = ''
                for key in ['公告摘要', '公告内容', '摘要', 'content']:
                    val = row.get(key)
                    if val and isinstance(val, str) and len(val.strip()) > 0:
                        content_text = val.strip()[:500]
                        break
                # cninfo list API does not return body text; use title as fallback
                if not content_text:
                    content_text = str(row.get('公告标题', ''))
                all_news.append({
                    'title': str(row.get('公告标题', '')),
                    'content': content_text,
                    'source': '巨潮信息网',
                    'datetime': str(row.get('公告时间', '')),
                    'url': str(row.get('公告链接', '')),
                    'type': 'announcement',
                })
            logger.info(
                f'[get_stock_news] cninfo: '
                f'{len(_selected)}/{len(df_cninfo)} sampled'
            )
    except Exception as e:
        errors.append(f'cninfo_announcements: {e}')
        logger.warning(f'[get_stock_news] cninfo error: {e}')

# 2. 辅助: AKShare 情绪数据 (1次重试)
    for _attempt in range(2):
        try:
            import akshare as ak
            # 尝试获取个股热度排名
            hot_df = ak.stock_hot_rank_em()
            if hot_df is not None and not hot_df.empty:
                # 查找当前股票
                match = hot_df[hot_df["股票代码"] == code6]
                if not match.empty:
                    row = match.iloc[0]
                    sentiment_data["hot_rank"] = int(row.get("当前排名", 0))
                    sentiment_data["hot_score"] = float(row.get("个股热度", 0))
            break
        except Exception as e:
            if _attempt == 0:
                logger.info(f"[get_stock_news] Sentiment data retry: {e}")
            else:
                logger.info(f"[get_stock_news] Sentiment data skipped: {e}")

    # 3. 补充: Tushare major_news (按股票名过滤, 带日期+来源参数)
    if len(all_news) < 5:
        try:
            if client is None:
                client = get_tushare_client()
            if stock_name:
                _mn_end = datetime.now().strftime("%Y%m%d")
                _mn_start = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
                raw = client._call("major_news", {
                    "src": "sina",
                    "start_date": _mn_start,
                    "end_date": _mn_end,
                })
                if isinstance(raw, list):
                    for item in raw:
                        title = str(item.get("title", ""))
                        content = str(item.get("content", ""))
                        if stock_name in title or stock_name in content:
                            all_news.append({
                                "title": title,
                                "content": content[:500],
                                "source": str(item.get("channels", "")),
                                "datetime": str(item.get("pub_time", "")),
                                "url": str(item.get("url", "")),
                            })
                    logger.info(f"[get_stock_news] Tushare major_news: found matches for {stock_name}")
        except Exception as e:
            errors.append(f"tushare_major_news: {e}")
            logger.warning(f"[get_stock_news] Tushare major_news error: {e}")

    # 4. 给每条新闻打标签 + 去重 + 板块限流
    _tagged = _add_news_tags(all_news, stock_name, code6)
    seen_titles = set()
    unique_news = []
    for n in _tagged:
        t = n["title"].strip()
        if t and t not in seen_titles:
            seen_titles.add(t)
            unique_news.append(n)

    # 板块综述限流: specificity=low 最多保留 3 条
    _low_count = 0
    _filtered = []
    for n in unique_news:
        if n.get("specificity") == "low":
            _low_count += 1
            if _low_count <= 3:
                _filtered.append(n)
        else:
            _filtered.append(n)
    unique_news = _filtered

    # 按时间降序排序，再截取最新20条
    unique_news.sort(key=lambda n: n.get("datetime", ""), reverse=True)
    output = unique_news[:20]

    # 5. 预计算 summary
    summary = _build_news_summary(output, sentiment_data)

    # 5.5 预计算 scoring_hints（确定性评分建议）
    scoring_hints = _calc_scoring_hints(output)

    duration_ms = int((time.time() - start_ms) * 1000)
    logger.info(
        f"[get_stock_news] {code} total: {len(output)} articles, "
        f"{duration_ms}ms"
    )

    # 计算分类统计
    _category_counts = {}
    for n in output:
        cat = n.get("event_category", "market")
        _category_counts[cat] = _category_counts.get(cat, 0) + 1

    return {
        "ok": len(output) > 0,
        "data": output,
        "sentiment": sentiment_data,
        "summary": summary,
        "scoring_hints": scoring_hints,
        "category_counts": _category_counts,
        "count": len(output),
        "duration_ms": duration_ms,
        "error": "; ".join(errors) if errors else None,
    }


def _get_stock_name(client, code: str) -> str:
    """从 stock_basic 获取股票名称"""
    try:
        ts_code = normalize_code(code)
        df = client._call("stock_basic", {
            "ts_code": ts_code,
            "fields": "ts_code,name",
        })
        if isinstance(df, list) and len(df) > 0:
            return str(df[0].get("name", ""))
        if hasattr(df, "empty") and not df.empty:
            return str(df.iloc[0].get("name", ""))
    except Exception:
        pass
    return ""




# 新闻分类标签关键词规则
_EVENT_CATEGORY_RULES = [
    ("financial", ["业绩", "营收", "利润", "财报", "季报", "年报", "毛利率",
                   "净利润", "每股收益", "净资产", "ROE", "分红",
                   "业绩预告", "业绩快报", "财务"]),
    ("governance", ["ST", "退市", "立案", "调查", "处罚", "违规", "资金占用",
                    "内控", "监管", "警示", "问询函", "关注函", "整改",
                    "否定意见", "保留意见", "造假"]),
    ("corporate", ["并购", "重组", "收购", "回购", "增持", "减持", "定增",
                   "股权激励", "举牌", "要约收购", "注入", "控制权"]),
    ("operational", ["中标", "签约", "获批", "投产", "量产", "新产品",
                     "合作", "战略", "项目", "订单"]),
]

_SECTOR_KEYWORDS = ["板块", "行业", "概念", "题材", "龙头", "ETF"]


def _classify_news(news: dict, stock_name: str, code6: str) -> dict:
    """给新闻打标签（描述性，非评价性）"""
    title = news.get("title", "")
    source = news.get("source", "")
    dt_str = news.get("datetime", "")

    # 1. source_type
    if news.get("type") == "announcement" or "巨潮" in source:
        source_type = "official"
    elif any(w in source for w in ["sina", "新浪", "财联社", "证券时报"]):
        source_type = "wire"
    else:
        source_type = "media"

    # 2. event_category
    event_category = "market"  # 兜底
    for cat, keywords in _EVENT_CATEGORY_RULES:
        if any(kw in title for kw in keywords):
            event_category = cat
            break

    # 3. specificity
    if stock_name and stock_name in title:
        specificity = "high"
    elif code6 in title:
        specificity = "high"
    elif any(kw in title for kw in _SECTOR_KEYWORDS):
        specificity = "low"
    else:
        specificity = "medium"

    # 4. time_weight
    time_weight = 0.2
    try:
        dt_clean = dt_str.split(".")[0].split("+")[0].strip()[:10]
        news_dt = datetime.strptime(dt_clean, "%Y-%m-%d")
        days = (datetime.now() - news_dt).days
        if days <= 7:
            time_weight = 1.0
        elif days <= 14:
            time_weight = 0.7
        elif days <= 30:
            time_weight = 0.4
    except (ValueError, IndexError):
        pass

    return {
        "source_type": source_type,
        "event_category": event_category,
        "specificity": specificity,
        "time_weight": time_weight,
    }


def _add_news_tags(news_list: list, stock_name: str, code6: str) -> list:
    """为每条新闻添加分类标签"""
    for n in news_list:
        tags = _classify_news(n, stock_name, code6)
        n.update(tags)
    return news_list


def _build_news_summary(news_list: list, sentiment_data: dict) -> dict:
    """构建新闻摘要"""
    if not news_list:
        return {
            "sentiment_hint": "neutral",
            "key_events": [],
            "latest_news_date": None,
            "news_count": 0,
        }

    # 情绪判断: 基于标题关键词
    pos_count = 0
    neg_count = 0
    for n in news_list:
        title = n.get("title", "")
        if any(kw in title for kw in _POSITIVE_KEYWORDS):
            pos_count += 1
        if any(kw in title for kw in _NEGATIVE_KEYWORDS):
            neg_count += 1

    if pos_count > neg_count + 1:
        sentiment_hint = "positive"
    elif neg_count > pos_count + 1:
        sentiment_hint = "negative"
    else:
        sentiment_hint = "mixed"

    # 关键事件识别
    key_events = []
    seen_events = set()
    for n in news_list:
        title = n.get("title", "")
        for kw in _EVENT_KEYWORDS:
            if kw in title and kw not in seen_events:
                seen_events.add(kw)
                key_events.append(kw)

    # 最新新闻日期
    dates = [n.get("datetime", "") for n in news_list if n.get("datetime")]
    latest_date = max(dates) if dates else None

    return {
        "sentiment_hint": sentiment_hint,
        "key_events": key_events[:5],
        "latest_news_date": latest_date,
        "news_count": len(news_list),
    }


# 高冲击事件关键词（用于 scoring_hints.event_impact）
_HIGH_IMPACT_KEYWORDS = [
    "ST", "退市", "摘帽", "暴雷", "并购", "重组", "要约收购",
    "业绩暴雷", "收购", "注入", "财务造假",
]
_MEDIUM_IMPACT_KEYWORDS = [
    "增减持", "中标", "签约", "获批", "定增", "股权激励",
    "解禁", "举牌", "业绩预告", "行业政策",
]
_HIGH_RISK_KEYWORDS = [
    "ST", "退市", "暴雷", "立案调查", "财务造假", "冻结",
    "资金占用", "破产",
]
_MEDIUM_RISK_KEYWORDS = [
    "减持", "质押", "违规", "处罚", "诉讼", "商誉减值",
    "问询函", "警示",
]


def _calc_scoring_hints(news_list: list) -> dict:
    """
    预计算新闻评分建议（确定性计算，非LLM判断）。

    对应 news-analyst.md 的 6 项 scoring_breakdown:
      positive_events: 正面事件数 x 3, 上限 15
      negative_events: 负面事件数 x -3, 下限 -15
      event_timeliness: 最新新闻距今天数映射 (<=3d:10, <=7d:7, <=14d:4, else:0)
      event_impact: 最强冲击等级 (high:10, medium:6, low:3, none:0)
      sentiment_alignment: 正/负面数比值 (一致:10, 大致:7, 分歧:3)
      risk_level: 风险等级 (high:-10, medium:-6, low:-3, none:0)
    """
    if not news_list:
        return {
            "positive_events": {"score": 0, "reason": "No news data"},
            "negative_events": {"score": 0, "reason": "No news data"},
            "event_timeliness": {"score": 0, "reason": "No news data"},
            "event_impact": {"score": 0, "reason": "No news data"},
            "sentiment_alignment": {"score": 3, "reason": "No data, default low"},
            "risk_level": {"score": 0, "reason": "No news data"},
        }

    # 1. positive_events / negative_events
    # 排除 specificity=low 的板块综述（不算该股票的正/负面事件）
    pos_count = 0
    neg_count = 0
    for n in news_list:
        if n.get("specificity") == "low":
            continue
        title = n.get("title", "")
        content_text = n.get("content", "")
        text = title + " " + content_text
        if any(kw in text for kw in _POSITIVE_KEYWORDS):
            pos_count += 1
        if any(kw in text for kw in _NEGATIVE_KEYWORDS):
            neg_count += 1

    positive_score = min(pos_count * 3, 15)
    negative_score = max(neg_count * -3, -15)

    # 2. event_timeliness
    timeliness_score = 0
    timeliness_reason = "No valid dates"
    now = datetime.now()
    for n in news_list:
        dt_str = n.get("datetime", "")
        if not dt_str:
            continue
        try:
            dt_str_clean = dt_str.split(".")[0].split("+")[0].strip()
            news_dt = datetime.strptime(dt_str_clean[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            try:
                news_dt = datetime.strptime(dt_str_clean[:10], "%Y-%m-%d")
            except (ValueError, IndexError):
                continue
        days_diff = (now - news_dt).days
        if days_diff <= 3:
            timeliness_score = 10
            timeliness_reason = f"Latest news {days_diff}d ago (within 3d)"
            break
        elif days_diff <= 7 and timeliness_score < 7:
            timeliness_score = 7
            timeliness_reason = f"Latest news {days_diff}d ago (within 7d)"
        elif days_diff <= 14 and timeliness_score < 4:
            timeliness_score = 4
            timeliness_reason = f"Latest news {days_diff}d ago (within 14d)"

    if timeliness_score == 0 and not timeliness_reason.startswith("Latest"):
        timeliness_reason = "All news older than 14 days"

    # 3. event_impact
    impact_score = 0
    impact_reason = "No impact events found"
    for n in news_list:
        title = n.get("title", "")
        if any(kw in title for kw in _HIGH_IMPACT_KEYWORDS):
            impact_score = 10
            impact_reason = f"High impact: {title[:40]}"
            break
    if impact_score == 0:
        for n in news_list:
            title = n.get("title", "")
            if any(kw in title for kw in _MEDIUM_IMPACT_KEYWORDS):
                impact_score = 6
                impact_reason = f"Medium impact: {title[:40]}"
                break
    if impact_score == 0 and pos_count + neg_count > 0:
        impact_score = 3
        impact_reason = "Only low impact events"

    # 4. sentiment_alignment
    total = pos_count + neg_count
    if total == 0:
        alignment_score = 3
        alignment_reason = "No sentiment signals, default low"
    elif min(pos_count, neg_count) == 0:
        alignment_score = 10
        alignment_reason = f"Unanimous: {pos_count} pos, {neg_count} neg"
    elif max(pos_count, neg_count) / max(total, 1) >= 0.75:
        alignment_score = 7
        alignment_reason = f"Mostly aligned: {pos_count} pos, {neg_count} neg"
    else:
        alignment_score = 3
        alignment_reason = f"Divergent: {pos_count} pos, {neg_count} neg"

    # 5. risk_level
    risk_score = 0
    risk_reason = "No risk events detected"
    for n in news_list:
        title = n.get("title", "")
        if any(kw in title for kw in _HIGH_RISK_KEYWORDS):
            risk_score = -10
            risk_reason = f"High risk: {title[:40]}"
            break
    if risk_score == 0:
        for n in news_list:
            title = n.get("title", "")
            if any(kw in title for kw in _MEDIUM_RISK_KEYWORDS):
                risk_score = -6
                risk_reason = f"Medium risk: {title[:40]}"
                break
    if risk_score == 0 and neg_count > 0:
        risk_score = -3
        risk_reason = f"Low risk: {neg_count} negative articles"

    return {
        "positive_events": {
            "score": positive_score,
            "reason": f"{pos_count} positive articles -> {positive_score}",
        },
        "negative_events": {
            "score": negative_score,
            "reason": f"{neg_count} negative articles -> {negative_score}",
        },
        "event_timeliness": {
            "score": timeliness_score,
            "reason": timeliness_reason,
        },
        "event_impact": {
            "score": impact_score,
            "reason": impact_reason,
        },
        "sentiment_alignment": {
            "score": alignment_score,
            "reason": alignment_reason,
        },
        "risk_level": {
            "score": risk_score,
            "reason": risk_reason,
        },
    }
