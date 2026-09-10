"""Free fundamental and price data from Yahoo Finance via yfinance.

No API key, no account, no cost. Yahoo is scraped rather than contracted, so
this module is defensive: every field is optional, every lookup tries several
label spellings, and anything missing is reported as missing rather than
guessed.

Observed coverage for NSE tickers, verified 2026-09-10:
  - Five years of annual income statement, balance sheet and cash flow.
  - Four or five recent quarters of the income statement, sometimes with a gap.
  - No quarterly cash flow at all.
  - Daily price history going back years.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import requests
import yfinance as yf

from app.net import configure_trust
from app.providers.base import Basis, Kind, Sourced

configure_trust()

SOURCE = "Yahoo Finance"

# Yahoo's row labels drift, so each canonical field lists the spellings seen.
INCOME_FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "gross_profit": ("Gross Profit",),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "ebit": ("EBIT", "Operating Income"),
    "operating_income": ("Operating Income",),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
    "pretax_income": ("Pretax Income",),
    "tax_provision": ("Tax Provision",),
    "pat": ("Net Income Common Stockholders", "Net Income", "Net Income Including Noncontrolling Interests"),
    "unusual_items": ("Total Unusual Items", "Total Unusual Items Excluding Goodwill"),
    "eps_basic": ("Basic EPS",),
    "eps_diluted": ("Diluted EPS",),
    "shares_diluted": ("Diluted Average Shares", "Basic Average Shares"),
    "total_expenses": ("Total Expenses",),
}

BALANCE_FIELDS: dict[str, tuple[str, ...]] = {
    "total_assets": ("Total Assets",),
    "equity": ("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"),
    "total_debt": ("Total Debt",),
    "net_debt": ("Net Debt",),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "End Cash Position"),
    "working_capital": ("Working Capital",),
    "invested_capital": ("Invested Capital",),
    "current_liabilities": ("Current Liabilities",),
    "current_assets": ("Current Assets",),
    "inventory": ("Inventory",),
    "receivables": ("Accounts Receivable", "Receivables"),
    "shares_outstanding": ("Ordinary Shares Number", "Share Issued"),
    "minority_interest": ("Minority Interest",),
    "tangible_book_value": ("Tangible Book Value",),
}

CASHFLOW_FIELDS: dict[str, tuple[str, ...]] = {
    "cfo": ("Operating Cash Flow",),
    "capex": ("Capital Expenditure", "Capital Expenditure Reported"),
    "fcf": ("Free Cash Flow",),
    "change_in_working_capital": ("Change In Working Capital",),
    "change_in_receivables": ("Change In Receivables",),
    "change_in_inventory": ("Change In Inventory",),
    "dividends_paid": ("Cash Dividends Paid",),
    "buyback": ("Repurchase Of Capital Stock",),
    "debt_issued": ("Issuance Of Debt", "Long Term Debt Issuance"),
    "debt_repaid": ("Repayment Of Debt", "Long Term Debt Payments"),
    "equity_issued": ("Issuance Of Capital Stock", "Common Stock Issuance"),
}


def _pick(frame: pd.DataFrame | None, aliases: tuple[str, ...], column: Any) -> float | None:
    if frame is None or frame.empty:
        return None
    for alias in aliases:
        if alias in frame.index:
            try:
                value = frame.loc[alias, column]
            except (KeyError, IndexError):
                continue
            if value is None or pd.isna(value):
                continue
            return float(value)
    return None


def _period_label(column: Any) -> str:
    if hasattr(column, "date"):
        return column.date().isoformat()
    return str(column)


def _as_date(column: Any) -> dt.date | None:
    if hasattr(column, "date"):
        return column.date()
    return None


@dataclass
class Period:
    """One reporting period, annual or quarterly."""

    label: str
    end_date: dt.date | None
    values: dict[str, float | None] = field(default_factory=dict)

    def get(self, name: str) -> float | None:
        return self.values.get(name)


@dataclass
class CompanyData:
    ticker: str
    yahoo_symbol: str
    name: str | None
    sector: str | None
    industry: str | None
    currency: str | None
    exchange: str | None
    price: float | None
    market_cap: float | None
    shares_outstanding: float | None
    enterprise_value: float | None
    trailing_pe: float | None
    forward_pe: float | None
    price_to_book: float | None
    dividend_yield: float | None
    beta: float | None
    week52_high: float | None
    week52_low: float | None
    annual: list[Period]
    quarterly: list[Period]
    history: pd.DataFrame
    fetched_at: dt.datetime
    warnings: list[str] = field(default_factory=list)

    def sourced(self, value: Any, kind: Kind = Kind.FACT, note: str | None = None) -> Sourced:
        return Sourced(
            value=value,
            source=SOURCE,
            as_of=self.fetched_at.date(),
            kind=kind,
            basis=Basis.CONSOLIDATED,
            note=note,
        )


def to_yahoo_symbol(ticker: str) -> str:
    """Accept RELIANCE, RELIANCE.NS or TCS.BO and return a Yahoo symbol."""
    t = ticker.strip().upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    return f"{t}.NS"


SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"

# Set when a search fails, so the interface can explain itself.
LAST_SEARCH_ERROR: str | None = None

# Yahoo's exchange codes for the two Indian exchanges, best listing first.
_EXCHANGE_RANK = {"NSI": 0, "BSE": 1}
_EXCHANGE_NAME = {"NSI": "NSE", "BSE": "BSE"}


def search(query: str, limit: int = 8) -> list[dict[str, str]]:
    """Find Indian listings whose name or symbol matches a search term.

    Foreign listings of the same company are dropped. An analyst working on
    Indian equities does not want the Frankfurt or New York line, and showing
    them would invite picking the wrong one.
    """
    global LAST_SEARCH_ERROR
    LAST_SEARCH_ERROR = None
    term = query.strip()
    if len(term) < 2:
        return []

    try:
        response = requests.get(
            SEARCH_URL,
            params={"q": term, "quotesCount": 25, "newsCount": 0, "enableFuzzyQuery": "false"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        response.raise_for_status()
        quotes = response.json().get("quotes", [])
    except Exception as exc:  # noqa: BLE001 - search must never crash the workbench
        # Recorded rather than swallowed. An empty result and a broken connection
        # look identical to the user otherwise, which makes a hosting problem
        # very hard to diagnose.
        LAST_SEARCH_ERROR = f"{type(exc).__name__}: {exc}"
        return []

    matches: list[dict[str, str]] = []
    for quote in quotes:
        exchange = quote.get("exchange")
        if exchange not in _EXCHANGE_RANK or quote.get("quoteType") != "EQUITY":
            continue
        symbol = quote.get("symbol", "")
        matches.append(
            {
                "symbol": symbol,
                "ticker": symbol.removesuffix(".NS").removesuffix(".BO"),
                "name": _title_case(quote.get("longname") or quote.get("shortname") or symbol),
                "exchange": _EXCHANGE_NAME[exchange],
                "rank": _EXCHANGE_RANK[exchange],
            }
        )

    # One row per company, preferring the NSE listing.
    best: dict[str, dict[str, str]] = {}
    for match in sorted(matches, key=lambda m: m["rank"]):
        best.setdefault(match["ticker"], match)

    ordered = sorted(best.values(), key=lambda m: (m["rank"], m["name"]))
    for match in ordered:
        match.pop("rank", None)
    return ordered[:limit]


def _title_case(name: str) -> str:
    """Yahoo shouts Indian company names. Make them readable without mangling initialisms."""
    keep_upper = {"NSE", "BSE", "IT", "IDFC", "HDFC", "ICICI", "SBI", "TCS", "ITC", "L&T",
                  "ONGC", "NTPC", "BPCL", "HPCL", "GAIL", "IOC", "LIC", "TVS", "MRF", "UPL"}
    words = []
    for word in name.replace(".", ". ").split():
        stripped = word.strip(".,")
        if stripped.upper() in keep_upper or (len(stripped) <= 3 and stripped.isupper()):
            words.append(word.upper())
        else:
            words.append(word.capitalize())
    return " ".join(words).replace(". ", ".").replace("Ltd", "Ltd").strip()


def _collect(frame: pd.DataFrame | None, fields: dict[str, tuple[str, ...]], limit: int) -> list[Period]:
    if frame is None or frame.empty:
        return []
    periods: list[Period] = []
    for column in list(frame.columns)[:limit]:
        values = {name: _pick(frame, aliases, column) for name, aliases in fields.items()}
        periods.append(Period(label=_period_label(column), end_date=_as_date(column), values=values))
    return periods


def _merge(primary: list[Period], *others: list[Period]) -> list[Period]:
    """Merge statements that share period labels into one period per label."""
    by_label: dict[str, Period] = {p.label: Period(p.label, p.end_date, dict(p.values)) for p in primary}
    order = [p.label for p in primary]
    for group in others:
        for p in group:
            if p.label in by_label:
                by_label[p.label].values.update(p.values)
            else:
                by_label[p.label] = Period(p.label, p.end_date, dict(p.values))
                order.append(p.label)
    return [by_label[label] for label in order]


def fetch(ticker: str, years: int = 5, quarters: int = 8) -> CompanyData:
    """Fetch everything free that Yahoo will give us for one ticker."""
    symbol = to_yahoo_symbol(ticker)
    t = yf.Ticker(symbol)
    warnings: list[str] = []

    try:
        info: dict[str, Any] = t.info or {}
    except Exception as exc:  # noqa: BLE001 - Yahoo is scraped, any failure is possible
        info = {}
        warnings.append(f"Company profile unavailable: {exc}")

    if not info.get("longName") and not info.get("shortName"):
        warnings.append("Yahoo returned no company profile; check the ticker symbol.")

    def frame(getter: str) -> pd.DataFrame | None:
        try:
            return getattr(t, getter)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{getter} unavailable: {exc}")
            return None

    annual = _merge(
        _collect(frame("income_stmt"), INCOME_FIELDS, years),
        _collect(frame("balance_sheet"), BALANCE_FIELDS, years),
        _collect(frame("cashflow"), CASHFLOW_FIELDS, years),
    )
    quarterly = _merge(
        _collect(frame("quarterly_income_stmt"), INCOME_FIELDS, quarters),
        _collect(frame("quarterly_balance_sheet"), BALANCE_FIELDS, quarters),
        _collect(frame("quarterly_cashflow"), CASHFLOW_FIELDS, quarters),
    )

    if len(annual) < 5:
        warnings.append(f"Only {len(annual)} annual periods available; the five-year table is incomplete.")
    if len(quarterly) < 8:
        warnings.append(
            f"Only {len(quarterly)} quarters available from the free source; framework 05 asks for eight."
        )
    if quarterly and all(p.get("cfo") is None for p in quarterly):
        warnings.append(
            "Quarterly cash flow is not published by the free source. Quarterly cash conversion "
            "must be entered manually or assessed annually."
        )

    try:
        history = t.history(period="5y", auto_adjust=False)
    except Exception as exc:  # noqa: BLE001
        history = pd.DataFrame()
        warnings.append(f"Price history unavailable: {exc}")
    if history.empty:
        warnings.append("No price history returned; the technical score cannot be computed.")

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if price is None and not history.empty:
        price = float(history["Close"].iloc[-1])

    return CompanyData(
        ticker=ticker.strip().upper().removesuffix(".NS").removesuffix(".BO"),
        yahoo_symbol=symbol,
        name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        currency=info.get("currency"),
        exchange=info.get("exchange"),
        price=price,
        market_cap=info.get("marketCap"),
        shares_outstanding=info.get("sharesOutstanding"),
        enterprise_value=info.get("enterpriseValue"),
        trailing_pe=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        price_to_book=info.get("priceToBook"),
        dividend_yield=info.get("dividendYield"),
        beta=info.get("beta"),
        week52_high=info.get("fiftyTwoWeekHigh"),
        week52_low=info.get("fiftyTwoWeekLow"),
        annual=annual,
        quarterly=quarterly,
        history=history,
        fetched_at=dt.datetime.now(),
        warnings=warnings,
    )
