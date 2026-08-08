"""AgriFlow API — minimal deployable backend for the hackathon demo.

Serves the seeded SQLite data (agriflow.db) so the frontend has a live API to
hit. This is the deploy-ready stub: Charvi's fuller skeleton can replace it on
the `backend` branch without changing the JSON shapes.

Endpoints (the agreed contract, plus 2 bonus):
  GET  /health                    — liveness check (used by Render)
  GET  /districts                 — all 20 districts with supply/prediction data
  GET  /districts/{district_name} — single district detail (powers the click panel)
  GET  /plants                    — all 6 plants with capacity
  GET  /plants/{plant_id}         — single plant detail incl. computed utilization
  GET  /matches                   — computed district→plant matches with distance
  POST /assistant/query           — LLM assistant: question in, answer out
  GET  /predictions               — bonus: biomass forecast per district
  GET  /sustainability            — bonus: headline numbers computed from the DB
"""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = Path(__file__).resolve().parent / "agriflow.db"

app = FastAPI(title="AgriFlow API", version="0.1.0")

# Wide-open CORS for the hackathon: the frontend lives on Vercel / v0 preview
# with a different origin, so any origin must be allowed for the demo to work.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query against agriflow.db, returning rows as dicts."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def scalar(sql: str, params: tuple = ()) -> float | None:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(sql, params).fetchone()[0]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "agriflow-api",
        "districts": scalar("SELECT COUNT(*) FROM districts"),
        "plants": scalar("SELECT COUNT(*) FROM plants"),
    }


@app.get("/districts")
def districts():
    return query("SELECT * FROM districts ORDER BY predicted_supply_2018 DESC")


@app.get("/districts/{district_name}")
def district_detail(district_name: str):
    rows = query("SELECT * FROM districts WHERE district = ?", (district_name,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Unknown district: {district_name}")
    return rows[0]


@app.get("/plants")
def plants():
    return query("SELECT * FROM plants ORDER BY plant_id")


@app.get("/plants/{plant_id}")
def plant_detail(plant_id: str):
    rows = query("SELECT * FROM plants WHERE plant_id = ?", (plant_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Unknown plant: {plant_id}")
    plant = rows[0]
    allocated = scalar(
        "SELECT COALESCE(SUM(allocated_quantity), 0) FROM matches WHERE plant_id = ?",
        (plant_id,),
    ) or 0.0
    capacity = plant["annual_capacity"]
    plant["utilization_pct"] = round(100 * allocated / capacity, 1) if capacity else 0.0
    return plant


@app.get("/predictions")
def predictions():
    return query("SELECT * FROM predictions ORDER BY predicted_supply DESC")


@app.get("/matches")
def matches():
    return query("SELECT * FROM matches ORDER BY id")


class AssistantRequest(BaseModel):
    question: str


@app.post("/assistant/query")
def assistant_query(request: AssistantRequest):
    # Stub for the LLM assistant (Feature 3). Returns a canned response until
    # the function-calling layer over the SQLite data is wired up.
    return {
        "question": request.question,
        "answer": "Stub response — the AI assistant isn't wired up yet. "
        "Soon it will answer questions like: Which district has the highest "
        "biomass next month?",
    }


@app.get("/sustainability")
def sustainability():
    total_supply = scalar("SELECT SUM(predicted_supply) FROM predictions") or 0.0
    total_capacity = scalar("SELECT SUM(annual_capacity) FROM plants") or 0.0
    matched = scalar("SELECT COALESCE(SUM(allocated_quantity), 0) FROM matches") or 0.0
    return {
        "total_predicted_supply_units": round(total_supply, 1),
        "total_plant_capacity_units": round(total_capacity, 1),
        "supply_capacity_ratio": round(total_supply / total_capacity, 2) if total_capacity else None,
        "matched_units": round(matched, 1),
        "note": "Values are dimensionless dataset biomass units (Shell.ai convention), not tonnes.",
    }
