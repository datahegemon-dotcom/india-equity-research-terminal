"""HTTP interface for the private workbench.

Bound to the loopback address by the launcher, so it is not reachable from the
network and needs no authentication.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse

from app import db
from app.core import pipeline
from app.core.scoring import CATEGORY_LABELS, CATEGORY_WEIGHTS, classify_margin_of_safety
from app.providers import yahoo
from app.report import publish as publisher
from app.report import render

router = APIRouter()


def _decision_payload(record: dict[str, Any]) -> dict[str, Any]:
    view = render.build_view(record)
    decision = view["decision"]
    return {
        "total": decision.total,
        "band": decision.band.value,
        "action": decision.action.value,
        "tone": view["tone"],
        "contributions": decision.contributions,
        "overrides": [o.value for o in decision.overrides],
        "labels": decision.labels,
        "publishable": decision.publishable,
        "publish_blockers": decision.publish_blockers,
        "margin_of_safety": decision.margin_of_safety.value,
        "columns": view["columns"],
        "expected_value": view["expected_value"],
        "scenario_chart": view["charts"].get("scenarios", ""),
    }


def _full(record: dict[str, Any]) -> dict[str, Any]:
    return {"record": record, "decision": _decision_payload(record)}


@router.get("/meta")
def meta() -> dict[str, Any]:
    return {
        "weights": CATEGORY_WEIGHTS,
        "labels": CATEGORY_LABELS,
        "actions": ["BUY", "ACCUMULATE", "HOLD", "WATCHLIST", "REDUCE", "EXIT", "AVOID"],
        "margin_of_safety": ["HIGH", "MODERATE", "LOW", "NEGATIVE", "UNKNOWN"],
        "expectation_gaps": [
            "Not assessed",
            "Expectations too low, positive asymmetric setup",
            "Expectations reasonable, balanced",
            "Expectations high, execution required",
            "Expectations extreme, high downside on disappointment",
        ],
    }


@router.get("/search")
def search_companies(q: str = "") -> list[dict[str, str]]:
    """Find listed companies by name or symbol, so nobody has to guess a ticker."""
    return yahoo.search(q)


@router.get("/health/data")
def data_health() -> dict[str, Any]:
    """Can this machine actually reach the data source?

    Worth having, because a blocked or intercepted connection otherwise looks
    exactly like a company that does not exist.
    """
    matches = yahoo.search("reliance")
    return {
        "reachable": bool(matches),
        "matches": len(matches),
        "error": yahoo.LAST_SEARCH_ERROR,
        "hint": (
            None
            if matches
            else "The data source could not be reached. On a host, check outbound HTTPS. "
            "On a machine whose antivirus intercepts TLS, point SSL_CERT_FILE at a bundle "
            "that includes its certificate."
        ),
    }


@router.get("/reports")
def list_reports() -> list[dict[str, Any]]:
    return db.list_reports()


@router.post("/reports")
def create_report(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="A ticker is required.")

    try:
        analysis = pipeline.analyse(ticker)
    except Exception as exc:  # noqa: BLE001 - surface the real reason to the analyst
        raise HTTPException(status_code=502, detail=f"Could not fetch data for {ticker}: {exc}") from exc

    if not analysis.company.get("name"):
        raise HTTPException(
            status_code=404,
            detail=f"No company found for {ticker}. Check the symbol as listed on the NSE.",
        )

    payload = _initial_payload(analysis)
    record = db.create_report(ticker, analysis.company.get("name"), payload)
    return _full(record)


def _initial_payload(analysis: pipeline.Analysis) -> dict[str, Any]:
    data = analysis.as_dict()
    scenarios = [dict(s) for s in data["scenarios"]]

    base = next((s for s in scenarios if s["name"] == "Base"), None)
    price = analysis.company.get("price")
    margin = "UNKNOWN"
    if base and base.get("value_per_share") and price:
        margin = classify_margin_of_safety(price, base["value_per_share"]).value

    return {
        "analysis": data,
        "scores": {k: v.score for k, v in analysis.drafts.items()},
        "score_notes": {k: "" for k in analysis.drafts},
        "draft_scores": {k: v.score for k, v in analysis.drafts.items()},
        "context": {
            "margin_of_safety": margin,
            "valuation_extreme": False,
            "multiple_compression_note": "",
            "thesis_break": False,
            "thesis_break_severe": False,
            "thesis_break_reasons": [],
            "severe_unresolved_risk": False,
            "credible_turnaround_catalyst": False,
            "asymmetry_justification": "",
            "portfolio_concentration_breach": False,
            "expectation_gap": "Not assessed",
            "technical_score": analysis.technical.score,
        },
        "narrative": {
            "why": [],
            "market_missing": [],
            "against": "",
            "catalysts": [],
            "risks": [],
            "invalidation": [],
            "monitor": [],
        },
        "scenarios": scenarios,
    }


@router.get("/reports/{report_id}")
def get_report(report_id: int) -> dict[str, Any]:
    try:
        return _full(db.get_report(report_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/reports/{report_id}")
def update_report(report_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        record = db.get_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = record["payload"]
    for key in ("scores", "score_notes", "context", "narrative", "scenarios"):
        if key in body:
            payload[key] = body[key]

    try:
        updated = db.update_payload(report_id, payload)
        return _full(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reports/{report_id}/refresh")
def refresh_report(report_id: int) -> dict[str, Any]:
    """Re-fetch market data, keeping every analyst judgement intact."""
    try:
        record = db.get_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        analysis = pipeline.analyse(record["ticker"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Refresh failed: {exc}") from exc

    payload = record["payload"]
    payload["analysis"] = analysis.as_dict()
    payload["draft_scores"] = {k: v.score for k, v in analysis.drafts.items()}
    payload["context"]["technical_score"] = analysis.technical.score
    return _full(db.update_payload(report_id, payload))


@router.post("/reports/{report_id}/publish")
def publish_report(report_id: int) -> dict[str, Any]:
    try:
        record = publisher.publish(report_id)
    except publisher.NotPublishable as exc:
        raise HTTPException(status_code=409, detail={"blockers": exc.blockers}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _full(record)


@router.post("/reports/{report_id}/unpublish")
def unpublish_report(report_id: int) -> dict[str, Any]:
    try:
        return _full(publisher.unpublish(report_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/reports/{report_id}")
def delete_report(report_id: int) -> dict[str, str]:
    try:
        record = db.get_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if record["status"] == "published":
        publisher.unpublish(report_id)
    db.delete_report(report_id)
    return {"status": "deleted"}


@router.get("/site")
def site_status() -> dict[str, Any]:
    return publisher.site_status()


@router.get("/reports/{report_id}/preview", response_class=HTMLResponse)
def preview(report_id: int) -> HTMLResponse:
    try:
        record = db.get_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HTMLResponse(render.render_report(record, public=False))
