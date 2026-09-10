"""Technical timing layer.

Framework 14 section 2 keeps technical analysis outside the hundred-point
fundamental score. It answers when the risk and reward might be better, not
whether the asset is worth owning.

The score is a transparent additive rubric printed alongside the number, so the
reader can see exactly which conditions earned which points.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

NIFTY_SYMBOL = "^NSEI"


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's relative strength index."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    signal_line = line.ewm(span=signal, adjust=False).mean()
    return line, signal_line, line - signal_line


def bollinger(series: pd.Series, window: int = 20, deviations: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = sma(series, window)
    spread = series.rolling(window=window, min_periods=window).std()
    return middle + deviations * spread, middle, middle - deviations * spread


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def _last(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    value = series.dropna()
    if value.empty:
        return None
    return float(value.iloc[-1])


@dataclass
class RubricLine:
    condition: str
    earned: float
    available: float
    detail: str


@dataclass
class TechnicalRead:
    price: float | None
    sma20: float | None
    sma50: float | None
    sma100: float | None
    sma200: float | None
    rsi14: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bollinger_upper: float | None
    bollinger_lower: float | None
    atr14: float | None
    atr_percent: float | None
    volume_ratio: float | None
    week52_high: float | None
    week52_low: float | None
    range_position: float | None
    relative_strength_6m: float | None
    support: list[float] = field(default_factory=list)
    resistance: list[float] = field(default_factory=list)
    rubric: list[RubricLine] = field(default_factory=list)
    score: float | None = None
    trend: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["rubric"] = [r.__dict__ for r in self.rubric]
        return d


def _describe_trend(read: TechnicalRead) -> str:
    p, s50, s200 = read.price, read.sma50, read.sma200
    if None in (p, s50, s200):
        return "unknown"
    if p > s50 > s200:
        return "uptrend"
    if p < s50 < s200:
        return "downtrend"
    if p > s200:
        return "recovering above the 200 day average"
    return "below the 200 day average"


def analyse(history: pd.DataFrame, benchmark: pd.DataFrame | None = None) -> TechnicalRead:
    """Compute indicators and the timing score from daily price history."""
    if history is None or history.empty:
        return TechnicalRead(*([None] * 18), notes=["No price history available."])

    close = history["Close"].astype(float)
    high = history["High"].astype(float)
    low = history["Low"].astype(float)
    volume = history["Volume"].astype(float)

    upper, _middle, lower = bollinger(close)
    macd_line, macd_signal, macd_hist = macd(close)
    atr_series = atr(high, low, close)

    price = _last(close)
    window52 = close.tail(252)
    high52 = float(window52.max()) if len(window52) else None
    low52 = float(window52.min()) if len(window52) else None

    range_position = None
    if price is not None and high52 is not None and low52 is not None and high52 > low52:
        range_position = (price - low52) / (high52 - low52)

    average_volume = _last(sma(volume, 20))
    latest_volume = _last(volume)
    volume_ratio = (latest_volume / average_volume) if (latest_volume and average_volume) else None

    relative_strength = _relative_strength(close, benchmark)
    atr_value = _last(atr_series)

    read = TechnicalRead(
        price=price,
        sma20=_last(sma(close, 20)),
        sma50=_last(sma(close, 50)),
        sma100=_last(sma(close, 100)),
        sma200=_last(sma(close, 200)),
        rsi14=_last(rsi(close)),
        macd_line=_last(macd_line),
        macd_signal=_last(macd_signal),
        macd_histogram=_last(macd_hist),
        bollinger_upper=_last(upper),
        bollinger_lower=_last(lower),
        atr14=atr_value,
        atr_percent=(atr_value / price) if (atr_value and price) else None,
        volume_ratio=volume_ratio,
        week52_high=high52,
        week52_low=low52,
        range_position=range_position,
        relative_strength_6m=relative_strength,
    )

    read.support = _levels(low, close, direction="support")
    read.resistance = _levels(high, close, direction="resistance")
    read.rubric = _build_rubric(read)
    earned = sum(line.earned for line in read.rubric)
    read.score = round(max(1.0, min(10.0, earned)), 1)
    read.trend = _describe_trend(read)
    return read


def _relative_strength(close: pd.Series, benchmark: pd.DataFrame | None) -> float | None:
    """Six-month return of the stock less the six-month return of the index."""
    if benchmark is None or benchmark.empty or len(close) < 130:
        return None
    bench_close = benchmark["Close"].astype(float)
    if len(bench_close) < 130:
        return None
    stock_return = float(close.iloc[-1] / close.iloc[-126] - 1)
    bench_return = float(bench_close.iloc[-1] / bench_close.iloc[-126] - 1)
    return stock_return - bench_return


def _levels(extreme: pd.Series, close: pd.Series, direction: str) -> list[float]:
    """Nearby structural levels from recent price extremes."""
    price = _last(close)
    if price is None:
        return []
    candidates: list[float] = []
    for window in (20, 60, 120, 252):
        segment = extreme.tail(window)
        if segment.empty:
            continue
        value = float(segment.min() if direction == "support" else segment.max())
        if direction == "support" and value < price:
            candidates.append(value)
        elif direction == "resistance" and value > price:
            candidates.append(value)
    unique = sorted({round(v, 2) for v in candidates}, reverse=(direction == "support"))
    return unique[:3]


def _build_rubric(read: TechnicalRead) -> list[RubricLine]:
    """The additive rubric. Weights total ten points."""
    lines: list[RubricLine] = []

    def add(condition: str, earned: float, available: float, detail: str) -> None:
        lines.append(RubricLine(condition, round(earned, 2), available, detail))

    price, s50, s200 = read.price, read.sma50, read.sma200

    if price is not None and s200 is not None:
        above = price > s200
        add("Price above the 200 day average", 1.5 if above else 0.0, 1.5,
            f"Price {price:,.2f} against 200 DMA {s200:,.2f}")
    else:
        add("Price above the 200 day average", 0.0, 1.5, "Insufficient history")

    if s50 is not None and s200 is not None:
        add("50 day average above the 200 day", 1.5 if s50 > s200 else 0.0, 1.5,
            f"50 DMA {s50:,.2f} against 200 DMA {s200:,.2f}")
    else:
        add("50 day average above the 200 day", 0.0, 1.5, "Insufficient history")

    if price is not None and s50 is not None:
        add("Price above the 50 day average", 1.0 if price > s50 else 0.0, 1.0,
            f"Price {price:,.2f} against 50 DMA {s50:,.2f}")
    else:
        add("Price above the 50 day average", 0.0, 1.0, "Insufficient history")

    if read.macd_line is not None and read.macd_signal is not None:
        add("MACD above its signal line", 1.0 if read.macd_line > read.macd_signal else 0.0, 1.0,
            f"MACD {read.macd_line:,.2f} against signal {read.macd_signal:,.2f}")
    else:
        add("MACD above its signal line", 0.0, 1.0, "Insufficient history")

    if read.rsi14 is not None:
        r = read.rsi14
        if 45 <= r <= 70:
            earned, detail = 1.5, f"RSI {r:.1f} sits in the constructive band"
        elif 40 <= r < 45 or 70 < r <= 75:
            earned, detail = 0.75, f"RSI {r:.1f} is at the edge of the constructive band"
        elif r > 75:
            earned, detail = 0.0, f"RSI {r:.1f} is overbought"
        else:
            earned, detail = 0.0, f"RSI {r:.1f} is weak"
        add("RSI in a constructive band", earned, 1.5, detail)
    else:
        add("RSI in a constructive band", 0.0, 1.5, "Insufficient history")

    if read.relative_strength_6m is not None:
        rs = read.relative_strength_6m
        add("Outperforming the Nifty over six months", 1.5 if rs > 0 else 0.0, 1.5,
            f"Six month relative return {rs * 100:+.1f}%")
    else:
        add("Outperforming the Nifty over six months", 0.0, 1.5, "Benchmark history unavailable")

    if read.volume_ratio is not None:
        add("Volume confirming the move", 1.0 if read.volume_ratio >= 1.0 else 0.0, 1.0,
            f"Latest volume is {read.volume_ratio:.2f}x the 20 day average")
    else:
        add("Volume confirming the move", 0.0, 1.0, "Volume unavailable")

    if read.range_position is not None:
        add("Upper half of the 52 week range", 1.0 if read.range_position >= 0.5 else 0.0, 1.0,
            f"Sits at {read.range_position * 100:.0f}% of the 52 week range")
    else:
        add("Upper half of the 52 week range", 0.0, 1.0, "Insufficient history")

    return lines
