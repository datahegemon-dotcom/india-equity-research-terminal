"""Report rendering.

Builds the view model for a report and renders it to HTML. The same view model
serves the workbench preview and the published page, so what the analyst checks
is exactly what a reader sees.

The attribution and disclaimer of framework 14 section 32 are reproduced
verbatim and appear at the end of every rendered report.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.scoring import (
    AUDIT_QUESTIONS,
    CATEGORY_LABELS,
    CATEGORY_WEIGHTS,
    Action,
    DecisionContext,
    ExpectationGap,
    MarginOfSafety,
    RawScores,
    decide,
    expected_value,
)

TEMPLATES = Path(__file__).resolve().parent / "templates"
STATIC = Path(__file__).resolve().parent / "static"

ATTRIBUTION = {
    "name": "Nagaraj Balasubramaniam",
    "credentials": [
        "Alumnus, IIM Lucknow",
        "Certified Economic Journalist",
        "NISM Certified | NCFM Certified",
        "AMFI Registered Mutual Fund & SIF Distributor — ARN: 309850",
        "APMI Registered PMS Distributor — APRN Code: APRN07791",
        "Registered AP — Code: AP2513037631",
        "NSE Academy Certified Market Professional (NCMP)",
    ],
    "books": [
        "A Common Man's Voyage in the Stock Market",
        "The Behavioral Investor",
        "Mastering Options Trading",
    ],
}

DISCLAIMER = [
    "Disclaimer as per SEBI norms: Equity investments are subject to 100% market risks. "
    "Refer to your financial consultant's advice before investing.",
    "This group/channel/project is intended only for educational, learning and knowledge purposes.",
    "Admins have no responsibility for any intended decision or financial losses.",
    "Always assess your cash position, financial circumstances and risk-bearing capacity before "
    "acting on any information or analysis.",
    "We do not provide any buy, sell, or hold recommendations, either directly or indirectly.",
    "This channel does not offer stock tips, trading signals, or personalized investment advice.",
    "The research output is provided for educational and analytical purposes only and should not be "
    "interpreted as personalized investment advice, a solicitation to buy or sell securities, or a "
    "guarantee of future returns.",
    "Users should conduct their own due diligence and, where appropriate, consult a qualified "
    "financial professional before making investment decisions.",
]

POSITIVE_ACTIONS = {Action.BUY, Action.ACCUMULATE}
NEGATIVE_ACTIONS = {Action.REDUCE, Action.EXIT, Action.AVOID}


def tone_for(action: Action) -> str:
    if action in POSITIVE_ACTIONS:
        return "positive"
    if action in NEGATIVE_ACTIONS:
        return "negative"
    return "neutral"


# ------------------------------------------------------------------ filters

def rupees(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"₹{number:,.{decimals}f}"


def crores(value: Any) -> str:
    """Indian readers think in crore. One crore is ten million."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number / 1e7:,.0f}"


def percent(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def signed_percent(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:+.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def times(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f}x"
    except (TypeError, ValueError):
        return "—"


def number(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def long_date(value: Any) -> str:
    if not value:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return parsed.strftime("%d %B %Y")


def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        rupees=rupees,
        crores=crores,
        percent=percent,
        signed_percent=signed_percent,
        times=times,
        number=number,
        long_date=long_date,
    )
    return env


# --------------------------------------------------------------- view model

def _context_from_payload(payload: dict[str, Any]) -> DecisionContext:
    raw = payload.get("context", {})
    return DecisionContext(
        margin_of_safety=MarginOfSafety(raw.get("margin_of_safety", "UNKNOWN")),
        valuation_extreme=bool(raw.get("valuation_extreme")),
        multiple_compression_note=raw.get("multiple_compression_note") or None,
        thesis_break=bool(raw.get("thesis_break")),
        thesis_break_severe=bool(raw.get("thesis_break_severe")),
        thesis_break_reasons=[r for r in raw.get("thesis_break_reasons", []) if r],
        severe_unresolved_risk=bool(raw.get("severe_unresolved_risk")),
        credible_turnaround_catalyst=bool(raw.get("credible_turnaround_catalyst")),
        asymmetry_justification=raw.get("asymmetry_justification") or None,
        portfolio_concentration_breach=bool(raw.get("portfolio_concentration_breach")),
        expectation_gap=ExpectationGap(raw.get("expectation_gap", ExpectationGap.UNASSESSED.value)),
        technical_score=raw.get("technical_score"),
        audit={k: bool(v) for k, v in (raw.get("audit") or {}).items()},
    )


def build_view(record: dict[str, Any]) -> dict[str, Any]:
    """Turn a stored report into everything a template needs."""
    payload = record["payload"]
    analysis = payload.get("analysis", {})
    scores_raw = payload.get("scores", {})

    raw = RawScores(**{k: float(scores_raw.get(k, 5)) for k in CATEGORY_WEIGHTS})
    ctx = _context_from_payload(payload)
    decision = decide(raw, ctx)

    columns = []
    for key, weight in CATEGORY_WEIGHTS.items():
        score = raw.as_dict()[key]
        columns.append(
            {
                "key": key,
                "label": CATEGORY_LABELS[key],
                "weight": weight,
                "score": score,
                "contribution": decision.contributions[key],
                "fill": score / 10 * 100,
                "tone": "strong" if score >= 8 else ("weak" if score <= 3 else ""),
                "note": (payload.get("score_notes") or {}).get(key, ""),
            }
        )

    scenarios = payload.get("scenarios") or analysis.get("scenarios") or []
    ev = None
    priced = {s["name"]: (s.get("value_per_share"), s.get("probability")) for s in scenarios
              if s.get("value_per_share") is not None}
    if priced and all(p is not None for _, p in priced.values()):
        try:
            ev = expected_value(priced)
        except ValueError:
            ev = None

    narrative = payload.get("narrative") or {}

    return {
        "record": record,
        "payload": payload,
        "analysis": analysis,
        "company": analysis.get("company", {}),
        "decision": decision,
        "columns": columns,
        "tone": tone_for(decision.action),
        "scenarios": scenarios,
        "expected_value": ev,
        "narrative": narrative,
        "audit_questions": AUDIT_QUESTIONS,
        "attribution": ATTRIBUTION,
        "disclaimer": DISCLAIMER,
        "category_labels": CATEGORY_LABELS,
        "category_weights": CATEGORY_WEIGHTS,
        "generated": record.get("published_at") or record.get("updated_at"),
    }


def render_report(record: dict[str, Any], public: bool = True) -> str:
    env = environment()
    view = build_view(record)
    view["public"] = public
    view["inline_css"] = (STATIC / "terminal.css").read_text(encoding="utf-8")
    return env.get_template("report.html").render(**view)


def render_index(records: list[dict[str, Any]]) -> str:
    env = environment()
    return env.get_template("index.html").render(
        reports=records,
        attribution=ATTRIBUTION,
        disclaimer=DISCLAIMER,
        inline_css=(STATIC / "terminal.css").read_text(encoding="utf-8"),
        generated=dt.datetime.now().isoformat(timespec="seconds"),
    )
