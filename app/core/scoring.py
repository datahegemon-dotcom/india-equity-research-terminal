"""The V1.2 Standardized Investment Decision Engine.

This module is pure. It performs no input or output, touches no database and
makes no network call. It takes seven raw analyst judgement scores plus the
surrounding context, and returns a decision.

Every rule here maps onto a numbered section of framework 14. Section numbers
appear in the docstrings so the code can be audited against the source document.

One reconciliation was needed. Framework 14 section 11 uses AVOID as an outcome,
while the project instructions restrict the final action to six verbs that do not
include it. AVOID is kept here as the terminal "not investable" state, and the
report renders it as "AVOID (no position)".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

# --- Section 1: master 100-point score ---------------------------------------

CATEGORY_WEIGHTS: dict[str, int] = {
    "quality": 20,
    "growth": 20,
    "earnings": 15,
    "valuation": 20,
    "moat": 10,
    "catalysts": 5,
    "risk": 10,
}

CATEGORY_LABELS: dict[str, str] = {
    "quality": "Quality",
    "growth": "Growth",
    "earnings": "Earnings",
    "valuation": "Valuation",
    "moat": "Competitive Moat",
    "catalysts": "Catalysts",
    "risk": "Risk",
}


class Band(str, Enum):
    """Section 10. Starting classifications that overrides may change."""

    HIGH_CONVICTION = "HIGH CONVICTION"
    ATTRACTIVE = "ATTRACTIVE"
    WATCHLIST = "WATCHLIST"
    CAUTION = "CAUTION"
    AVOID = "AVOID"

    @classmethod
    def for_total(cls, total: float) -> "Band":
        if total >= 85:
            return cls.HIGH_CONVICTION
        if total >= 75:
            return cls.ATTRACTIVE
        if total >= 65:
            return cls.WATCHLIST
        if total >= 50:
            return cls.CAUTION
        return cls.AVOID


class Action(str, Enum):
    """Section 19 action matrix, plus the terminal AVOID state from section 11."""

    BUY = "BUY"
    ACCUMULATE = "ACCUMULATE"
    HOLD = "HOLD"
    WATCHLIST = "WATCHLIST"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    AVOID = "AVOID"


# Ordered most to least conviction. REDUCE and EXIT sit outside the ladder
# because they are positions on an existing holding, not degrees of enthusiasm.
CONVICTION_LADDER: tuple[Action, ...] = (
    Action.BUY,
    Action.ACCUMULATE,
    Action.HOLD,
    Action.WATCHLIST,
    Action.AVOID,
)


class MarginOfSafety(str, Enum):
    """Section 15."""

    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class OverrideRule(str, Enum):
    A_HIGH_QUALITY_LOW_MOS = "HIGH-QUALITY BUSINESS / LOW MARGIN OF SAFETY"
    B_CHEAP_BUT_WEAK = "CHEAP BUT FUNDAMENTALLY WEAK"
    C_EXTREME_VALUATION = "EXTREME VALUATION / MULTIPLE-COMPRESSION RISK"
    THESIS_BREAK = "THESIS BREAK"
    PORTFOLIO_CONCENTRATION = "PORTFOLIO CONCENTRATION"


class ExpectationGap(str, Enum):
    """Section 13."""

    TOO_LOW = "Expectations too low, positive asymmetric setup"
    REASONABLE = "Expectations reasonable, balanced"
    HIGH = "Expectations high, execution required"
    EXTREME = "Expectations extreme, high downside on disappointment"
    UNASSESSED = "Not assessed"


# --- Margin of safety thresholds ---------------------------------------------
# Framework 15 is qualitative, so these cut-offs are an explicit model assumption
# and are printed as such in every report.
MOS_HIGH_DISCOUNT = 0.25
MOS_MODERATE_DISCOUNT = 0.10
MOS_LOW_PREMIUM = -0.10


def classify_margin_of_safety(price: float, base_value: float) -> MarginOfSafety:
    """Section 15. Classify the current price against the base-case fair value."""
    if base_value <= 0:
        raise ValueError("Base-case fair value must be positive to classify margin of safety.")
    discount = (base_value - price) / base_value
    if discount >= MOS_HIGH_DISCOUNT:
        return MarginOfSafety.HIGH
    if discount >= MOS_MODERATE_DISCOUNT:
        return MarginOfSafety.MODERATE
    if discount >= MOS_LOW_PREMIUM:
        return MarginOfSafety.LOW
    return MarginOfSafety.NEGATIVE


def expected_value(scenarios: Mapping[str, tuple[float, float | None]]) -> float | None:
    """Sections 14 and 22.

    Returns None when any scenario lacks a defensible probability, because the
    framework forbids manufacturing them.
    """
    probabilities = [p for _, p in scenarios.values()]
    if any(p is None for p in probabilities):
        return None
    total_probability = sum(probabilities)  # type: ignore[arg-type]
    if abs(total_probability - 1.0) > 1e-6:
        raise ValueError(f"Scenario probabilities must sum to 1.0, got {total_probability}.")
    return sum(value * p for value, p in scenarios.values())  # type: ignore[operator]


@dataclass(frozen=True)
class RawScores:
    """The seven analyst judgement scores, each 1 to 10.

    Risk is scored in reverse: 10 is low risk, 1 is extreme risk (section 9).
    """

    quality: float
    growth: float
    earnings: float
    valuation: float
    moat: float
    catalysts: float
    risk: float

    def __post_init__(self) -> None:
        for name in CATEGORY_WEIGHTS:
            value = getattr(self, name)
            if not 1 <= value <= 10:
                raise ValueError(f"{name} score must be between 1 and 10, got {value}.")

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in CATEGORY_WEIGHTS}


@dataclass
class DecisionContext:
    """Everything outside the seven scores that the decision depends on."""

    margin_of_safety: MarginOfSafety = MarginOfSafety.UNKNOWN
    valuation_extreme: bool = False
    multiple_compression_note: str | None = None
    thesis_break: bool = False
    thesis_break_severe: bool = False
    thesis_break_reasons: list[str] = field(default_factory=list)
    severe_unresolved_risk: bool = False
    credible_turnaround_catalyst: bool = False
    asymmetry_justification: str | None = None
    portfolio_concentration_breach: bool = False
    expectation_gap: ExpectationGap = ExpectationGap.UNASSESSED
    technical_score: float | None = None

    def validate(self) -> None:
        if self.thesis_break and not self.thesis_break_reasons:
            raise ValueError("A thesis break must record at least one evidence-supported reason.")
        if self.technical_score is not None and not 1 <= self.technical_score <= 10:
            raise ValueError("Technical score must be between 1 and 10.")


@dataclass
class Decision:
    raw: dict[str, float]
    contributions: dict[str, float]
    total: float
    band: Band
    action: Action
    overrides: list[OverrideRule]
    labels: list[str]
    publish_blockers: list[str]
    margin_of_safety: MarginOfSafety
    technical_score: float | None

    @property
    def publishable(self) -> bool:
        return not self.publish_blockers


def _cap(current: Action, ceiling: Action) -> Action:
    """Return whichever of the two sits lower on the conviction ladder."""
    return max(current, ceiling, key=CONVICTION_LADDER.index)


def decide(raw: RawScores, ctx: DecisionContext) -> Decision:
    """Run the full engine and return the decision with its reasoning."""
    ctx.validate()

    contributions = {
        name: round(getattr(raw, name) / 10 * weight, 2)
        for name, weight in CATEGORY_WEIGHTS.items()
    }
    total = round(sum(contributions.values()), 2)
    band = Band.for_total(total)

    overrides: list[OverrideRule] = []
    labels: list[str] = []
    blockers: list[str] = []

    # Section 19: the band sets the starting action.
    action = {
        Band.HIGH_CONVICTION: Action.BUY,
        Band.ATTRACTIVE: Action.ACCUMULATE,
        Band.WATCHLIST: Action.HOLD,
        Band.CAUTION: Action.WATCHLIST,
        Band.AVOID: Action.AVOID,
    }[band]

    # Section 19 exception: a BUY below 85 needs a written asymmetry argument.
    if band is Band.ATTRACTIVE and ctx.asymmetry_justification:
        action = Action.BUY
        labels.append("BUY below 85 on stated asymmetry: " + ctx.asymmetry_justification)

    # Section 11 Rule A.
    if raw.quality >= 8 and raw.growth >= 8 and raw.moat >= 8 and raw.valuation <= 3:
        overrides.append(OverrideRule.A_HIGH_QUALITY_LOW_MOS)
        labels.append(OverrideRule.A_HIGH_QUALITY_LOW_MOS.value)
        action = _cap(action, Action.HOLD)

    # Section 11 Rule B.
    if raw.valuation >= 8 and raw.quality <= 4 and raw.earnings <= 4 and raw.risk <= 4:
        overrides.append(OverrideRule.B_CHEAP_BUT_WEAK)
        labels.append(OverrideRule.B_CHEAP_BUT_WEAK.value)
        ceiling = Action.WATCHLIST if ctx.credible_turnaround_catalyst else Action.AVOID
        action = _cap(action, ceiling)

    # Section 11 Rule C.
    if ctx.valuation_extreme:
        overrides.append(OverrideRule.C_EXTREME_VALUATION)
        if not ctx.multiple_compression_note:
            blockers.append(
                "Rule C: valuation flagged extreme, so a written multiple-compression "
                "note is required before publishing."
            )
        else:
            labels.append("Multiple-compression risk: " + ctx.multiple_compression_note)

    # Section 15 gates on the action matrix.
    if ctx.margin_of_safety is MarginOfSafety.NEGATIVE:
        action = _cap(action, Action.HOLD)
    elif ctx.margin_of_safety is MarginOfSafety.LOW:
        action = _cap(action, Action.ACCUMULATE)
    elif ctx.margin_of_safety is MarginOfSafety.UNKNOWN:
        action = _cap(action, Action.HOLD)
        blockers.append("Margin of safety is unclassified; a base-case fair value is required.")

    # Section 19: no BUY with a severe unresolved risk.
    if ctx.severe_unresolved_risk:
        action = _cap(action, Action.ACCUMULATE)
        labels.append("Severe unresolved risk blocks a BUY.")

    # Section 18: portfolio concentration can override standalone attractiveness.
    if ctx.portfolio_concentration_breach:
        overrides.append(OverrideRule.PORTFOLIO_CONCENTRATION)
        labels.append("Portfolio concentration breach overrides the standalone score.")
        action = Action.REDUCE

    # Section 12: a thesis break outranks everything above it.
    if ctx.thesis_break:
        overrides.append(OverrideRule.THESIS_BREAK)
        labels.append("Thesis break: " + "; ".join(ctx.thesis_break_reasons))
        action = Action.EXIT if ctx.thesis_break_severe else Action.REDUCE

    return Decision(
        raw=raw.as_dict(),
        contributions=contributions,
        total=total,
        band=band,
        action=action,
        overrides=overrides,
        labels=labels,
        publish_blockers=blockers,
        margin_of_safety=ctx.margin_of_safety,
        technical_score=ctx.technical_score,
    )
