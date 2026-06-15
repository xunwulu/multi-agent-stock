"""
announcement_sampler - 公告科学取样模块

两阶段取样：
  Stage 1: 分类保底（确保每类事件至少 1 条）
  Stage 2: MMR 多样性选取（同类内选最不重复的）

学术基础: MMR (Carbonell & Goldstein, SIGIR 1998)
  score = lambda * relevance - (1-lambda) * max_similarity_to_selected
  贪心算法: 先选最相关的, 再选第二相关但和第一条不同的, 依此类推
"""
import math
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 事件分类规则（优先级从高到低，匹配第一个就停止）
# (类别名, 关键词列表, 是否风险类)
EVENT_CATEGORIES = [
    ("listing", [
        "ST", "退市", "摘帽", "停牌", "复牌",
    ], True),
    ("governance", [
        "立案", "调查", "处罚", "违规", "资金占用", "内控",
        "监管", "警示", "问询函", "关注函", "整改", "造假",
        "否定意见", "保留意见",
    ], True),
    ("major", [
        "并购", "重组", "收购", "要约收购", "注入", "控制权",
    ], False),
    ("equity", [
        "增持", "减持", "回购", "质押", "解禁", "举牌",
        "定增", "股权激励",
    ], False),
    ("earnings", [
        "业绩", "业绩预告", "业绩快报", "分红",
        "年报", "季报", "半年报", "财务报告",
    ], False),
    ("contract", [
        "中标", "签约", "获批", "投产", "量产", "订单",
    ], False),
    ("regulatory", [
        "更名", "制度", "章程", "股东大会", "董事会",
    ], False),
]

BUDGET = 10   # 总选取数量
LAMBDA = 0.6  # MMR 参数: 0.6 = 偏重相关性, 0.4 = 偏重多样性

# --- 用于相关性评分的关键词 ---
_HIGH_IMPACT = [
    "ST", "退市", "摘帽", "暴雷", "并购", "重组",
    "要约收购", "收购", "注入", "财务造假",
]
_MED_IMPACT = [
    "增减持", "中标", "签约", "获批", "定增", "股权激励",
    "解禁", "举牌", "业绩预告", "业绩快报",
]
_HIGH_RISK = [
    "ST", "退市", "暴雷", "立案调查", "财务造假",
    "资金占用", "破产", "冻结",
]
_MED_RISK = [
    "减持", "质押", "违规", "处罚", "诉讼", "商誉减值",
    "问询函", "警示",
]

# 用于相似度计算的合并关键词集合
_ALL_KWS = set()
for _, kws, _ in EVENT_CATEGORIES:
    _ALL_KWS.update(kws)


def classify_announcement(title: str) -> str:
    """按优先级匹配事件类别（第一个匹配的生效）"""
    for cat_name, keywords, _ in EVENT_CATEGORIES:
        if any(kw in title for kw in keywords):
            return cat_name
    return "routine"


def _relevance_score(item: dict) -> float:
    """
    公告相关性评分（确定性计算，不用 LLM）

    考虑因素：
      - 影响力关键词加分 (ST/并购 等 = 10, 中标/签约 等 = 6)
      - 风险关键词加分 (退市/造假 等 = 10, 违规/处罚 等 = 6)
      - 时效性指数衰减 (半衰期 ~125 天)
      - 官方来源加分 (+2)
    """
    title = item.get("title", "")
    dt_str = item.get("datetime", "")
    score = 0.0

    # 影响力加分
    if any(kw in title for kw in _HIGH_IMPACT):
        score += 10
    elif any(kw in title for kw in _MED_IMPACT):
        score += 6

    # 风险加分
    if any(kw in title for kw in _HIGH_RISK):
        score += 10
    elif any(kw in title for kw in _MED_RISK):
        score += 6

    # 时效性: 指数衰减
    try:
        dt_clean = dt_str.split(".")[0].split("+")[0].strip()[:10]
        days_ago = (datetime.now() - datetime.strptime(dt_clean, "%Y-%m-%d")).days
        score += 10 * math.exp(-days_ago / 180)
    except (ValueError, IndexError):
        score += 1

    # 官方来源加分
    if item.get("type") == "announcement":
        score += 2

    return score


def _similarity(a: dict, b: dict) -> float:
    """
    两条公告的相似度（关键词 Jaccard，不需要外部依赖）

    范围 [0, 1]: 0 = 完全不同, 1 = 关键词完全一样
    """
    kw_a = {kw for kw in _ALL_KWS if kw in a.get("title", "")}
    kw_b = {kw for kw in _ALL_KWS if kw in b.get("title", "")}

    if not kw_a and not kw_b:
        # 都没有已知关键词 -> 用字符 bigram 重叠度
        ta, tb = a.get("title", ""), b.get("title", "")
        if len(ta) < 2 or len(tb) < 2:
            return 0.0
        ba = {ta[i:i + 2] for i in range(len(ta) - 1)}
        bb = {tb[i:i + 2] for i in range(len(tb) - 1)}
        return len(ba & bb) / max(len(ba | bb), 1)

    if not kw_a or not kw_b:
        return 0.0

    return len(kw_a & kw_b) / len(kw_a | kw_b)


def _mmr_select(candidates: list, budget: int) -> list:
    """MMR 贪心选取: 选 budget 条既相关又不重复的公告"""
    if not candidates:
        return []
    if len(candidates) <= budget:
        return list(candidates)

    remaining = list(candidates)
    selected = []

    for _ in range(budget):
        if not remaining:
            break
        best_score = float("-inf")
        best_idx = 0

        for i, item in enumerate(remaining):
            rel = _relevance_score(item)
            if not selected:
                div = 0
            else:
                div = max(_similarity(item, s) for s in selected)
            score = LAMBDA * rel - (1 - LAMBDA) * div
            if score > best_score:
                best_score = score
                best_idx = i

        selected.append(remaining.pop(best_idx))

    return selected


def sample_announcements(df_rows: list, stock_name: str = "",
                         code6: str = "", budget: int = BUDGET) -> list:
    """
    两阶段科学取样:
      Stage 1: 分类保底 - 风险类至少 1 条
      Stage 2: MMR 多样性 - 同类内选最不重复的

    Args:
        df_rows: DataFrame 行列表 (cninfo 公告)
        stock_name: 股票名称 (用于日志)
        code6: 6位代码 (用于日志)
        budget: 总选取数量 (默认 10)

    Returns:
        选取后的行列表 (最多 budget 条)
    """
    # 总数不够就直接返回
    if len(df_rows) <= budget:
        logger.info(
            f"[announcement_sampler] {stock_name or code6}: "
            f"{len(df_rows)} <= budget {budget}, returning all"
        )
        return list(df_rows)

    # Step 1: 分类
    classified = {}
    for row in df_rows:
        title = str(row.get("公告标题", ""))
        cat = classify_announcement(title)
        if cat not in classified:
            classified[cat] = []
        classified[cat].append(row)

    # Step 2: 分类保底分配
    risk_cats = {cat for cat, _, is_risk in EVENT_CATEGORIES if is_risk}
    risk_slots = {}
    normal_slots = {}
    reserved = 0

    for cat, items in classified.items():
        if cat in risk_cats:
            risk_slots[cat] = 1
            reserved += 1
        else:
            normal_slots[cat] = 0

    # 剩余名额按比例分给非风险类
    remaining_budget = budget - reserved
    normal_total = sum(len(classified[cat]) for cat in normal_slots)
    if normal_total > 0 and remaining_budget > 0:
        for cat in normal_slots:
            share = len(classified[cat]) / normal_total
            normal_slots[cat] = max(1, round(share * remaining_budget))
        # 校正: 确保总数不超过 budget
        total_allocated = reserved + sum(normal_slots.values())
        if total_allocated > budget:
            excess = total_allocated - budget
            for cat in sorted(
                normal_slots, key=lambda c: normal_slots[c], reverse=True
            ):
                if excess <= 0:
                    break
                reduce_by = min(excess, max(0, normal_slots[cat] - 1))
                normal_slots[cat] -= reduce_by
                excess -= reduce_by

    # Step 3: 每个类别内用 MMR 选取
    all_slots = {**risk_slots, **normal_slots}
    selected = []
    for cat, slot_count in all_slots.items():
        if slot_count <= 0 or cat not in classified:
            continue
        cat_selected = _mmr_select(classified[cat], slot_count)
        selected.extend(cat_selected)

    # 如果还有空位, 从最多的类别补
    if len(selected) < budget:
        used_titles = {str(s.get("公告标题", "")) for s in selected}
        for cat, items in classified.items():
            for item in items:
                if len(selected) >= budget:
                    break
                title = str(item.get("公告标题", ""))
                if title not in used_titles:
                    selected.append(item)
                    used_titles.add(title)

    # 日志
    cat_dist = {}
    for s in selected:
        c = classify_announcement(str(s.get("公告标题", "")))
        cat_dist[c] = cat_dist.get(c, 0) + 1
    logger.info(
        f"[announcement_sampler] {stock_name or code6}: "
        f"{len(df_rows)} -> {len(selected)} selected, "
        f"distribution: {cat_dist}"
    )

    return selected
