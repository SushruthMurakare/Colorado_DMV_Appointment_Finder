"""
api.py — FastAPI wrapper around dmv.py

Run:
  uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Then open http://localhost:8000 in your browser.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import os
import httpx

from dmv import search_offices, VALID_TYPES, OFFICES


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
    """Convert a result dict to JSON-safe form (datetime → ISO string)."""
    out = {k: v for k, v in r.items()}
    if isinstance(out.get("earliest_date"), datetime):
        out["earliest_date"] = out["earliest_date"].isoformat()
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

    found = sorted(
        [r for r in results if r["earliest_date"]],
        key=lambda r: r["earliest_date"]
    )
    no_date = [r for r in results if not r["earliest_date"]]

    response_data = {
        "type":        type,
        "searched":    len(results),
        "available":   len(found),
        "results":     [serialize_result(r) for r in found],
        "unavailable": [serialize_result(r) for r in no_date],
        "cached":      False,
        "cached_at":   datetime.utcnow().isoformat(),
    }

    _cache[cache_key] = (datetime.utcnow(), response_data)

    return JSONResponse(response_data)


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Serve the frontend ────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")