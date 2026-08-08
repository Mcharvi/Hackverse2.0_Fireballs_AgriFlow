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

import json
import os
import sqlite3
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from matching import compute_matches  # reuse Person B's real matching logic

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
# Assistant — IBM Granite function-calling layer.
#
# Pattern: question -> LLM picks a tool -> we run the lookup against the DB
# above -> structured result -> LLM writes the natural-language answer.
#
# Requires a WATSONX_API_KEY env var (IBM Cloud API key) and, for the current
# watsonx.ai ml/v1 chat endpoint, WATSONX_PROJECT_ID. When the key is absent
# or the call fails, we fall back to deterministic keyword rules so the
# endpoint always answers.
# ---------------------------------------------------------------------------
WATSONX_API_KEY = os.environ.get("WATSONX_API_KEY")
WATSONX_PROJECT_ID = os.environ.get("WATSONX_PROJECT_ID")
WATSONX_URL = os.environ.get(
    "WATSONX_URL",
    "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat?version=2024-10-08",
)
GRANITE_MODEL = os.environ.get("GRANITE_MODEL", "ibm/granite-3-8b-instruct")


class AssistantQuery(BaseModel):
    question: str


# --- Tool implementations (query the database above) ------------------------
def _district_lookup(district: str) -> dict | None:
    for d in load_all_districts():
        if d["district"] == district:
            return d
    return None


def _tool_get_district_supply(district: str) -> dict:
    d = _district_lookup(district)
    if not d:
        known = ", ".join(sorted(x["district"] for x in load_all_districts()))
        return {"error": f"Unknown district '{district}'. Known districts: {known}."}
    return {
        "district": d["district"],
        "predicted_supply_2018": d["predicted_supply_2018"],
        "confidence_label": d["confidence_label"],
        "supply_tier": d["supply_tier"],
        "residue_type": d["residue_type"],
        "harvest_window": d["harvest_window"],
    }


def _tool_get_top_hotspots(n: int = 3) -> dict:
    districts = sorted(
        load_all_districts(), key=lambda x: -float(x["predicted_supply_2018"])
    )[: max(1, min(int(n), 20))]
    return {
        "hotspots": [
            {
                "district": d["district"],
                "predicted_supply_2018": d["predicted_supply_2018"],
                "confidence_label": d["confidence_label"],
                "supply_tier": d["supply_tier"],
            }
            for d in districts
        ]
    }


def _tool_get_plant_utilization(plant_id: str = None) -> dict:
    plants = get_plant_utilization()
    if plant_id:
        for p in plants:
            if p["plant_id"] == plant_id:
                matched = [m["district"] for m in get_matches() if m["matched_plant_id"] == plant_id]
                return {
                    "plant_id": p["plant_id"],
                    "plant_name": p["plant_name"],
                    "annual_capacity": p["annual_capacity"],
                    "current_utilization": p["current_utilization"],
                    "utilization_pct": p["utilization_pct"],
                    "matched_districts": matched,
                }
        known = ", ".join(sorted(x["plant_id"] for x in load_all_plants()))
        return {"error": f"Unknown plant '{plant_id}'. Known plants: {known}."}
    return [
        {
            "plant_id": p["plant_id"],
            "utilization_pct": p["utilization_pct"],
            "current_utilization": p["current_utilization"],
            "annual_capacity": p["annual_capacity"],
        }
        for p in sorted(plants, key=lambda x: x["utilization_pct"])
    ]


def _tool_get_underused_plants() -> dict:
    plants = sorted(get_plant_utilization(), key=lambda p: p["utilization_pct"])
    return {
        "plants": [
            {"plant_id": p["plant_id"], "utilization_pct": p["utilization_pct"]} for p in plants
        ]
    }


def _tool_get_unmatched_districts() -> dict:
    matched_names = {m["district"] for m in get_matches()}
    unmatched = [d["district"] for d in load_all_districts() if d["district"] not in matched_names]
    return {"unmatched_districts": unmatched, "count": len(unmatched)}


def _sustainability_summary() -> dict:
    districts = load_all_districts()
    plants = load_all_plants()
    matches = get_matches()
    total_supply = sum(float(d["predicted_supply_2018"]) for d in districts)
    matched = sum(m["matched_supply"] for m in matches)
    utilization = {
        p["plant_id"]: round(
            100
            * sum(m["matched_supply"] for m in matches if m["matched_plant_id"] == p["plant_id"])
            / p["annual_capacity"],
            1,
        )
        for p in plants
    }
    return {
        "total_supply": round(total_supply, 1),
        "matched": round(matched, 1),
        "leftover": round(total_supply - matched, 1),
        "absorbed_pct": round(100 * matched / total_supply, 1),
        "utilization": utilization,
        "match_count": len(matches),
    }


TOOLS = {
    "get_district_supply": {
        "function": _tool_get_district_supply,
        "schema": {
            "name": "get_district_supply",
            "description": "Get predicted biomass supply and confidence for one Gujarat district.",
            "parameters": {
                "type": "object",
                "properties": {
                    "district": {"type": "string", "description": "District name, e.g. Amreli"}
                },
                "required": ["district"],
            },
        },
    },
    "get_top_hotspots": {
        "function": _tool_get_top_hotspots,
        "schema": {
            "name": "get_top_hotspots",
            "description": "List the top N districts by predicted biomass supply.",
            "parameters": {
                "type": "object",
                "properties": {"n": {"type": "integer", "description": "How many districts, default 3"}},
                "required": [],
            },
        },
    },
    "get_plant_utilization": {
        "function": _tool_get_plant_utilization,
        "schema": {
            "name": "get_plant_utilization",
            "description": "Get current utilization for all plants, or one plant by id (e.g. P1).",
            "parameters": {
                "type": "object",
                "properties": {"plant_id": {"type": "string", "description": "Plant id like P1 (optional)"}},
                "required": [],
            },
        },
    },
    "get_underused_plants": {
        "function": _tool_get_underused_plants,
        "schema": {
            "name": "get_underused_plants",
            "description": "List plants ranked least-utilized first.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_unmatched_districts": {
        "function": _tool_get_unmatched_districts,
        "schema": {
            "name": "get_unmatched_districts",
            "description": "List districts whose supply is not matched to any plant.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
}

_TOOL_NAMES = ", ".join(TOOLS)

SYSTEM_PROMPT = (
    "You are AgriFlow Assistant, helping a non-technical user understand biomass "
    "supply and plant utilization in Gujarat, India. "
    "When the question needs data from the system, reply with ONLY a JSON object "
    "of the form {\"tool\": \"<tool_name>\", \"args\": {<arguments>}} and nothing else. "
    f"Available tools: {_TOOL_NAMES}. "
    "Use the exact district name capitalization (e.g. Amreli, The Dangs). "
    "If the question can be answered without system data, answer directly in plain text. "
    "Never invent numbers that are not in the tool results."
)


def _call_granite(messages: list[dict], max_tokens: int = 400) -> str:
    """Call IBM watsonx chat API. Raises on failure — caller falls back.

    Supports the current ml/v1/text/chat endpoint (OpenAI-style response)
    and the legacy BAM v2 shape, parsing both defensively.
    """
    body: dict = {
        "model_id": GRANITE_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if WATSONX_PROJECT_ID:
        body["project_id"] = WATSONX_PROJECT_ID
    else:
        body["parameters"] = {"max_tokens": max_tokens, "temperature": 0.1}

    req = urllib.request.Request(
        WATSONX_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WATSONX_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # ml/v1/text/chat response: data["choices"][0]["message"]["content"].
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        pass
    # Legacy BAM v2 response: data["results"][0]["generated_text"].
    try:
        return data["results"][0]["generated_text"]
    except (KeyError, IndexError, TypeError):
        return data.get("generated_text", "")


def _rule_based_answer(q: str) -> dict:
    """Deterministic fallback so the endpoint always answers without an LLM."""
    plants = get_plant_utilization()

    if "underused" in q or "underutilized" in q or "underutilised" in q:
        lowest = min(plants, key=lambda p: p["utilization_pct"])
        return {
            "answer": (
                f"{lowest['plant_name']} is currently the most underused, running at "
                f"{lowest['utilization_pct']}% of its capacity."
            ),
            "supporting_data": {"plant_id": lowest["plant_id"]},
        }

    if "unused" in q or "unmatched" in q or "leftover" in q:
        matched_names = {m["district"] for m in get_matches()}
        unmatched = [d["district"] for d in load_all_districts() if d["district"] not in matched_names]
        if unmatched:
            return {
                "answer": f"These districts have supply that isn't fully matched to a plant: {', '.join(unmatched)}.",
                "supporting_data": {"districts": unmatched},
            }
        return {
            "answer": "All districts currently have some biomass matched to a plant.",
            "supporting_data": {},
        }

    if "sustain" in q or "total" in q or "matched" in q or "absorbed" in q or "burn" in q:
        s = _sustainability_summary()
        return {
            "answer": (
                f"Predicted supply is {s['total_supply']:,.1f} units, of which "
                f"{s['matched']:,.1f} is matched to plants ({s['absorbed_pct']}%). "
                f"That leaves {s['leftover']:,.1f} units — about "
                f"{100 - s['absorbed_pct']:.1f}% — as residue that would otherwise burn."
            ),
            "supporting_data": s,
        }

    if "highest" in q or "top" in q or "hotspot" in q or "biggest" in q:
        top = _tool_get_top_hotspots(3)["hotspots"]
        return {
            "answer": (
                "The highest predicted supply is "
                + ", ".join(f"{h['district']} ({h['predicted_supply_2018']:,.1f} units)" for h in top)
                + "."
            ),
            "supporting_data": {"hotspots": top},
        }

    return {
        "answer": (
            "I can answer questions like \"which district has the highest supply?\", "
            "\"which plant is most underused?\", \"what's unmatched?\", or \"what's the "
            "sustainability picture?\". For free-form questions, add a WATSONX_API_KEY "
            "environment variable to enable the IBM Granite assistant."
        ),
        "supporting_data": {},
    }


@app.post("/assistant/query")
def assistant_query(payload: AssistantQuery):
    question = payload.question.strip()
    if not WATSONX_API_KEY:
        return _rule_based_answer(question.lower())

    try:
        # Step 1: let Granite pick a tool (or answer directly).
        first = _call_granite(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ]
        ).strip()

        tool_call = None
        try:
            parsed = json.loads(first)
            if isinstance(parsed, dict) and "tool" in parsed:
                tool_call = parsed
        except json.JSONDecodeError:
            pass

        supporting_data = {}
        if tool_call and tool_call["tool"] in TOOLS:
            tool = TOOLS[tool_call["tool"]]
            args = tool_call.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            supporting_data = {"tool": tool_call["tool"], "result": tool["function"](**args)}
            evidence = json.dumps(supporting_data["result"], default=str)

            # Step 2: Granite writes the answer from the structured result.
            answer = _call_granite(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                    {
                        "role": "assistant",
                        "content": f"I looked up the data. Tool result: {evidence}",
                    },
                    {
                        "role": "user",
                        "content": "Write a short, plain-language answer to the original question "
                        "using that data. If the result contains an error, say so clearly.",
                    },
                ]
            ).strip()
            return {"answer": answer, "supporting_data": supporting_data}

        # Granite answered directly — no tool needed.
        return {"answer": first, "supporting_data": {}}
    except Exception as exc:  # any LLM/network failure -> deterministic fallback
        result = _rule_based_answer(question.lower())
        result["supporting_data"] = {
            **result.get("supporting_data", {}),
            "llm_error": str(exc),
        }
        return result