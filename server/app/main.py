"""FastAPI entrypoint. `make run` / `uvicorn app.main:app --reload` from server/."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import caregiver, device, web
from .services.storage import STORAGE_ROOT

STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ChiYaoLe API")

app.include_router(caregiver.router)
app.include_router(device.router)
app.include_router(web.router)

# ★ Local-dev stand-in for OSS's public bucket URLs (app/services/storage.py). A real
# deployment serves assets from OSS directly; this exists only so storage.url_for() results
# are actually fetchable while OSS credentials aren't configured.
app.mount("/media", StaticFiles(directory=STORAGE_ROOT), name="media")

# ★ Deliberately NOT "/static" — that name is conventionally claimed by frameworks/tooling
# and collides easily; the caregiver web app's own JS/CSS live at /web-static (web/static/).
_WEB_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
app.mount("/web-static", StaticFiles(directory=str(_WEB_STATIC)))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
