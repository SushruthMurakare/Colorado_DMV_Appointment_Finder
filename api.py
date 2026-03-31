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
from datetime import datetime
from typing import Optional
import asyncio

from datetime import datetime, timedelta
from typing import Optional

from dmv import search_offices, VALID_TYPES, OFFICES

app = FastAPI(title="Colorado DMV Appointment Finder", version="1.0.0")

# Allow local dev (e.g. Vite / live-server on a different port)
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
    """Return the list of valid appointment types."""
    return {"types": VALID_TYPES}


@app.get("/api/offices")
def get_offices():
    """Return all office names and addresses."""
    return {"offices": [{"id": o["id"], "name": o["name"], "address": o["address"]} for o in OFFICES]}


_cache: dict = {}
CACHE_TTL_MINUTES = 15

@app.get("/api/search")
async def search(
    type: str = Query(..., description="Appointment type, e.g. 'Written Test'"),
    office: Optional[str] = Query(None, description="Filter to a single office by name fragment"),
):
    """
    Search for the earliest available appointment across all (or one) offices.
    Results are cached for 15 minutes per (type, office) pair to avoid hammering the DMV site.
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
# Must be registered AFTER API routes so /api/* isn't swallowed.
# Place your index.html (and any other assets) inside the static/ folder.
app.mount("/", StaticFiles(directory="static", html=True), name="static")