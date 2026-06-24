"""Import-from-My-Financial-Life wizard (ADR-020, Phase 4).

Three steps:
  GET  /import          — choose an MFL .mfl file
  POST /import/preview  — read it, build the plan, show a review/edit form
  POST /import/apply    — apply the (edited) plan, show next-steps

The uploaded file is staged at a fixed path under the data dir and re-read at
apply time (so no file path is carried through the form — avoids path
injection). Wizard edits — investment growth/dividend rates, FX, loan/budget
amounts, from/to years, and per-row include toggles — are overlaid on the
freshly-rebuilt plan before it is applied.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse

from src.api.templates import templates
from src.config import settings as app_settings
from src.mfl_import.reader import read_snapshot, MflReadError
from src.mfl_import.mapping import build_plan
from src.mfl_import.apply import apply_plan

router = APIRouter()


def _staged_path() -> Path:
    return Path(app_settings.data_dir) / "_mfl_import.mfl"


def _ctx(**kw):
    base = {"app_name": app_settings.app_name, "active": "import"}
    base.update(kw)
    return base


def _f(arr: list, i: int):
    """Parse arr[i] as float, or None if missing/blank/invalid."""
    if i < len(arr) and str(arr[i]).strip() != "":
        try:
            return float(arr[i])
        except (ValueError, TypeError):
            return None
    return None


@router.get("/import", response_class=HTMLResponse)
async def import_start(request: Request):
    return templates.TemplateResponse(request=request, name="import_start.html",
                                      context=_ctx())


@router.post("/import/preview", response_class=HTMLResponse)
async def import_preview(request: Request, mfl_file: UploadFile = File(...)):
    staged = _staged_path()
    try:
        content = await mfl_file.read()
        staged.write_bytes(content)
        snapshot = read_snapshot(str(staged))
        plan = build_plan(snapshot, current_year=date.today().year)
    except MflReadError as e:
        staged.unlink(missing_ok=True)
        return templates.TemplateResponse(
            request=request, name="import_start.html",
            context=_ctx(error=f"Could not read that file as a My Financial Life "
                               f"database: {e}"))
    except Exception as e:                                   # pragma: no cover
        staged.unlink(missing_ok=True)
        return templates.TemplateResponse(
            request=request, name="import_start.html",
            context=_ctx(error=f"Unexpected error reading the file: {e}"))

    return templates.TemplateResponse(
        request=request, name="import_review.html",
        context=_ctx(plan=plan, summary=plan.summary(),
                     filename=mfl_file.filename or "your MFL file"))


@router.post("/import/apply", response_class=HTMLResponse)
async def import_apply(
    request: Request,
    acct_include: list[str] = Form(default=[]),
    acct_growth: list[str] = Form(default=[]),
    acct_dividend: list[str] = Form(default=[]),
    acct_fx: list[str] = Form(default=[]),
    asset_include: list[str] = Form(default=[]),
    asset_appr: list[str] = Form(default=[]),
    bl_include: list[str] = Form(default=[]),
    bl_amount: list[str] = Form(default=[]),
    bl_from: list[str] = Form(default=[]),
    bl_to: list[str] = Form(default=[]),
):
    staged = _staged_path()
    if not staged.exists():
        return templates.TemplateResponse(
            request=request, name="import_start.html",
            context=_ctx(error="Your upload expired — please choose the file again."))

    try:
        plan = build_plan(read_snapshot(str(staged)), current_year=date.today().year)
    except Exception as e:                                   # pragma: no cover
        staged.unlink(missing_ok=True)
        return templates.TemplateResponse(
            request=request, name="import_start.html",
            context=_ctx(error=f"Could not re-read the staged file: {e}"))

    inc_a, inc_as, inc_b = set(acct_include), set(asset_include), set(bl_include)

    accounts = []
    for i, a in enumerate(plan.accounts):
        if a.source_ref not in inc_a:
            continue
        if a.kind == "investment":
            g, d = _f(acct_growth, i), _f(acct_dividend, i)
            if g is not None:
                a.growth_rate = g
            if d is not None:
                a.dividend_rate = d
        fx = _f(acct_fx, i)
        if fx is not None:
            a.exchange_rate = Decimal(str(fx))
        accounts.append(a)
    plan.accounts = accounts

    assets = []
    for i, a in enumerate(plan.assets):
        if a.source_ref not in inc_as:
            continue
        appr = _f(asset_appr, i)
        if appr is not None:
            a.appreciation_rate = appr
        assets.append(a)
    plan.assets = assets

    budget_lines = []
    for i, b in enumerate(plan.budget_lines):
        if b.source_ref not in inc_b:
            continue
        amt = _f(bl_amount, i)
        if amt is not None:
            b.monthly_amount = Decimal(str(amt))
        fr, to = _f(bl_from, i), _f(bl_to, i)
        if fr is not None:
            b.from_year = int(fr)
        b.to_year = int(to) if to is not None else None
        budget_lines.append(b)
    plan.budget_lines = budget_lines

    result = apply_plan(plan)
    staged.unlink(missing_ok=True)

    return templates.TemplateResponse(
        request=request, name="import_done.html",
        context=_ctx(result=result))
