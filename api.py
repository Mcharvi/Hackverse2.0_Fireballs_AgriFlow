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
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from matching import compute_matches  # reuse Person B's real matching logic
from economics import compute_economics  # sale-profit vs transport-cost layer
from llm_assistant import answer_question, generate_insights  # Granite/OpenAI function-calling layer

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


def get_matches(min_alloc: float = 2000.0) -> list[dict]:
    """Live matches, computed with the real economic-lot-threshold logic
    from matching.py — not a separate implementation.

    matching.py returns {plant_id, allocated_quantity, ...}. The frontend
    (frontend/src/App.jsx) expects {matched_plant_id, matched_supply, ...}.
    Alias here at the API boundary instead of renaming inside matching.py,
    so the matching module's field names stay stable for anything else
    that reads it directly (e.g. the `matches` table via matching.py's
    own --dry-run / DB write path).
    """
    districts = load_all_districts()
    plants = load_all_plants()
    raw = compute_matches(districts, plants, min_alloc=min_alloc)
    return [
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


def get_economics(
    sale_price_per_unit: float = 10.0,
    cost_per_km_per_unit: float = 0.05,
    round_trip_factor: float = 2.0,
    min_alloc: float = 2000.0,
    top_n: int = 5,
) -> dict:
    """Route economics — a pure function of the same matches the rest of
    the app shows. All parameters are demo rates (see economics.py); the
    module's compute_economics() does the actual math."""
    districts = load_all_districts()
    plants = load_all_plants()
    raw = compute_matches(districts, plants, min_alloc=min_alloc)
    return compute_economics(
        raw,
        sale_price_per_unit=sale_price_per_unit,
        cost_per_km_per_unit=cost_per_km_per_unit,
        round_trip_factor=round_trip_factor,
        top_n=top_n,
    )


def get_plant_utilization(min_alloc: float = 2000.0) -> list[dict]:
    plants = load_all_plants()
    matches = get_matches(min_alloc=min_alloc)

    used = {p["plant_id"]: 0.0 for p in plants}
    for m in matches:
        used[m["matched_plant_id"]] += m["matched_supply"]

    result = []
    for p in plants:
        util = used[p["plant_id"]]
        result.append({
            **p,
            "current_utilization": round(util, 1),
            "utilization_pct": round(100 * util / p["annual_capacity"], 1),
        })
    return result


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


@app.get("/districts")
def get_districts():
    return load_all_districts()


@app.get("/districts/{district_name}")
def get_district(district_name: str):
    for d in load_all_districts():
        if d["district"] == district_name:
            return d
    raise HTTPException(status_code=404, detail=f"District '{district_name}' not found")


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


@app.get("/economics")
def get_economics_route(
    sale_price_per_unit: float = 10.0,
    cost_per_km_per_unit: float = 0.05,
    round_trip_factor: float = 2.0,
    min_alloc: float = 2000.0,
    top_n: int = 5,
):
    """Sale-profit vs transport-cost comparison for the current match plan.

    GET (no body, cacheable) so the frontend can fetch it on load and the
    LLM assistant can read the same numbers. Parameters are demo rates,
    overridable via query string for live sensitivity (e.g.
    ?sale_price_per_unit=8&cost_per_km_per_unit=0.3).
    """
    return get_economics(
        sale_price_per_unit=sale_price_per_unit,
        cost_per_km_per_unit=cost_per_km_per_unit,
        round_trip_factor=round_trip_factor,
        min_alloc=min_alloc,
        top_n=top_n,
    )


# ---------------------------------------------------------------------------
# Assistant — real function-calling layer via OpenAI.
# See llm_assistant.py: question -> model picks a function -> we run it
# against the DB -> model phrases the answer in natural language.
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class AssistantQuery(BaseModel):
    question: str
    history: list[ChatMessage] = []


@app.post("/assistant/query")
def assistant_query(payload: AssistantQuery):
    return answer_question(
        payload.question,
        history=[m.model_dump() for m in payload.history],
        load_all_districts=load_all_districts,
        load_all_plants=load_all_plants,
        get_plant_utilization=get_plant_utilization,
        get_matches=get_matches,
        get_economics=get_economics,
    )


@app.get("/assistant/insights")
def assistant_insights():
    """Proactive, unprompted insight bullets for dashboard load.

    GET (not POST) since it takes no user input — same real data every
    caller sees, so a CDN/browser can cache this if we ever want it to.
    Never raises: generate_insights() fails soft internally and returns a
    deterministic fallback if the OpenAI call errors, so a flaky LLM call
    can't take down the dashboard on load.
    """
    return generate_insights(
        load_all_districts=load_all_districts,
        load_all_plants=load_all_plants,
        get_plant_utilization=get_plant_utilization,
        get_matches=get_matches,
        get_economics=get_economics,
    )


# ---------------------------------------------------------------------------
# Plant siting simulator — "what if we built a 7th plant here?"
#
# Reuses compute_matches() unmodified: a hypothetical plant is just another
# dict with plant_id/latitude/longitude/annual_capacity appended to the real
# plant list, then the same greedy matching runs twice — once with just the
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
    total_supply = sum(float(d["predicted_supply_2018"]) for d in districts)
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
    return {
        "total_supply": round(total_supply, 1),
        "matched": round(matched, 1),
        "leftover": round(total_supply - matched, 1),
        "utilization": utilization,
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