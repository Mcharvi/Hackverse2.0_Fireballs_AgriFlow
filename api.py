"""
AgriFlow backend — now reading from agriflow.db (SQLite) instead of
hardcoded in-memory lists, and reusing matching.py's compute_matches()
instead of a second copy of the same logic.

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
from llm_assistant import answer_question  # Granite function-calling layer

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


# ---------------------------------------------------------------------------
# Assistant — real function-calling layer via IBM Granite (watsonx.ai).
# See llm_assistant.py: question -> Granite picks a function -> we run it
# against the DB -> Granite phrases the answer in natural language.
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
    )