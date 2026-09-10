"""The analysis pipeline.

Fetches free data for one ticker and produces everything the scoring workbench
needs. It stops short of the decision itself, because the decision requires the
analyst's seven raw scores.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import yfinance as yf

from app.core import drafts, forensics, metrics, sectors, technical, valuation
from app.providers import yahoo
from app.report import charts as chart_maker

DEFAULT_GROWTH_FADE = (0.12, 0.10, 0.09, 0.08, 0.07)


@dataclass
class Analysis:
    ticker: str
    generated_at: dt.datetime
    company: dict[str, Any]
    core_table: metrics.CoreTable
    quarterly: list[metrics.QuarterRow]
    forensics: forensics.ForensicReport
    technical: technical.TechnicalRead
    profile: sectors.SectorProfile
    relative: dict[str, Any]
    wacc: valuation.WACC
    dcf: valuation.DCFResult | None
    sensitivity: dict[str, Any] | None
    scenarios: list[valuation.Scenario]
    valuation_flags: list[str]
    drafts: dict[str, drafts.DraftScore]
    charts: dict[str, str] = field(default_factory=dict)
    # Kept on the object for chart building, deliberately not serialised: once the
    # charts are drawn the raw series only bloats the stored report.
    price_series: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assumptions: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "generated_at": self.generated_at.isoformat(),
            "company": self.company,
            "core_table": {
                "rows": [r.as_dict() for r in self.core_table.rows],
                "cagr": self.core_table.cagr,
                "trend": self.core_table.trend,
                "years": self.core_table.years,
            },
            "quarterly": [q.__dict__ for q in self.quarterly],
            "forensics": self.forensics.as_dict(),
            "technical": self.technical.as_dict(),
            "profile": self.profile.as_dict(),
            "relative": self.relative,
            "wacc": self.wacc.as_dict(),
            "dcf": self.dcf.as_dict() if self.dcf else None,
            "sensitivity": self.sensitivity,
            "scenarios": [s.as_dict() for s in self.scenarios],
            "valuation_flags": self.valuation_flags,
            "drafts": {k: v.as_dict() for k, v in self.drafts.items()},
            "charts": self.charts,
            "warnings": self.warnings,
            "assumptions": self.assumptions,
        }


def _benchmark_history() -> pd.DataFrame | None:
    try:
        return yf.Ticker(technical.NIFTY_SYMBOL).history(period="2y", auto_adjust=False)
    except Exception:  # noqa: BLE001 - the benchmark is optional
        return None


def _price_series(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Weekly samples of close, both moving averages and volume.

    Sampled weekly rather than daily so the stored payload stays small while the
    five-year shape and both averages remain faithful. The averages are computed
    on the daily series first, then sampled.
    """
    if history is None or history.empty:
        return []

    close = history["Close"].astype(float)
    frame = pd.DataFrame(
        {
            "close": close,
            "sma50": technical.sma(close, 50),
            "sma200": technical.sma(close, 200),
            "volume": history["Volume"].astype(float),
        }
    )
    weekly = frame.resample("W").agg(
        {"close": "last", "sma50": "last", "sma200": "last", "volume": "sum"}
    ).dropna(subset=["close"])

    out: list[dict[str, Any]] = []
    for index, row in weekly.iterrows():
        out.append(
            {
                "date": index.date().isoformat(),
                "close": round(float(row["close"]), 2),
                "sma50": None if pd.isna(row["sma50"]) else round(float(row["sma50"]), 2),
                "sma200": None if pd.isna(row["sma200"]) else round(float(row["sma200"]), 2),
                "volume": None if pd.isna(row["volume"]) else float(row["volume"]),
            }
        )
    return out


def analyse(ticker: str, growth_rates: list[float] | None = None, name_hint: str | None = None) -> Analysis:
    data = yahoo.fetch(ticker, name_hint=name_hint)
    warnings = list(data.warnings)

    core = metrics.build_core_table(data.annual)
    quarters = metrics.build_quarterly_table(data.quarterly)
    profile = sectors.classify(data.sector, data.industry)
    forensic_report = forensics.analyse(core, lender=profile.suppress_ev_multiples)

    tech = technical.analyse(data.history, _benchmark_history())

    history_multiples = metrics.historical_multiples(data, core)
    latest = core.latest

    book_per_share = None
    if latest and latest.equity is not None and data.shares_outstanding:
        book_per_share = latest.equity / data.shares_outstanding

    relative = valuation.relative_valuation(
        price=data.price,
        eps=latest.eps if latest else None,
        book_per_share=book_per_share,
        median_pe=history_multiples.get("median_pe"),
        median_pb=history_multiples.get("median_pb"),
        trailing_pe=data.trailing_pe,
        price_to_book=data.price_to_book,
    )
    relative["history"] = history_multiples

    wacc = valuation.build_wacc(
        market_cap=data.market_cap,
        total_debt=latest.total_debt if latest else None,
        beta=data.beta,
    )

    fcf_yield = None
    if latest and latest.fcf is not None and data.market_cap:
        fcf_yield = latest.fcf / data.market_cap

    rates = growth_rates or list(DEFAULT_GROWTH_FADE)
    dcf_result: valuation.DCFResult | None = None
    sensitivity: dict[str, Any] | None = None

    if profile.suppress_ev_multiples:
        warnings.append(
            "Discounted cash flow is not applied to a lender. Valuation uses price to book "
            "against sustainable return on equity."
        )
    elif latest and latest.fcf is not None and latest.fcf > 0 and data.shares_outstanding:
        try:
            dcf_result = valuation.discounted_cash_flow(
                base_fcf=latest.fcf,
                growth_rates=rates,
                terminal_growth=valuation.DEFAULT_TERMINAL_GROWTH,
                wacc=wacc.value,
                net_debt=latest.net_debt or 0.0,
                shares_outstanding=data.shares_outstanding,
            )
            sensitivity = valuation.sensitivity_grid(
                base_fcf=latest.fcf,
                growth_rates=rates,
                net_debt=latest.net_debt or 0.0,
                shares_outstanding=data.shares_outstanding,
                wacc=wacc.value,
                terminal_growth=valuation.DEFAULT_TERMINAL_GROWTH,
            )
        except ValueError as exc:
            warnings.append(f"Discounted cash flow not computed: {exc}")
    else:
        warnings.append(
            "Discounted cash flow needs positive latest free cash flow and a share count; "
            "one of those is missing, so scenarios rest on multiples."
        )

    scenarios = _build_scenarios(latest, relative, dcf_result, history_multiples)

    flags = valuation.valuation_flags(
        dcf=dcf_result,
        growth_rates=rates,
        historical_growth=core.cagr.get("revenue"),
        latest_fcf=latest.fcf if latest else None,
        net_debt_included=True,
    )

    price_series = _price_series(data.history)
    core_rows = [r.as_dict() for r in core.rows]
    lender = profile.suppress_ev_multiples
    multiple_points = history_multiples.get("pb" if lender else "pe") or []
    multiple_median = history_multiples.get("median_pb" if lender else "median_pe")

    built_charts = {
        "price": chart_maker.price_chart(price_series),
        "revenue_profit": chart_maker.revenue_profit_chart(core_rows),
        "returns": chart_maker.returns_chart(core_rows, lender=lender),
        "multiple": chart_maker.multiple_history_chart(
            multiple_points,
            multiple_median,
            "Price to book" if lender else "Price to earnings",
        ),
    }

    draft_scores = drafts.draft_all(
        table=core,
        quarters=quarters,
        forensics=forensic_report,
        relative=relative,
        profile=profile,
        fcf_yield=fcf_yield,
        beta=data.beta,
    )

    return Analysis(
        ticker=data.ticker,
        generated_at=dt.datetime.now(),
        company={
            "name": data.name,
            "ticker": data.ticker,
            "yahoo_symbol": data.yahoo_symbol,
            "sector": data.sector,
            "industry": data.industry,
            "currency": data.currency,
            "exchange": data.exchange,
            "price": data.price,
            "market_cap": data.market_cap,
            "shares_outstanding": data.shares_outstanding,
            "enterprise_value": data.enterprise_value,
            "trailing_pe": data.trailing_pe,
            "forward_pe": data.forward_pe,
            "price_to_book": data.price_to_book,
            "dividend_yield": data.dividend_yield,
            "beta": data.beta,
            "week52_high": data.week52_high,
            "week52_low": data.week52_low,
            "book_per_share": book_per_share,
            "fcf_yield": fcf_yield,
            "source": yahoo.SOURCE,
            "fetched_at": data.fetched_at.isoformat(),
        },
        core_table=core,
        quarterly=quarters,
        forensics=forensic_report,
        technical=tech,
        profile=profile,
        relative=relative,
        wacc=wacc,
        dcf=dcf_result,
        sensitivity=sensitivity,
        scenarios=scenarios,
        valuation_flags=flags,
        drafts=draft_scores,
        charts=built_charts,
        price_series=price_series,
        warnings=warnings,
        assumptions={
            "risk_free": valuation.DEFAULT_RISK_FREE,
            "equity_risk_premium": valuation.DEFAULT_EQUITY_RISK_PREMIUM,
            "pretax_cost_of_debt": valuation.DEFAULT_PRETAX_COST_OF_DEBT,
            "tax_rate": valuation.DEFAULT_TAX_RATE,
            "terminal_growth": valuation.DEFAULT_TERMINAL_GROWTH,
            "growth_rates": rates,
            "margin_of_safety_thresholds": {
                "high": 0.25,
                "moderate": 0.10,
                "negative_above_premium": 0.10,
            },
            "note": (
                "These are model assumptions, not published figures. Review each one before "
                "relying on the valuation."
            ),
        },
    )


def _build_scenarios(
    latest: metrics.PeriodMetrics | None,
    relative: dict[str, Any],
    dcf_result: valuation.DCFResult | None,
    history_multiples: dict[str, Any],
) -> list[valuation.Scenario]:
    """Bear, base and bull, per framework 14 section 14.

    Probabilities are deliberately left unset. The framework forbids
    manufacturing them, so the analyst supplies them or the report omits
    expected value.
    """
    eps = latest.eps if latest else None
    median_pe = history_multiples.get("median_pe")
    scenarios: list[valuation.Scenario] = []

    if eps and median_pe:
        scenarios.append(
            valuation.scenario_from_multiple(
                "Bear", eps, median_pe * 0.75,
                "Earnings hold at the latest reported level and the multiple de-rates by a quarter.",
            )
        )
        scenarios.append(
            valuation.scenario_from_multiple(
                "Base", eps, median_pe,
                "Earnings hold and the shares revert to their own five-year median multiple.",
            )
        )
        scenarios.append(
            valuation.scenario_from_multiple(
                "Bull", eps, median_pe * 1.25,
                "Earnings hold and the multiple re-rates by a quarter on improving execution.",
            )
        )

    if dcf_result and dcf_result.value_per_share:
        scenarios.append(
            valuation.Scenario(
                name="Discounted cash flow",
                description="Five-year forecast with a Gordon terminal value at the stated cost of capital.",
                value_per_share=dcf_result.value_per_share,
                assumptions={
                    "wacc": dcf_result.wacc,
                    "terminal_growth": dcf_result.terminal_growth,
                    "terminal_share": dcf_result.terminal_share,
                },
            )
        )

    return scenarios
