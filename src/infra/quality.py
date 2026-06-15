"""
quality - 输出质检层

两道防线:
  1. 工具输出校验: 工具返回数据后，检查数据是否有效
  2. 分析师输出校验: LLM 输出的 JSON 是否符合 schema

参考: iFinD data-accuracy-evaluator 的5级验证优先级链
"""

import json
import logging

logger = logging.getLogger(__name__)

# 工具数据字段映射: 部分工具不用 "data" 字段存放主要数据
_TOOL_DATA_FIELDS: dict[str, str] = {
    "get_peers": "peers",
    "get_dcf_valuation": "dcf",
}


# ---------- 第一道防线: 工具输出校验 ----------

def validate_tool_output(tool_name: str, result: dict) -> dict:
    """
    校验工具返回数据是否有效。

    检查项:
      - ok 字段为 True
      - data 非空（或 count > 0）
      - data 是 list 类型
      - 第一条记录的关键字段非 None

    Returns:
        原始 result（如果通过）或带有 _validation_warning 的 result
    """
    warnings = []

    # 1. ok 字段检查
    if not result.get("ok"):
        warning = f"Tool {tool_name} returned ok=False: {result.get('error', 'unknown')}"
        warnings.append(warning)
        result["_validation_warning"] = "; ".join(warnings)
        logger.warning(f"[Quality] {warning}")
        return result

    # 2. data 非空检查（X3: 按工具名查映射字段，默认 "data"）
    data_field = _TOOL_DATA_FIELDS.get(tool_name, "data")
    data = result.get(data_field)
    if data is None or (isinstance(data, (list, dict)) and len(data) == 0):
        warning = f"Tool {tool_name} returned empty {data_field}"
        warnings.append(warning)
        result["_validation_warning"] = "; ".join(warnings)
        logger.warning(f"[Quality] {warning}")
        return result

    # 3. 关键字段非 None 检查（抽查第一条，仅 list[dict] 数据）
    if isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            none_fields = [k for k, v in first.items() if v is None]
            if len(none_fields) > len(first) / 2:
                warning = (
                    f"Tool {tool_name} first row has {len(none_fields)}/{len(first)} "
                    f"None fields: {none_fields[:5]}"
                )
                warnings.append(warning)
                logger.warning(f"[Quality] {warning}")

    # 4. 时间范围新鲜度检查（仅 list[dict] 数据）
    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[-1], dict):
            latest_date = data[-1].get("trade_date", "")
            if latest_date:
                result["_latest_data_date"] = latest_date

    if warnings:
        result["_validation_warning"] = "; ".join(warnings)

    return result


# ---------- 第二道防线: 分析师输出校验 ----------

# 技术分析师 JSON schema
TECHNICAL_ANALYST_SCHEMA = {
    "required_fields": [
        "score", "direction", "short_term_trend", "mid_term_trend",
        "long_term_trend", "trend", "strong_support", "weak_support",
        "strong_resistance", "weak_resistance", "stop_loss_price",
        "target_price", "risk_reward_ratio", "volume_signal",
        "macd_signal", "macd_divergence", "kdj_signal", "kdj_divergence",
        "rsi_signal", "rsi_divergence", "money_flow_signal",
        "money_flow_summary", "relative_strength", "ma_pattern",
        "scoring_breakdown", "summary",
    ],
    "numeric_ranges": {
        "score": (0, 100),
    },
    "enum_values": {
        "direction": ["bullish", "bearish", "neutral"],
        "macd_signal": ["golden_cross", "death_cross", "neutral"],
        "macd_divergence": ["top_divergence", "bottom_divergence", "none"],
        "kdj_signal": ["overbought", "oversold", "neutral"],
        "kdj_divergence": ["top_divergence", "bottom_divergence", "none"],
        "rsi_signal": ["overbought", "oversold", "neutral"],
        "rsi_divergence": ["top_divergence", "bottom_divergence", "none"],
        "money_flow_signal": [
            "continuous_inflow", "continuous_outflow",
            "inflow_reversal", "outflow_reversal", "neutral",
        ],
        "relative_strength": ["outperform", "underperform", "inline"],
        "ma_pattern": ["bullish_alignment", "bearish_alignment", "mixed"],
    },
    "scoring_breakdown_fields": [
        "trend_ma", "trend_macd", "trend_price_position",
        "signal_macd", "signal_kdj", "signal_rsi",
        "volume_price", "volume_turnover",
        "relative_vs_index", "relative_volatility",
        "risk_reward",
    ],
}

FUNDAMENTALS_ANALYST_SCHEMA = {
    "required_fields": [
        "score", "verdict",
        "profitability_grade", "growth_grade", "safety_grade",
        "valuation_grade",
        "roe_latest", "roe_trend", "gross_margin", "net_margin",
        "revenue_yoy", "revenue_trend", "net_profit_yoy", "profit_trend",
        "debt_ratio", "current_ratio", "ocf_to_np_ratio",
        "debt_structure",
        "pe_ttm", "pe_percentile", "pb", "pb_percentile",
        "valuation_summary",
        "holder_num_change_pct", "holder_trend",
        "institutional_holders", "institutional_ratio",
        "key_strengths", "key_risks",
        "scoring_breakdown", "summary",
        # P1: 新增必填字段
        "business_model", "expense_leakage",
        "dupont_analysis", "cross_layer_notes",
        # P2: 新增必填字段
        "peg", "growth_attribution",
        # P3: 新增必填字段
        "insider_signal", "pledge_risk",
        # 结构化对象（检查是否存在，不检查内部字段）
        "industry_analysis", "scenario_analysis",
        "key_observations",
        # dcf_cross_check: conditional (see check 3b after required_fields loop)
    ],
    "numeric_ranges": {
        "score": (0, 100),
    },
    "enum_values": {
        "verdict": ["strong_bullish", "bullish", "neutral", "bearish", "strong_bearish"],
        "profitability_grade": ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"],
        "growth_grade": ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"],
        "safety_grade": ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"],
        "valuation_grade": ["undervalued", "fair", "overvalued"],
        "roe_trend": ["improving", "stable", "declining"],
        "revenue_trend": ["accelerating", "stable", "decelerating"],
        "profit_trend": ["accelerating", "stable", "decelerating"],
        "holder_trend": ["concentrating", "stable", "dispersing"],
        "insider_signal": ["net_buy", "leaning_buy", "neutral", "leaning_sell", "net_sell"],
        "pledge_risk": ["none", "low", "medium", "high"],
    },
    "scoring_breakdown_fields": [
        "profitability_roe", "profitability_margin",
        "growth_revenue", "growth_profit",
        "safety_debt", "cashflow_quality",
        "valuation_pe", "valuation_pb",
        "holder_concentration", "institutional_presence",
        "safety_liquidity", "dcf_valuation",
        "peg_signal", "peer_valuation",
    ],
}

NEWS_ANALYST_SCHEMA = {
    "required_fields": [
        "score", "direction", "news_analyzed", "sentiment",
        "key_events", "risk_events",
        "positive_factors", "negative_factors",
        "scoring_breakdown", "summary",
    ],
    "numeric_ranges": {
        "score": (0, 100),
    },
    "enum_values": {
        "direction": ["bullish", "bearish", "neutral"],
        "sentiment": ["positive", "negative", "mixed", "neutral"],
    },
    "scoring_breakdown_fields": [
        "positive_events", "negative_events",
        "event_timeliness", "event_impact",
        "sentiment_alignment", "risk_level",
    ],
}


def validate_analyst_output(output_text: str, schema_type: str = "technical") -> dict:
    """
    校验分析师 LLM 输出（文本解析模式，fallback 用）。
    从文本提取 JSON，校验字段。
    """
    json_str = _extract_json(output_text)
    if json_str is None:
        return {
            "valid": False,
            "json_data": None,
            "errors": ["Cannot extract JSON from LLM output"],
            "warnings": [],
        }
    try:
        json_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "json_data": None,
            "errors": [f"JSON parse error: {e}"],
            "warnings": [],
        }
    return _validate_analyst_dict(json_data, schema_type)


def validate_structured_output(data: dict, schema_type: str) -> dict:
    """校验工具提交的结构化数据（跳过 JSON 解析）。"""
    if not isinstance(data, dict):
        return {
            "valid": False,
            "json_data": None,
            "errors": [f"Expected dict, got {type(data).__name__}"],
            "warnings": [],
        }
    return _validate_analyst_dict(data, schema_type)


def _validate_analyst_dict(json_data: dict, schema_type: str) -> dict:
    """Shared validation logic for analyst output (works on pre-parsed dict)."""
    import copy
    json_data = copy.deepcopy(json_data)
    errors = []
    warnings = []

    schema = (
        TECHNICAL_ANALYST_SCHEMA
        if schema_type == "technical"
        else NEWS_ANALYST_SCHEMA
        if schema_type == "news"
        else FUNDAMENTALS_ANALYST_SCHEMA
    )

    # 3. 必填字段检查
    for field in schema["required_fields"]:
        if field not in json_data:
            errors.append(f"Missing required field: {field}")
        else:
            # 检查空值（存在但无效）
            val = json_data.get(field)
            if val is None:
                warnings.append(f"Required field '{field}' is null")
            elif isinstance(val, str) and len(val.strip()) == 0:
                warnings.append(f"Required field '{field}' is empty string")
            elif isinstance(val, list) and len(val) == 0:
                warnings.append(f"Required field '{field}' is empty array")

    # 3b. Conditional check: dcf_cross_check required only when DCF data exists.
    # When FCF<=0, DCF is inapplicable and the LLM may omit dcf_cross_check;
    # only error when DCF valuation data IS present but cross_check is missing.
    if schema_type == "fundamentals" and "dcf_cross_check" not in json_data:
        breakdown = json_data.get("scoring_breakdown") or {}
        dcf_val = breakdown.get("dcf_valuation") if isinstance(breakdown, dict) else None
        if isinstance(dcf_val, (int, float)) and dcf_val > 0:
            errors.append(
                "dcf_cross_check is required when DCF valuation data is present "
                "(scoring_breakdown.dcf_valuation > 0)"
            )
        else:
            warnings.append(
                "dcf_cross_check missing: if FCF<=0 makes DCF inapplicable, output "
                "dcf_cross_check with {note: 'FCF<=0, DCF not applicable', "
                "intrinsic_value: null, dcf_upside_pct: null, "
                "sensitivity_note: 'N/A', pe_vs_dcf: 'PE/PEG only'}"
            )

    # 3c. dcf_cross_check shape: when present, must be an object (dict).
    # Catches malformed values like a bare string "N/A" or empty array.
    if schema_type == "fundamentals":
        dcf_cc = json_data.get("dcf_cross_check")
        if dcf_cc is not None and not isinstance(dcf_cc, dict):
            warnings.append(
                f"dcf_cross_check should be an object, got {type(dcf_cc).__name__}: {dcf_cc}"
            )

    # 4. 数值范围检查
    for field, (min_val, max_val) in schema.get("numeric_ranges", {}).items():
        value = json_data.get(field)
        if value is not None:
            if not isinstance(value, (int, float)):
                errors.append(f"Field {field} should be numeric, got {type(value)}")
            elif value < min_val or value > max_val:
                errors.append(
                    f"Field {field} out of range: {value} (expected {min_val}-{max_val})"
                )

    # 5. 枚举值检查
    for field, valid_values in schema.get("enum_values", {}).items():
        value = json_data.get(field)
        if value is not None and value not in valid_values:
            warnings.append(
                f"Field {field} has unexpected value: {value} "
                f"(expected one of {valid_values})"
            )

    # 6. scoring_breakdown 检查
    breakdown = json_data.get("scoring_breakdown", {})
    if breakdown:
        for sb_field in schema["scoring_breakdown_fields"]:
            val = breakdown.get(sb_field)
            if val is not None:
                if not isinstance(val, (int, float)):
                    warnings.append(f"scoring_breakdown.{sb_field} not numeric: {val}")
                    continue
                # 新闻面负数字段符号检查（negative_events 和 risk_level 必须为负）
                if schema_type == "news" and sb_field in ("negative_events", "risk_level"):
                    if val > 0:
                        warnings.append(
                            f"scoring_breakdown.{sb_field} should be negative, "
                            f"got {val}, auto-flipped"
                        )
                        breakdown[sb_field] = -val
                        val = -val  # update local for truncation check
                # 截断（在符号修正之后执行）
                if abs(val) > 15:
                    warnings.append(
                        f"scoring_breakdown.{sb_field} out of range: {val}"
                    )
                    breakdown[sb_field] = 15 if val > 0 else -15

        # 检查 score 是否匹配 breakdown 映射值（自动修正）
        actual_score = json_data.get("score")
        if actual_score is not None and breakdown:
            if schema_type == "news":
                # 新闻公式: 50 + 仅已知6项breakdown值之和
                news_fields = schema.get("scoring_breakdown_fields", [])
                breakdown_sum = sum(
                    breakdown.get(f, 0)
                    for f in news_fields
                    if isinstance(breakdown.get(f), (int, float))
                )
                expected_score = max(0, min(100, round(50 + breakdown_sum, 1)))
            else:
                # 技术面/基本面: breakdown 之和映射到百分制
                breakdown_sum = sum(
                    v for v in breakdown.values()
                    if isinstance(v, (int, float))
                )
                num_expected = len(schema.get("scoring_breakdown_fields", []))
                max_possible = num_expected * 10
                if max_possible > 0 and max_possible != 100:
                    expected_score = round(breakdown_sum * 100 / max_possible, 1)
                else:
                    expected_score = breakdown_sum
            if abs(actual_score - expected_score) > 1:
                warnings.append(
                    f"Score ({actual_score}) != expected ({expected_score}), "
                    f"auto-corrected to {expected_score}"
                )
                json_data["score"] = expected_score

    # 6.5 新闻分析专用检查
    if schema_type == "news":
        # direction-score 矛盾检查
        score_val = json_data.get("score", 0)
        direction = json_data.get("direction", "")
        if score_val >= 65 and direction == "bearish":
            warnings.append(
                f"Score {score_val} >= 65 but direction is bearish (contradiction)"
            )
        if score_val <= 35 and direction == "bullish":
            warnings.append(
                f"Score {score_val} <= 35 but direction is bullish (contradiction)"
            )

    # 7-10. 技术分析专用检查（仅对技术分析报告运行）
    if schema_type == "technical":
        # 7. 关键价位合理性检查
        score_val = json_data.get("score", 0)
        direction = json_data.get("direction", "")
        if score_val >= 60 and direction == "bearish":
            warnings.append(f"Score {score_val} >= 60 but direction is bearish (contradiction)")
        if score_val <= 40 and direction == "bullish":
            warnings.append(f"Score {score_val} <= 40 but direction is bullish (contradiction)")

        # 8. 支撑压力价位排序合理性
        strong_s = json_data.get("strong_support")
        weak_s = json_data.get("weak_support")
        weak_r = json_data.get("weak_resistance")
        strong_r = json_data.get("strong_resistance")
        price_levels = {
            "strong_support": strong_s,
            "weak_support": weak_s,
            "weak_resistance": weak_r,
            "strong_resistance": strong_r,
        }
        # 检查是否有None
        none_levels = [k for k, v in price_levels.items() if v is None]
        if none_levels:
            warnings.append(f"Missing price levels: {none_levels}")
        # 检查排序: 强支撑 < 弱支撑 < 弱压力 < 强压力（检测 + 自动修正）
        levels = [strong_s, weak_s, weak_r, strong_r]
        if all(v is not None for v in levels):
            if not (strong_s <= weak_s <= weak_r <= strong_r):
                warnings.append(
                    f"Price levels not sorted correctly: "
                    f"strong_s={strong_s}, weak_s={weak_s}, "
                    f"weak_r={weak_r}, strong_r={strong_r}. "
                    f"Auto-corrected by sorting"
                )
                sorted_levels = sorted(levels)
                json_data["strong_support"] = sorted_levels[0]
                json_data["weak_support"] = sorted_levels[1]
                json_data["weak_resistance"] = sorted_levels[2]
                json_data["strong_resistance"] = sorted_levels[3]

        # 9. 止损/目标价合理性（方向感知）
        direction = json_data.get("direction", "neutral")
        stop_loss_buy = json_data.get("stop_loss_price")
        stop_loss_sell = json_data.get("stop_loss_sell")
        target = json_data.get("target_price")
        latest_close = json_data.get("latest_close")

        # 9a. 方向与目标价一致性检查
        if target is not None and latest_close is not None:
            deviation = (target - latest_close) / latest_close * 100 if latest_close else 0
            if direction == "bullish" and target <= latest_close:
                # Auto-correct: bullish target must be above current price.
                # Prefer weak_resistance * 1.05 if available, fallback to
                # latest_close * 1.05. Take the max to ensure above both.
                candidates = []
                if weak_r is not None:
                    candidates.append(weak_r * 1.05)
                candidates.append(latest_close * 1.05)
                corrected = round(max(candidates), 2)
                warnings.append(
                    f"bullish direction but target_price ({target}) <= latest_close ({latest_close}): "
                    f"contradiction - auto-corrected target to {corrected} "
                    f"(target must be above current price)"
                )
                json_data["target_price"] = corrected
            elif direction == "bearish" and target >= latest_close:
                # Auto-correct: bearish target must be below current price.
                # Prefer weak_support * 0.95 if available, fallback to
                # latest_close * 0.95. Take the min to ensure below both.
                candidates = []
                if weak_s is not None:
                    candidates.append(weak_s * 0.95)
                candidates.append(latest_close * 0.95)
                corrected = round(min(candidates), 2)
                warnings.append(
                    f"bearish direction but target_price ({target}) >= latest_close ({latest_close}): "
                    f"contradiction - auto-corrected target to {corrected} "
                    f"(target must be below current price)"
                )
                json_data["target_price"] = corrected
            elif direction == "neutral" and abs(deviation) > 15:
                warnings.append(
                    f"neutral direction but target_price deviates {deviation:.1f}% from latest_close: "
                    f"neutral targets should stay within ±15%"
                )
            # Refresh local var so subsequent checks (e.g. target vs weak_resistance)
            # use the corrected value instead of the original contradictory one.
            target = json_data.get("target_price")
        if stop_loss_buy is not None and latest_close is not None and direction == "bullish":
            if stop_loss_buy >= latest_close:
                warnings.append(
                    f"bullish direction but stop_loss_price ({stop_loss_buy}) >= latest_close ({latest_close}): "
                    f"stop loss should be below current price for long positions"
                )

        # 9b. 场景分析概率总和检查
        scenario = json_data.get("scenario_analysis", {})
        if scenario:
            probs = []
            for key in ("bull", "base", "bear"):
                s = scenario.get(key, {})
                p = s.get("probability")
                if p is not None:
                    try:
                        probs.append(float(p))
                    except (TypeError, ValueError):
                        pass
            if len(probs) == 3:
                total = sum(probs)
                if abs(total - 100) > 5:
                    warnings.append(
                        f"scenario_analysis probabilities sum to {total:.0f}% (expected 100%): "
                        f"bull={probs[0]}%, base={probs[1]}%, bear={probs[2]}%"
                    )

        # 买入止损: 应低于弱支撑
        if stop_loss_buy is not None and weak_s is not None:
            if stop_loss_buy > weak_s:
                warnings.append(
                    f"stop_loss_price ({stop_loss_buy}) > weak_support ({weak_s}): "
                    f"buy-side stop loss should be below support"
                )
        # 卖出止损: bearish 时应有值且高于弱阻力
        if direction == "bearish":
            if not stop_loss_sell:
                warnings.append(
                    "bearish direction missing stop_loss_sell: "
                    "sell-side stop loss should be provided when direction is bearish"
                )
            elif stop_loss_sell is not None and weak_r is not None:
                if stop_loss_sell < weak_r:
                    warnings.append(
                        f"stop_loss_sell ({stop_loss_sell}) < weak_resistance ({weak_r}): "
                        f"sell-side stop loss should be above resistance"
                    )
        if target is not None and weak_r is not None:
            if target < weak_r:
                warnings.append(
                    f"target_price ({target}) < weak_resistance ({weak_r}): "
                    f"target should be above resistance"
                )

        # 10. 风险收益比合理性
        ratio_str = json_data.get("risk_reward_ratio", "")
        if ratio_str and ":" in ratio_str:
            try:
                parts = ratio_str.split(":")
                reward = float(parts[1])
                if reward < 1.0:
                    warnings.append(
                        f"risk_reward_ratio {ratio_str} < 1:1, unfavorable trade"
                    )
            except (ValueError, IndexError):
                pass

    # 11. 基本面 score vs verdict 一致性检查
    if schema_type == "fundamentals":
        score_val = json_data.get("score", 0)
        verdict = json_data.get("verdict", "")
        if score_val >= 75 and verdict not in ("strong_bullish", "bullish"):
            warnings.append(
                f"Score {score_val} >= 75 but verdict is '{verdict}' (expected bullish/strong_bullish)"
            )
        elif score_val >= 60 and verdict == "strong_bearish":
            warnings.append(
                f"Score {score_val} >= 60 but verdict is 'strong_bearish' (contradiction)"
            )
        elif score_val <= 25 and verdict not in ("strong_bearish", "bearish"):
            warnings.append(
                f"Score {score_val} <= 25 but verdict is '{verdict}' (expected bearish/strong_bearish)"
            )
        elif score_val <= 40 and verdict == "strong_bullish":
            warnings.append(
                f"Score {score_val} <= 40 but verdict is 'strong_bullish' (contradiction)"
            )

    is_valid = len(errors) == 0

    if errors:
        logger.warning(f"[Quality] Analyst output validation FAILED: {errors}")
    if warnings:
        logger.info(f"[Quality] Analyst output warnings: {warnings}")

    return {
        "valid": is_valid,
        "json_data": json_data,
        "errors": errors,
        "warnings": warnings,
    }


def _repair_json(json_str: str) -> str:
    r"""Fix common JSON format errors in LLM output."""
    import re

    # 1. 行末分号代替逗号
    repaired = re.sub(r'";(\s*\n)', r'",\1', json_str)

    # 2. 尾随逗号
    repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)

    # 3. 修复JSON字符串值内的未转义双引号
    repaired = _escape_inner_quotes(repaired)

    return repaired


def _escape_inner_quotes(s: str) -> str:
    r"""Escape unescaped double quotes inside JSON string values."""
    result = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '\\' and i + 1 < n:
            result.append(ch)
            result.append(s[i + 1])
            i += 2
            continue
        if ch == '"':
            result.append('"')
            i += 1
            while i < n:
                c = s[i]
                if c == '\\' and i + 1 < n:
                    result.append(c)
                    result.append(s[i + 1])
                    i += 2
                    continue
                if c == '"':
                    rest = s[i + 1:].lstrip()
                    if not rest:
                        result.append('"')
                        i += 1
                        break
                    next_ch = rest[0]
                    if next_ch in (',', '}', ']', ':', '\n', '\r'):
                        result.append('"')
                        i += 1
                        break
                    else:
                        result.append('\\"')
                        i += 1
                        continue
                result.append(c)
                i += 1
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def _extract_json(text: str) -> str | None:
    """从 LLM 输出中提取 JSON 块，并自动修复常见格式错误"""
    if not text:
        return None

    raw = None

    # 尝试找 ```json ... ``` 代码块
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        raw = text[start:end].strip()

    # 尝试找 { ... } 配对
    elif "{" in text:
        start = text.index("{")
        end = text.rindex("}") + 1
        raw = text[start:end]

    if raw is None:
        return None

    # 先尝试原始解析
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # 原始解析失败，尝试修复
    repaired = _repair_json(raw)
    try:
        json.loads(repaired)
        logger.info("[Quality] JSON auto-repair succeeded")
        return repaired
    except json.JSONDecodeError as e:
        logger.warning(f"[Quality] JSON auto-repair failed: {e}")
        return raw  # 返回原始版本，让上层报告具体错误


# ---------- Research Manager 输出校验 ----------

RESEARCH_MANAGER_REQUIRED_FIELDS = [
    "debate_winner",
    "debate_delta",
    "debate_rationale",
    "strongest_bull_point",
    "strongest_bear_point",
    "adjusted_score",
    "adjusted_direction",
    "recommendation",
    "risk_warnings",
    "summary",
]


def validate_research_manager_output(output_text: str) -> dict:
    """校验 Research Manager LLM 输出（文本解析模式，fallback 用）。"""
    json_str = _extract_json(output_text)
    if json_str is None:
        return {
            "valid": False,
            "json_data": None,
            "errors": ["Cannot extract JSON from Research Manager output"],
            "warnings": [],
        }
    try:
        json_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "json_data": None,
            "errors": [f"JSON parse error: {e}"],
            "warnings": [],
        }
    return _validate_research_manager_dict(json_data)


def validate_research_manager_structured(data: dict) -> dict:
    """校验 Research Manager 工具提交的结构化数据。"""
    if not isinstance(data, dict):
        return {
            "valid": False,
            "json_data": None,
            "errors": [f"Expected dict, got {type(data).__name__}"],
            "warnings": [],
        }
    return _validate_research_manager_dict(data)


def _validate_research_manager_dict(json_data: dict) -> dict:
    """Shared validation logic for Research Manager output."""
    import copy
    json_data = copy.deepcopy(json_data)
    errors = []
    warnings = []

    # 必填字段检查
    for field in RESEARCH_MANAGER_REQUIRED_FIELDS:
        if field not in json_data:
            errors.append(f"Missing required field: {field}")

    # debate_winner 枚举检查
    winner = json_data.get("debate_winner")
    if winner and winner not in ("bull", "bear", "draw"):
        errors.append(f"Invalid debate_winner: {winner}")

    # debate_delta 范围检查
    delta = json_data.get("debate_delta")
    if delta is not None:
        if not isinstance(delta, (int, float)):
            errors.append(f"debate_delta must be numeric, got {type(delta)}")
        elif delta < -5 or delta > 5:
            clamped = max(-5, min(5, int(round(delta))))
            warnings.append(
                f"debate_delta {delta} clamped to {clamped}"
            )
            json_data["debate_delta"] = clamped

    # adjusted_score 范围检查
    score = json_data.get("adjusted_score")
    if score is not None:
        if not isinstance(score, (int, float)):
            errors.append(f"adjusted_score must be numeric, got {type(score)}")
        elif score < 0 or score > 100:
            errors.append(f"adjusted_score out of range: {score} (expected 0-100)")

    # adjusted_direction 枚举检查
    direction = json_data.get("adjusted_direction")
    valid_directions = (
        "strong_bullish", "bullish", "neutral", "bearish", "strong_bearish",
    )
    if direction and direction not in valid_directions:
        warnings.append(
            f"Unexpected adjusted_direction: {direction} "
            f"(expected one of {valid_directions})"
        )

    is_valid = len(errors) == 0
    if errors:
        logger.warning(f"[Quality] Research Manager validation FAILED: {errors}")
    if warnings:
        logger.info(f"[Quality] Research Manager warnings: {warnings}")

    return {
        "valid": is_valid,
        "json_data": json_data,
        "errors": errors,
        "warnings": warnings,
    }


# ---------- Risk Manager 输出校验 ----------

RISK_MANAGER_REQUIRED_FIELDS = [
    "risk_level",
    "risk_score",
    "risk_winner",
    "risk_rationale",
    "adjusted_direction",
    "key_risks",
    "key_opportunities",
    "risk_warnings",
]

RISK_LEVEL_VALUES = {"very_high", "high", "medium", "low", "very_low"}
RISK_WINNER_VALUES = {"aggressive", "conservative", "neutral_draw"}
VALID_DIRECTIONS = (
    "strong_bullish", "bullish", "neutral", "bearish", "strong_bearish",
)


def validate_risk_manager_structured(data: dict) -> dict:
    """Validate Risk Manager tool-submitted structured output."""
    if not isinstance(data, dict):
        return {
            "valid": False,
            "json_data": None,
            "errors": [f"Expected dict, got {type(data).__name__}"],
            "warnings": [],
        }
    return _validate_risk_manager_dict(data)


def _validate_risk_manager_dict(json_data: dict) -> dict:
    """Validation logic for Risk Manager output."""
    import copy
    json_data = copy.deepcopy(json_data)
    errors = []
    warnings = []

    for field in RISK_MANAGER_REQUIRED_FIELDS:
        if field not in json_data:
            errors.append(f"Missing required field: {field}")

    risk_level = json_data.get("risk_level")
    if risk_level and risk_level not in RISK_LEVEL_VALUES:
        errors.append(f"Invalid risk_level: {risk_level}")

    risk_winner = json_data.get("risk_winner")
    if risk_winner and risk_winner not in RISK_WINNER_VALUES:
        errors.append(f"Invalid risk_winner: {risk_winner}")

    risk_score = json_data.get("risk_score")
    if risk_score is not None:
        if not isinstance(risk_score, (int, float)):
            errors.append(f"risk_score must be numeric, got {type(risk_score)}")
        elif risk_score < 0 or risk_score > 100:
            errors.append(f"risk_score out of range: {risk_score}")

    direction = json_data.get("adjusted_direction")
    if direction and direction not in VALID_DIRECTIONS:
        warnings.append(f"Unexpected adjusted_direction: {direction}")

    score = json_data.get("score")
    if score is not None:
        if not isinstance(score, (int, float)):
            errors.append(f"score must be numeric, got {type(score)}")
        elif score < 0 or score > 100:
            errors.append(f"score out of range: {score}")

    is_valid = len(errors) == 0
    if errors:
        logger.warning(f"[Quality] Risk Manager validation FAILED: {errors}")
    if warnings:
        logger.info(f"[Quality] Risk Manager warnings: {warnings}")

    return {
        "valid": is_valid,
        "json_data": json_data,
        "errors": errors,
        "warnings": warnings,
    }


# ---------- Trader 输出校验 ----------

TRADER_REQUIRED_FIELDS = [
    "action",
    "action_strength",
    "target_price",
    "target_price_rationale",
    "stop_loss",
    "stop_loss_rationale",
    "confidence_components",
    "confidence_total",
    "confidence_label",
    "position_advice",
    "position_range",
    "risk_score",
    "risk_level",
    "time_horizon",
    "reasoning",
    "warnings",
]

TRADER_CONFIDENCE_COMPONENT_FIELDS = [
    "signal_consistency",
    "data_sufficiency",
    "debate_certainty",
    "risk_controllability",
    "valuation_reasonableness",
]

TRADER_ENUM_VALUES = {
    "action": ["buy", "hold", "sell", "watch"],
    "action_strength": ["strong", "normal", "weak"],
    "confidence_label": ["very_high", "high", "medium", "low", "very_low"],
    "position_advice": ["heavy", "standard", "light", "watch"],
    "risk_level": ["very_low", "low", "medium", "high", "very_high"],
}

# confidence_total -> confidence_label 映射
CONFIDENCE_LABEL_RANGES = {
    "very_high": (80, 100),
    "high": (60, 79),
    "medium": (40, 59),
    "low": (20, 39),
    "very_low": (0, 19),
}

# confidence_total -> position_advice 映射
POSITION_ADVICE_RANGES = {
    "heavy": (80, 100),
    "standard": (60, 79),
    "light": (40, 59),
    "watch": (0, 39),
}


def _check_label_consistency(value, label, ranges):
    """检查数值与标签是否一致"""
    if value is None or label is None:
        return None
    lo, hi = ranges.get(label, (0, 999))
    if not (lo <= value <= hi):
        return f"{label} expects range [{lo},{hi}] but got {value}"
    return None


def validate_trader_output(output_text: str) -> dict:
    """校验 Trader LLM 输出（文本解析模式，fallback 用）。"""
    json_str = _extract_json(output_text)
    if json_str is None:
        return {
            "valid": False,
            "json_data": None,
            "errors": ["Cannot extract JSON from Trader output"],
            "warnings": [],
        }
    try:
        json_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "json_data": None,
            "errors": [f"JSON parse error: {e}"],
            "warnings": [],
        }
    return _validate_trader_dict(json_data)


def validate_trader_structured(data: dict) -> dict:
    """校验 Trader 工具提交的结构化数据。"""
    if not isinstance(data, dict):
        return {
            "valid": False,
            "json_data": None,
            "errors": [f"Expected dict, got {type(data).__name__}"],
            "warnings": [],
        }
    return _validate_trader_dict(data)


def _validate_trader_dict(json_data: dict) -> dict:
    """Shared validation logic for Trader output."""
    import copy
    json_data = copy.deepcopy(json_data)
    errors = []
    warnings = []

    # 1. 必填字段检查
    for field in TRADER_REQUIRED_FIELDS:
        if field not in json_data:
            errors.append(f"Missing required field: {field}")

    # 2. action 枚举检查
    action = json_data.get("action")
    if action and action not in TRADER_ENUM_VALUES["action"]:
        errors.append(f"Invalid action: {action} (expected buy/hold/sell/watch)")

    # 3. action_strength 枚举检查
    strength = json_data.get("action_strength")
    if strength and strength not in TRADER_ENUM_VALUES["action_strength"]:
        warnings.append(f"Unexpected action_strength: {strength}")

    # 4. 目标价和止损检查
    target_price = json_data.get("target_price")
    stop_loss = json_data.get("stop_loss")

    # 4a. watch action: use current price as fallback, but warn if all three are equal
    if action == "watch":
        _cp_for_watch = json_data.get("_current_price")
        if target_price is None:
            json_data["target_price"] = _cp_for_watch if _cp_for_watch else 0
            target_price = json_data["target_price"]
            warnings.append("watch action: target_price defaulted to current_price")
        if stop_loss is None:
            json_data["stop_loss"] = _cp_for_watch if _cp_for_watch else 0
            stop_loss = json_data["stop_loss"]
            warnings.append("watch action: stop_loss defaulted to current_price")
        # Warn if target == stop == current (meaningless placeholder)
        if (
            _cp_for_watch
            and target_price == _cp_for_watch
            and stop_loss == _cp_for_watch
        ):
            warnings.append(
                "watch action: target_price == stop_loss == current_price, "
                "provide meaningful hypothetical entry prices"
            )

    if target_price is not None:
        if not isinstance(target_price, (int, float)):
            errors.append(f"target_price must be numeric, got {type(target_price)}")
        elif target_price <= 0:
            errors.append(f"target_price must be > 0, got {target_price}")

    if stop_loss is None:
        errors.append("stop_loss is required and must not be null")
    elif not isinstance(stop_loss, (int, float)):
        errors.append(f"stop_loss must be numeric, got {type(stop_loss)}")
    elif stop_loss <= 0:
        errors.append(f"stop_loss must be > 0, got {stop_loss}")

    # buy 时 stop_loss 应 < target_price; sell 时反过来
    if target_price and stop_loss and action == "buy":
        if stop_loss >= target_price:
            warnings.append(
                f"stop_loss ({stop_loss}) >= target_price ({target_price}) "
                f"for buy action: stop loss should be below target"
            )
    elif target_price and stop_loss and action == "sell":
        if stop_loss <= target_price:
            warnings.append(
                f"stop_loss ({stop_loss}) <= target_price ({target_price}) "
                f"for sell action: stop loss should be above target"
            )

    # 4b. stop_loss vs current_price 方向验证 + 自动修正
    _cp = json_data.get("_current_price")
    if _cp and stop_loss and action:
        if action == "buy" and stop_loss >= _cp:
            corrected = round(_cp * 0.95, 2)
            warnings.append(
                f"buy stop_loss ({stop_loss}) >= current_price ({_cp}), "
                f"auto-corrected to {corrected}"
            )
            json_data["stop_loss"] = corrected
        elif action == "sell" and stop_loss <= _cp:
            corrected = round(_cp * 1.05, 2)
            warnings.append(
                f"sell stop_loss ({stop_loss}) <= current_price ({_cp}), "
                f"auto-corrected to {corrected}"
            )
            json_data["stop_loss"] = corrected

    # 4c. target_price 偏离度校验
    if _cp and target_price and isinstance(target_price, (int, float)):
        deviation_pct = abs(target_price - _cp) / _cp * 100
        if deviation_pct > 50:
            errors.append(
                f"target_price ({target_price}) deviates {deviation_pct:.1f}% "
                f"from current_price ({_cp}), exceeds 50% threshold"
            )
        elif deviation_pct > 30:
            warnings.append(
                f"target_price ({target_price}) deviates {deviation_pct:.1f}% "
                f"from current_price ({_cp}), consider watch action"
            )

    # 5. 置信度组件检查
    components = json_data.get("confidence_components", {})
    if components:
        component_sum = 0
        for comp_field in TRADER_CONFIDENCE_COMPONENT_FIELDS:
            val = components.get(comp_field)
            if val is not None:
                if not isinstance(val, (int, float)):
                    warnings.append(
                        f"confidence_components.{comp_field} not numeric: {val}"
                    )
                elif val < 0 or val > 20:
                    warnings.append(
                        f"confidence_components.{comp_field} out of 0-20: {val}"
                    )
                else:
                    component_sum += val
            else:
                warnings.append(
                    f"confidence_components missing field: {comp_field}"
                )

        # 6. confidence_total 一致性检查
        reported_total = json_data.get("confidence_total")
        if reported_total is not None and component_sum > 0:
            if abs(reported_total - component_sum) > 1:
                warnings.append(
                    f"confidence_total ({reported_total}) != sum of components "
                    f"({component_sum}), auto-corrected to {component_sum}"
                )
                json_data["confidence_total"] = component_sum
                reported_total = component_sum

    # 7. confidence_label 自动修正
    conf_total = json_data.get("confidence_total")
    if conf_total is not None:
        correct_label = _derive_confidence_label(conf_total)
        if json_data.get("confidence_label") != correct_label:
            warnings.append(
                f"confidence_label auto-corrected: "
                f"{json_data.get('confidence_label')} -> {correct_label}"
            )
            json_data["confidence_label"] = correct_label

        # 8. position_advice 和 position_range 自动修正
        correct_advice, correct_range = _derive_position_advice(conf_total)
        if json_data.get("position_advice") != correct_advice:
            warnings.append(
                f"position_advice auto-corrected -> {correct_advice}"
            )
            json_data["position_advice"] = correct_advice
            json_data["position_range"] = correct_range

    # 9. risk_level 自动修正
    risk_score = json_data.get("risk_score")
    if risk_score is not None:
        correct_risk = _derive_risk_level(risk_score)
        if json_data.get("risk_level") != correct_risk:
            warnings.append(
                f"risk_level auto-corrected -> {correct_risk}"
            )
            json_data["risk_level"] = correct_risk

    # 9a. Fix 3: confidence_total cap based on risk_level
    risk_level = json_data.get("risk_level")
    if risk_level and conf_total is not None:
        cap = None
        if risk_level == "very_high":
            cap = 50
        elif risk_level == "high":
            cap = 65
        if cap is not None and conf_total > cap:
            warnings.append(
                f"confidence_total {conf_total} capped to {cap} "
                f"due to risk_level={risk_level}"
            )
            json_data["confidence_total"] = cap
            conf_total = cap  # keep local var in sync for step 12
            # re-derive label and position advice from capped value
            new_label = _derive_confidence_label(cap)
            new_advice, new_range = _derive_position_advice(cap)
            json_data["confidence_label"] = new_label
            json_data["position_advice"] = new_advice
            json_data["position_range"] = new_range

    # 9b. Fix 1: position_advice override based on risk_level
    risk_level = json_data.get("risk_level")
    current_advice = json_data.get("position_advice")
    if risk_level and current_advice:
        if risk_level == "very_high" and current_advice in ("heavy", "standard"):
            warnings.append(
                f"position_advice auto-corrected -> light "
                f"(risk_level={risk_level} prohibits {current_advice})"
            )
            json_data["position_advice"] = "light"
            json_data["position_range"] = "20-40%"
        elif risk_level == "high" and current_advice == "heavy":
            warnings.append(
                f"position_advice auto-corrected -> standard "
                f"(risk_level={risk_level} prohibits heavy)"
            )
            json_data["position_advice"] = "standard"
            json_data["position_range"] = "40-70%"

    # 9c. risk_score 范围检查
    risk_score = json_data.get("risk_score")
    if risk_score is not None:
        if not isinstance(risk_score, (int, float)):
            errors.append(f"risk_score must be numeric, got {type(risk_score)}")
        elif risk_score < 0 or risk_score > 100:
            errors.append(f"risk_score out of range: {risk_score} (expected 0-100)")

    # 10. risk_level 枚举检查
    risk_level = json_data.get("risk_level")
    if risk_level and risk_level not in TRADER_ENUM_VALUES["risk_level"]:
        warnings.append(f"Unexpected risk_level: {risk_level}")

    # 11. take_profit_levels 增强（E1+E2）
    tp_levels = json_data.get("take_profit_levels")
    if tp_levels and isinstance(tp_levels, list) and len(tp_levels) > 0:
        # E1: 比例总和检查
        total_portion = 0
        for tp in tp_levels:
            portion_str = str(tp.get("portion", "0"))
            try:
                total_portion += float(portion_str.replace("%", ""))
            except ValueError:
                pass
        if abs(total_portion - 100) > 1:
            warnings.append(
                f"take_profit portions sum to {total_portion}%, expected 100%"
            )

        # E2: 价格排序检查 + 自动修正 (X1)
        # sell: take_profit 降序（最近价位先止盈）| buy/hold: 升序
        prices = [tp.get("price", 0) for tp in tp_levels]
        if action == "sell":
            if prices != sorted(prices, reverse=True):
                warnings.append("take_profit_levels not sorted descending for sell, auto-corrected")
                json_data["take_profit_levels"] = sorted(tp_levels, key=lambda x: x.get("price", 0), reverse=True)
        else:
            if prices != sorted(prices):
                warnings.append("take_profit_levels not sorted ascending, auto-corrected")
                json_data["take_profit_levels"] = sorted(tp_levels, key=lambda x: x.get("price", 0))

    # 12. action 与综合方向逻辑一致性
    if action == "buy" and conf_total is not None and conf_total < 40:
        warnings.append(
            f"action is 'buy' but confidence_total is low ({conf_total})"
        )
    if action == "sell" and conf_total is not None and conf_total >= 70:
        warnings.append(
            f"action is 'sell' but confidence_total is high ({conf_total})"
        )

    # 13. warnings 数组长度检查
    trader_warnings = json_data.get("warnings")
    if trader_warnings is not None and isinstance(trader_warnings, list):
        if len(trader_warnings) < 2:
            warnings.append(
                f"warnings has {len(trader_warnings)} items, expected at least 2"
            )
        elif len(trader_warnings) > 5:
            warnings.append(
                f"warnings has {len(trader_warnings)} items, expected at most 5"
            )

    is_valid = len(errors) == 0
    if errors:
        logger.warning(f"[Quality] Trader validation FAILED: {errors}")
    if warnings:
        logger.info(f"[Quality] Trader warnings: {warnings}")

    return {
        "valid": is_valid,
        "json_data": json_data,
        "errors": errors,
        "warnings": warnings,
    }


def _derive_confidence_label(score):
    """根据 confidence_total 数值推导正确的 label"""
    if score is None:
        return "medium"
    if score >= 80:
        return "very_high"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 20:
        return "low"
    return "very_low"


def _derive_position_advice(score):
    """根据 confidence_total 数值推导正确的 position_advice 和 position_range"""
    if score is None:
        return ("light", "20-40%")
    if score >= 80:
        return ("heavy", "70-100%")
    if score >= 60:
        return ("standard", "40-70%")
    if score >= 40:
        return ("light", "20-40%")
    return ("watch", "0%")


def _derive_risk_level(score):
    """根据 risk_score 数值推导正确的 risk_level"""
    if score is None:
        return "medium"
    if score >= 80:
        return "very_high"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 20:
        return "low"
    return "very_low"
