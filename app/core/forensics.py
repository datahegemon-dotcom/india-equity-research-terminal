"""Financial quality and forensic checks.

Framework 04 asks whether reported accounting performance converts into durable
cash flow, and sets a red-flag score: 0 to 2 low concern, 3 to 5 moderate, 6 to
8 high, 9 or more severe.

The framework is explicit that a ratio alone never supports an accusation. Every
flag here therefore states the observation and the evidence, and the language is
descriptive rather than accusatory.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.metrics import CoreTable, cagr


@dataclass
class Flag:
    code: str
    title: str
    severity: int
    observation: str
    evidence: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ForensicReport:
    flags: list[Flag]
    score: int
    concern: str
    cash_conversion: float | None
    financial_strength: float | None
    cash_flow_quality: float | None

    def as_dict(self) -> dict:
        return {
            "flags": [f.as_dict() for f in self.flags],
            "score": self.score,
            "concern": self.concern,
            "cash_conversion": self.cash_conversion,
            "financial_strength": self.financial_strength,
            "cash_flow_quality": self.cash_flow_quality,
        }


def _concern(score: int) -> str:
    if score >= 9:
        return "severe"
    if score >= 6:
        return "high"
    if score >= 3:
        return "moderate"
    return "low"


def _pct(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.1f}%"


def _x(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.2f}x"


def analyse(table: CoreTable) -> ForensicReport:
    flags: list[Flag] = []
    rows = table.rows
    latest = table.latest

    cfo_series = [r.cfo for r in rows if r.cfo is not None]
    pat_series = [r.pat for r in rows if r.pat is not None]
    cumulative_conversion = None
    if cfo_series and pat_series and sum(pat_series) > 0:
        cumulative_conversion = sum(cfo_series) / sum(pat_series)

    # Earnings quality: profit that does not become cash.
    if cumulative_conversion is not None and cumulative_conversion < 0.8:
        flags.append(
            Flag(
                "cash_conversion",
                "Profit is not converting into operating cash",
                severity=2 if cumulative_conversion < 0.6 else 1,
                observation=(
                    "Cumulative operating cash flow over the period covers only "
                    f"{cumulative_conversion * 100:.0f}% of cumulative reported profit."
                ),
                evidence=f"Sum of operating cash flow against sum of profit across {len(rows)} periods.",
            )
        )

    pat_growth = cagr([r.pat for r in rows])
    cfo_growth = cagr([r.cfo for r in rows])
    if pat_growth is not None and cfo_growth is not None and pat_growth > 0.10 and cfo_growth < pat_growth / 2:
        flags.append(
            Flag(
                "pat_cfo_divergence",
                "Profit growing faster than operating cash flow",
                severity=2,
                observation=(
                    f"Profit compounded at {_pct(pat_growth)} while operating cash flow "
                    f"compounded at {_pct(cfo_growth)}."
                ),
                evidence="Compound growth of profit against operating cash flow over the reported years.",
            )
        )

    # Balance sheet.
    if latest and latest.net_debt_to_ebitda is not None and latest.net_debt_to_ebitda > 3:
        flags.append(
            Flag(
                "leverage",
                "Leverage above three times earnings before interest, tax, depreciation and amortisation",
                severity=2 if latest.net_debt_to_ebitda > 4 else 1,
                observation=f"Net debt stands at {_x(latest.net_debt_to_ebitda)} of EBITDA.",
                evidence=f"Latest reported period {latest.label}.",
            )
        )

    if latest and latest.interest_coverage is not None and latest.interest_coverage < 3:
        flags.append(
            Flag(
                "interest_cover",
                "Thin interest cover",
                severity=2 if latest.interest_coverage < 2 else 1,
                observation=f"Operating profit covers interest {_x(latest.interest_coverage)}.",
                evidence=f"Latest reported period {latest.label}.",
            )
        )

    # Free cash flow.
    negative_fcf_years = [r.label for r in rows if r.fcf is not None and r.fcf < 0]
    if len(negative_fcf_years) >= 2:
        flags.append(
            Flag(
                "negative_fcf",
                "Free cash flow negative in multiple years",
                severity=2 if len(negative_fcf_years) >= 3 else 1,
                observation=f"Free cash flow was negative in {len(negative_fcf_years)} of {len(rows)} years.",
                evidence="Years affected: " + ", ".join(negative_fcf_years),
            )
        )

    # Returns.
    roce_series = [r.roce for r in rows if r.roce is not None]
    if len(roce_series) >= 3 and roce_series[-1] < roce_series[0] * 0.7:
        flags.append(
            Flag(
                "roce_decline",
                "Return on capital has fallen materially",
                severity=2,
                observation=(
                    f"Return on capital employed moved from {_pct(roce_series[0])} to {_pct(roce_series[-1])}."
                ),
                evidence="First and last reported years in the table.",
            )
        )

    # Tax anomalies.
    tax_rates = [r.effective_tax_rate for r in rows if r.effective_tax_rate is not None]
    if tax_rates:
        odd = [t for t in tax_rates if t < 0.10 or t > 0.45]
        if odd:
            flags.append(
                Flag(
                    "tax_rate",
                    "Effective tax rate outside the usual range",
                    severity=1,
                    observation=(
                        "At least one year shows an effective tax rate of "
                        + ", ".join(_pct(t) for t in odd)
                        + ", which warrants reading the tax note."
                    ),
                    evidence="Tax provision against pre-tax income by year.",
                )
            )

    # Exceptional items.
    # Recorded on the raw periods rather than the derived table, so read defensively.
    unusual_years = [r.label for r in rows if getattr(r, "unusual_items", None)]
    if len(unusual_years) >= 3:
        flags.append(
            Flag(
                "exceptional_items",
                "Exceptional items recur",
                severity=1,
                observation=f"Unusual or exceptional items appear in {len(unusual_years)} of {len(rows)} years.",
                evidence="Items that recur every year are arguably operating in nature.",
            )
        )

    # Dilution.
    equity_series = [r.equity for r in rows if r.equity is not None]
    if len(equity_series) >= 2 and pat_growth is not None:
        equity_growth = cagr(equity_series)
        if equity_growth is not None and equity_growth > 0.15 and pat_growth < equity_growth / 2:
            flags.append(
                Flag(
                    "capital_efficiency",
                    "Equity base growing faster than profit",
                    severity=1,
                    observation=(
                        f"Shareholders' funds compounded at {_pct(equity_growth)} while profit "
                        f"compounded at {_pct(pat_growth)}, which dilutes return on equity."
                    ),
                    evidence="Compound growth of shareholders' funds against profit.",
                )
            )

    score = sum(f.severity for f in flags)

    return ForensicReport(
        flags=flags,
        score=score,
        concern=_concern(score),
        cash_conversion=cumulative_conversion,
        financial_strength=_strength_score(latest),
        cash_flow_quality=_cash_quality_score(cumulative_conversion),
    )


def _strength_score(latest) -> float | None:
    """A ten-point balance-sheet strength read, per framework 04's output block."""
    if latest is None:
        return None
    points = 5.0
    if latest.net_debt_to_ebitda is not None:
        if latest.net_debt_to_ebitda <= 0:
            points += 2.5
        elif latest.net_debt_to_ebitda < 1:
            points += 1.5
        elif latest.net_debt_to_ebitda < 2:
            points += 0.5
        elif latest.net_debt_to_ebitda > 3:
            points -= 1.5
    if latest.interest_coverage is not None:
        if latest.interest_coverage > 8:
            points += 2.0
        elif latest.interest_coverage > 4:
            points += 1.0
        elif latest.interest_coverage < 2:
            points -= 2.0
    return round(max(1.0, min(10.0, points)), 1)


def _cash_quality_score(conversion: float | None) -> float | None:
    if conversion is None:
        return None
    if conversion >= 1.2:
        return 9.0
    if conversion >= 1.0:
        return 8.0
    if conversion >= 0.85:
        return 7.0
    if conversion >= 0.7:
        return 5.5
    if conversion >= 0.5:
        return 4.0
    return 2.5
