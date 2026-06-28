"""
api.py — FastAPI wrapper around dmv.py

Run:
  uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Then open http://localhost:8000 in your browser.
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import asyncio
import re
import os
import httpx

from dmv import search_offices, VALID_TYPES, OFFICES
from notifications import create_subscription, deactivate_subscription, run_poller


# ── Keep-alive (prevents Render free tier from spinning down) ─────────────────
# Add RENDER_EXTERNAL_URL in your Render dashboard environment variables:
#   RENDER_EXTERNAL_URL = https://your-app-name.onrender.com
# Has no effect locally (variable won't be set).

PING_INTERVAL = 13 * 60  # 10 min — Render spins down after 15 min of inactivity


async def _keep_alive():
    base_url = os.getenv("RENDER_EXTERNAL_URL")
    if not base_url:
        return
    ping_url = base_url.rstrip("/") + "/api/health"
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await client.get(ping_url, timeout=10)
            except Exception:
                pass  # silently retry next cycle


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_keep_alive())
    asyncio.create_task(run_poller())
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Colorado DMV Appointment Finder",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def serialize_result(r: dict) -> dict:
    out = {k: v for k, v in r.items()}
    if isinstance(out.get("earliest_date"), datetime):
        out["earliest_date"] = out["earliest_date"].isoformat()
    if isinstance(out.get("available_dates"), list):
        out["available_dates"] = [
            d.isoformat() if isinstance(d, datetime) else d
            for d in out["available_dates"]
        ]
    return out


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/types")
def get_types():
    return {"types": VALID_TYPES}


@app.get("/api/offices")
def get_offices():
    return {"offices": [{"id": o["id"], "name": o["name"], "address": o["address"]} for o in OFFICES]}


_cache: dict = {}
CACHE_TTL_MINUTES = 60  # ← bumped from 15 to 60


@app.get("/api/search")
async def search(
    type: str = Query(..., description="Appointment type, e.g. 'Written Test'"),
    office: Optional[str] = Query(None, description="Filter to a single office by name fragment"),
):
    """
    Search for the earliest available appointment across all (or one) offices.
    Results are cached for 60 minutes per (type, office) pair.
    """
    if type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type. Must be one of: {VALID_TYPES}"
        )

    cache_key = (type, office)
    if cache_key in _cache:
        cached_at, data = _cache[cache_key]
        if datetime.utcnow() - cached_at < timedelta(minutes=CACHE_TTL_MINUTES):
            return JSONResponse({**data, "cached": True, "cached_at": cached_at.isoformat()})

    results = await search_offices(type, office_filter=office)

    found   = [r for r in results if r["earliest_date"]]
    no_date = [r for r in results if not r["earliest_date"]]

    # by_office: one entry per office sorted by earliest slot
    by_office = sorted(found, key=lambda r: r["earliest_date"])

    # top_slots: all slots within the next 7 days across all offices, capped at 50
    now      = datetime.utcnow()
    week_end = now + timedelta(days=7)
    flat = []
    for r in found:
        for dt in r["available_dates"]:
            if dt <= week_end:
                flat.append({
                    "id":            r["id"],
                    "name":          r["name"],
                    "address":       r["address"],
                    "earliest_date": dt,
                })
    flat.sort(key=lambda x: x["earliest_date"])
    top_slots = flat[:50]

    response_data = {
        "type":      type,
        "searched":  len(results),
        "available": len(found),
        "by_office": [serialize_result(r) for r in by_office],
        "top_slots": [serialize_result(s) for s in top_slots],
        "unavailable": [serialize_result(r) for r in no_date],
        "cached":    False,
        "cached_at": datetime.utcnow().isoformat(),
    }

    _cache[cache_key] = (datetime.utcnow(), response_data)

    return JSONResponse(response_data)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_OFFICE_IDS = {o["id"] for o in OFFICES}


class SubscribeBody(BaseModel):
    name: str
    email: str
    appt_type: str
    office_id: Optional[int] = None
    office_name: Optional[str] = None
    before_date: Optional[str] = None


@app.post("/api/subscribe", status_code=201)
async def subscribe(body: SubscribeBody):
    if not body.name.strip():
        raise HTTPException(400, detail="Name is required")
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(400, detail="Invalid email address")
    if body.appt_type not in VALID_TYPES:
        raise HTTPException(400, detail="Invalid appointment type")
    if body.office_id is not None and body.office_id not in _OFFICE_IDS:
        raise HTTPException(400, detail="Unknown office")
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(503, detail="Notifications not configured")
    try:
        sub = await create_subscription(
            name=body.name.strip(),
            email=body.email,
            appt_type=body.appt_type,
            office_id=body.office_id or None,
            office_name=body.office_name or None,
            before_date=body.before_date or None,
        )
        return {"ok": True, "id": sub["id"]}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/unsubscribe")
async def unsubscribe(token: str = Query(...)):
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(503, detail="Notifications not configured")
    ok = await deactivate_subscription(token)
    if not ok:
        return HTMLResponse("<p style='font-family:sans-serif'>Link not found or already unsubscribed.</p>", status_code=404)
    return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Unsubscribed</title>
<style>body{font-family:-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f7f7f5}
.card{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:32px 36px;text-align:center;max-width:360px}
h2{margin:0 0 8px;font-size:18px;color:#111}p{margin:0;font-size:13.5px;color:#666}</style></head>
<body><div class="card"><h2>Unsubscribed</h2><p>You won't receive any more DMV slot alerts.</p></div></body></html>""")


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Serve the frontend ────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")