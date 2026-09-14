"""test_data_flow_fixes - 验证数据流断点修复（RM 收 news + risk_loop key 兼容）

修复1: _run_research_manager 补传 news_json 给 _format_reports
修复2: risk_loop._format_rm_output 兼容 combined_score/combined_direction 键名
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_project_root if False else project_root)

from src.agents.debate_loop import DebateLoop
from src.agents.risk_loop import RiskLoop

_CONFIG = {"model": "x", "base_url": "x", "api_key": "x"}


# === 修复1: _format_reports 含新闻面 ===
def test_format_reports_includes_news_section():
    """_format_reports 第3参数(news)真的展开新闻面摘要"""
    debate = DebateLoop(_CONFIG)
    news = {"score": 80, "direction": "bullish",
            "key_events": [{"event": "业绩超预期", "direction": "bullish"}]}
    out = debate._format_reports({"score": 70}, {"score": 75}, news)
    assert "新闻" in out or "news" in out.lower(), "应含新闻面段落"
    assert "业绩超预期" in out, "应含新闻事件内容"


def test_format_reports_without_news_still_works():
    """不传 news(向后兼容) 不报错"""
    debate = DebateLoop(_CONFIG)
    out = debate._format_reports({"score": 70}, {"score": 75})
    assert "技术" in out or "tech" in out.lower()


# === 修复2: _format_rm_output key 兼容 ===
def test_format_rm_output_prefers_combined_keys():
    """combined 键优先, 不再 N/A"""
    loop = RiskLoop(_CONFIG)
    out = loop._format_rm_output(
        {"combined_score": 65, "combined_direction": "bullish",
         "debate_winner": "bull", "debate_rationale": "r"})
    assert "65" in out
    assert "bullish" in out
    # 综合评分行不应是 N/A
    score_line = [l for l in out.split("\n") if "综合评分" in l][0]
    assert "N/A" not in score_line, f"综合评分不应 N/A: {score_line}"


def test_format_rm_output_falls_back_to_adjusted():
    """缺 combined 时退到 adjusted"""
    loop = RiskLoop(_CONFIG)
    out = loop._format_rm_output(
        {"adjusted_score": 55, "adjusted_direction": "bearish"})
    assert "55" in out
    assert "bearish" in out


def test_format_rm_output_empty_dict_no_crash():
    """空 dict 不抛异常, 走 early return"""
    loop = RiskLoop(_CONFIG)
    out = loop._format_rm_output({})
    assert "无" in out  # 空 dict → "无研究经理结论"
