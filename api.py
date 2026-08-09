"""
AgriFlow backend — reading from agriflow.db (SQLite) and reusing
matching.py's compute_matches() instead of a second copy of the same logic.

NEW: /assistant/insights — proactive, unprompted insight bullets for the
dashboard on load (see llm_assistant.generate_insights). Separate from
/assistant/query on purpose: it's a GET with no request body, cacheable by
the frontend, and never enters the multi-step tool-calling loop that the
Q&A endpoint uses.

Run:
    python seed_agriflow_db.py        # creates/refreshes agriflow.db
    pip install -r requirements.txt --break-system-packages
    uvicorn api:app --reload --port 8000

Note: generate_api_contract.py does `from main import app` — either
rename this file to main.py, or change that import to `from api import app`.
"""

import sqlite3
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from matching import COST_PER_TON_KM, compute_matches, district_supply  # reuse Person B's real matching logic
from profit_analysis import (  # route-economics math (shared with the CLI)
    DEFAULT_RESIDUE_PRICE_PER_TONNE,
    DEFAULT_ROUND_TRIP_FACTOR,
    compute_route_economics,
)
from llm_assistant import answer_question, generate_insights  # OpenAI function-calling layer (GPT-4o-mini)

from impact import compute_impact  # CO2-avoided metric

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agriflow.db"

app = FastAPI(title="AgriFlow API")

# Dev-open CORS so the vibecoded frontend can hit this from anywhere.
# Frontend is deployed at:
#   https://hackverse2-0-fireballs-agriflow-1.onrender.com
# Wildcard is fine for a hackathon demo (no cookies/credentials involved).
# If you want to lock it down before judging, swap "*" for a list:
#   allow_origins=["https://hackverse2-0-fireballs-agriflow-1.onrender.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Process-lifetime match cache — keyed on min_alloc.
# compute_matches() is a pure function of districts + plants, which only
# change when the DB is re-seeded (= a process restart on Render).  Cache
# the result so the matching pass runs once per process, not once per request.
# ---------------------------------------------------------------------------
_match_cache: dict[float, list[dict]] = {}

# Process-lifetime economics cache — recomputed whenever matches change.
_economics_cache: dict | None = None


def _invalidate_match_cache() -> None:
    """Call this if the DB is ever mutated at runtime (not currently needed,
    but makes the cache safe to keep when a write path is added later)."""
    global _economics_cache
    _match_cache.clear()
    _economics_cache = None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"{DB_PATH.name} not found — run `python seed_agriflow_db.py` first.",
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_all_districts() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM districts").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_all_plants() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM plants").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_all_predictions() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM predictions").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_crop_composition() -> dict[str, list[dict]]:
    """CROPGRIDS v1.08 crop-area mix per district, top crops first.

    Returns {district: [{crop, croparea_ha, share_pct}, ...]} — the same data
    process_cropgrids.py wrote, read back from the seeded DB.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT district, crop, croparea_ha, share_pct FROM crop_composition "
            "ORDER BY district, share_pct DESC"
        ).fetchall()
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["district"], []).append(dict(r))
        return out
    finally:
        conn.close()


def get_matches(min_alloc: float = 2000.0) -> list[dict]:
    """Cached matches — computed once per process lifetime per min_alloc value.

    matching.py returns {plant_id, allocated_quantity, ...}. The frontend
    (frontend/src/App.jsx) expects {matched_plant_id, matched_supply, ...}.
    Alias here at the API boundary instead of renaming inside matching.py,
    so the matching module's field names stay stable for anything else
    that reads it directly (e.g. the `matches` table via matching.py's
    own --dry-run / DB write path).
    """
    if min_alloc not in _match_cache:
        districts = load_all_districts()
        plants = load_all_plants()
        raw = compute_matches(districts, plants, min_alloc=min_alloc)
        _match_cache[min_alloc] = [
            {
                "district": m["district"],
                "matched_plant_id": m["plant_id"],
                "matched_supply": m["allocated_quantity"],
                "distance_km": m["distance_km"],
                "pickup_order": m["pickup_order"],
                "status": m["status"],
            }
            for m in raw
        ]
    return _match_cache[min_alloc]


def get_plant_utilization(min_alloc: float = 2000.0) -> list[dict]:
    plants = load_all_plants()
    matches = get_matches(min_alloc=min_alloc)

    used = {p["plant_id"]: 0.0 for p in plants}
    for m in matches:
        # Skip any match that references a plant_id no longer in the plants table
        # (could happen if the DB was re-seeded after matches were written).
        if m["matched_plant_id"] in used:
            used[m["matched_plant_id"]] += m["matched_supply"]

    result = []
    for p in plants:
        util = used[p["plant_id"]]
        capacity = p["annual_capacity"] or 0
        result.append({
            **p,
            "current_utilization": round(util, 1),
            "utilization_pct": round(100 * util / capacity, 1) if capacity else 0.0,
        })
    return result

# CO2-avoided metric
def get_impact() -> dict:
    districts = load_all_districts()
    matches = get_matches()
    return compute_impact(districts, matches)
@app.get("/impact")
def get_impact_route():
    """CO2-avoided-by-matching metric — see impact.py for methodology
    and assumptions."""
    return get_impact()


def get_route_economics() -> dict:
    """Network profit analysis over the current matches.

    Same math as `python profit_analysis.py` (compute_route_economics in
    profit_analysis.py) applied to the cached matches, so every number is
    consistent with what the map and the rest of the API report. Cached per
    process like the matches themselves."""
    global _economics_cache
    if _economics_cache is None:
        raw_matches = [
            {
                "district": m["district"],
                "plant_id": m["matched_plant_id"],
                "allocated_quantity": m["matched_supply"],
                "distance_km": m["distance_km"],
            }
            for m in get_matches()
        ]
        _economics_cache = compute_route_economics(
            raw_matches,
            price=DEFAULT_RESIDUE_PRICE_PER_TONNE,
            round_trip=DEFAULT_ROUND_TRIP_FACTOR,
            rate=COST_PER_TON_KM,
            plant_names={p["plant_id"]: p["plant_name"] for p in load_all_plants()},
        )
    return _economics_cache


@app.get("/economics")
def get_economics_route():
    """Network profit analysis: totals, per-plant P&L, and per-route
    revenue/transport/profit/margin. See profit_analysis.py for the model
    and assumptions. Data/chat layer only — deliberately not shown in the UI."""
    return get_route_economics()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "AgriFlow API is running. See /health and /districts."}


@app.get("/health")
def health():
    db_ok = DB_PATH.exists()
    return {"status": "ok" if db_ok else "db_missing", "db_path": str(DB_PATH)}


# Legacy 2017/2018 columns from the old data layer. The whole app now runs on
# the 2026 forecast family (matching.district_supply is 2026-primary), so these
# are stripped from the API response — nothing downstream can read the old
# numbers, and the JSON surface stays clean for the frontend/judges.
LEGACY_DISTRICT_COLUMNS = {
    "baseline_supply_2017", "rolling_3yr_supply", "trend_forecast_2018",
    "predicted_supply_2018", "trend_r2", "confidence_score_heuristic",
    "confidence_label", "cropland_2017", "avg_precipitation_2017",
    "avg_elevation_2017", "site_count_2017", "rolling_3yr_2022",
}


def _trim_district(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in LEGACY_DISTRICT_COLUMNS}


@app.get("/districts")
def get_districts():
    rows = load_all_districts()
    mix = load_crop_composition()
    for r in rows:
        r["crop_mix"] = mix.get(r["district"], [])
    return [_trim_district(r) for r in rows]


@app.get("/districts/{district_name}")
def get_district(district_name: str):
    mix = load_crop_composition()
    for d in load_all_districts():
        if d["district"] == district_name:
            return _trim_district({**d, "crop_mix": mix.get(district_name, [])})
    raise HTTPException(status_code=404, detail=f"District '{district_name}' not found")


@app.get("/crops")
def get_crops():
    """Full CROPGRIDS v1.08 crop-area composition table (district x crop)."""
    return {
        "source": "CROPGRIDS v1.08 (2020 crop area, Tang et al. 2024, CC BY 4.0)",
        "units": "ha",
        "composition": load_crop_composition(),
    }


@app.get("/predictions")
def get_predictions():
    return load_all_predictions()


@app.get("/predictions/{district_name}")
def get_prediction(district_name: str):
    for p in load_all_predictions():
        if p["district"] == district_name:
            return p
    raise HTTPException(status_code=404, detail=f"No prediction for '{district_name}'")


@app.get("/plants")
def get_plants():
    return get_plant_utilization()


@app.get("/plants/{plant_id}")
def get_plant(plant_id: str):
    for p in get_plant_utilization():
        if p["plant_id"] == plant_id:
            matched_districts = [
                m["district"] for m in get_matches() if m["matched_plant_id"] == plant_id
            ]
            return {**p, "matched_districts": matched_districts}
    raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")


@app.get("/matches")
def get_matches_route():
    return get_matches()


# ---------------------------------------------------------------------------
# Assistant — real function-calling layer via OpenAI.
# See llm_assistant.py: question -> model picks a function -> we run it
# against the DB -> model phrases the answer in natural language.
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]  # reject any other value at the request boundary
    content: str


class AssistantQuery(BaseModel):
    question: str
    history: list[ChatMessage] = []
    language: str = "en"  # UI language the user picked — the assistant answers in it


@app.post("/assistant/query")
def assistant_query(payload: AssistantQuery):
    return answer_question(
        payload.question,
        language=payload.language,
        history=[m.model_dump() for m in payload.history],
        load_all_districts=load_all_districts,
        load_all_plants=load_all_plants,        get_plant_utilization=get_plant_utilization,
        get_matches=get_matches,
        get_impact=get_impact,
        simulate_plant=_simulate_for_assistant,
        get_route_economics=get_route_economics,
    )


# ---------------------------------------------------------------------------
# Process-lifetime insights cache — TTL so repeated dashboard loads don't
# re-hit OpenAI. The payload is a pure function of the same loaders (which
# only change when the DB is re-seeded = a process restart on Render), so a
# 5-minute window is plenty for a demo: the second load is instant, and a
# slow/stale LLM call can't stall the page in front of judges.
# ---------------------------------------------------------------------------
_insights_cache: dict = {"ts": 0.0, "payload": None}
INSIGHTS_TTL_SECONDS = 300  # 5 minutes


@app.get("/assistant/insights")
def assistant_insights():
    """Proactive, unprompted insight bullets for dashboard load.

    GET (not POST) since it takes no user input — same real data every
    caller sees. Cached in-process for INSIGHTS_TTL_SECONDS so dashboard
    loads don't hit OpenAI on every refresh.
    Never raises: generate_insights() fails soft internally and returns a
    deterministic fallback if the OpenAI call errors, so a flaky LLM call
    can't take down the dashboard on load.
    """
    now = time.monotonic()
    if _insights_cache["payload"] is None or now - _insights_cache["ts"] > INSIGHTS_TTL_SECONDS:
        _insights_cache["payload"] = generate_insights(
            load_all_districts=load_all_districts,
            load_all_plants=load_all_plants,
            get_plant_utilization=get_plant_utilization,
            get_matches=get_matches,
            get_impact=get_impact,
        )
        _insights_cache["ts"] = now
    return _insights_cache["payload"]


# ---------------------------------------------------------------------------
# Plant siting simulator — "what if we built a 7th plant here?"
#
# Reuses compute_matches() unmodified: a hypothetical plant is just another
# dict with plant_id/latitude/longitude/annual_capacity appended to the real
# plant list, then the same optimal matching runs twice — once with just the
# real plants (baseline) and once with the hypothetical one added — so the
# "impact" is a straight diff between two runs of logic that's already
# tested and live elsewhere in the app. No new matching algorithm.
# ---------------------------------------------------------------------------
class SimulatedPlantInput(BaseModel):
    latitude: float
    longitude: float
    annual_capacity: float
    plant_name: str = "Simulated Plant"
    min_alloc: float = 2000.0


SIM_PLANT_ID = "SIM"


def _summarize(matches: list[dict], districts: list[dict], plants: list[dict]) -> dict:
    """Same shape as matching.py's summarize(), but per-plant rows include
    plant_name too, since the frontend needs to label the hypothetical plant
    without a second lookup."""
    total_supply = sum(district_supply(d) for d in districts)
    matched = sum(m["allocated_quantity"] for m in matches)
    utilization = {}
    for p in plants:
        allocated = sum(
            m["allocated_quantity"] for m in matches if m["plant_id"] == p["plant_id"]
        )
        utilization[p["plant_id"]] = {
            "plant_name": p["plant_name"],
            "allocated": round(allocated, 1),
            "capacity": p["annual_capacity"],
            "utilization_pct": round(100 * allocated / p["annual_capacity"], 1)
            if p["annual_capacity"] else 0.0,
        }
    ton_km = sum(m["allocated_quantity"] * m["distance_km"] for m in matches)
    return {
        "total_supply": round(total_supply, 1),
        "matched": round(matched, 1),
        "leftover": round(total_supply - matched, 1),
        "utilization": utilization,
        "total_ton_km": round(ton_km, 1),
        "haul_cost": round(ton_km * COST_PER_TON_KM, 1),
    }


@app.post("/simulate/plant")
def simulate_plant(payload: SimulatedPlantInput):
    if payload.annual_capacity <= 0:
        raise HTTPException(status_code=400, detail="annual_capacity must be positive.")

    districts = load_all_districts()
    real_plants = load_all_plants()

    sim_plant = {
        "plant_id": SIM_PLANT_ID,
        "plant_name": payload.plant_name,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "annual_capacity": payload.annual_capacity,
    }

    baseline_matches = compute_matches(districts, real_plants, min_alloc=payload.min_alloc)
    simulated_matches = compute_matches(
        districts, real_plants + [sim_plant], min_alloc=payload.min_alloc
    )

    baseline_summary = _summarize(baseline_matches, districts, real_plants)
    simulated_summary = _summarize(simulated_matches, districts, real_plants + [sim_plant])
    sim_util = simulated_summary["utilization"].get(SIM_PLANT_ID, {})

    return {
        "baseline": baseline_summary,
        "simulated": simulated_summary,
        "leftover_reduction": round(
            baseline_summary["leftover"] - simulated_summary["leftover"], 1
        ),
        "simulated_plant_utilization_pct": sim_util.get("utilization_pct", 0.0),
        "simulated_plant_allocated": sim_util.get("allocated", 0.0),
        # Same field names/aliases as GET /matches, so the frontend can reuse
        # its existing route-drawing code for this too.
        "matches": [
            {
                "district": m["district"],
                "matched_plant_id": m["plant_id"],
                "matched_supply": m["allocated_quantity"],
                "distance_km": m["distance_km"],
                "pickup_order": m["pickup_order"],
                "status": m["status"],
            }
            for m in simulated_matches
        ],
    }


def _simulate_for_assistant(
    latitude: float, longitude: float, annual_capacity: float, plant_name: str = "Simulated Plant"
) -> dict:
    """Thin adapter so the LLM's simulate_plant tool runs the exact same
    engine as POST /simulate/plant without going through HTTP: same pydantic
    boundary, same function the route calls."""
    return simulate_plant(
        SimulatedPlantInput(
            latitude=latitude,
            longitude=longitude,
            annual_capacity=annual_capacity,
            plant_name=plant_name,
        )
    )