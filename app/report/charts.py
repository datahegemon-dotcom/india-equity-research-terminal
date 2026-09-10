"""Charts, drawn as plain SVG.

No charting library and no content delivery network. The published pages must
load instantly, print correctly and work offline, and the workbench must not
depend on a build step. Hand-written SVG satisfies all three.

Every chart uses CSS custom properties for colour, so the same markup reads
correctly on the dark workbench and the light report page.

The chart set follows what the better equity sites put in front of an analyst:
price against its own moving averages, revenue and profit bars with a margin
line over them, return ratios, the valuation multiple against its own history,
and the scenario range against today's price.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Number = float | int | None


def _clean(values: Iterable[Number]) -> list[float]:
    return [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]


def _bounds(*series: Sequence[Number], pad: float = 0.06) -> tuple[float, float]:
    pool: list[float] = []
    for s in series:
        pool.extend(_clean(s))
    if not pool:
        return 0.0, 1.0
    low, high = min(pool), max(pool)
    if low == high:
        return low - 1, high + 1
    span = high - low
    return low - span * pad, high + span * pad


def _escape(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _compact(value: float) -> str:
    """Indian readers think in crore and lakh crore."""
    crore = value / 1e7
    if abs(crore) >= 100000:
        return f"{crore / 100000:,.1f}L cr"
    if abs(crore) >= 1000:
        return f"{crore:,.0f} cr"
    return f"{crore:,.1f} cr"


def _path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def _empty(message: str, height: int = 200) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 600 {height}" preserveAspectRatio="xMidYMid meet" role="img">'
        f'<text x="300" y="{height // 2}" text-anchor="middle" class="chart__empty">{_escape(message)}</text>'
        "</svg>"
    )


# ----------------------------------------------------------------- price chart

def price_chart(series: list[dict], width: int = 900, height: int = 300) -> str:
    """Close price with its 50 and 200 day averages, and volume beneath."""
    if not series or len(series) < 10:
        return _empty("Not enough price history to draw a chart.")

    left, right, top = 8, 64, 12
    price_h = int(height * 0.72)
    volume_h = height - price_h - 34
    plot_w = width - left - right

    closes = [p.get("close") for p in series]
    sma50 = [p.get("sma50") for p in series]
    sma200 = [p.get("sma200") for p in series]
    volumes = [p.get("volume") or 0 for p in series]

    low, high = _bounds(closes, sma50, sma200)
    n = len(series)

    def x_at(i: int) -> float:
        return left + (i / max(n - 1, 1)) * plot_w

    def y_at(value: float) -> float:
        return top + (1 - (value - low) / (high - low)) * (price_h - top)

    def line(values: list[Number]) -> str:
        return _path([(x_at(i), y_at(float(v))) for i, v in enumerate(values) if v is not None])

    area_points = [(x_at(i), y_at(float(v))) for i, v in enumerate(closes) if v is not None]
    area = ""
    if area_points:
        area = (
            f'<path class="chart__area" d="{_path(area_points)} '
            f'L {area_points[-1][0]:.1f},{price_h} L {area_points[0][0]:.1f},{price_h} Z"/>'
        )

    # Horizontal guides at the extremes and the midpoint.
    guides = []
    for value in (high, (high + low) / 2, low):
        y = y_at(value)
        guides.append(f'<line class="chart__grid" x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}"/>')
        guides.append(
            f'<text class="chart__axis" x="{left + plot_w + 6}" y="{y + 3.5:.1f}">{value:,.0f}</text>'
        )

    max_volume = max(volumes) or 1
    bar_w = max(plot_w / n * 0.7, 0.6)
    bars = []
    volume_top = price_h + 18
    for i, v in enumerate(volumes):
        h = (v / max_volume) * volume_h
        bars.append(
            f'<rect class="chart__vol" x="{x_at(i) - bar_w / 2:.1f}" y="{volume_top + volume_h - h:.1f}" '
            f'width="{bar_w:.1f}" height="{max(h, 0.5):.1f}"/>'
        )

    # Date labels at the ends and the middle.
    labels = []
    for i in (0, n // 2, n - 1):
        date = series[i].get("date", "")
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        labels.append(
            f'<text class="chart__axis" x="{x_at(i):.1f}" y="{height - 4}" text-anchor="{anchor}">'
            f'{_escape(str(date)[:7])}</text>'
        )

    last = next((float(c) for c in reversed(closes) if c is not None), None)
    marker = ""
    if last is not None:
        marker = (
            f'<circle class="chart__dot" cx="{x_at(n - 1):.1f}" cy="{y_at(last):.1f}" r="3.5"/>'
            f'<text class="chart__last" x="{left + plot_w + 6}" y="{y_at(last) + 3.5:.1f}">{last:,.0f}</text>'
        )

    legend = (
        '<g class="chart__legend" transform="translate(12, 20)">'
        '<text x="0" y="0">Close</text>'
        '<text x="46" y="0" class="chart__key50">50 day</text>'
        '<text x="104" y="0" class="chart__key200">200 day</text>'
        "</g>"
    )

    return f"""<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Share price with 50 and 200 day moving averages">
  {''.join(guides)}
  {area}
  <path class="chart__line" d="{line(closes)}"/>
  <path class="chart__line50" d="{line(sma50)}"/>
  <path class="chart__line200" d="{line(sma200)}"/>
  {marker}
  {''.join(bars)}
  {''.join(labels)}
  {legend}
</svg>"""


# ------------------------------------------------------- revenue, profit, margin

def revenue_profit_chart(rows: list[dict], width: int = 900, height: int = 260) -> str:
    """Revenue and profit as paired bars, with the operating margin as a line."""
    usable = [r for r in rows if r.get("revenue") is not None]
    if len(usable) < 2:
        return _empty("Not enough annual data to draw a chart.")

    left, right, top, bottom = 8, 58, 26, 30
    plot_w = width - left - right
    plot_h = height - top - bottom

    revenues = [r.get("revenue") for r in usable]
    profits = [r.get("pat") for r in usable]
    margins = [r.get("ebitda_margin") for r in usable]

    value_max = max(_clean(revenues) + _clean(profits) + [1])
    margin_low, margin_high = _bounds(margins, pad=0.35)
    n = len(usable)
    slot = plot_w / n
    bar_w = min(slot * 0.28, 34)

    def y_value(v: float) -> float:
        return top + (1 - v / value_max) * plot_h

    def y_margin(v: float) -> float:
        if margin_high == margin_low:
            return top + plot_h / 2
        return top + (1 - (v - margin_low) / (margin_high - margin_low)) * plot_h

    parts: list[str] = []
    for i, row in enumerate(usable):
        centre = left + slot * (i + 0.5)
        revenue, profit = row.get("revenue"), row.get("pat")
        if revenue is not None:
            y = y_value(float(revenue))
            parts.append(
                f'<rect class="chart__bar" x="{centre - bar_w - 2:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{top + plot_h - y:.1f}"><title>Revenue {_compact(float(revenue))}</title></rect>'
            )
        if profit is not None and profit > 0:
            y = y_value(float(profit))
            parts.append(
                f'<rect class="chart__bar2" x="{centre + 2:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{top + plot_h - y:.1f}"><title>Profit {_compact(float(profit))}</title></rect>'
            )
        parts.append(
            f'<text class="chart__axis" x="{centre:.1f}" y="{height - 10}" text-anchor="middle">'
            f'{_escape(str(row.get("label", ""))[:4])}</text>'
        )

    margin_points = [
        (left + slot * (i + 0.5), y_margin(float(m)))
        for i, m in enumerate(margins) if m is not None
    ]
    margin_line = f'<path class="chart__marginline" d="{_path(margin_points)}"/>' if len(margin_points) > 1 else ""
    margin_dots = "".join(
        f'<circle class="chart__margindot" cx="{x:.1f}" cy="{y:.1f}" r="3"/>' for x, y in margin_points
    )

    margin_labels = ""
    if margins and _clean(margins):
        last_margin = _clean(margins)[-1]
        margin_labels = (
            f'<text class="chart__axis" x="{width - right + 6}" y="{y_margin(last_margin) + 3.5:.1f}">'
            f'{last_margin * 100:.0f}%</text>'
        )

    legend = (
        '<g class="chart__legend" transform="translate(12, 14)">'
        '<text x="0" y="0">Revenue</text>'
        '<text x="62" y="0" class="chart__key2">Profit</text>'
        '<text x="112" y="0" class="chart__keymargin">Operating margin</text>'
        "</g>"
    )

    return f"""<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Revenue and profit by year with operating margin">
  <line class="chart__grid" x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}"/>
  {''.join(parts)}
  {margin_line}{margin_dots}{margin_labels}
  {legend}
</svg>"""


# ------------------------------------------------------------------ return ratios

def returns_chart(rows: list[dict], lender: bool = False, width: int = 900, height: int = 220) -> str:
    """Return on capital and return on equity across the reported years."""
    primary_key = "roa" if lender else "roce"
    primary_name = "Return on assets" if lender else "Return on capital"

    usable = [r for r in rows if r.get(primary_key) is not None or r.get("roe") is not None]
    if len(usable) < 2:
        return _empty("Not enough data to draw return ratios.")

    left, right, top, bottom = 8, 52, 26, 28
    plot_w = width - left - right
    plot_h = height - top - bottom

    primary = [r.get(primary_key) for r in usable]
    roe = [r.get("roe") for r in usable]
    low, high = _bounds(primary, roe, pad=0.2)
    low = min(low, 0.0)
    n = len(usable)

    def x_at(i: int) -> float:
        return left + (i / max(n - 1, 1)) * plot_w

    def y_at(v: float) -> float:
        return top + (1 - (v - low) / (high - low)) * plot_h

    def series(values: list[Number], klass: str) -> str:
        points = [(x_at(i), y_at(float(v))) for i, v in enumerate(values) if v is not None]
        if len(points) < 2:
            return ""
        dots = "".join(f'<circle class="{klass}dot" cx="{x:.1f}" cy="{y:.1f}" r="3"/>' for x, y in points)
        return f'<path class="{klass}" d="{_path(points)}"/>{dots}'

    zero = f'<line class="chart__grid" x1="{left}" y1="{y_at(0):.1f}" x2="{width - right}" y2="{y_at(0):.1f}"/>' if low <= 0 <= high else ""

    labels = "".join(
        f'<text class="chart__axis" x="{x_at(i):.1f}" y="{height - 8}" text-anchor="middle">'
        f'{_escape(str(r.get("label", ""))[:4])}</text>'
        for i, r in enumerate(usable)
    )

    end_labels = ""
    for values, klass in ((primary, "chart__line"), (roe, "chart__line50")):
        clean = _clean(values)
        if clean:
            end_labels += (
                f'<text class="chart__axis" x="{width - right + 6}" y="{y_at(clean[-1]) + 3.5:.1f}">'
                f'{clean[-1] * 100:.1f}%</text>'
            )

    legend = (
        '<g class="chart__legend" transform="translate(12, 14)">'
        f'<text x="0" y="0">{_escape(primary_name)}</text>'
        '<text x="122" y="0" class="chart__key50">Return on equity</text>'
        "</g>"
    )

    return f"""<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Return ratios by year">
  {zero}
  {series(primary, "chart__line")}
  {series(roe, "chart__line50")}
  {labels}{end_labels}
  {legend}
</svg>"""


# ------------------------------------------------------------ valuation history

def multiple_history_chart(points: list[dict], median: float | None, label: str,
                           width: int = 900, height: int = 200) -> str:
    """The valuation multiple at each year end against its own median."""
    usable = [p for p in points if p.get("value") is not None]
    if len(usable) < 2 or median is None:
        return _empty("Not enough history to compare the multiple.")

    left, right, top, bottom = 8, 52, 26, 28
    plot_w = width - left - right
    plot_h = height - top - bottom

    values = [p["value"] for p in usable]
    low, high = _bounds(values, [median], pad=0.18)
    n = len(usable)

    def x_at(i: int) -> float:
        return left + (i / max(n - 1, 1)) * plot_w

    def y_at(v: float) -> float:
        return top + (1 - (v - low) / (high - low)) * plot_h

    band_top, band_bottom = y_at(median * 1.15), y_at(median * 0.85)
    band = (
        f'<rect class="chart__band" x="{left}" y="{band_top:.1f}" width="{plot_w:.1f}" '
        f'height="{max(band_bottom - band_top, 1):.1f}"/>'
    )
    median_line = (
        f'<line class="chart__median" x1="{left}" y1="{y_at(median):.1f}" '
        f'x2="{width - right}" y2="{y_at(median):.1f}"/>'
        f'<text class="chart__axis" x="{width - right + 6}" y="{y_at(median) + 3.5:.1f}">{median:.1f}</text>'
    )

    pts = [(x_at(i), y_at(float(v))) for i, v in enumerate(values)]
    dots = "".join(
        f'<circle class="chart__dot" cx="{x:.1f}" cy="{y:.1f}" r="3.5"><title>{_escape(usable[i]["period"])}: '
        f'{float(values[i]):.1f}x</title></circle>' for i, (x, y) in enumerate(pts)
    )
    labels = "".join(
        f'<text class="chart__axis" x="{x_at(i):.1f}" y="{height - 8}" text-anchor="middle">'
        f'{_escape(str(p.get("period", ""))[:4])}</text>' for i, p in enumerate(usable)
    )

    return f"""<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="{_escape(label)} against its own median">
  {band}{median_line}
  <path class="chart__line" d="{_path(pts)}"/>{dots}
  {labels}
  <g class="chart__legend" transform="translate(12, 14)"><text x="0" y="0">{_escape(label)} at each year end</text></g>
</svg>"""


# --------------------------------------------------------------- scenario range

def scenario_chart(scenarios: list[dict], price: float | None,
                   width: int = 900, height: int = 150) -> str:
    """Where today's price sits inside the bear to bull range."""
    priced = [s for s in scenarios if s.get("value_per_share")]
    if not priced or not price:
        return _empty("Scenario values are needed to draw this.", height=120)

    values = [float(s["value_per_share"]) for s in priced] + [float(price)]
    low, high = min(values), max(values)
    span = (high - low) or 1
    low, high = low - span * 0.12, high + span * 0.12

    left, right = 60, 60
    plot_w = width - left - right
    axis_y = 74

    def x_at(v: float) -> float:
        return left + (v - low) / (high - low) * plot_w

    bear = min(float(s["value_per_share"]) for s in priced)
    bull = max(float(s["value_per_share"]) for s in priced)

    parts = [
        f'<line class="chart__axisline" x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}"/>',
        f'<rect class="chart__range" x="{x_at(bear):.1f}" y="{axis_y - 7}" '
        f'width="{max(x_at(bull) - x_at(bear), 1):.1f}" height="14"/>',
    ]

    for index, s in enumerate(priced):
        value = float(s["value_per_share"])
        x = x_at(value)
        above = index % 2 == 0
        label_y = axis_y - 22 if above else axis_y + 34
        name_y = axis_y - 34 if above else axis_y + 46
        parts.append(f'<line class="chart__tick" x1="{x:.1f}" y1="{axis_y - 12}" x2="{x:.1f}" y2="{axis_y + 12}"/>')
        parts.append(f'<text class="chart__value" x="{x:.1f}" y="{label_y}" text-anchor="middle">₹{value:,.0f}</text>')
        parts.append(f'<text class="chart__axis" x="{x:.1f}" y="{name_y}" text-anchor="middle">{_escape(s.get("name", ""))}</text>')

    px = x_at(float(price))
    parts.append(
        f'<line class="chart__now" x1="{px:.1f}" y1="{axis_y - 26}" x2="{px:.1f}" y2="{axis_y + 26}"/>'
        f'<text class="chart__nowlabel" x="{px:.1f}" y="{axis_y + 60}" text-anchor="middle">'
        f'Price today ₹{float(price):,.0f}</text>'
    )

    return f"""<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Scenario values against today's price">
  {''.join(parts)}
</svg>"""


# --------------------------------------------------------------------- sparkline

def sparkline(values: Sequence[Number], width: int = 88, height: int = 22) -> str:
    clean = _clean(values)
    if len(clean) < 2:
        return ""
    low, high = min(clean), max(clean)
    span = (high - low) or 1
    step = width / (len(clean) - 1)
    points = [(i * step, height - 2 - ((v - low) / span) * (height - 4)) for i, v in enumerate(clean)]
    rising = clean[-1] >= clean[0]
    klass = "spark--up" if rising else "spark--down"
    return (
        f'<svg class="spark {klass}" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'aria-hidden="true"><path d="{_path(points)}"/>'
        f'<circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="2"/></svg>'
    )
