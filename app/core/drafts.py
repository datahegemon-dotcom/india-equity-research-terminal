"""Draft raw scores.

These are suggestions, never conclusions. Each one starts from a neutral five,
moves on computed evidence, and reports every adjustment it made so the analyst
can see what drove the number and overrule it.

Framework 14 is emphatic that judgement belongs to the analyst. Two categories,
moat and catalysts, cannot be derived honestly from reported financials at all.
They are returned at a neutral value and marked as requiring analyst input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.forensics import ForensicReport
from app.core.metrics import CoreTable
from app.core.sectors import SectorProfile


@dataclass
class Adjustment:
    reason: str
    points: float
    evidence: str


@dataclass
class DraftScore:
    category: str
    score: float
    confidence: str
    adjustments: list[Adjustment] = field(default_factory=list)
    requires_analyst: bool = False
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "score": self.score,
            "confidence": self.confidence,
            "requires_analyst": self.requires_analyst,
            "note": self.note,
            "adjustments": [a.__dict__ for a in self.adjustments],
        }


class _Builder:
    def __init__(self, category: str, base: float = 5.0) -> None:
        self.category = category
        self.score = base
        self.adjustments: list[Adjustment] = []

    def add(self, reason: str, points: float, evidence: str) -> None:
        if points == 0:
            return
        self.score += points
        self.adjustments.append(Adjustment(reason, points, evidence))

    def build(self, confidence: str, requires_analyst: bool = False, note: str = "") -> DraftScore:
        return DraftScore(
            category=self.category,
            score=round(max(1.0, min(10.0, self.score)), 1),
            confidence=confidence,
            adjustments=self.adjustments,
            requires_analyst=requires_analyst,
            note=note,
        )


def _pct(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.1f}%"


def _x(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.2f}x"


def draft_quality(table: CoreTable, forensics: ForensicReport, profile: SectorProfile) -> DraftScore:
    b = _Builder("quality")
    latest = table.latest
    evidence_count = 0

    if latest and latest.roce is not None:
        evidence_count += 1
        roce = latest.roce
        if roce > 0.25:
            b.add("Exceptional return on capital", 2.0, f"ROCE {_pct(roce)}")
        elif roce > 0.18:
            b.add("Strong return on capital", 1.5, f"ROCE {_pct(roce)}")
        elif roce > 0.12:
            b.add("Adequate return on capital", 0.75, f"ROCE {_pct(roce)}")
        elif roce < 0.08:
            b.add("Return on capital below a plausible cost of capital", -1.5, f"ROCE {_pct(roce)}")

    if latest and latest.roe is not None:
        evidence_count += 1
        if latest.roe > 0.20:
            b.add("High return on equity", 0.75, f"ROE {_pct(latest.roe)}")
        elif latest.roe < 0.08:
            b.add("Low return on equity", -0.75, f"ROE {_pct(latest.roe)}")

    if forensics.cash_conversion is not None:
        evidence_count += 1
        c = forensics.cash_conversion
        if c >= 1.0:
            b.add("Profit converts fully into cash", 1.0, f"Cumulative cash conversion {c:.2f}x")
        elif c >= 0.8:
            b.add("Reasonable cash conversion", 0.5, f"Cumulative cash conversion {c:.2f}x")
        elif c < 0.6:
            b.add("Weak cash conversion", -1.5, f"Cumulative cash conversion {c:.2f}x")

    if latest and latest.net_debt_to_ebitda is not None and not profile.suppress_ev_multiples:
        evidence_count += 1
        nd = latest.net_debt_to_ebitda
        if nd <= 0:
            b.add("Net cash balance sheet", 1.0, f"Net debt to EBITDA {_x(nd)}")
        elif nd < 1:
            b.add("Low leverage", 0.5, f"Net debt to EBITDA {_x(nd)}")
        elif nd > 3:
            b.add("High leverage", -1.5, f"Net debt to EBITDA {_x(nd)}")

    if table.trend.get("ebitda_margin") == "consistently rising":
        b.add("Operating margin rising consistently", 0.5, "Five-year margin trend")
    elif table.trend.get("ebitda_margin") == "consistently falling":
        b.add("Operating margin falling consistently", -0.75, "Five-year margin trend")

    confidence = "moderate" if evidence_count >= 3 else "low"
    note = profile.note if profile.suppress_ev_multiples else ""
    return b.build(confidence, note=note)


def draft_growth(table: CoreTable) -> DraftScore:
    b = _Builder("growth")
    revenue_growth = table.cagr.get("revenue")
    pat_growth = table.cagr.get("pat")
    fcf_growth = table.cagr.get("fcf")
    evidence_count = 0

    if revenue_growth is not None:
        evidence_count += 1
        if revenue_growth > 0.20:
            b.add("Revenue compounding above twenty percent", 2.0, f"Revenue CAGR {_pct(revenue_growth)}")
        elif revenue_growth > 0.12:
            b.add("Revenue compounding at a healthy rate", 1.25, f"Revenue CAGR {_pct(revenue_growth)}")
        elif revenue_growth > 0.08:
            b.add("Moderate revenue growth", 0.5, f"Revenue CAGR {_pct(revenue_growth)}")
        elif revenue_growth < 0.03:
            b.add("Revenue barely growing", -1.5, f"Revenue CAGR {_pct(revenue_growth)}")

    if pat_growth is not None and revenue_growth is not None:
        evidence_count += 1
        if pat_growth > revenue_growth:
            b.add(
                "Profit growing faster than revenue, indicating operating leverage",
                0.75,
                f"Profit CAGR {_pct(pat_growth)} against revenue CAGR {_pct(revenue_growth)}",
            )
        elif pat_growth < revenue_growth - 0.05:
            b.add(
                "Profit lagging revenue, indicating margin pressure",
                -1.0,
                f"Profit CAGR {_pct(pat_growth)} against revenue CAGR {_pct(revenue_growth)}",
            )

    if fcf_growth is not None and fcf_growth > 0:
        evidence_count += 1
        b.add("Free cash flow growing alongside profit", 0.5, f"Free cash flow CAGR {_pct(fcf_growth)}")

    # Framework 14 section 4: growth funded by debt is lower quality growth.
    debt_series = [r.total_debt for r in table.rows if r.total_debt is not None]
    if len(debt_series) >= 2 and revenue_growth is not None and debt_series[0] > 0:
        debt_growth = (debt_series[-1] / debt_series[0]) ** (1 / max(len(debt_series) - 1, 1)) - 1
        if debt_growth > revenue_growth + 0.05:
            b.add(
                "Growth appears partly debt funded",
                -1.0,
                f"Debt CAGR {_pct(debt_growth)} against revenue CAGR {_pct(revenue_growth)}",
            )

    return b.build("moderate" if evidence_count >= 2 else "low")


def draft_earnings(table: CoreTable, quarters: list) -> DraftScore:
    b = _Builder("earnings")
    latest = table.latest
    evidence_count = 0

    margin_trend = table.trend.get("ebitda_margin", "")
    if margin_trend == "consistently rising":
        evidence_count += 1
        b.add("Margins expanding consistently", 1.5, "Five-year EBITDA margin trend")
    elif margin_trend == "consistently falling":
        evidence_count += 1
        b.add("Margins compressing consistently", -1.5, "Five-year EBITDA margin trend")
    elif margin_trend == "rising with volatility":
        evidence_count += 1
        b.add("Margins higher but uneven", 0.5, "Five-year EBITDA margin trend")

    pat_growth = table.cagr.get("pat")
    if pat_growth is not None:
        evidence_count += 1
        if pat_growth > 0.15:
            b.add("Earnings compounding strongly", 1.0, f"Profit CAGR {_pct(pat_growth)}")
        elif pat_growth < 0:
            b.add("Earnings declining over the period", -1.5, f"Profit CAGR {_pct(pat_growth)}")

    if latest and latest.cfo_to_pat is not None:
        evidence_count += 1
        if latest.cfo_to_pat >= 1.0:
            b.add("Latest year converts profit into cash in full", 1.0, f"Cash flow to profit {_x(latest.cfo_to_pat)}")
        elif latest.cfo_to_pat < 0.6:
            b.add("Latest year converts little profit into cash", -1.5, f"Cash flow to profit {_x(latest.cfo_to_pat)}")

    recent = [q for q in quarters if q.revenue_yoy is not None]
    if recent:
        evidence_count += 1
        latest_yoy = recent[-1].revenue_yoy
        if latest_yoy > 0.15:
            b.add("Most recent quarter growing strongly", 0.75, f"Revenue up {_pct(latest_yoy)} year on year")
        elif latest_yoy < 0:
            b.add("Most recent quarter shrinking", -1.0, f"Revenue down {_pct(abs(latest_yoy))} year on year")

    note = ""
    if not quarters:
        note = "No quarterly data was available from the free source, so momentum rests on annual figures alone."
    return b.build("moderate" if evidence_count >= 3 else "low", note=note)


def draft_valuation(relative: dict, fcf_yield: float | None, profile: SectorProfile) -> DraftScore:
    b = _Builder("valuation")
    evidence_count = 0

    key = "pb_premium" if profile.valuation_primary == "pb" else "pe_premium"
    label = "price to book" if profile.valuation_primary == "pb" else "price to earnings"
    premium = relative.get(key)

    if premium is not None:
        evidence_count += 1
        if premium <= -0.25:
            b.add(f"Trades well below its own median {label}", 2.5, f"{_pct(premium)} against the median")
        elif premium <= -0.10:
            b.add(f"Trades below its own median {label}", 1.5, f"{_pct(premium)} against the median")
        elif premium <= 0.10:
            b.add(f"Trades close to its own median {label}", 0.0, f"{_pct(premium)} against the median")
        elif premium <= 0.30:
            b.add(f"Trades above its own median {label}", -1.5, f"{_pct(premium)} against the median")
        else:
            b.add(f"Trades far above its own median {label}", -2.5, f"{_pct(premium)} against the median")

    if fcf_yield is not None and not profile.suppress_ev_multiples:
        evidence_count += 1
        if fcf_yield > 0.06:
            b.add("Attractive free cash flow yield", 1.5, f"Free cash flow yield {_pct(fcf_yield)}")
        elif fcf_yield > 0.04:
            b.add("Reasonable free cash flow yield", 0.75, f"Free cash flow yield {_pct(fcf_yield)}")
        elif fcf_yield < 0.01:
            b.add("Thin free cash flow yield", -1.0, f"Free cash flow yield {_pct(fcf_yield)}")

    note = (
        "Compared against the company's own history only. A peer comparison is still required."
        if evidence_count
        else "Insufficient data to propose a valuation score."
    )
    return b.build("moderate" if evidence_count >= 2 else "low", note=note)


def draft_moat(table: CoreTable, profile: SectorProfile) -> DraftScore:
    """Weak proxies only. Framework 06 requires judgement this cannot supply."""
    b = _Builder("moat")
    roce_series = [r.roce for r in table.rows if r.roce is not None]

    if len(roce_series) >= 3:
        if all(r > 0.18 for r in roce_series):
            b.add(
                "Return on capital stayed above eighteen percent every year",
                2.0,
                "Persistently high returns are consistent with a barrier to entry, though they do not prove one",
            )
        elif all(r > 0.12 for r in roce_series):
            b.add("Return on capital stayed in double digits every year", 1.0, "Persistent double-digit returns")
        elif roce_series[-1] < roce_series[0] * 0.7:
            b.add("Return on capital eroding", -1.5, "Falling returns can indicate a weakening moat")

    if table.trend.get("ebitda_margin") in ("consistently rising", "flat"):
        b.add("Margins stable or improving, consistent with pricing power", 0.5, "Five-year margin trend")

    return b.build(
        "low",
        requires_analyst=True,
        note=(
            "Financial statements can only hint at a moat. Framework 06 requires the analyst to "
            "assess brand, cost advantage, network effects, switching costs and scale directly, "
            "and to explain why competitors would struggle to take the economics away."
        ),
    )


def draft_catalysts() -> DraftScore:
    return DraftScore(
        category="catalysts",
        score=5.0,
        confidence="none",
        requires_analyst=True,
        note=(
            "Catalysts cannot be derived from reported financials. Framework 14 section 8 requires "
            "timing, direction, earnings impact, visibility, and what would confirm or invalidate "
            "each one. Enter them before publishing."
        ),
    )


def draft_risk(table: CoreTable, forensics: ForensicReport, relative: dict, beta: float | None) -> DraftScore:
    """Reversed scale: ten is low risk, one is extreme risk."""
    b = _Builder("risk", base=6.0)
    latest = table.latest

    if forensics.score >= 9:
        b.add("Severe forensic concern", -3.0, f"Red-flag score {forensics.score}")
    elif forensics.score >= 6:
        b.add("High forensic concern", -2.0, f"Red-flag score {forensics.score}")
    elif forensics.score >= 3:
        b.add("Moderate forensic concern", -1.0, f"Red-flag score {forensics.score}")
    else:
        b.add("Few forensic concerns", 1.0, f"Red-flag score {forensics.score}")

    if latest and latest.net_debt_to_ebitda is not None:
        if latest.net_debt_to_ebitda <= 0:
            b.add("Net cash reduces financial risk", 1.0, f"Net debt to EBITDA {_x(latest.net_debt_to_ebitda)}")
        elif latest.net_debt_to_ebitda > 3:
            b.add("Leverage raises financial risk", -1.5, f"Net debt to EBITDA {_x(latest.net_debt_to_ebitda)}")

    if latest and latest.interest_coverage is not None and latest.interest_coverage < 3:
        b.add("Thin interest cover", -1.0, f"Interest cover {_x(latest.interest_coverage)}")

    premium = relative.get("pe_premium")
    if premium is not None and premium > 0.30:
        b.add("Valuation risk from a large premium to its own history", -1.0, f"{_pct(premium)} above median")

    if beta is not None and beta > 1.3:
        b.add("Above-market volatility", -0.5, f"Beta {beta:.2f}")

    return b.build(
        "moderate",
        note=(
            "Covers financial and valuation risk only. Governance, regulatory, competitive, macro, "
            "currency and commodity risk require analyst assessment per framework 14 section 9."
        ),
    )


def draft_all(
    table: CoreTable,
    quarters: list,
    forensics: ForensicReport,
    relative: dict,
    profile: SectorProfile,
    fcf_yield: float | None,
    beta: float | None,
) -> dict[str, DraftScore]:
    return {
        "quality": draft_quality(table, forensics, profile),
        "growth": draft_growth(table),
        "earnings": draft_earnings(table, quarters),
        "valuation": draft_valuation(relative, fcf_yield, profile),
        "moat": draft_moat(table, profile),
        "catalysts": draft_catalysts(),
        "risk": draft_risk(table, forensics, relative, beta),
    }
