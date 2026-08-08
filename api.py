"""
AgriFlow backend — Hour 0-3 skeleton.

In-memory data for now (real districts/plants, from the validated CSVs).
Person B: swap DISTRICTS/PLANTS for a real SQLite read once the seed
script is ready — the endpoint shapes below should not need to change.

Run:
    pip install fastapi uvicorn --break-system-packages   # if needed
    uvicorn api:app --reload --port 8000
"""

import math
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="AgriFlow API")

# Dev-only: wide open CORS so the test UI / vibecoded frontend can hit this
# from anywhere. Tighten to the real Vercel URL before the final demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Residue type -> harvest window (fixes the "every district identical" issue)
# ---------------------------------------------------------------------------
HARVEST_WINDOWS = {
    "Groundnut shell / cotton stalk": "Oct–Dec",
    "Groundnut shell": "Oct–Dec",
    "Rice straw / mixed residue": "Sep–Nov",
    "Rice straw": "Sep–Nov",
    "Mixed agricultural residue": "Sep–Dec",
    "Cumin/fennel residue": "Nov–Jan",
    "Pulse residue": "Feb–Apr",
    "Castor stalk / mixed residue": "Nov–Jan",
}

# ---------------------------------------------------------------------------
# Districts — from agriflow_district_supply.csv
# ---------------------------------------------------------------------------
_RAW_DISTRICTS = [
    ("Amreli", 21.480991, 71.329378, 37242.91, 33540.806, 32989.178, 33375.317, 0.023, 47.7, "Low", 7465.5, 8.395, 127.086, 116, "Groundnut shell / cotton stalk", "official district crop profile", "High"),
    ("Rajkot", 22.122745, 70.709604, 44996.159, 21467.252, 22480.176, 21771.129, 0.037, 32.0, "Low", 6641.5, 6.565, 135.914, 105, "Groundnut shell / cotton stalk", "official crop profile", "High"),
    ("Surendranagar", 22.892453, 71.594366, 22698.586, 20535.134, 20879.435, 20638.424, 0.063, 54.8, "Low", 5338.0, 4.971, 64.312, 96, "Groundnut shell / cotton stalk", "official crop profile", "High"),
    ("Morbi", 22.892876, 70.994324, 23320.198, 19312.785, 19386.985, 19335.045, 0.096, 51.8, "Low", 4143.5, 4.84, 56.091, 77, "Mixed agricultural residue", "demo assumption", "High"),
    ("Bhavnagar", 21.621486, 71.956497, 24931.391, 19390.101, 18307.13, 19065.21, 0.06, 50.1, "Low", 4625.0, 8.734, 41.33, 100, "Groundnut shell", "official crop profile", "High"),
    ("Ahmadabad", 22.862573, 72.16126, 17041.899, 17461.897, 16075.469, 17045.968, 0.103, 58.7, "Moderate", 5619.0, 5.757, 23.686, 102, "Rice straw / mixed residue", "official crop profile", "High"),
    ("Jamnagar", 22.459506, 70.260924, 25918.495, 15548.442, 18176.552, 16336.875, 0.076, 39.5, "Low", 3691.5, 5.821, 53.167, 72, "Groundnut shell / cotton stalk", "official district crop profile", "High"),
    ("Surat", 21.354159, 73.02082, 9735.6, 10297.089, 11023.635, 10515.053, 0.204, 61.9, "Moderate", 2407.5, 11.52, 51.183, 60, "Rice straw", "official crop profile", "Medium"),
    ("Patan", 23.843651, 71.73231, 8750.403, 10416.458, 10315.406, 10386.142, 0.112, 56.8, "Moderate", 5347.5, 4.854, 48.299, 87, "Cumin/fennel residue", "official crop profile", "Medium"),
    ("Kheda", 22.932698, 72.947661, 7675.523, 8086.568, 8499.148, 8210.342, 0.319, 65.8, "Moderate", 3611.5, 7.291, 61.34, 47, "Rice straw", "official crop profile", "Medium"),
    ("Chhota Udaipur", 22.288349, 73.890618, 7742.487, 7965.956, 8634.648, 8166.564, 0.044, 53.4, "Low", 1624.0, 10.133, 181.298, 57, "Pulse residue", "official crop profile", "Medium"),
    ("Gandhinagar", 23.270535, 72.646102, 6845.399, 7698.58, 7793.09, 7726.933, 0.013, 53.9, "Low", 3441.5, 6.45, 79.894, 47, "Mixed agricultural residue", "demo assumption", "Medium"),
    ("Sabar Kantha", 23.836993, 72.993614, 6900.154, 5802.356, 6256.084, 5938.474, 0.295, 63.1, "Moderate", 2198.0, 7.656, 198.719, 32, "Castor stalk / mixed residue", "official crop profile", "Medium"),
    ("Tapi", 21.296815, 73.726413, 4109.696, 4507.959, 5038.179, 4667.025, 0.302, 63.4, "Moderate", 2740.0, 11.262, 121.578, 64, "Mixed agricultural residue", "demo assumption", "Low"),
    ("Porbandar", 21.727127, 69.718608, 4519.609, 3138.89, 4006.87, 3399.284, 0.091, 45.5, "Low", 2094.0, 6.805, 36.872, 47, "Mixed agricultural residue", "demo assumption", "Low"),
    ("Navsari", 20.892172, 73.037348, 2646.733, 2939.821, 3112.068, 2991.495, 0.172, 59.2, "Moderate", 804.0, 17.04, 33.061, 33, "Rice straw", "official crop profile", "Low"),
    ("Valsad", 20.536067, 73.096464, 2082.183, 2241.89, 2207.698, 2231.632, 0.094, 57.1, "Moderate", 147.5, 21.846, 104.3, 30, "Rice straw", "official crop profile", "Low"),
    ("Mahisagar", 23.289337, 73.632036, 1800.968, 1997.984, 2045.052, 2012.104, 0.016, 55.4, "Moderate", 1525.0, 9.153, 143.607, 28, "Pulse residue", "demo assumption", "Low"),
    ("Dohad", 22.892283, 74.107701, 608.354, 579.025, 567.488, 575.564, 0.04, 58.8, "Moderate", 1422.5, 10.408, 275.233, 30, "Pulse residue", "official crop profile", "Low"),
    ("The Dangs", 20.892686, 73.644758, 97.63, 113.172, 130.249, 118.295, 0.234, 60.4, "Moderate", 62.5, 14.855, 272.211, 19, "Mixed agricultural residue", "demo assumption", "Low"),
]

DISTRICT_FIELDS = [
    "district", "latitude", "longitude", "baseline_supply_2017", "rolling_3yr_supply",
    "trend_forecast_2018", "predicted_supply_2018", "trend_r2", "confidence_score",
    "confidence_label", "cropland_2017", "avg_precipitation_2017", "avg_elevation_2017",
    "site_count_2017", "residue_type", "residue_type_source", "supply_tier",
]

DISTRICTS = []
for row in _RAW_DISTRICTS:
    d = dict(zip(DISTRICT_FIELDS, row))
    d["harvest_window"] = HARVEST_WINDOWS.get(d["residue_type"], "Sep–Nov")
    DISTRICTS.append(d)

# ---------------------------------------------------------------------------
# Plants — representative district coords reused as plant location
# ---------------------------------------------------------------------------
_PLANT_SPECS = [
    ("P1", "AgriFlow Plant 1", "Rajkot", 30000),
    ("P2", "AgriFlow Plant 2", "Bhavnagar", 25000),
    ("P3", "AgriFlow Plant 3", "Ahmadabad", 22000),
    ("P4", "AgriFlow Plant 4", "Jamnagar", 22000),
    ("P5", "AgriFlow Plant 5", "Surat", 18000),
    ("P6", "AgriFlow Plant 6", "Kheda", 18000),
]

_district_by_name = {d["district"]: d for d in DISTRICTS}

PLANTS = []
for pid, name, rep_district, capacity in _PLANT_SPECS:
    rd = _district_by_name[rep_district]
    PLANTS.append({
        "plant_id": pid,
        "plant_name": name,
        "representative_district": rep_district,
        "latitude": rd["latitude"],
        "longitude": rd["longitude"],
        "annual_capacity": capacity,
        "capacity_unit": "dataset biomass units/year",
        "facility_status": "synthetic demo facility",
    })

_plant_by_id = {p["plant_id"]: p for p in PLANTS}


# ---------------------------------------------------------------------------
# Distance + matching (computed at request time, no stored distance file)
# ---------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def compute_matches():
    """
    Greedy nearest-viable-plant matching, largest-supply districts first.
    Not full VRP -- deliberately simple, deliberately explainable live.
    """
    remaining = {p["plant_id"]: p["annual_capacity"] for p in PLANTS}
    route_counter = {p["plant_id"]: 0 for p in PLANTS}
    matches = []

    for d in sorted(DISTRICTS, key=lambda x: -x["predicted_supply_2018"]):
        candidates = sorted(
            PLANTS,
            key=lambda p: haversine_km(d["latitude"], d["longitude"], p["latitude"], p["longitude"]),
        )
        for p in candidates:
            if remaining[p["plant_id"]] > 0:
                dist = haversine_km(d["latitude"], d["longitude"], p["latitude"], p["longitude"])
                matched_supply = min(d["predicted_supply_2018"], remaining[p["plant_id"]])
                remaining[p["plant_id"]] -= matched_supply
                route_counter[p["plant_id"]] += 1
                matches.append({
                    "district": d["district"],
                    "matched_plant_id": p["plant_id"],
                    "matched_plant_name": p["plant_name"],
                    "distance_km": round(dist, 1),
                    "matched_supply": round(matched_supply, 1),
                    "route_order": route_counter[p["plant_id"]],
                })
                break
    return matches


def compute_plant_utilization():
    matches = compute_matches()
    used = {p["plant_id"]: 0.0 for p in PLANTS}
    for m in matches:
        used[m["matched_plant_id"]] += m["matched_supply"]

    result = []
    for p in PLANTS:
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
    return {"status": "ok"}


@app.get("/districts")
def get_districts():
    return DISTRICTS


@app.get("/districts/{district_name}")
def get_district(district_name: str):
    d = _district_by_name.get(district_name)
    if not d:
        raise HTTPException(status_code=404, detail=f"District '{district_name}' not found")
    return d


@app.get("/plants")
def get_plants():
    return compute_plant_utilization()


@app.get("/plants/{plant_id}")
def get_plant(plant_id: str):
    plants = compute_plant_utilization()
    for p in plants:
        if p["plant_id"] == plant_id:
            matched_districts = [
                m["district"] for m in compute_matches() if m["matched_plant_id"] == plant_id
            ]
            return {**p, "matched_districts": matched_districts}
    raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")


@app.get("/matches")
def get_matches():
    return compute_matches()


# ---------------------------------------------------------------------------
# Assistant — STUB for hour 0-3. Real LLM function-calling layer goes in
# during the Hour 9-13 sprint (same pattern as Task360: question -> pick a
# function -> query the data above -> generate a natural-language answer).
# ---------------------------------------------------------------------------
class AssistantQuery(BaseModel):
    question: str


@app.post("/assistant/query")
def assistant_query(payload: AssistantQuery):
    q = payload.question.lower()
    plants = compute_plant_utilization()

    if "underused" in q or "underutilized" in q or "underutilised" in q:
        lowest = min(plants, key=lambda p: p["utilization_pct"])
        return {
            "answer": (
                f"{lowest['plant_name']} is currently the most underused, running at "
                f"{lowest['utilization_pct']}% of its capacity."
            ),
            "supporting_data": {"plant_id": lowest["plant_id"]},
        }

    if "unused" in q or "unmatched" in q:
        matched_names = {m["district"] for m in compute_matches()}
        unmatched = [d["district"] for d in DISTRICTS if d["district"] not in matched_names]
        if unmatched:
            return {
                "answer": f"These districts have supply that isn't matched to a plant yet: {', '.join(unmatched)}.",
                "supporting_data": {"districts": unmatched},
            }
        return {
            "answer": "All districts currently have some biomass matched to a plant.",
            "supporting_data": {},
        }

    return {
        "answer": (
            "This is a placeholder response -- the real LLM function-calling layer "
            "isn't wired in yet. Try asking about 'underused plants' or 'unused biomass' "
            "for a working example of the pattern."
        ),
        "supporting_data": {},
    }
