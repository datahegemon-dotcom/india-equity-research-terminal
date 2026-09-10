"""Application entry point.

Run with:  python -m app.main
Then open: http://127.0.0.1:8848

The server binds to the loopback address only. It is not reachable from your
network, which is why there is no login.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.api.routes import router
from app.net import configure_trust

HOST = "127.0.0.1"
PORT = 8848

WEB = Path(__file__).resolve().parent / "web"
STATIC = Path(__file__).resolve().parent / "report" / "static"

app = FastAPI(title="India Equity Research Terminal", docs_url="/api/docs")
app.include_router(router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    configure_trust()
    db.init()


@app.get("/")
def workbench() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/assets", StaticFiles(directory=str(STATIC)), name="assets")
app.mount("/web", StaticFiles(directory=str(WEB)), name="web")


def main() -> None:
    import uvicorn

    url = f"http://{HOST}:{PORT}"
    print(f"India Equity Research Terminal running at {url}")
    print("Private to this machine. Nothing is published until you press Publish.")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - opening a browser is a convenience, not a requirement
        pass
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
