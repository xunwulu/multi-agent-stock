"""
Tests for _resample_kline in get_kline.py.

When the native weekly/monthly Tushare API returns 0 records (common for SZ
stocks due to permission limits), get_kline falls back to fetching daily data
and resampling it. These tests verify the resample aggregation rules:

  open      -> first
  high      -> max
  low       -> min
  close     -> last
  pre_close -> last
  vol       -> sum
  amount    -> sum
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.tools.get_kline import _resample_kline


def make_daily_record(date, o, h, l, c, vol, amount, pre_close=None):
    """Helper to build one daily candle dict (Tushare-like fields)."""
    rec = {
        "trade_date": date,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "vol": vol,
        "amount": amount,
    }
    if pre_close is not None:
        rec["pre_close"] = pre_close
    return rec


# Two full trading weeks in May 2026 (Sundays 5/10 and 5/17 split the weeks).
WEEK1 = [
    # 5/4 Mon - 5/8 Fri
    make_daily_record("20260504", 10.0, 10.5, 9.5, 10.2, 100, 1000, 9.8),
    make_daily_record("20260505", 10.2, 11.0, 10.0, 10.8, 120, 1200, 10.2),
    make_daily_record("20260506", 10.8, 12.5, 10.5, 12.0, 150, 1500, 10.8),  # high=12.5
    make_daily_record("20260507", 12.0, 12.2, 11.5, 11.8, 110, 1100, 12.0),
    make_daily_record("20260508", 11.8, 11.9, 11.0, 11.0, 90, 900, 11.8),
]
WEEK2 = [
    # 5/11 Mon - 5/15 Fri
    make_daily_record("20260511", 11.0, 11.5, 10.8, 11.2, 80, 800, 11.0),
    make_daily_record("20260512", 11.2, 11.8, 11.0, 11.5, 95, 950, 11.2),
    make_daily_record("20260513", 11.5, 12.0, 11.2, 11.8, 105, 1050, 11.5),
    make_daily_record("20260514", 11.8, 12.2, 11.6, 12.0, 110, 1100, 11.8),
    make_daily_record("20260515", 12.0, 12.5, 11.9, 12.3, 130, 1300, 12.0),
]
TWO_WEEKS = WEEK1 + WEEK2


def test_resample_empty_input():
    """Empty daily list -> empty result."""
    assert _resample_kline([], "weekly") == []
    print("PASS: empty input -> empty output")


def test_resample_invalid_period_returns_original():
    """Period other than weekly/monthly returns input unchanged."""
    result = _resample_kline(TWO_WEEKS, "daily")
    assert result is TWO_WEEKS, "daily period should return original data"
    print("PASS: invalid period returns original data")


def test_resample_two_weeks_count():
    """10 daily records across 2 weeks -> 2 weekly candles."""
    result = _resample_kline(TWO_WEEKS, "weekly")
    assert len(result) == 2, f"Expected 2 weekly candles, got {len(result)}"
    print(f"PASS: 10 daily -> {len(result)} weekly candles")


def test_resample_week1_ohlc():
    """Verify OHLC aggregation for week 1 (5/4-5/8, labeled 5/10)."""
    result = _resample_kline(TWO_WEEKS, "weekly")
    assert len(result) == 2
    week1 = result[0]
    # open = first day's open
    assert abs(week1["open"] - 10.0) < 0.001, f"Week1 open: expected 10.0, got {week1['open']}"
    # high = max across week (12.5 on 5/6)
    assert abs(week1["high"] - 12.5) < 0.001, f"Week1 high: expected 12.5, got {week1['high']}"
    # low = min across week (9.5 on 5/4)
    assert abs(week1["low"] - 9.5) < 0.001, f"Week1 low: expected 9.5, got {week1['low']}"
    # close = last day's close
    assert abs(week1["close"] - 11.0) < 0.001, f"Week1 close: expected 11.0, got {week1['close']}"
    print(f"PASS: week1 OHLC open={week1['open']} high={week1['high']} "
          f"low={week1['low']} close={week1['close']}")


def test_resample_week2_ohlc():
    """Verify OHLC aggregation for week 2 (5/11-5/15, labeled 5/17)."""
    result = _resample_kline(TWO_WEEKS, "weekly")
    assert len(result) == 2
    week2 = result[1]
    assert abs(week2["open"] - 11.0) < 0.001, f"Week2 open: expected 11.0, got {week2['open']}"
    assert abs(week2["high"] - 12.5) < 0.001, f"Week2 high: expected 12.5, got {week2['high']}"
    assert abs(week2["low"] - 10.8) < 0.001, f"Week2 low: expected 10.8, got {week2['low']}"
    assert abs(week2["close"] - 12.3) < 0.001, f"Week2 close: expected 12.3, got {week2['close']}"
    print(f"PASS: week2 OHLC open={week2['open']} high={week2['high']} "
          f"low={week2['low']} close={week2['close']}")


def test_resample_vol_amount_sum():
    """Verify vol and amount are summed across the week."""
    result = _resample_kline(TWO_WEEKS, "weekly")
    week1 = result[0]
    # vol week1 = 100+120+150+110+90 = 570
    assert abs(week1["vol"] - 570) < 0.001, f"Week1 vol: expected 570, got {week1['vol']}"
    # amount week1 = 1000+1200+1500+1100+900 = 5700
    assert abs(week1["amount"] - 5700) < 0.001, f"Week1 amount: expected 5700, got {week1['amount']}"

    week2 = result[1]
    # vol week2 = 80+95+105+110+130 = 520
    assert abs(week2["vol"] - 520) < 0.001, f"Week2 vol: expected 520, got {week2['vol']}"
    # amount week2 = 800+950+1050+1100+1300 = 5200
    assert abs(week2["amount"] - 5200) < 0.001, f"Week2 amount: expected 5200, got {week2['amount']}"
    print(f"PASS: vol/amount summed correctly (w1: {week1['vol']}/{week1['amount']}, "
          f"w2: {week2['vol']}/{week2['amount']})")


def test_resample_weekly_date_labels():
    """Weekly candles labeled by LAST trading day of week (Tushare convention)."""
    result = _resample_kline(TWO_WEEKS, "weekly")
    # Week1 (5/4-5/8) last trade day = Friday 5/8; Week2 (5/11-5/15) = Friday 5/15
    assert result[0]["trade_date"] == "20260508", (
        f"Expected week1 label 20260508 (last trade day), got {result[0]['trade_date']}"
    )
    assert result[1]["trade_date"] == "20260515", (
        f"Expected week2 label 20260515 (last trade day), got {result[1]['trade_date']}"
    )
    print(f"PASS: weekly labels (last trade day) {result[0]['trade_date']}, {result[1]['trade_date']}")


def test_resample_monthly_two_months():
    """Daily records across April and May -> 2 monthly candles."""
    cross_month = [
        make_daily_record("20260428", 8.0, 8.5, 7.8, 8.2, 100, 1000),
        make_daily_record("20260429", 8.2, 8.8, 8.0, 8.5, 110, 1100),
        make_daily_record("20260430", 8.5, 9.0, 8.3, 9.0, 120, 1200),
        make_daily_record("20260504", 9.0, 9.5, 8.8, 9.3, 130, 1300),
        make_daily_record("20260505", 9.3, 9.8, 9.1, 9.6, 140, 1400),
    ]
    result = _resample_kline(cross_month, "monthly")
    assert len(result) == 2, f"Expected 2 monthly candles, got {len(result)}"
    apr = result[0]
    may = result[1]
    # April: open=8.0 (first), close=9.0 (last of 4/30)
    assert abs(apr["open"] - 8.0) < 0.001
    assert abs(apr["close"] - 9.0) < 0.001
    # May: open=9.0 (first), close=9.6 (last of 5/5)
    assert abs(may["open"] - 9.0) < 0.001
    assert abs(may["close"] - 9.6) < 0.001
    print(f"PASS: monthly resample -> {len(result)} months "
          f"(apr close={apr['close']}, may close={may['close']})")


def test_resample_single_week():
    """A single week of data -> 1 weekly candle."""
    result = _resample_kline(WEEK1, "weekly")
    assert len(result) == 1, f"Expected 1 weekly candle, got {len(result)}"
    w = result[0]
    assert abs(w["open"] - 10.0) < 0.001
    assert abs(w["close"] - 11.0) < 0.001
    print(f"PASS: single week -> 1 candle (open={w['open']}, close={w['close']})")


def test_resample_carries_ts_code():
    """ts_code column is carried through resample (last value)."""
    data = [
        {"trade_date": "20260504", "open": 10, "high": 11, "low": 9, "close": 10.5,
         "vol": 100, "amount": 1000, "ts_code": "000001.SZ"},
        {"trade_date": "20260505", "open": 10.5, "high": 11, "low": 10, "close": 10.8,
         "vol": 110, "amount": 1100, "ts_code": "000001.SZ"},
    ]
    result = _resample_kline(data, "weekly")
    assert len(result) == 1
    assert result[0].get("ts_code") == "000001.SZ", (
        f"ts_code not carried, got {result[0].get('ts_code')}"
    )
    print(f"PASS: ts_code carried -> {result[0]['ts_code']}")


def test_resample_recomputes_pct_chg():
    """pct_chg recomputed close-to-close; first candle has no prior -> None."""
    result = _resample_kline(TWO_WEEKS, "weekly")
    assert len(result) == 2
    # Week1 is the first candle -> no prior close -> pct_chg None
    assert result[0].get("pct_chg") is None, (
        f"First candle pct_chg should be None, got {result[0].get('pct_chg')}"
    )
    # Week2 close=12.3 vs Week1 close=11.0 -> (12.3/11.0-1)*100
    expected = round((12.3 / 11.0 - 1) * 100, 2)
    assert abs(result[1]["pct_chg"] - expected) < 0.01, (
        f"Week2 pct_chg: expected {expected}, got {result[1]['pct_chg']}"
    )
    print(f"PASS: pct_chg recomputed (w1=None, w2={result[1]['pct_chg']})")


def test_resample_missing_trade_date_returns_empty():
    """Records without trade_date column -> empty (cannot resample)."""
    bad_records = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    result = _resample_kline(bad_records, "weekly")
    assert result == [], f"Missing trade_date should return empty, got {result}"
    print("PASS: missing trade_date -> empty result")


if __name__ == "__main__":
    print("=" * 50)
    print("K-line Resample Fallback Tests")
    print("=" * 50)

    tests = [
        test_resample_empty_input,
        test_resample_invalid_period_returns_original,
        test_resample_two_weeks_count,
        test_resample_week1_ohlc,
        test_resample_week2_ohlc,
        test_resample_vol_amount_sum,
        test_resample_weekly_date_labels,
        test_resample_monthly_two_months,
        test_resample_single_week,
        test_resample_carries_ts_code,
        test_resample_recomputes_pct_chg,
        test_resample_missing_trade_date_returns_empty,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Result: {passed}/{passed+failed} passed")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"FAILED: {failed} tests")
