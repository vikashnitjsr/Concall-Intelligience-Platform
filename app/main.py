"""FastAPI application entrypoint."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_dashboard, routes_transcripts

app = FastAPI(
    title="Concall Intelligence Platform",
    version="0.1.0",
    description="Analyze quarterly earnings-call transcripts, track management "
                "guidance vs delivery, score companies against the Business "
                "Analysis Template, and rank stocks. Decision-support only.",
)

app.include_router(routes_transcripts.router, tags=["companies & transcripts"])
app.include_router(routes_dashboard.router, tags=["dashboard"])

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok"}
