"""
submit_tool - submit_analysis tool definition

Instead of outputting JSON as text, agents call this tool to submit
their analysis. Each agent type gets its own focused schema to reduce
token waste and LLM confusion.
"""

# -- Shared core properties (all agents) --
_CORE_PROPERTIES = {
    "score": {
        "type": "number",
        "description": "0-100. Fill 0 for auto-calculation from scoring_breakdown.",
    },
    "scoring_breakdown": {
        "type": "object",
        "description": "Scoring breakdown by dimension.",
    },
    "summary": {
        "type": "string",
        "description": "3-4 sentence summary in Chinese.",
    },
    "key_observations": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Key observations.",
    },
    "data_freshness": {
        "type": "object",
        "description": "Data freshness info.",
    },
}

_CORE_REQUIRED = ["score", "scoring_breakdown", "summary"]

_DESCRIPTION = (
    "Submit your completed analysis as structured data. "
    "Call this tool when you have finished your analysis. "
    "This is the ONLY way to submit your final output. "
    "Do NOT output JSON as text -- call this tool instead."
)

# -- News analyst properties --
_NEWS_PROPERTIES = {
    **_CORE_PROPERTIES,
    "direction": {
        "type": "string",
        "description": "bullish/bearish/neutral",
    },
    "news_analyzed": {"type": "integer"},
    "sentiment": {
        "type": "string",
        "description": "positive/negative/mixed/neutral",
    },
    "sentiment_confidence": {"type": "number"},
    "key_events": {"type": "array", "items": {"type": "object"}},
    "risk_events": {"type": "array", "items": {"type": "object"}},
    "positive_factors": {"type": "array", "items": {"type": "string"}},
    "negative_factors": {"type": "array", "items": {"type": "string"}},
    "market_attention": {"type": "string"},
    "failure_conditions": {
        "type": "array",
        "items": {"type": "object"},
        "description": "What signals would prove this analysis wrong.",
    },
}

# -- Technical analyst properties --
_TECH_PROPERTIES = {
    **_CORE_PROPERTIES,
    "direction": {
        "type": "string",
        "description": "bullish/bearish/neutral",
    },
    "short_term_trend": {"type": "string"},
    "mid_term_trend": {"type": "string"},
    "long_term_trend": {"type": "string"},
    "trend": {"type": "string"},
    "strong_support": {"type": "number"},
    "weak_support": {"type": "number"},
    "strong_resistance": {"type": "number"},
    "weak_resistance": {"type": "number"},
    "stop_loss_price": {"type": "number"},
    "stop_loss_sell": {"type": "number"},
    "latest_close": {"type": "number"},
    "target_price": {"type": "number"},
    "risk_reward_ratio": {"type": "string"},
    "volume_signal": {"type": "string"},
    "turnover_signal": {"type": "string"},
    "macd_signal": {"type": "string"},
    "macd_divergence": {"type": "string"},
    "kdj_signal": {"type": "string"},
    "kdj_divergence": {"type": "string"},
    "rsi_signal": {"type": "string"},
    "rsi_divergence": {"type": "string"},
    "kline_patterns": {"type": "array", "items": {"type": "string"}},
    "money_flow_signal": {"type": "string"},
    "money_flow_summary": {"type": "string"},
    "relative_strength": {"type": "string"},
    "industry_comparison": {"type": "string"},
    "ma_pattern": {"type": "string"},
    "weekly_signal": {"type": "string"},
    "resonance": {"type": "string"},
    "scenario_analysis": {"type": "object"},
    "failure_conditions": {"type": "array", "items": {"type": "object"}},
}

# -- Fundamentals analyst properties --
_FUND_PROPERTIES = {
    **_CORE_PROPERTIES,
    "verdict": {"type": "string"},
    "profitability_grade": {"type": "string"},
    "growth_grade": {"type": "string"},
    "safety_grade": {"type": "string"},
    "valuation_grade": {"type": "string"},
    "business_model": {"type": "string"},
    "roe_latest": {"type": "number"},
    "roe_annual": {"type": "number"},
    "roe_trend": {"type": "string"},
    "gross_margin": {"type": "number"},
    "net_margin": {"type": "number"},
    "expense_leakage": {"type": "string"},
    "revenue_yoy": {"type": "number"},
    "revenue_trend": {"type": "string"},
    "net_profit_yoy": {"type": "number"},
    "profit_trend": {"type": "string"},
    "deducted_profit_ratio": {"type": "string"},
    "debt_ratio": {"type": "number"},
    "debt_structure": {"type": "string"},
    "current_ratio": {"type": "number"},
    "ocf_to_np_ratio": {"type": "number"},
    "free_cash_flow": {"type": "number"},
    "fcf_margin": {"type": "number"},
    "cashflow_type": {"type": "string"},
    "revenue_cash_ratio": {"type": "number"},
    "dupont_analysis": {"type": "string"},
    "growth_attribution": {"type": "string"},
    "working_capital": {"type": "string"},
    "pe_ttm": {"type": "number"},
    "pe_percentile": {"type": "number"},
    "pb": {"type": "number"},
    "pb_percentile": {"type": "number"},
    "peg": {"type": "string"},
    "valuation_summary": {"type": "string"},
    "holder_num_change_pct": {"type": "number"},
    "holder_trend": {"type": "string"},
    "institutional_holders": {"type": "number"},
    "institutional_ratio": {"type": "number"},
    "insider_signal": {"type": "string"},
    "insider_note": {"type": "string"},
    "pledge_risk": {"type": "string"},
    "pledge_note": {"type": "string"},
    "industry_analysis": {"type": "object"},
    "scenario_analysis": {"type": "object"},
    "dividend": {"type": "object"},
    "earnings_forecast": {"type": "object"},
    "key_strengths": {"type": "array", "items": {"type": "string"}},
    "key_risks": {"type": "array", "items": {"type": "string"}},
    "cross_layer_notes": {"type": "string"},
    "dcf_cross_check": {"type": "object"},
    "tracking_indicators": {"type": "array", "items": {"type": "object"}},
    # Governance risk fields (optional, injected by orchestrator)
    "governance_risk": {"type": "string", "description": "clean / watch / critical"},
    "governance_events": {"type": "array", "items": {"type": "string"}},
    "st_status": {"type": "string", "description": "normal / ST / *ST"},
    "st_reason": {"type": "string"},
}

# -- Research Manager properties --
_RM_PROPERTIES = {
    **_CORE_PROPERTIES,
    "debate_winner": {"type": "string"},
    "debate_delta": {"type": "integer"},
    "debate_rationale": {"type": "string"},
    "strongest_bull_point": {"type": "string"},
    "strongest_bear_point": {"type": "string"},
    "adjusted_score": {"type": "number"},
    "adjusted_direction": {"type": "string"},
    "recommendation": {"type": "string"},
    "risk_warnings": {"type": "array", "items": {"type": "string"}},
}

# -- Trader properties --
_TRADER_PROPERTIES = {
    **_CORE_PROPERTIES,
    "action": {"type": "string", "description": "buy/hold/sell/watch. watch=no position, monitor for signals."},
    "action_strength": {"type": "string"},
    "target_price": {"type": "number", "description": "Target price in CNY. For watch, provide hypothetical entry target based on resistance or valuation."},
    "stop_loss": {"type": "number", "description": "Stop loss price in CNY. For watch, provide hypothetical stop based on support level."},
    "target_price_rationale": {"type": "string"},
    "stop_loss_rationale": {"type": "string"},
    "take_profit_levels": {"type": "array", "items": {"type": "object"}},
    "confidence_components": {"type": "object"},
    "confidence_total": {"type": "integer"},
    "confidence_label": {"type": "string"},
    "position_advice": {"type": "string"},
    "position_range": {"type": "string"},
    "risk_score": {"type": "integer"},
    "risk_level": {"type": "string"},
    "time_horizon": {"type": "string"},
    "entry_conditions": {"type": "array", "items": {"type": "string"}},
    "key_catalysts": {"type": "array", "items": {"type": "string"}},
    "reasoning": {"type": "string"},
    "warnings": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Risk warnings (2-5 items).",
    },
}

# -- Risk Manager properties --
_RISK_MANAGER_PROPERTIES = {
    **_CORE_PROPERTIES,
    "risk_level": {
        "type": "string",
        "description": "very_high / high / medium / low / very_low",
    },
    "risk_score": {
        "type": "integer",
        "description": "Risk score 0-100 (100 = highest risk).",
    },
    "risk_winner": {
        "type": "string",
        "description": "aggressive / conservative / neutral_draw",
    },
    "risk_rationale": {"type": "string"},
    "adjusted_direction": {"type": "string"},
    "key_risks": {"type": "array", "items": {"type": "string"}},
    "key_opportunities": {"type": "array", "items": {"type": "string"}},
    "position_suggestion": {"type": "string"},
    "stop_loss_suggestion": {"type": "string"},
    "risk_warnings": {"type": "array", "items": {"type": "string"}},
}

_AGENT_SCHEMAS = {
    "news": _NEWS_PROPERTIES,
    "technical": _TECH_PROPERTIES,
    "fundamentals": _FUND_PROPERTIES,
    "research_manager": _RM_PROPERTIES,
    "risk_manager": _RISK_MANAGER_PROPERTIES,
    "trader": _TRADER_PROPERTIES,
}


def get_submit_tool(agent_type: str = "generic") -> dict:
    """
    Return the submit_analysis tool definition for a specific agent type.

    Args:
        agent_type: One of "news", "technical", "fundamentals",
                    "research_manager", "trader", "generic".
                    "generic" returns the full combined schema (backward compat).
    """
    if agent_type == "generic":
        # Backward compat: merge all properties
        all_props = {}
        for props in _AGENT_SCHEMAS.values():
            all_props.update(props)
        properties = all_props
    else:
        properties = _AGENT_SCHEMAS.get(agent_type, _NEWS_PROPERTIES)

    return {
        "name": "submit_analysis",
        "description": _DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": _CORE_REQUIRED,
        },
    }
