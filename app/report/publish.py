"""Publishing.

Turns a finished report into a static page under `site/`, which GitHub Pages
serves. Publishing is always an explicit action, and only a report that passes
the score audit can be published.

Nothing else in the local database is written to `site/`. Drafts stay private.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app import db
from app.report import render

SITE = Path(__file__).resolve().parent.parent.parent / "site"


class NotPublishable(Exception):
    """Raised when the score audit or an override rule blocks publication."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__("; ".join(blockers))
        self.blockers = blockers


def _ensure_site() -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    # GitHub Pages runs Jekyll by default, which ignores folders starting with
    # an underscore and rewrites some files. This turns that off.
    (SITE / ".nojekyll").write_text("", encoding="utf-8")


def publish(report_id: int) -> dict[str, Any]:
    record = db.get_report(report_id)
    view = render.build_view(record)
    decision = view["decision"]

    if not decision.publishable:
        raise NotPublishable(decision.publish_blockers)

    _ensure_site()
    html = render.render_report(record, public=True)
    target = SITE / record["slug"]
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(html, encoding="utf-8")

    updated = db.mark_published(report_id)
    rebuild_index()
    return updated


def unpublish(report_id: int) -> dict[str, Any]:
    record = db.get_report(report_id)
    target = SITE / record["slug"]
    if target.exists():
        shutil.rmtree(target)
    updated = db.unpublish(report_id)
    rebuild_index()
    return updated


def rebuild_index() -> Path:
    _ensure_site()
    rows: list[dict[str, Any]] = []
    for summary in db.list_reports(status="published"):
        record = db.get_report(summary["id"])
        view = render.build_view(record)
        rows.append(
            {
                **summary,
                "total": view["decision"].total,
                "action": view["decision"].action.value,
                "tone": view["tone"],
            }
        )
    rows.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    path = SITE / "index.html"
    path.write_text(render.render_index(rows), encoding="utf-8")
    return path


def site_status() -> dict[str, Any]:
    published = db.list_reports(status="published")
    return {
        "site_path": str(SITE),
        "published_count": len(published),
        "pages": [p["slug"] for p in published],
        "index_exists": (SITE / "index.html").exists(),
    }
