"""
test_financials_degraded - 验证 get_financials 的降级标记（第1刀保守版）

验证点:
  1. 全部核心报表失败 -> data_status="empty", data_degraded=True
  2. 部分报表失败    -> data_status="partial", data_degraded=True, degraded_reports 列出失败项
  3. 全部成功        -> data_status="complete", data_degraded=False
  4. 向后兼容        -> 任何降级情况 ok 保持 True（保守版核心：不破坏现有成功判定）

Usage: python -m pytest tests/test_financials_degraded.py -v
"""
import sys
import os
from unittest.mock import patch, MagicMock

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.tools.get_financials import get_financials


def _make_record():
    """构造一条非空报表记录（含 INCOME_FIELDS 关键字段，能通过 trim）"""
    return {
        "ann_date": "20251231",
        "end_date": "20251231",
        "total_revenue": 100,
        "n_income": 50,
    }


def _run_get_financials(call_side_effect):
    """用 mock 的 service._call 运行 get_financials，返回 result"""
    mock_service = MagicMock()
    mock_service._call.side_effect = call_side_effect
    with patch("src.tools.get_financials.get_tushare_client", return_value=mock_service):
        return get_financials("300033.SZ")


def test_complete_success_no_degraded():
    """全部报表都有数据 -> complete, 不降级"""
    def call_impl(api_name, params):
        return [_make_record()]
    result = _run_get_financials(call_impl)
    assert result["ok"] is True
    assert result["data_status"] == "complete"
    assert result["data_degraded"] is False
    assert result["degraded_reports"] == []


def test_all_reports_empty_marks_empty():
    """全部核心报表返回空 -> empty, 降级"""
    def call_impl(api_name, params):
        return []
    result = _run_get_financials(call_impl)
    assert result["ok"] is True  # 保守版保持 True
    assert result["data_status"] == "empty"
    assert result["data_degraded"] is True
    # 4 张核心报表都应在 degraded_reports
    for report in ("income", "balancesheet", "cashflow", "indicators"):
        assert report in result["degraded_reports"]


def test_partial_reports_failed_marks_partial():
    """部分报表抛异常 -> partial, 降级，列出失败项"""
    def call_impl(api_name, params):
        # fetch_map: income/balancesheet/cashflow/fina_indicator, 然后 dividend
        if api_name == "income":
            return [_make_record()]
        if api_name in ("balancesheet", "cashflow", "fina_indicator"):
            raise Exception(f"simulated {api_name} failure")
        return []  # dividend
    result = _run_get_financials(call_impl)
    assert result["ok"] is True
    assert result["data_status"] == "partial"
    assert result["data_degraded"] is True
    # income 有数据不在失败列表；其余 3 张失败
    assert "income" not in result["degraded_reports"]
    assert "balancesheet" in result["degraded_reports"]
    assert "cashflow" in result["degraded_reports"]
    assert "indicators" in result["degraded_reports"]
    # fetch_failures 记录了失败原因
    assert "balancesheet" in result["fetch_failures"]
    assert "simulated" in result["fetch_failures"]["balancesheet"]


def test_backward_compat_ok_stays_true():
    """保守版核心: 即使全空，ok 仍 True（不破坏现有成功判定），但降级可见"""
    def call_impl(api_name, params):
        return []
    result = _run_get_financials(call_impl)
    assert result["ok"] is True  # 保守版: 永远 True
    # 但数据残缺可见性已具备
    assert result["data_degraded"] is True
    assert "data_status" in result
    assert "degraded_reports" in result
    assert "fetch_failures" in result
    # 原有字段仍在（向后兼容）
    assert "data" in result
    assert "summary" in result
    assert "count" in result


def test_dividend_failure_does_not_degrade_core():
    """dividend 抛异常时不算核心降级（dividend 非核心报表），但记入 fetch_failures"""
    def call_impl(api_name, params):
        if api_name == "dividend":
            raise Exception("dividend api down")
        return [_make_record()]
    result = _run_get_financials(call_impl)
    assert result["ok"] is True
    assert result["data_degraded"] is False  # dividend 失败不算核心降级
    assert result["data_status"] == "complete"
    assert result["degraded_reports"] == []
    # 但 dividend 失败原因被记录
    assert "dividend" in result["fetch_failures"]
    assert "dividend api down" in result["fetch_failures"]["dividend"]


def test_single_report_type_success_not_degraded():
    """report_type='income' 时只检查 income；income 有数据就不算降级"""
    mock_service = MagicMock()
    mock_service._call.side_effect = lambda api_name, params: (
        [_make_record()] if api_name == "income" else []
    )
    with patch("src.tools.get_financials.get_tushare_client", return_value=mock_service):
        result = get_financials("300033.SZ", report_type="income")
    assert result["ok"] is True
    assert result["data_degraded"] is False  # 单表模式只查 income, 有数据=complete
    assert result["data_status"] == "complete"
    assert result["degraded_reports"] == []


def test_single_report_type_failed_only_marks_that_report():
    """report_type='income' 且 income 为空 -> 只标 income 失败, 不误报其他表"""
    mock_service = MagicMock()
    mock_service._call.side_effect = lambda api_name, params: []
    with patch("src.tools.get_financials.get_tushare_client", return_value=mock_service):
        result = get_financials("300033.SZ", report_type="income")
    assert result["ok"] is True
    assert result["data_degraded"] is True
    assert result["data_status"] == "empty"
    # 只标 income, 不误报 balancesheet/cashflow/indicators
    assert result["degraded_reports"] == ["income"]


def test_outer_exception_returns_error_status():
    """外层异常(如 get_tushare_client 抛错) -> data_status='error', 含降级字段"""
    with patch("src.tools.get_financials.get_tushare_client",
               side_effect=RuntimeError("no token")):
        result = get_financials("300033.SZ")
    assert result["ok"] is False
    assert result["data_status"] == "error"
    assert result["data_degraded"] is True
    assert "fetch_failures" in result
    assert "_outer" in result["fetch_failures"]
