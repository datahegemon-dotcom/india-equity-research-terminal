"""Derived financial metrics.

Framework 04 asks for a five-year core table plus trend direction. Everything
here is computed from the reported statements. Where an input is missing the
output is None, never a substituted guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from typing import Iterable, Sequence

from app.providers.yahoo import CompanyData, Period


def _div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _abs_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / abs(denominator)


def cagr(series: Sequence[float | None], years: int | None = None) -> float | None:
    """Compound annual growth rate across a chronological series.

    Returns None when either endpoint is missing or non-positive, because a
    growth rate spanning a sign change is meaningless rather than merely large.
    """
    clean = [v for v in series if v is not None]
    if len(clean) < 2:
        return None
    first, last = clean[0], clean[-1]
    if first <= 0 or last <= 0:
        return None
    periods = (years if years is not None else len(clean) - 1)
    if periods <= 0:
        return None
    return (last / first) ** (1 / periods) - 1


def trend(series: Sequence[float | None]) -> str:
    """Describe the direction of a series in words."""
    clean = [v for v in series if v is not None]
    if len(clean) < 2:
        return "insufficient data"
    rises = sum(1 for a, b in zip(clean, clean[1:]) if b > a)
    falls = sum(1 for a, b in zip(clean, clean[1:]) if b < a)
    if rises and not falls:
        return "consistently rising"
    if falls and not rises:
        return "consistently falling"
    if clean[-1] > clean[0]:
        return "rising with volatility"
    if clean[-1] < clean[0]:
        return "falling with volatility"
    return "flat"


@dataclass
class PeriodMetrics:
    label: str
    revenue: float | None
    ebitda: float | None
    ebitda_margin: float | None
    ebit: float | None
    ebit_margin: float | None
    pat: float | None
    pat_margin: float | None
    eps: float | None
    cfo: float | None
    capex: float | None
    fcf: float | None
    equity: float | None
    total_debt: float | None
    net_debt: float | None
    total_assets: float | None
    roe: float | None
    roa: float | None
    roce: float | None
    net_debt_to_ebitda: float | None
    interest_coverage: float | None
    cfo_to_pat: float | None
    working_capital: float | None
    effective_tax_rate: float | None
    unusual_items: float | None

    def as_dict(self) -> dict[str, float | str | None]:
        return self.__dict__.copy()


def _period_metrics(p: Period) -> PeriodMetrics:
    revenue = p.get("revenue")
    ebitda = p.get("ebitda")
    ebit = p.get("ebit") or p.get("operating_income")
    pat = p.get("pat")
    cfo = p.get("cfo")
    capex = p.get("capex")
    fcf = p.get("fcf")
    if fcf is None and cfo is not None and capex is not None:
        # Yahoo reports capex as a negative number.
        fcf = cfo + capex
    equity = p.get("equity")
    total_debt = p.get("total_debt")
    net_debt = p.get("net_debt")
    if net_debt is None and total_debt is not None and p.get("cash") is not None:
        net_debt = total_debt - (p.get("cash") or 0)

    invested_capital = p.get("invested_capital")
    if invested_capital is None and equity is not None and total_debt is not None:
        invested_capital = equity + total_debt

    return PeriodMetrics(
        label=p.label,
        revenue=revenue,
        ebitda=ebitda,
        ebitda_margin=_div(ebitda, revenue),
        ebit=ebit,
        ebit_margin=_div(ebit, revenue),
        pat=pat,
        pat_margin=_div(pat, revenue),
        eps=p.get("eps_diluted") or p.get("eps_basic"),
        cfo=cfo,
        capex=capex,
        fcf=fcf,
        equity=equity,
        total_debt=total_debt,
        net_debt=net_debt,
        total_assets=p.get("total_assets"),
        roe=_div(pat, equity),
        roa=_div(pat, p.get("total_assets")),
        roce=_div(ebit, invested_capital),
        net_debt_to_ebitda=_div(net_debt, ebitda),
        interest_coverage=_abs_div(ebit, p.get("interest_expense")),
        cfo_to_pat=_div(cfo, pat),
        working_capital=p.get("working_capital"),
        effective_tax_rate=_div(p.get("tax_provision"), p.get("pretax_income")),
        unusual_items=p.get("unusual_items"),
    )


def chronological(periods: Iterable[Period]) -> list[Period]:
    """Yahoo returns newest first. Analysis reads oldest first."""
    return list(reversed(list(periods)))


@dataclass
class CoreTable:
    """The five-year core table of framework 04, plus growth and trend."""

    rows: list[PeriodMetrics]
    cagr: dict[str, float | None]
    trend: dict[str, str]
    years: int

    @property
    def latest(self) -> PeriodMetrics | None:
        return self.rows[-1] if self.rows else None

    def series(self, name: str) -> list[float | None]:
        return [getattr(r, name) for r in self.rows]


CAGR_FIELDS = ("revenue", "ebitda", "ebit", "pat", "eps", "cfo", "fcf")
TREND_FIELDS = ("ebitda_margin", "pat_margin", "roe", "roa", "roce", "net_debt", "cfo_to_pat", "interest_coverage")


def build_core_table(periods: Iterable[Period]) -> CoreTable:
    """Build the table, discarding periods the source returned empty.

    Yahoo frequently includes an oldest column with every value blank. Keeping it
    would understate growth rates and print an empty row in the report.
    """
    rows = [_period_metrics(p) for p in chronological(periods)]
    rows = [r for r in rows if r.revenue is not None or r.pat is not None]
    return CoreTable(
        rows=rows,
        cagr={f: cagr([getattr(r, f) for r in rows]) for f in CAGR_FIELDS},
        trend={f: trend([getattr(r, f) for r in rows]) for f in TREND_FIELDS},
        years=max(len(rows) - 1, 0),
    )


@dataclass
class QuarterRow:
    label: str
    revenue: float | None
    revenue_yoy: float | None
    revenue_qoq: float | None
    ebitda: float | None
    ebitda_margin: float | None
    pat: float | None
    pat_yoy: float | None
    eps: float | None


def build_quarterly_table(periods: Iterable[Period]) -> list[QuarterRow]:
    """Framework 05 asks for up to eight quarters with year and quarter comparisons.

    The free source is often incomplete and sometimes skips a quarter, so
    comparisons are computed by matching labels rather than by counting back a
    fixed number of rows.
    """
    ordered = chronological(periods)
    by_label = {p.label: p for p in ordered}
    rows: list[QuarterRow] = []

    for index, p in enumerate(ordered):
        revenue = p.get("revenue")
        pat = p.get("pat")
        ebitda = p.get("ebitda")

        prior_quarter = ordered[index - 1] if index > 0 else None
        year_ago_label = _shift_year(p.label)
        year_ago = by_label.get(year_ago_label)

        rows.append(
            QuarterRow(
                label=p.label,
                revenue=revenue,
                revenue_yoy=_growth(revenue, year_ago.get("revenue") if year_ago else None),
                revenue_qoq=_growth(revenue, prior_quarter.get("revenue") if prior_quarter else None),
                ebitda=ebitda,
                ebitda_margin=_div(ebitda, revenue),
                pat=pat,
                pat_yoy=_growth(pat, year_ago.get("pat") if year_ago else None),
                eps=p.get("eps_diluted") or p.get("eps_basic"),
            )
        )
    return rows


def _shift_year(label: str) -> str:
    try:
        year, rest = label.split("-", 1)
        return f"{int(year) - 1}-{rest}"
    except (ValueError, AttributeError):
        return ""


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior <= 0:
        return None
    return current / prior - 1


def historical_multiples(data: CompanyData, table: CoreTable) -> dict[str, object]:
    """Price-to-earnings and price-to-book at each past year end.

    Framework 03 wants the current multiple compared with the company's own
    history, not only with peers. The share price on each fiscal year-end date
    is taken from the price history, so the comparison uses the company's own
    reported earnings rather than a third party's estimate.
    """
    if data.history is None or data.history.empty:
        return {"pe": [], "pb": [], "median_pe": None, "median_pb": None}

    closes = data.history["Close"]
    pe_points: list[dict[str, object]] = []
    pb_points: list[dict[str, object]] = []

    for row in table.rows:
        price = _price_on(closes, row.label)
        if price is None:
            continue
        if row.eps and row.eps > 0:
            pe_points.append({"period": row.label, "price": price, "value": price / row.eps})
        book_per_share = _book_per_share(row, data)
        if book_per_share and book_per_share > 0:
            pb_points.append({"period": row.label, "price": price, "value": price / book_per_share})

    return {
        "pe": pe_points,
        "pb": pb_points,
        "median_pe": _median([p["value"] for p in pe_points]),
        "median_pb": _median([p["value"] for p in pb_points]),
    }


def _book_per_share(row: PeriodMetrics, data: CompanyData) -> float | None:
    if row.equity is None or not data.shares_outstanding:
        return None
    return row.equity / data.shares_outstanding


def _price_on(closes, label: str) -> float | None:
    try:
        target = _date.fromisoformat(label)
    except (ValueError, TypeError):
        return None
    for series_date, value in zip(closes.index, closes.values):
        if series_date.date() >= target:
            return float(value)
    return None


def _median(values: list) -> float | None:
    nums = sorted(float(v) for v in values if v is not None)
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2
