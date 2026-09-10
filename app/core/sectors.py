"""Sector adapters.

Framework 14 section 16 keeps the weights identical across sectors but changes
the evidence used to score each category. Version one ships the generic adapter
and a banking adapter, because enterprise-value multiples are meaningless for a
lender and price to book against sustainable return on equity is not optional.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SectorProfile:
    key: str
    label: str
    valuation_primary: str
    suppress_ev_multiples: bool
    evidence: dict[str, list[str]] = field(default_factory=dict)
    note: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


GENERIC = SectorProfile(
    key="generic",
    label="Generic",
    valuation_primary="pe",
    suppress_ev_multiples=False,
    evidence={
        "quality": ["Return on capital employed", "Return on equity", "Cash conversion", "Balance-sheet strength"],
        "growth": ["Revenue growth", "EBITDA growth", "Earnings growth", "Growth funding mix"],
        "earnings": ["Margin trajectory", "Cash conversion", "Earnings consistency"],
        "valuation": ["Price to earnings against own history", "Free cash flow yield", "Discounted cash flow"],
        "moat": ["Pricing power", "Market position", "Entry barriers"],
        "catalysts": ["Orders", "Capacity", "Products", "Policy"],
        "risk": ["Leverage", "Interest cover", "Cash flow quality", "Valuation risk"],
    },
)

BANKING = SectorProfile(
    key="banking_nbfc",
    label="Banking and NBFC",
    valuation_primary="pb",
    suppress_ev_multiples=True,
    evidence={
        "quality": ["Return on assets", "Return on equity", "Underwriting quality", "Funding strength", "CASA"],
        "growth": ["Loan growth", "Deposit growth", "Assets under management growth"],
        "earnings": ["Net interest margin", "Credit cost", "Slippages", "Fee income", "Cost to income"],
        "valuation": ["Price to book against sustainable return on equity", "Residual income", "Price to earnings as a cross-check"],
        "moat": ["Deposit franchise", "Distribution", "Cost of funds advantage"],
        "catalysts": ["Rate cycle", "Credit cycle", "Regulation", "Capital raise"],
        "risk": ["Asset quality", "Liquidity", "Capital adequacy", "Regulatory risk"],
    },
    note=(
        "Enterprise value multiples and free cash flow are not meaningful for a lender. "
        "Valuation is driven by price to book against sustainable return on equity, and "
        "falling non-performing assets are not treated as improvement when write-offs or "
        "restructuring may be masking stress."
    ),
)

PROFILES = {p.key: p for p in (GENERIC, BANKING)}

_BANKING_SECTORS = {"financial services", "financials"}
_BANKING_INDUSTRIES = {
    "banks", "banks - regional", "banks - diversified", "banks—regional", "banks—diversified",
    "credit services", "mortgage finance", "financial conglomerates", "financial data & stock exchanges",
}
_NON_BANKING_INDUSTRIES = {"insurance", "asset management", "capital markets", "insurance - life"}


def classify(sector: str | None, industry: str | None) -> SectorProfile:
    """Pick the adapter from the sector and industry Yahoo reports."""
    s = (sector or "").strip().lower()
    i = (industry or "").strip().lower()

    if any(token in i for token in _NON_BANKING_INDUSTRIES):
        return GENERIC
    if i in _BANKING_INDUSTRIES or "bank" in i or "finance" in i or "lending" in i:
        return BANKING
    if s in _BANKING_SECTORS and ("bank" in i or "credit" in i or not i):
        return BANKING
    return GENERIC
