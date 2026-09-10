"""Valuation.

Framework 03 requires a defensible range rather than a single number, every
assumption shown, and a list of standard traps checked. This module produces the
cost of capital, a discounted cash flow, a sensitivity grid, scenario values and
the valuation flags, and it labels all of it as model assumption rather than fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Defaults for Indian equities. These are starting points that the analyst is
# expected to review, not published figures, and the report prints them as
# model assumptions.
DEFAULT_RISK_FREE = 0.065        # Ten year government security yield
DEFAULT_EQUITY_RISK_PREMIUM = 0.06
DEFAULT_PRETAX_COST_OF_DEBT = 0.085
DEFAULT_TAX_RATE = 0.25
DEFAULT_TERMINAL_GROWTH = 0.04


@dataclass
class WACC:
    risk_free: float
    equity_risk_premium: float
    beta: float
    pretax_cost_of_debt: float
    tax_rate: float
    equity_weight: float
    debt_weight: float

    @property
    def cost_of_equity(self) -> float:
        return self.risk_free + self.beta * self.equity_risk_premium

    @property
    def after_tax_cost_of_debt(self) -> float:
        return self.pretax_cost_of_debt * (1 - self.tax_rate)

    @property
    def value(self) -> float:
        return self.equity_weight * self.cost_of_equity + self.debt_weight * self.after_tax_cost_of_debt

    def as_dict(self) -> dict:
        return {
            "risk_free": self.risk_free,
            "equity_risk_premium": self.equity_risk_premium,
            "beta": self.beta,
            "pretax_cost_of_debt": self.pretax_cost_of_debt,
            "tax_rate": self.tax_rate,
            "equity_weight": self.equity_weight,
            "debt_weight": self.debt_weight,
            "cost_of_equity": self.cost_of_equity,
            "after_tax_cost_of_debt": self.after_tax_cost_of_debt,
            "wacc": self.value,
        }


def build_wacc(
    market_cap: float | None,
    total_debt: float | None,
    beta: float | None,
    risk_free: float = DEFAULT_RISK_FREE,
    equity_risk_premium: float = DEFAULT_EQUITY_RISK_PREMIUM,
    pretax_cost_of_debt: float = DEFAULT_PRETAX_COST_OF_DEBT,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> WACC:
    """Framework 03 forbids a generic cost of capital, so every input is explicit."""
    equity = float(market_cap or 0)
    debt = float(total_debt or 0)
    total = equity + debt
    if total <= 0:
        equity_weight, debt_weight = 1.0, 0.0
    else:
        equity_weight, debt_weight = equity / total, debt / total

    # A beta close to zero produces a cost of equity below the risk-free rate,
    # which is not defensible for an equity claim. Floor it and say so.
    safe_beta = beta if beta and beta > 0.3 else 0.8

    return WACC(
        risk_free=risk_free,
        equity_risk_premium=equity_risk_premium,
        beta=safe_beta,
        pretax_cost_of_debt=pretax_cost_of_debt,
        tax_rate=tax_rate,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
    )


@dataclass
class DCFResult:
    projected_fcf: list[float]
    discounted_fcf: list[float]
    terminal_value: float
    discounted_terminal_value: float
    enterprise_value: float
    equity_value: float
    value_per_share: float | None
    terminal_share: float
    wacc: float
    terminal_growth: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def discounted_cash_flow(
    base_fcf: float,
    growth_rates: list[float],
    terminal_growth: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float | None,
) -> DCFResult:
    """A standard five-year forecast with a Gordon terminal value."""
    if wacc <= terminal_growth:
        raise ValueError(
            "The cost of capital must exceed terminal growth, otherwise the terminal value is infinite."
        )
    if base_fcf <= 0:
        raise ValueError("A discounted cash flow needs a positive starting free cash flow.")

    projected: list[float] = []
    value = base_fcf
    for rate in growth_rates:
        value = value * (1 + rate)
        projected.append(value)

    discounted = [f / (1 + wacc) ** (i + 1) for i, f in enumerate(projected)]
    terminal_value = projected[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    discounted_terminal = terminal_value / (1 + wacc) ** len(projected)

    enterprise_value = sum(discounted) + discounted_terminal
    equity_value = enterprise_value - net_debt
    per_share = equity_value / shares_outstanding if shares_outstanding else None

    return DCFResult(
        projected_fcf=projected,
        discounted_fcf=discounted,
        terminal_value=terminal_value,
        discounted_terminal_value=discounted_terminal,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=per_share,
        terminal_share=discounted_terminal / enterprise_value if enterprise_value else 0.0,
        wacc=wacc,
        terminal_growth=terminal_growth,
    )


def sensitivity_grid(
    base_fcf: float,
    growth_rates: list[float],
    net_debt: float,
    shares_outstanding: float | None,
    wacc: float,
    terminal_growth: float,
    step: float = 0.01,
) -> dict:
    """Framework 03 asks for cost of capital and terminal growth each moved by one point."""
    waccs = [round(wacc - step, 4), round(wacc, 4), round(wacc + step, 4)]
    growths = [round(terminal_growth - step, 4), round(terminal_growth, 4), round(terminal_growth + step, 4)]
    grid: list[list[float | None]] = []
    for w in waccs:
        row: list[float | None] = []
        for g in growths:
            try:
                row.append(
                    discounted_cash_flow(base_fcf, growth_rates, g, w, net_debt, shares_outstanding).value_per_share
                )
            except ValueError:
                row.append(None)
        grid.append(row)
    return {"wacc_axis": waccs, "terminal_growth_axis": growths, "values": grid}


@dataclass
class Scenario:
    name: str
    description: str
    value_per_share: float | None
    probability: float | None = None
    assumptions: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def scenario_from_multiple(
    name: str, earnings_per_share: float | None, exit_multiple: float | None, description: str,
    probability: float | None = None,
) -> Scenario:
    value = None
    if earnings_per_share is not None and exit_multiple is not None:
        value = earnings_per_share * exit_multiple
    return Scenario(
        name=name,
        description=description,
        value_per_share=value,
        probability=probability,
        assumptions={"eps": earnings_per_share, "exit_multiple": exit_multiple},
    )


VALUATION_FLAG_CHECKS = (
    "Multiple expansion assumed without fundamental support",
    "Terminal value dominating the discounted cash flow",
    "Growth assumptions above historical or industry evidence",
    "Margin assumptions inconsistent with competition",
    "Negative free cash flow masked by working capital assumptions",
    "Net debt or minority interest omitted",
    "Dilution or share-based compensation ignored",
    "Cyclical peak earnings used as sustainable earnings",
)


def valuation_flags(
    dcf: DCFResult | None,
    growth_rates: list[float],
    historical_growth: float | None,
    latest_fcf: float | None,
    net_debt_included: bool,
) -> list[str]:
    """Automatic checks against framework 03's list of valuation traps."""
    flags: list[str] = []

    if dcf is not None and dcf.terminal_share > 0.75:
        flags.append(
            f"Terminal value is {dcf.terminal_share * 100:.0f}% of enterprise value, so the "
            "valuation rests mainly on assumptions beyond the forecast period."
        )

    if growth_rates and historical_growth is not None:
        assumed = sum(growth_rates) / len(growth_rates)
        if assumed > historical_growth + 0.05:
            flags.append(
                f"Assumed growth of {assumed * 100:.1f}% exceeds the historical rate of "
                f"{historical_growth * 100:.1f}% by more than five points."
            )

    if latest_fcf is not None and latest_fcf < 0:
        flags.append("The latest reported free cash flow is negative, so the starting point is an estimate.")

    if not net_debt_included:
        flags.append("Net debt was not deducted from enterprise value.")

    return flags


def relative_valuation(
    price: float | None,
    eps: float | None,
    book_per_share: float | None,
    median_pe: float | None,
    median_pb: float | None,
    trailing_pe: float | None,
    price_to_book: float | None,
) -> dict:
    """Current multiples against the company's own history, per framework 03."""
    current_pe = trailing_pe
    if current_pe is None and price and eps and eps > 0:
        current_pe = price / eps
    current_pb = price_to_book
    if current_pb is None and price and book_per_share and book_per_share > 0:
        current_pb = price / book_per_share

    def implied(multiple: float | None, per_share: float | None) -> float | None:
        if multiple is None or per_share is None or per_share <= 0:
            return None
        return multiple * per_share

    def premium(current: float | None, median: float | None) -> float | None:
        if current is None or median is None or median <= 0:
            return None
        return current / median - 1

    return {
        "current_pe": current_pe,
        "median_pe": median_pe,
        "pe_premium": premium(current_pe, median_pe),
        "implied_price_at_median_pe": implied(median_pe, eps),
        "current_pb": current_pb,
        "median_pb": median_pb,
        "pb_premium": premium(current_pb, median_pb),
        "implied_price_at_median_pb": implied(median_pb, book_per_share),
    }
