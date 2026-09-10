"""Application entry point.

Run with:  python -m app.main
Then open: http://127.0.0.1:8848

By default the server binds to the loopback address and is reachable only from
this machine. When a hosting platform sets PORT, it binds to every interface
instead and the workbench becomes publicly reachable.

There is no authentication. On a public host that means anyone with the address
can read the database, change scores and create reports. That is a deliberate
choice by the operator, not an oversight.
"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.api.routes import router
from app.net import configure_trust

# A platform that hosts the app sets PORT. When it does, listen on every
# interface, because the platform's router reaches the container from outside.
# Without it, stay on the loopback address so the workbench is reachable only
# from this machine.
PORT = int(os.environ.get("PORT", "8848"))
HOSTED = "PORT" in os.environ
HOST = os.environ.get("HOST", "0.0.0.0" if HOSTED else "127.0.0.1")

WEB = Path(__file__).resolve().parent / "web"
STATIC = Path(__file__).resolve().parent / "report" / "static"

app = FastAPI(title="India Equity Research Terminal", docs_url="/api/docs")
app.include_router(router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    configure_trust()
    db.init()


@app.middleware("http")
async def no_cache(request, call_next):
    """Never let the browser cache the workbench.

    This is a local tool that is edited while it runs. A stale stylesheet or
    script cached from a previous version is confusing in a way that no amount
    of cache-busting query strings reliably fixes.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.get("/")
def workbench() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/assets", StaticFiles(directory=str(STATIC)), name="assets")
app.mount("/web", StaticFiles(directory=str(WEB)), name="web")


@app.get("/api/runtime")
def runtime() -> dict:
    """What the interface needs to know about where it is running."""
    return {
        "hosted": HOSTED,
        "note": (
            "Running on a public host with no login. Anyone with this address can read and "
            "change these reports, and published pages stay inside this container until the "
            "project is pushed from a machine that has git access."
            if HOSTED
            else "Private to this machine."
        ),
    }


def main() -> None:
    import uvicorn

    if HOSTED:
        print(f"India Equity Research Terminal listening on {HOST}:{PORT}")
        print("Public host, no authentication. Anyone with the address has full access.")
    else:
        url = f"http://127.0.0.1:{PORT}"
        print(f"India Equity Research Terminal running at {url}")
        print("Private to this machine. Nothing is published until you press Publish.")
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - opening a browser is a convenience
            pass
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
