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


@app.get("/api/search")
async def search(
    type: str = Query(..., description="Appointment type, e.g. 'Written Test'"),
    office: Optional[str] = Query(None, description="Filter to a single office by name fragment"),
):
    """
    Search for the earliest available appointment across all (or one) offices.

    Returns a list of office results sorted by earliest_date ascending,
    with offices that have no availability at the end.
    """
    if type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type. Must be one of: {VALID_TYPES}"
        )

    results = await search_offices(type, office_filter=office)

    found   = sorted(
        [r for r in results if r["earliest_date"]],
        key=lambda r: r["earliest_date"]
    )
    no_date = [r for r in results if not r["earliest_date"]]

    return JSONResponse({
        "type":         type,
        "searched":     len(results),
        "available":    len(found),
        "results":      [serialize_result(r) for r in found],
        "unavailable":  [serialize_result(r) for r in no_date],
    })


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Serve the frontend ────────────────────────────────────────────────────────
# Must be registered AFTER API routes so /api/* isn't swallowed.
# Place your index.html (and any other assets) inside the static/ folder.
app.mount("/", StaticFiles(directory="static", html=True), name="static")