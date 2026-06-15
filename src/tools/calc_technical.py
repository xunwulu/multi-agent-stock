"""
calc_technical - 技术指标预计算工具

从 K线数据计算常用技术指标，返回给分析师直接使用。
不依赖 LLM 计算，确保指标数值准确。

计算的指标:
  - 均线系统: MA5 / MA10 / MA20 / MA60 / MA120
  - MACD: DIF / DEA / 柱状图
  - KDJ: K / D / J
  - RSI: RSI6 / RSI12 / RSI24
  - 布林带: 上轨 / 中轨 / 下轨
"""

import time
import logging
from datetime import datetime, timedelta

from src.tools.tushare_utils import normalize_code

logger = logging.getLogger(__name__)


def _get_kline_data(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    """内部获取K线数据（复用 get_kline 工具，获取全部数据用于指标计算）"""
    from src.tools.get_kline import get_kline
    result = get_kline(
        code=ts_code,
        start_date=start_date,
        end_date=end_date,
        period="daily",
        max_output=0,  # 获取全部数据，calc_technical 自行截断
    )
    if result.get("ok") and result.get("data"):
        return result["data"]
    return []


# ---------- 指标计算函数 ----------

def _calc_ma(closes: list[float], period: int) -> list[float | None]:
    """简单移动平均"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            result.append(round(sum(window) / period, 3))
    return result


def _calc_ema(values: list[float], period: int) -> list[float | None]:
    """指数移动平均"""
    k = 2 / (period + 1)
    result = []
    for i, v in enumerate(values):
        if i < period - 1:
            result.append(None)
        elif i == period - 1:
            # 第一个 EMA = SMA
            result.append(round(sum(values[:period]) / period, 3))
        else:
            prev = result[i - 1]
            result.append(round(v * k + prev * (1 - k), 3))
    return result


def _calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list, list, list]:
    """MACD: DIF / DEA / 柱状图"""
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)

    dif = []
    for i in range(len(closes)):
        if ema_fast[i] is None or ema_slow[i] is None:
            dif.append(None)
        else:
            dif.append(round(ema_fast[i] - ema_slow[i], 4))

    # DEA = EMA(DIF, signal)
    dif_valid = [d if d is not None else 0 for d in dif]
    dea = _calc_ema(dif_valid, signal)
    # 对齐: DEA 的 None 区间应与 DIF 一致
    for i in range(len(dif)):
        if dif[i] is None:
            dea[i] = None

    histogram = []
    for i in range(len(closes)):
        if dif[i] is None or dea[i] is None:
            histogram.append(None)
        else:
            histogram.append(round(2 * (dif[i] - dea[i]), 4))

    return dif, dea, histogram


def _calc_kdj(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> tuple[list, list, list]:
    """KDJ: K / D / J"""
    rsv_list = []
    for i in range(len(closes)):
        if i < n - 1:
            rsv_list.append(None)
        else:
            h_n = max(highs[i - n + 1 : i + 1])
            l_n = min(lows[i - n + 1 : i + 1])
            if h_n == l_n:
                rsv_list.append(50.0)
            else:
                rsv_list.append(round((closes[i] - l_n) / (h_n - l_n) * 100, 3))

    k_list = []
    d_list = []
    j_list = []

    prev_k = 50.0
    prev_d = 50.0

    for rsv in rsv_list:
        if rsv is None:
            k_list.append(None)
            d_list.append(None)
            j_list.append(None)
        else:
            k = round((2 / m1) * prev_k + (1 / m1) * rsv, 3)
            d = round((2 / m2) * prev_d + (1 / m2) * k, 3)
            j = round(3 * k - 2 * d, 3)
            k_list.append(k)
            d_list.append(d)
            j_list.append(j)
            prev_k = k
            prev_d = d

    return k_list, d_list, j_list


def _calc_rsi(closes: list[float], period: int) -> list[float | None]:
    """
    RSI: 相对强弱指标（Wilder 平滑法）

    算法:
      1. 计算每日涨跌幅，分离 gain 和 loss
      2. 第一个 avg_gain/avg_loss = SMA(period)
      3. 后续用 Wilder 平滑: avg = (prev_avg * (period-1) + current) / period
      4. RSI = 100 - 100 / (1 + avg_gain/avg_loss)
    """
    result = []
    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = 0.0
    avg_loss = 0.0

    for i in range(len(closes)):
        if i < period:
            result.append(None)
        elif i == period:
            # 第一个 RSI: 用 SMA 种子
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(round(100 - 100 / (1 + rs), 3))
        else:
            # Wilder 平滑: 维护滚动 avg_gain/avg_loss
            idx = i - 1
            avg_gain = (avg_gain * (period - 1) + gains[idx]) / period
            avg_loss = (avg_loss * (period - 1) + losses[idx]) / period
            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(round(100 - 100 / (1 + rs), 3))

    return result


def _calc_boll(
    closes: list[float],
    period: int = 20,
    nbdev: int = 2,
) -> tuple[list, list, list]:
    """布林带: 上轨 / 中轨 / 下轨"""
    upper = []
    middle = []
    lower = []

    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None)
            middle.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            ma = sum(window) / period
            std = (sum((x - ma) ** 2 for x in window) / period) ** 0.5
            middle.append(round(ma, 3))
            upper.append(round(ma + nbdev * std, 3))
            lower.append(round(ma - nbdev * std, 3))

    return upper, middle, lower


def _calc_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """
    ATR (Average True Range) - 真实波动幅度

    TR = max(当日最高-当日最低, |当日最高-昨收|, |当日最低-昨收|)
    ATR = SMA(TR, period)

    用于: 科学止损（止损 = 最新价 - n*ATR）、仓位管理、波动率评估
    """
    tr_list = []
    for i in range(len(closes)):
        if i == 0:
            tr_list.append(highs[i] - lows[i])
        else:
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            tr_list.append(max(tr1, tr2, tr3))

    # SMA of TR
    atr = []
    for i in range(len(tr_list)):
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(round(sum(tr_list[:period]) / period, 3))
        else:
            # 使用 Wilder 平滑 (前值 * (period-1) + 当前值) / period
            prev = atr[i - 1]
            atr.append(round((prev * (period - 1) + tr_list[i]) / period, 3))

    return atr


def _calc_fibonacci(highs: list[float], lows: list[float], closes: list[float]) -> dict:
    """
    Fibonacci 回撤位计算

    基于近60日最高价和最低价，计算关键黄金分割回撤位。
    专业分析师必备工具，比"凭感觉找前高低"科学得多。
    """
    # 取近60日数据
    window = min(60, len(closes))
    h_window = highs[-window:]
    l_window = lows[-window:]

    swing_high = max(h_window)
    swing_low = min(l_window)
    diff = swing_high - swing_low

    if diff <= 0:
        return {}

    # 回撤位（从高点回撤）
    fib_levels = {
        "retracement_236": round(swing_high - diff * 0.236, 2),
        "retracement_382": round(swing_high - diff * 0.382, 2),
        "retracement_500": round(swing_high - diff * 0.500, 2),
        "retracement_618": round(swing_high - diff * 0.618, 2),
        "retracement_786": round(swing_high - diff * 0.786, 2),
    }

    # 判断当前价处于哪两个Fib位之间
    latest_close = closes[-1]
    position = "above_swing_high"
    fib_names = ["retracement_236", "retracement_382", "retracement_500",
                 "retracement_618", "retracement_786"]
    fib_values = [fib_levels[n] for n in fib_names]

    if latest_close >= swing_high:
        position = "above_swing_high"
    elif latest_close <= swing_low:
        position = "below_swing_low"
    else:
        for idx in range(len(fib_values)):
            if latest_close >= fib_values[idx]:
                if idx == 0:
                    position = f"between_0_and_236"
                else:
                    position = f"between_{fib_names[idx-1][-3:]}_and_{fib_names[idx][-3:]}"
                break
        else:
            position = f"between_786_and_low"

    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        **fib_levels,
        "current_position": position,
    }


def _calc_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> tuple[list | None, list | None, list | None]:
    """
    ADX (Average Directional Index) - 趋势强度指标

    ADX > 25: 有明确趋势
    ADX > 50: 强趋势
    ADX < 20: 无趋势/震荡

    +DI > -DI: 多头主导
    -DI > +DI: 空头主导

    返回: (adx, plus_di, minus_di)
    """
    n = len(closes)
    if n < period * 2:
        return None, None, None

    # 1. 计算方向运动 +DM / -DM
    plus_dm = []
    minus_dm = []
    tr_list = []

    for i in range(n):
        if i == 0:
            plus_dm.append(0)
            minus_dm.append(0)
            tr_list.append(highs[i] - lows[i])
        else:
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]

            plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
            minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            tr_list.append(max(tr1, tr2, tr3))

    # 2. Wilder 平滑
    def wilder_smooth(values: list, period: int) -> list:
        result = []
        for i in range(len(values)):
            if i < period - 1:
                result.append(None)
            elif i == period - 1:
                result.append(sum(values[:period]))
            else:
                prev = result[i - 1]
                result.append(prev - prev / period + values[i])
        return result

    smooth_plus_dm = wilder_smooth(plus_dm, period)
    smooth_minus_dm = wilder_smooth(minus_dm, period)
    smooth_tr = wilder_smooth(tr_list, period)

    # 3. 计算 +DI / -DI
    plus_di = []
    minus_di = []
    for i in range(n):
        if smooth_tr[i] is None or smooth_tr[i] == 0:
            plus_di.append(None)
            minus_di.append(None)
        else:
            plus_di.append(round(smooth_plus_dm[i] / smooth_tr[i] * 100, 2))
            minus_di.append(round(smooth_minus_dm[i] / smooth_tr[i] * 100, 2))

    # 4. 计算 DX -> ADX
    dx = []
    for i in range(n):
        if plus_di[i] is None or minus_di[i] is None:
            dx.append(None)
        else:
            di_sum = plus_di[i] + minus_di[i]
            di_diff = abs(plus_di[i] - minus_di[i])
            dx.append(round(di_diff / di_sum * 100, 2) if di_sum > 0 else 0)

    # ADX = Wilder 平滑 DX
    adx = []
    dx_valid = [d if d is not None else 0 for d in dx]
    adx_smooth = wilder_smooth(dx_valid, period)
    for i in range(n):
        if adx_smooth[i] is None:
            adx.append(None)
        else:
            adx.append(round(adx_smooth[i] / period, 2))

    return adx, plus_di, minus_di


# ---------- 背离检测 ----------

def _detect_peaks(values: list, window: int = 5) -> list[int]:
    """
    检测峰值索引。峰值 = 比左右各window个邻居都大的点。

    Args:
        values: 数值列表（可以包含None）
        window: 左右各看多少个点

    Returns:
        峰值所在的索引列表
    """
    peaks = []
    n = len(values)
    for i in range(window, n - window):
        # 跳过None值
        if values[i] is None:
            continue
        is_peak = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if values[j] is not None and values[j] >= values[i]:
                is_peak = False
                break
        if is_peak:
            peaks.append(i)
    return peaks


def _detect_valleys(values: list, window: int = 5) -> list[int]:
    """
    检测谷值索引。谷值 = 比左右各window个邻居都小的点。

    Args:
        values: 数值列表（可以包含None）
        window: 左右各看多少个点

    Returns:
        谷值所在的索引列表
    """
    valleys = []
    n = len(values)
    for i in range(window, n - window):
        if values[i] is None:
            continue
        is_valley = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if values[j] is not None and values[j] <= values[i]:
                is_valley = False
                break
        if is_valley:
            valleys.append(i)
    return valleys


def _detect_divergence(
    closes: list[float],
    indicator: list,
    window: int = 5,
    min_peaks: int = 2,
) -> dict:
    """
    检测单个指标与价格的背离。

    顶背离: 价格创新高但指标没创新高 -> 上涨动能衰竭
    底背离: 价格创新低但指标没创新低 -> 下跌动能衰竭

    Args:
        closes: 收盘价列表
        indicator: 指标值列表（可以包含None）
        window: 峰谷检测窗口
        min_peaks: 至少需要几个峰/谷才判断背离

    Returns:
        {
            "top_divergence": True/False,
            "bottom_divergence": True/False,
            "details": {
                "price_peaks": [价格峰值],
                "indicator_peaks": [指标峰值],
                "price_valleys": [价格谷值],
                "indicator_valleys": [指标谷值],
            }
        }
    """
    result = {
        "top_divergence": False,
        "bottom_divergence": False,
        "details": None,
    }

    # 将None替换为0用于峰谷检测（None区域不会被选为峰/谷）
    ind_clean = [v if v is not None else 0 for v in indicator]
    closes_clean = closes

    # 检测峰和谷
    price_peaks_idx = _detect_peaks(closes_clean, window)
    ind_peaks_idx = _detect_peaks(ind_clean, window)
    price_valleys_idx = _detect_valleys(closes_clean, window)
    ind_valleys_idx = _detect_valleys(ind_clean, window)

    # 取最后几个峰/谷比较方向
    # 顶背离检测：价格的最后N个峰是否在上升，但指标的对应峰是否在下降/持平
    if len(price_peaks_idx) >= min_peaks and len(ind_peaks_idx) >= min_peaks:
        # 取最近的几个峰
        recent_price_peaks = price_peaks_idx[-min_peaks:]
        recent_ind_peaks = ind_peaks_idx[-min_peaks:]

        # 价格峰值方向：是否在上升
        price_ascending = all(
            closes_clean[recent_price_peaks[i]] < closes_clean[recent_price_peaks[i + 1]]
            for i in range(len(recent_price_peaks) - 1)
        )

        # 指标峰值方向：是否在下降或持平
        ind_descending = all(
            ind_clean[recent_ind_peaks[i]] > ind_clean[recent_ind_peaks[i + 1]]
            for i in range(len(recent_ind_peaks) - 1)
        )

        if price_ascending and ind_descending:
            result["top_divergence"] = True

    # 底背离检测：价格的最后N个谷是否在下降，但指标的对应谷是否在上升/持平
    if len(price_valleys_idx) >= min_peaks and len(ind_valleys_idx) >= min_peaks:
        recent_price_valleys = price_valleys_idx[-min_peaks:]
        recent_ind_valleys = ind_valleys_idx[-min_peaks:]

        price_descending = all(
            closes_clean[recent_price_valleys[i]] > closes_clean[recent_price_valleys[i + 1]]
            for i in range(len(recent_price_valleys) - 1)
        )

        ind_ascending = all(
            ind_clean[recent_ind_valleys[i]] < ind_clean[recent_ind_valleys[i + 1]]
            for i in range(len(recent_ind_valleys) - 1)
        )

        if price_descending and ind_ascending:
            result["bottom_divergence"] = True

    # 附加详细信息
    if result["top_divergence"] or result["bottom_divergence"]:
        result["details"] = {
            "price_recent_peaks": [
                {"index": idx, "value": round(closes_clean[idx], 2)}
                for idx in price_peaks_idx[-3:]
            ],
            "indicator_recent_peaks": [
                {"index": idx, "value": round(ind_clean[idx], 4) if ind_clean[idx] else None}
                for idx in ind_peaks_idx[-3:]
            ],
            "price_recent_valleys": [
                {"index": idx, "value": round(closes_clean[idx], 2)}
                for idx in price_valleys_idx[-3:]
            ],
            "indicator_recent_valleys": [
                {"index": idx, "value": round(ind_clean[idx], 4) if ind_clean[idx] else None}
                for idx in ind_valleys_idx[-3:]
            ],
        }

    return result


# ---------- K线形态识别 ----------

def _detect_kline_patterns(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    dates: list[str],
) -> list[dict]:
    """
    检测最近出现的经典K线形态。

    识别的形态:
      - 锤子线 (Hammer): 底部反转信号
      - 倒锤子 (Inverted Hammer): 底部反转信号
      - 上吊线 (Hanging Man): 顶部反转信号
      - 射击之星 (Shooting Star): 顶部反转信号
      - 看涨吞没 (Bullish Engulfing): 底部反转信号
      - 看跌吞没 (Bearish Engulfing): 顶部反转信号
      - 十字星 (Doji): 犹豫信号
      - 长下影线 (Long Lower Shadow): 底部支撑信号
      - 长上影线 (Long Upper Shadow): 顶部压力信号

    Returns:
        最近5个交易日内出现的形态列表
        [{"name": "锤子线", "date": "20260423", "signal": "bullish", "description": "..."}]
    """
    patterns = []
    n = len(closes)
    if n < 5:
        return patterns

    # 只检查最近5根K线
    check_range = range(max(0, n - 5), n)

    for i in check_range:
        o = opens[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        date = dates[i]

        body = abs(c - o)
        full_range = h - l
        if full_range == 0:
            continue

        upper_shadow = h - max(o, c)
        lower_shadow = min(o, c) - l
        is_bullish = c > o

        # 十字星: 实体很小，上下影线差不多
        if body / full_range < 0.1 and upper_shadow > body and lower_shadow > body:
            patterns.append({
                "name": "十字星",
                "date": date,
                "signal": "neutral",
                "description": "多空均衡，方向待确认",
            })
            continue

        # 锤子线: 出现在下跌后，长下影线(>实体2倍)，短上影线，实体在上方
        if lower_shadow > body * 2 and upper_shadow < body * 0.5:
            if i > 0 and closes[i - 1] > c:
                # 前一日收跌 -> 底部锤子
                patterns.append({
                    "name": "锤子线",
                    "date": date,
                    "signal": "bullish",
                    "description": "下跌后出现长下影线，底部反转信号",
                })
            else:
                # 上涨中出现 -> 上吊线
                patterns.append({
                    "name": "上吊线",
                    "date": date,
                    "signal": "bearish",
                    "description": "上涨后出现长下影线，顶部反转预警",
                })
            continue

        # 倒锤子 / 射击之星: 长上影线(>实体2倍)，短下影线
        if upper_shadow > body * 2 and lower_shadow < body * 0.5:
            if is_bullish:
                patterns.append({
                    "name": "射击之星",
                    "date": date,
                    "signal": "bearish",
                    "description": "上涨后出现长上影线，顶部反转预警",
                })
            else:
                patterns.append({
                    "name": "倒锤子",
                    "date": date,
                    "signal": "bullish",
                    "description": "下跌后出现长上影线，底部反转信号",
                })
            continue

        # 长下影线（不满足锤子条件但下影线明显）
        if lower_shadow > body * 1.5 and lower_shadow > upper_shadow * 2:
            patterns.append({
                "name": "长下影线",
                "date": date,
                "signal": "bullish",
                "description": "下方买盘支撑较强",
            })
            continue

        # 长上影线
        if upper_shadow > body * 1.5 and upper_shadow > lower_shadow * 2:
            patterns.append({
                "name": "长上影线",
                "date": date,
                "signal": "bearish",
                "description": "上方抛压较重",
            })
            continue

    # 吞没形态（需要看前后两根K线）
    for i in check_range:
        if i < 1:
            continue
        date = dates[i]
        prev_o, prev_c = opens[i - 1], closes[i - 1]
        curr_o, curr_c = opens[i], closes[i]

        prev_body = abs(prev_c - prev_o)
        curr_body = abs(curr_c - curr_o)

        # 看涨吞没: 前阴后阳，阳线完全包裹阴线
        if prev_c < prev_o and curr_c > curr_o:
            if curr_o <= prev_c and curr_c >= prev_o and curr_body > prev_body:
                # 避免重复添加（同一日期）
                if not any(p["date"] == date for p in patterns):
                    patterns.append({
                        "name": "看涨吞没",
                        "date": date,
                        "signal": "bullish",
                        "description": "阳线完全包裹前日阴线，强烈底部反转信号",
                    })

        # 看跌吞没: 前阳后阴，阴线完全包裹阳线
        if prev_c > prev_o and curr_c < curr_o:
            if curr_o >= prev_c and curr_c <= prev_o and curr_body > prev_body:
                if not any(p["date"] == date for p in patterns):
                    patterns.append({
                        "name": "看跌吞没",
                        "date": date,
                        "signal": "bearish",
                        "description": "阴线完全包裹前日阳线，强烈顶部反转信号",
                    })

    # === 多日组合形态 ===
    for i in check_range:
        if i < 2:
            continue
        date = dates[i]

        o0, c0 = opens[i - 2], closes[i - 2]  # 前前日
        o1, c1 = opens[i - 1], closes[i - 1]  # 前日
        o2, c2 = opens[i], closes[i]            # 当日

        body0 = abs(c0 - o0)
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        # 跳过有重复日期的
        if any(p["date"] == date for p in patterns):
            continue

        # 三白兵: 连续3根阳线，每根收盘价递增，实体较大
        if c0 > o0 and c1 > o1 and c2 > o2:
            if c2 > c1 > c0 and body2 > 0 and body1 > 0:
                patterns.append({
                    "name": "三白兵",
                    "date": date,
                    "signal": "bullish",
                    "description": "连续3日阳线上涨，多头力量强劲",
                })
                continue

        # 三只乌鸦: 连续3根阴线，每根收盘价递减
        if c0 < o0 and c1 < o1 and c2 < o2:
            if c2 < c1 < c0 and body2 > 0 and body1 > 0:
                patterns.append({
                    "name": "三只乌鸦",
                    "date": date,
                    "signal": "bearish",
                    "description": "连续3日阴线下跌，空头力量强劲",
                })
                continue

        # 晨星（看涨）: 第1日大阴线 + 第2日小实体（星） + 第3日大阳线回升
        # 条件：第1日收阴，第3日收阳，第2日实体小，第3日收盘接近第1日开盘
        prev_bearish = c0 < o0 and body0 > body1 * 2
        curr_bullish = c2 > o2 and body2 > body1 * 2
        star_small = body1 < body0 * 0.3 and body1 < body2 * 0.3

        if prev_bearish and curr_bullish and star_small:
            if c2 > (o0 + c0) / 2:
                patterns.append({
                    "name": "晨星",
                    "date": date,
                    "signal": "bullish",
                    "description": "大阴+小实体星+大阳，底部反转组合形态",
                })
                continue

        # 暮星（看跌）: 第1日大阳线 + 第2日小实体（星） + 第3日大阴线回落
        prev_bullish = c0 > o0 and body0 > body1 * 2
        curr_bearish = c2 < o2 and body2 > body1 * 2

        if prev_bullish and curr_bearish and star_small:
            if c2 < (o0 + c0) / 2:
                patterns.append({
                    "name": "暮星",
                    "date": date,
                    "signal": "bearish",
                    "description": "大阳+小实体星+大阴，顶部反转组合形态",
                })
                continue

    return patterns


def _detect_advanced_patterns(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    dates: list[str],
) -> list[dict]:
    """
    检测多日复合形态: 头肩顶/底、双顶/底、三角形、楔形、矩形等。

    基于波峰/波谷的位置关系，匹配经典形态模板。
    每个形态返回: name, signal, confidence, neckline/target/invalidation。
    """
    results = []
    n = len(closes)
    if n < 20:
        return results

    # 检测波峰和波谷（窗口=5）
    peak_indices = _detect_peaks(highs, window=5)
    valley_indices = _detect_valleys(lows, window=5)

    # 过滤: 只保留最近60日内的
    cutoff = max(0, n - 60)
    recent_peaks = [(i, highs[i]) for i in peak_indices if i >= cutoff]
    recent_valleys = [(i, lows[i]) for i in valley_indices if i >= cutoff]

    if len(recent_peaks) < 2 or len(recent_valleys) < 2:
        return results

    # ---------- 双顶（M头）----------
    if len(recent_peaks) >= 2:
        p1_idx, p1_val = recent_peaks[-2]
        p2_idx, p2_val = recent_peaks[-1]
        # 两个峰的高度接近（差异<3%），中间有明显的谷
        if abs(p1_val - p2_val) / max(p1_val, p2_val) < 0.03:
            # 找两峰之间的谷
            between_valleys = [
                (i, v) for i, v in recent_valleys
                if p1_idx < i < p2_idx
            ]
            if between_valleys:
                neck_idx, neck_val = between_valleys[-1]
                drop = min(p1_val, p2_val) - neck_val
                if drop / min(p1_val, p2_val) > 0.03:  # 至少3%回调
                    latest = closes[-1]
                    conf = 0.7 if abs(p1_val - p2_val) / max(p1_val, p2_val) < 0.015 else 0.5
                    results.append({
                        "name": "double_top",
                        "name_cn": "双顶（M头）",
                        "signal": "bearish_reversal",
                        "confidence": conf,
                        "neckline": round(neck_val, 2),
                        "target": round(neck_val - drop, 2),
                        "invalidation": round(max(p1_val, p2_val) * 1.02, 2),
                        "description": f"双峰 {p1_val:.2f}/{p2_val:.2f} 颈线 {neck_val:.2f}",
                    })

    # ---------- 双底（W底）----------
    if len(recent_valleys) >= 2:
        v1_idx, v1_val = recent_valleys[-2]
        v2_idx, v2_val = recent_valleys[-1]
        if abs(v1_val - v2_val) / min(v1_val, v2_val) < 0.03:
            between_peaks = [
                (i, v) for i, v in recent_peaks
                if v1_idx < i < v2_idx
            ]
            if between_peaks:
                neck_idx, neck_val = between_peaks[-1]
                rise = neck_val - min(v1_val, v2_val)
                if rise / min(v1_val, v2_val) > 0.03:
                    conf = 0.7 if abs(v1_val - v2_val) / min(v1_val, v2_val) < 0.015 else 0.5
                    results.append({
                        "name": "double_bottom",
                        "name_cn": "双底（W底）",
                        "signal": "bullish_reversal",
                        "confidence": conf,
                        "neckline": round(neck_val, 2),
                        "target": round(neck_val + rise, 2),
                        "invalidation": round(min(v1_val, v2_val) * 0.98, 2),
                        "description": f"双底 {v1_val:.2f}/{v2_val:.2f} 颈线 {neck_val:.2f}",
                    })

    # ---------- 头肩顶 ----------
    if len(recent_peaks) >= 3:
        ls_idx, ls_val = recent_peaks[-3]  # 左肩
        head_idx, head_val = recent_peaks[-2]  # 头
        rs_idx, rs_val = recent_peaks[-1]  # 右肩
        # 头 > 两肩，两肩高度接近
        if (head_val > ls_val and head_val > rs_val
                and abs(ls_val - rs_val) / max(ls_val, rs_val) < 0.05):
            # 找颈线（头两侧的谷）
            left_v = [(i, v) for i, v in recent_valleys if ls_idx < i < head_idx]
            right_v = [(i, v) for i, v in recent_valleys if head_idx < i < rs_idx]
            if left_v and right_v:
                neckline = (left_v[-1][1] + right_v[-1][1]) / 2
                drop = head_val - neckline
                if drop / head_val > 0.03:
                    results.append({
                        "name": "head_shoulders_top",
                        "name_cn": "头肩顶",
                        "signal": "bearish_reversal",
                        "confidence": 0.8,
                        "neckline": round(neckline, 2),
                        "target": round(neckline - drop, 2),
                        "invalidation": round(head_val * 1.02, 2),
                        "description": f"左肩{ls_val:.2f} 头{head_val:.2f} 右肩{rs_val:.2f} 颈线{neckline:.2f}",
                    })

    # ---------- 头肩底 ----------
    if len(recent_valleys) >= 3:
        ls_idx, ls_val = recent_valleys[-3]
        head_idx, head_val = recent_valleys[-2]
        rs_idx, rs_val = recent_valleys[-1]
        if (head_val < ls_val and head_val < rs_val
                and abs(ls_val - rs_val) / max(ls_val, rs_val) < 0.05):
            left_p = [(i, v) for i, v in recent_peaks if ls_idx < i < head_idx]
            right_p = [(i, v) for i, v in recent_peaks if head_idx < i < rs_idx]
            if left_p and right_p:
                neckline = (left_p[-1][1] + right_p[-1][1]) / 2
                rise = neckline - head_val
                if rise / head_val > 0.03:
                    results.append({
                        "name": "head_shoulders_bottom",
                        "name_cn": "头肩底",
                        "signal": "bullish_reversal",
                        "confidence": 0.8,
                        "neckline": round(neckline, 2),
                        "target": round(neckline + rise, 2),
                        "invalidation": round(head_val * 0.98, 2),
                        "description": f"左肩{ls_val:.2f} 头{head_val:.2f} 右肩{rs_val:.2f} 颈线{neckline:.2f}",
                    })

    # ---------- 三角形/楔形/矩形 ----------
    # 需要至少3个峰和3个谷
    if len(recent_peaks) >= 3 and len(recent_valleys) >= 3:
        last_3p = recent_peaks[-3:]
        last_3v = recent_valleys[-3:]

        # 峰值趋势
        p_vals = [v for _, v in last_3p]
        p_rising = p_vals[-1] > p_vals[0]
        p_flat = abs(p_vals[-1] - p_vals[0]) / max(p_vals) < 0.02

        # 谷值趋势
        v_vals = [v for _, v in last_3v]
        v_rising = v_vals[-1] > v_vals[0]
        v_flat = abs(v_vals[-1] - v_vals[0]) / max(v_vals) < 0.02

        latest_close = closes[-1]
        support = min(v_vals)
        resistance = max(p_vals)
        amplitude = resistance - support

        # 上升三角形: 峰平 + 谷上升
        if p_flat and v_rising:
            results.append({
                "name": "ascending_triangle",
                "name_cn": "上升三角形",
                "signal": "bullish_continuation",
                "confidence": 0.6,
                "resistance": round(resistance, 2),
                "support": round(support, 2),
                "target": round(resistance + amplitude, 2),
                "invalidation": round(support * 0.98, 2),
                "description": f"水平阻力{resistance:.2f} + 上升趋势支撑",
            })

        # 下降三角形: 谷平 + 峰下降
        if v_flat and not v_rising:
            results.append({
                "name": "descending_triangle",
                "name_cn": "下降三角形",
                "signal": "bearish_continuation",
                "confidence": 0.6,
                "resistance": round(resistance, 2),
                "support": round(support, 2),
                "target": round(support - amplitude, 2),
                "invalidation": round(resistance * 1.02, 2),
                "description": f"水平支撑{support:.2f} + 下降趋势压力",
            })

        # 对称三角形: 峰下降 + 谷上升 -> 收敛
        if not p_rising and v_rising and amplitude / max(p_vals) > 0.02:
            results.append({
                "name": "symmetric_triangle",
                "name_cn": "对称三角形",
                "signal": "neutral_consolidation",
                "confidence": 0.5,
                "resistance": round(resistance, 2),
                "support": round(support, 2),
                "target_up": round(resistance + amplitude, 2),
                "target_down": round(support - amplitude, 2),
                "description": f"收敛区间 {support:.2f}-{resistance:.2f}，待突破",
            })

        # 上升楔形: 峰上升 + 谷上升，但峰上升慢于谷上升 -> 看空
        if p_rising and v_rising:
            p_slope = (p_vals[-1] - p_vals[0]) / max(1, last_3p[-1][0] - last_3p[0][0])
            v_slope = (v_vals[-1] - v_vals[0]) / max(1, last_3v[-1][0] - last_3v[0][0])
            if v_slope > p_slope > 0:  # 谷上升更快
                results.append({
                    "name": "rising_wedge",
                    "name_cn": "上升楔形",
                    "signal": "bearish_reversal",
                    "confidence": 0.55,
                    "resistance": round(resistance, 2),
                    "support": round(support, 2),
                    "target": round(support - amplitude, 2),
                    "invalidation": round(resistance * 1.02, 2),
                    "description": "两条上升边线收敛，看空反转信号",
                })

        # 下降楔形: 峰下降 + 谷下降，但谷下降慢于峰下降 -> 看多
        if not p_rising and not v_rising:
            p_slope = (p_vals[-1] - p_vals[0]) / max(1, last_3p[-1][0] - last_3p[0][0])
            v_slope = (v_vals[-1] - v_vals[0]) / max(1, last_3v[-1][0] - last_3v[0][0])
            if p_slope < v_slope < 0:  # 峰下降更快
                results.append({
                    "name": "falling_wedge",
                    "name_cn": "下降楔形",
                    "signal": "bullish_reversal",
                    "confidence": 0.55,
                    "resistance": round(resistance, 2),
                    "support": round(support, 2),
                    "target": round(resistance + amplitude, 2),
                    "invalidation": round(support * 0.98, 2),
                    "description": "两条下降边线收敛，看多反转信号",
                })

        # 矩形整理: 峰平 + 谷平
        if p_flat and v_flat and amplitude / max(p_vals) > 0.03:
            results.append({
                "name": "rectangle",
                "name_cn": "矩形整理",
                "signal": "neutral_consolidation",
                "confidence": 0.5,
                "resistance": round(resistance, 2),
                "support": round(support, 2),
                "target_up": round(resistance + amplitude, 2),
                "target_down": round(support - amplitude, 2),
                "description": f"横盘整理区间 {support:.2f}-{resistance:.2f}",
            })

    return results


# ---------- 主入口 ----------

def calc_technical(
    code: str,
    start_date: str = "",
    end_date: str = "",
    indicators: str = "all",
) -> dict:
    """
    计算股票技术指标

    Args:
        code: 股票代码（如 300033.SZ 或 300033）
        start_date: 开始日期（YYYYMMDD 或 YYYY-MM-DD），为空则自动计算
        end_date: 结束日期（YYYYMMDD 或 YYYY-MM-DD），为空则用今天
        indicators: 计算哪些指标
            "all" - 全部（默认）
            "ma" - 仅均线
            "macd" - 仅MACD
            "kdj" - 仅KDJ
            "rsi" - 仅RSI
            "boll" - 仅布林带
            也可以逗号组合，如 "ma,macd"

    Returns:
        {"ok": True, "data": [...], "count": N, "error": None}

    每条记录按日期对齐，包含请求的指标值。
    注意: 前 N 行某些指标可能为 null（数据不足以计算）。
    """
    start_ms = time.time()

    try:
        ts_code = normalize_code(code)

        # 自动计算日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=300)).strftime("%Y%m%d")

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        # 获取K线数据
        raw = _get_kline_data(ts_code, start, end)

        if not raw:
            return {
                "ok": False,
                "data": None,
                "count": 0,
                "error": "No kline data available",
            }

        # 解析数据，按日期正序排列
        records = sorted(raw, key=lambda r: r.get("trade_date", ""))

        # A1 fix: skip records with missing prices instead of inserting 0.0
        valid_records = []
        for r in records:
            close_raw = r.get("close")
            if close_raw is None or close_raw == '':
                continue
            high_raw = r.get("high")
            if high_raw is None or high_raw == '':
                continue
            low_raw = r.get("low")
            if low_raw is None or low_raw == '':
                continue
            open_raw = r.get("open")
            if open_raw is None or open_raw == '':
                continue
            valid_records.append(r)

        if len(valid_records) < 10:
            return {
                "ok": False,
                "data": None,
                "count": len(valid_records),
                "error": f"Too few valid records ({len(valid_records)}) after filtering missing prices",
            }

        closes = [float(r["close"]) for r in valid_records]
        highs = [float(r["high"]) for r in valid_records]
        lows = [float(r["low"]) for r in valid_records]
        opens = [float(r["open"]) for r in valid_records]
        dates = [r.get("trade_date", "") for r in valid_records]
        vols_raw = [r.get("vol") or r.get("volume") for r in valid_records]

        # 解析需要计算的指标
        if indicators == "all":
            ind_set = {"ma", "macd", "kdj", "rsi", "boll"}
        else:
            ind_set = set(indicators.split(","))

        # 计算指标
        computed = {}

        if "ma" in ind_set:
            for period in [5, 10, 20, 60, 120]:
                computed[f"ma{period}"] = _calc_ma(closes, period)

        if "macd" in ind_set:
            dif, dea, hist = _calc_macd(closes)
            computed["macd_dif"] = dif
            computed["macd_dea"] = dea
            computed["macd_hist"] = hist

        if "kdj" in ind_set:
            k, d, j = _calc_kdj(highs, lows, closes)
            computed["kdj_k"] = k
            computed["kdj_d"] = d
            computed["kdj_j"] = j

        if "rsi" in ind_set:
            for period in [6, 12, 24]:
                computed[f"rsi{period}"] = _calc_rsi(closes, period)

        if "boll" in ind_set:
            upper, middle, lower = _calc_boll(closes)
            computed["boll_upper"] = upper
            computed["boll_middle"] = middle
            computed["boll_lower"] = lower

        # 背离检测（依赖MACD/KDJ/RSI，所以放最后）
        divergence_results = {}
        if "macd" in ind_set and "macd_dif" in computed:
            divergence_results["macd"] = _detect_divergence(
                closes, computed["macd_dif"], window=5
            )
        if "kdj" in ind_set and "kdj_k" in computed:
            divergence_results["kdj"] = _detect_divergence(
                closes, computed["kdj_k"], window=5
            )
        if "rsi" in ind_set and "rsi6" in computed:
            divergence_results["rsi"] = _detect_divergence(
                closes, computed["rsi6"], window=5
            )

        # K线形态识别
        pattern_results = _detect_kline_patterns(opens, highs, lows, closes, dates)

        # 组装结果 - 只返回最近的数据（避免数据量过大）
        # 截取最近 min(60, len) 条，但保留足够的计算窗口
        n = len(dates)
        output_start = max(0, n - 60)

        result_rows = []
        for i in range(output_start, n):
            row = {
                "trade_date": dates[i],
                "close": closes[i],
                "high": highs[i],
                "low": lows[i],
                "open": opens[i],
                "vol": vols_raw[i] if i < len(vols_raw) else None,
            }
            for key, values in computed.items():
                row[key] = values[i]
            result_rows.append(row)

        duration_ms = int((time.time() - start_ms) * 1000)
        logger.info(
            f"[calc_technical] {ts_code} "
            f"{start}-{end}: {n} rows raw, {len(result_rows)} rows output, "
            f"{duration_ms}ms"
        )

        # 额外返回最新一期的指标摘要（方便 LLM 快速判断）
        latest = result_rows[-1] if result_rows else {}
        summary = _build_summary(result_rows, latest)

        # 将背离检测结果加入摘要
        if divergence_results:
            summary["divergence"] = {}
            for ind_name, div_result in divergence_results.items():
                summary["divergence"][ind_name] = {
                    "top_divergence": div_result["top_divergence"],
                    "bottom_divergence": div_result["bottom_divergence"],
                }
                if div_result["top_divergence"]:
                    summary["divergence"][ind_name]["signal"] = "top_divergence"
                elif div_result["bottom_divergence"]:
                    summary["divergence"][ind_name]["signal"] = "bottom_divergence"
                else:
                    summary["divergence"][ind_name]["signal"] = "none"

        # 将K线形态识别结果加入摘要
        if pattern_results:
            summary["kline_patterns"] = pattern_results

        # 高级复合形态识别（头肩/双顶底/三角形等）
        advanced_patterns = _detect_advanced_patterns(highs, lows, closes, dates)
        if advanced_patterns:
            summary["advanced_patterns"] = advanced_patterns

        return {
            "ok": True,
            "data": result_rows,
            "count": len(result_rows),
            "summary": summary,
            "duration_ms": duration_ms,
            "error": None,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.error(f"[calc_technical] Error: {e}")
        return {
            "ok": False,
            "data": None,
            "count": 0,
            "duration_ms": duration_ms,
            "error": str(e),
        }


def _build_summary(rows: list[dict], latest: dict) -> dict:
    """构建最新指标摘要，帮 LLM 快速判断信号"""
    if not rows:
        return {}

    summary = {
        "latest_date": latest.get("trade_date"),
        "latest_close": latest.get("close"),
    }

    # --- 涨跌幅统计 ---
    closes = [r.get("close") for r in rows if r.get("close") is not None]
    if len(closes) >= 2:
        # 近20日涨跌幅
        recent_20 = closes[-20:] if len(closes) >= 20 else closes
        chg_20 = round((recent_20[-1] - recent_20[0]) / recent_20[0] * 100, 2)
        summary["change_pct_20d"] = chg_20

        # 近5日涨跌幅
        recent_5 = closes[-5:] if len(closes) >= 5 else closes
        chg_5 = round((recent_5[-1] - recent_5[0]) / recent_5[0] * 100, 2)
        summary["change_pct_5d"] = chg_5

    # --- 价格百分位（当前价在近60日中的位置）---
    if len(closes) >= 20:
        window = closes[-60:] if len(closes) >= 60 else closes
        sorted_c = sorted(window)
        current = closes[-1]
        rank = sum(1 for c in sorted_c if c <= current)
        summary["price_percentile_60d"] = round(rank / len(sorted_c) * 100, 1)
        summary["period_high"] = max(window)
        summary["period_low"] = min(window)

    # --- 波动率（近20日年化）---
    if len(closes) >= 20:
        daily_returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(len(closes) - 20, len(closes))
        ]
        mean_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
        annual_vol = round(variance ** 0.5 * (252 ** 0.5) * 100, 1)
        summary["volatility_20d_annual"] = annual_vol

    # --- 成交量趋势（5日均量 / 20日均量）---
    vols = [r.get("vol") or r.get("volume") for r in rows]
    vols = [v for v in vols if v is not None]
    if len(vols) >= 20:
        vol_ma5 = sum(vols[-5:]) / 5
        vol_ma20 = sum(vols[-20:]) / 20
        summary["vol_ratio_5_20"] = round(vol_ma5 / vol_ma20, 2)

    # MACD 信号判断
    if "macd_dif" in latest and "macd_dea" in latest:
        dif = latest.get("macd_dif")
        dea = latest.get("macd_dea")
        hist = latest.get("macd_hist")
        if dif is not None and dea is not None:
            if dif > dea and hist is not None and hist > 0:
                summary["macd_signal"] = "golden_cross_bullish"
            elif dif < dea:
                summary["macd_signal"] = "death_cross_bearish"
            else:
                summary["macd_signal"] = "neutral"
            summary["macd_dif"] = dif
            summary["macd_dea"] = dea

    # KDJ 信号判断
    if "kdj_k" in latest and "kdj_d" in latest:
        k = latest.get("kdj_k")
        d = latest.get("kdj_d")
        j = latest.get("kdj_j")
        if k is not None and d is not None:
            if k > 80 and d > 80:
                summary["kdj_signal"] = "overbought"
            elif k < 20 and d < 20:
                summary["kdj_signal"] = "oversold"
            else:
                summary["kdj_signal"] = "neutral"
            summary["kdj_k"] = k
            summary["kdj_d"] = d
            summary["kdj_j"] = j

    # RSI 信号判断
    if "rsi6" in latest:
        rsi6 = latest.get("rsi6")
        if rsi6 is not None:
            if rsi6 > 80:
                summary["rsi_signal"] = "overbought"
            elif rsi6 < 20:
                summary["rsi_signal"] = "oversold"
            else:
                summary["rsi_signal"] = "neutral"
            summary["rsi6"] = rsi6

    # 均线多头/空头排列
    ma_keys = ["ma5", "ma10", "ma20", "ma60"]
    ma_values = [latest.get(k) for k in ma_keys]
    if all(v is not None for v in ma_values):
        if all(ma_values[i] > ma_values[i + 1] for i in range(len(ma_values) - 1)):
            summary["ma_pattern"] = "bullish_alignment"
        elif all(ma_values[i] < ma_values[i + 1] for i in range(len(ma_values) - 1)):
            summary["ma_pattern"] = "bearish_alignment"
        else:
            summary["ma_pattern"] = "mixed"

    # --- 均线交叉信号（MA5 vs MA20 金叉/死叉）---
    if len(rows) >= 2:
        prev = rows[-2]
        curr = rows[-1]
        prev_ma5 = prev.get("ma5")
        prev_ma20 = prev.get("ma20")
        curr_ma5 = curr.get("ma5")
        curr_ma20 = curr.get("ma20")
        if all(v is not None for v in [prev_ma5, prev_ma20, curr_ma5, curr_ma20]):
            if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
                summary["ma_cross_signal"] = "ma5_crossed_above_ma20"
            elif prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
                summary["ma_cross_signal"] = "ma5_crossed_below_ma20"

    # 布林带位置
    if "boll_upper" in latest and "boll_lower" in latest:
        close = latest.get("close", 0)
        upper = latest.get("boll_upper", 0)
        lower = latest.get("boll_lower", 0)
        if upper and lower and (upper - lower) > 0:
            position = (close - lower) / (upper - lower) * 100
            summary["boll_position_pct"] = round(position, 1)
            if position > 90:
                summary["boll_signal"] = "near_upper_pressure"
            elif position < 10:
                summary["boll_signal"] = "near_lower_support"
            else:
                summary["boll_signal"] = "middle_zone"

    # --- OBV 趋势判断 ---
    if len(closes) >= 20:
        obv_signal = _calc_obv_signal(rows)
        if obv_signal:
            summary["obv_signal"] = obv_signal

    # --- ATR（真实波动幅度）---
    highs_all = [r.get("high") for r in rows if r.get("high") is not None]
    lows_all = [r.get("low") for r in rows if r.get("low") is not None]
    if len(highs_all) >= 14 and len(lows_all) >= 14 and len(closes) >= 15:
        atr_series = _calc_atr(highs_all, lows_all, closes, period=14)
        if atr_series and atr_series[-1] is not None:
            atr_val = atr_series[-1]
            summary["atr_14"] = atr_val
            latest_price = closes[-1]
            # A股T+1 + 涨跌停需要更宽止损，Wilder原版3x，取折中2.5x
            _atr_mult = 2.5
            summary["atr_stop_long"] = round(latest_price - _atr_mult * atr_val, 2)
            summary["atr_stop_short"] = round(latest_price + _atr_mult * atr_val, 2)
            summary["atr_pct_of_price"] = round(atr_val / latest_price * 100, 2)

    # --- Fibonacci 回撤 ---
    if len(highs_all) >= 20 and len(lows_all) >= 20:
        fib = _calc_fibonacci(highs_all, lows_all, closes)
        if fib:
            summary["fibonacci"] = fib

    # --- ADX（趋势强度）---
    if len(highs_all) >= 28 and len(lows_all) >= 28 and len(closes) >= 28:
        adx_series, pdi_series, mdi_series = _calc_adx(
            highs_all, lows_all, closes, period=14
        )
        if adx_series and adx_series[-1] is not None:
            adx_val = adx_series[-1]
            pdi_val = pdi_series[-1] if pdi_series else None
            mdi_val = mdi_series[-1] if mdi_series else None

            if adx_val > 50:
                strength = "strong_trend"
            elif adx_val > 25:
                strength = "moderate_trend"
            elif adx_val > 20:
                strength = "weak_trend"
            else:
                strength = "no_trend"

            # ADX 方向（最近5个值）
            adx_recent = [v for v in adx_series[-5:] if v is not None]
            adx_dir = "unknown"
            if len(adx_recent) >= 3:
                if adx_recent[-1] > adx_recent[0]:
                    adx_dir = "rising"
                else:
                    adx_dir = "falling"

            summary["adx"] = {
                "adx_value": adx_val,
                "plus_di": pdi_val,
                "minus_di": mdi_val,
                "trend_strength": strength,
                "adx_direction": adx_dir,
            }

    # --- 评分建议（工具预计算，模型可直接使用或微调）---
    hints = _calc_scoring_hints(summary, rows, closes)
    if hints:
        summary["scoring_hints"] = hints

    return summary


def _calc_scoring_hints(summary: dict, rows: list[dict], closes: list[float]) -> dict:
    """
    按评分锚定表逐项预计算建议分数。

    工具负责"判断"，模型只需"打分"或微调。
    这样两次运行的评分会稳定一致。
    """
    hints = {}
    latest_close = closes[-1] if closes else None

    # 1. 均线排列 (trend_ma): 多头排列10, 多头减弱7, 震荡5, 空头减弱3, 空头排列0
    ma_pattern = summary.get("ma_pattern")
    if ma_pattern == "bullish_alignment":
        hints["trend_ma"] = {"score": 10, "reason": "多头排列"}
    elif ma_pattern == "bearish_alignment":
        # 检查是否"空头减弱"：MA5/MA10 开始拐头
        ma5 = summary.get("ma5") or rows[-1].get("ma5")
        ma10 = summary.get("ma10") or rows[-1].get("ma10")
        if ma5 and ma10 and ma5 > ma10:
            hints["trend_ma"] = {"score": 3, "reason": "空头减弱（MA5上穿MA10）"}
        else:
            hints["trend_ma"] = {"score": 0, "reason": "空头排列"}
    else:  # mixed
        hints["trend_ma"] = {"score": 5, "reason": "震荡（均线mixed）"}

    # 2. MACD方向 (trend_macd): 金叉+红柱扩大10, 金叉+红柱缩小7, 零轴附近5, 死叉+绿柱缩小3, 死叉+绿柱扩大0
    macd_signal = summary.get("macd_signal", "")
    dif = summary.get("macd_dif")
    dea = summary.get("macd_dea")
    if "golden_cross" in macd_signal or (dif is not None and dea is not None and dif > dea):
        # 检查红柱是在扩大还是缩小
        # 从 rows 中取最近3个柱状图
        hist_recent = [r.get("macd_hist") for r in rows[-3:] if r.get("macd_hist") is not None]
        # 零轴下方金叉信号较弱，降分处理
        below_zero = dif is not None and dif < 0
        if len(hist_recent) >= 2:
            if hist_recent[-1] > hist_recent[0]:
                if below_zero:
                    hints["trend_macd"] = {"score": 7, "reason": "零轴下方金叉+红柱扩大（弱信号）"}
                else:
                    hints["trend_macd"] = {"score": 10, "reason": "金叉+红柱扩大"}
            else:
                if below_zero:
                    hints["trend_macd"] = {"score": 5, "reason": "零轴下方金叉+红柱缩小（弱信号）"}
                else:
                    hints["trend_macd"] = {"score": 7, "reason": "金叉+红柱缩小"}
        else:
            if below_zero:
                hints["trend_macd"] = {"score": 5, "reason": "零轴下方金叉（弱信号）"}
            else:
                hints["trend_macd"] = {"score": 7, "reason": "金叉状态"}
    elif dif is not None and abs(dif) < 1.0 and dea is not None and abs(dea) < 1.0:
        hints["trend_macd"] = {"score": 5, "reason": "零轴附近"}
    else:
        # 死叉
        hist_recent = [r.get("macd_hist") for r in rows[-3:] if r.get("macd_hist") is not None]
        if hist_recent and len(hist_recent) >= 2:
            if abs(hist_recent[-1]) < abs(hist_recent[0]):
                hints["trend_macd"] = {"score": 3, "reason": "死叉+绿柱缩小"}
            else:
                hints["trend_macd"] = {"score": 0, "reason": "死叉+绿柱扩大"}
        else:
            hints["trend_macd"] = {"score": 3, "reason": "死叉状态"}

    # 3. 价格位置 (trend_price_position): MA20上方+创新高10, MA20上方7, MA20-MA60之间5, MA60下方3, 跌破MA120:0
    if latest_close:
        ma20 = rows[-1].get("ma20") if rows else None
        ma60 = rows[-1].get("ma60") if rows else None
        ma120 = rows[-1].get("ma120") if rows else None
        if ma20 and ma60 and ma120:
            recent_high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
            if latest_close > ma20 and latest_close >= recent_high * 0.98:
                hints["trend_price_position"] = {"score": 10, "reason": "MA20上方+接近新高"}
            elif latest_close > ma20:
                hints["trend_price_position"] = {"score": 7, "reason": "MA20上方"}
            elif latest_close > ma60:
                hints["trend_price_position"] = {"score": 5, "reason": "MA20-MA60之间"}
            elif latest_close > ma120:
                hints["trend_price_position"] = {"score": 3, "reason": "MA60下方"}
            else:
                hints["trend_price_position"] = {"score": 0, "reason": "跌破MA120"}

    # 4. MACD信号 (signal_macd): 金叉10, 即将金叉7, 零轴附近5, 即将死叉3, 死叉0
    # 零轴下方金叉降分：零轴下方金叉7（弱），零轴上方金叉10（强）
    if dif is not None and dea is not None:
        if dif > dea:
            if dif < 0:
                hints["signal_macd"] = {"score": 7, "reason": "零轴下方金叉（弱信号）"}
            else:
                hints["signal_macd"] = {"score": 10, "reason": "金叉"}
        elif dif > dea * 0.9:  # 接近交叉
            hints["signal_macd"] = {"score": 7, "reason": "即将金叉"}
        elif abs(dif) < 1.0 and abs(dea) < 1.0:
            hints["signal_macd"] = {"score": 5, "reason": "零轴附近"}
        elif dif < dea and dif > dea * 0.9:
            hints["signal_macd"] = {"score": 3, "reason": "即将死叉"}
        else:
            hints["signal_macd"] = {"score": 0, "reason": "死叉"}

    # 5. KDJ信号 (signal_kdj): 超卖区金叉10, 中性区7, 超买区5, 超买区死叉3, 超卖区且下行0
    k_val = summary.get("kdj_k")
    d_val = summary.get("kdj_d")
    j_val = summary.get("kdj_j")
    if k_val is not None and d_val is not None:
        kdj_sig = summary.get("kdj_signal", "neutral")
        if kdj_sig == "oversold" and k_val > d_val:
            hints["signal_kdj"] = {"score": 10, "reason": "超卖区金叉"}
        elif kdj_sig == "overbought" and k_val < d_val:
            hints["signal_kdj"] = {"score": 3, "reason": "超买区死叉"}
        elif kdj_sig == "oversold" and k_val < d_val:
            hints["signal_kdj"] = {"score": 0, "reason": "超卖区且下行"}
        elif kdj_sig == "overbought":
            hints["signal_kdj"] = {"score": 5, "reason": "超买区"}
        else:
            hints["signal_kdj"] = {"score": 7, "reason": "中性区"}

    # 6. RSI信号 (signal_rsi): RSI6<20:10, 20-40:7, 40-60:5, 60-80:3, >80:0
    rsi6 = summary.get("rsi6")
    if rsi6 is not None:
        if rsi6 < 20:
            hints["signal_rsi"] = {"score": 10, "reason": f"RSI6={rsi6:.1f}极端超卖"}
        elif rsi6 < 40:
            hints["signal_rsi"] = {"score": 7, "reason": f"RSI6={rsi6:.1f}超卖偏弱"}
        elif rsi6 < 60:
            hints["signal_rsi"] = {"score": 5, "reason": f"RSI6={rsi6:.1f}中性"}
        elif rsi6 < 80:
            hints["signal_rsi"] = {"score": 3, "reason": f"RSI6={rsi6:.1f}偏强"}
        else:
            hints["signal_rsi"] = {"score": 0, "reason": f"RSI6={rsi6:.1f}超买"}

    # 7. 量价配合 (volume_price): 上涨放量+下跌缩量10, 上涨放量7, 缩量横盘5, 放量下跌3, 缩量下跌0
    if len(rows) >= 10:
        vols = [r.get("vol") or r.get("volume") for r in rows[-10:]]
        vols = [v for v in vols if v is not None and v > 0]
        prices = [r.get("close") for r in rows[-10:]]
        if len(vols) >= 5 and len(prices) >= 5:
            up_vols = [vols[i] for i in range(1, len(prices)) if prices[i] > prices[i-1]]
            down_vols = [vols[i] for i in range(1, len(prices)) if prices[i] < prices[i-1]]
            avg_up = sum(up_vols) / len(up_vols) if up_vols else 0
            avg_down = sum(down_vols) / len(down_vols) if down_vols else 0

            price_chg = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0

            if avg_up > 0 and avg_down > 0:
                if avg_up > avg_down * 1.3 and price_chg > 0:
                    hints["volume_price"] = {"score": 10, "reason": "上涨放量+下跌缩量"}
                elif avg_up > avg_down and price_chg > 0:
                    hints["volume_price"] = {"score": 7, "reason": "上涨放量"}
                elif avg_up < avg_down and price_chg < -1:
                    hints["volume_price"] = {"score": 3, "reason": "放量下跌"}
                elif price_chg < -1:
                    hints["volume_price"] = {"score": 0, "reason": "缩量下跌"}
                else:
                    hints["volume_price"] = {"score": 5, "reason": "缩量横盘"}
            elif price_chg > 0:
                hints["volume_price"] = {"score": 7, "reason": "上涨放量"}
            elif price_chg < -1:
                hints["volume_price"] = {"score": 3, "reason": "量价偏弱"}

    # 10. 波动率 (relative_volatility): 低<20→10, 适中20-35→8, 偏高35-40→5, 剧烈≥40→2
    vol = summary.get("volatility_20d_annual")
    if vol is not None:
        if vol < 20:
            hints["relative_volatility"] = {"score": 10, "reason": f"低波动{vol:.1f}%"}
        elif vol < 35:
            hints["relative_volatility"] = {"score": 8, "reason": f"适中波动{vol:.1f}%"}
        elif vol < 40:
            hints["relative_volatility"] = {"score": 5, "reason": f"偏高波动{vol:.1f}%"}
        else:
            hints["relative_volatility"] = {"score": 2, "reason": f"剧烈波动{vol:.1f}%"}

    return hints


def _calc_obv_signal(rows: list[dict]) -> str | None:
    """
    计算 OBV（能量潮）趋势信号。

    OBV = 累计成交量，涨日加，跌日减。
    价格上涨但 OBV 不涨 = 顶背离（看空）
    价格下跌但 OBV 不跌 = 底背离（看多）
    """
    recent = rows[-20:] if len(rows) >= 20 else rows
    obv = 0
    obv_list = []
    price_list = []

    for i, r in enumerate(recent):
        close = r.get("close")
        vol = r.get("vol") or r.get("volume")
        if close is None or vol is None:
            continue

        price_list.append(close)

        if i == 0:
            obv = vol
        else:
            if close > price_list[-2] if len(price_list) >= 2 else True:
                obv += vol
            elif close < (price_list[-2] if len(price_list) >= 2 else close):
                obv -= vol
        obv_list.append(obv)

    if len(obv_list) < 10 or len(price_list) < 10:
        return None

    # OBV 趋势：比较前半段和后半段的均值
    mid = len(obv_list) // 2
    obv_first_half = sum(obv_list[:mid]) / mid
    obv_second_half = sum(obv_list[mid:]) / (len(obv_list) - mid)
    price_first_half = sum(price_list[:mid]) / mid
    price_second_half = sum(price_list[mid:]) / (len(price_list) - mid)

    price_up = price_second_half > price_first_half
    obv_up = obv_second_half > obv_first_half

    if price_up and not obv_up:
        return "top_divergence_price_up_obv_flat"
    elif not price_up and obv_up:
        return "bottom_divergence_price_down_obv_up"
    elif price_up and obv_up:
        return "trend_confirmed_bullish"
    else:
        return "trend_confirmed_bearish"
