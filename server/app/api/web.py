"""Caregiver mobile web app (spec: Jinja2 + vanilla JS, no build step). Renders thin HTML
shells only — every page fetches its own data client-side against the same JSON API the
Android app uses, so business logic lives in exactly one place.

★ These page routes are deliberately unauthenticated at the server: the caregiver token
travels as a query param the adult child got over WeChat (never a password, per
app/deps.py's own docstring), and every client-side fetch on the page re-sends it as `t`.
A wrong/expired token still renders the page shell; the JSON calls underneath will 401."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/web", tags=["web"])

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"
_templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


def _context(patient_id: str, t: str) -> dict[str, object]:
    return {"patient_id": patient_id, "token": t}


@router.get("/start")
def start_page(request: Request):  # type: ignore[no-untyped-def]
    """The one self-serve entry point (see caregiver.py's account_start docstring) — no
    patient_id/token yet, so it renders base.html with an empty nav (base.html hides the
    nav entirely when patient_id is falsy) rather than reusing _context."""
    return _templates.TemplateResponse(request, "start.html", {"patient_id": "", "token": ""})


@router.get("/{patient_id}/elders")
def elders_page(request: Request, patient_id: str, t: str):  # type: ignore[no-untyped-def]
    return _templates.TemplateResponse(request, "elders.html", _context(patient_id, t))


@router.get("/{patient_id}/upload")
def upload_page(request: Request, patient_id: str, t: str):  # type: ignore[no-untyped-def]
    return _templates.TemplateResponse(request, "upload.html", _context(patient_id, t))


@router.get("/{patient_id}/confirm")
def confirm_page(request: Request, patient_id: str, t: str):  # type: ignore[no-untyped-def]
    return _templates.TemplateResponse(request, "confirm.html", _context(patient_id, t))


@router.get("/{patient_id}/lab")
def lab_page(request: Request, patient_id: str, t: str):  # type: ignore[no-untyped-def]
    return _templates.TemplateResponse(request, "lab.html", _context(patient_id, t))


@router.get("/{patient_id}/dashboard")
def dashboard_page(request: Request, patient_id: str, t: str):  # type: ignore[no-untyped-def]
    return _templates.TemplateResponse(request, "dashboard.html", _context(patient_id, t))


@router.get("/{patient_id}/setup")
def setup_page(request: Request, patient_id: str, t: str):  # type: ignore[no-untyped-def]
    return _templates.TemplateResponse(request, "setup.html", _context(patient_id, t))
