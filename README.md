# AgriFlow — AI-Powered Biomass Intelligence Platform

**AgriFlow predicts where crop residue will be available, matches it to the nearest
processing plant, and optimizes collection logistics — turning a burning problem into
a revenue stream.**

India generates **500+ million tonnes of crop residue every year**. Most of it is
burned — not out of necessity, but because farmers have no visibility into who wants
to buy it. The cost: toxic air, rising emissions, and lost income for the people who
grew it. AgriFlow uses AI, geospatial analytics, and optimization to close that
visibility gap.

> **The one-line distinction:** strategic depot-siting solutions answer *"where should
> we build depots?"* (a one-time, offline planning problem). AgriFlow answers
> *"which existing plant should today's supply route to, right now?"* — an operational
> problem re-solved continuously, with a conversational interface a non-technical
> user can just ask.

---

## Features

- **District-level supply forecasting through 2026** — aggregates 2,418 site-level
  harvest observations into 20 Gujarat districts, extends the historical series with
  official DES Agristat crop-production data (via Residue-to-Product Ratios), and
  projects supply 3 harvests ahead with a conservative, bounded forecast.
- **Provably optimal supply–demand matching** — an exact min-cost max-flow
  transportation solver (successive shortest paths, ~60 lines, **no external solver
  dependency**) allocates every district's supply to the 6 processing plants so that
  **total haul ton-km is minimized to proven optimality**. A greedy heuristic is kept
  for head-to-head comparison.
- **Route ordering & economics** — nearest-first pickup ordering per plant, plus a
  full per-route P&L layer: revenue, transport cost, profit, and margin at configurable
  residue price and haulage rate (breakeven distance included).
- **Environmental impact metric** — converts "leftover supply that would otherwise be
  burned" into tonnes of CO₂ avoided, cars off the road, and tree-seedling
  equivalents (sourced methodology, documented assumptions).
- **Conversational AI assistant** — GPT-4o-mini function-calling agent with **10 tools**
  over the live database: multi-turn memory, typo-tolerant fuzzy name matching,
  multi-step tool chaining, **answers in English, Hindi, or Gujarati**, and a strict
  grounding rule (never states a number that isn't in a function result).
- **Proactive dashboard insights** — unprompted 2–3 bullet insights on load, phrased
  by the LLM from a fixed payload with a deterministic, LLM-free fallback.
- **Plant siting simulator** — "what if we built a 7th plant near district X with
  capacity N?" runs the *same* optimizer twice (baseline vs. hypothetical) and diffs
  the results: leftover reduction, new plant utilization, haul-cost savings.
- **Interactive GIS dashboard** — Leaflet map with supply heatmap tiers, plant
  utilization, matched-route table, impact cards, insight chips, and the chat panel,
  all in **EN / HI / GU**.

---

## Pipeline

```
 raw data ──► aggregate ──► forecast ──► match ──► route ──► economics ──► impact
                                                                              │
 users ◄── React + Leaflet dashboard ◄── FastAPI (SQLite) ◄───────────────────┘
                ▲
                └── LLM assistant (function calling over the same loaders)
```

| Stage | Script / module | Output |
|---|---|---|
| 1. Source data | Shell.ai 2023 agri-waste dataset (2,418 sites, 2010–2017) | `agriflow_reference_data_v2/` |
| 2. Site → district aggregation | `prepare_agriflow_data.py` | district/year biomass, cropland, weather, elevation; 20-district selection (7 low / 6 mid / 7 high supply) |
| 3. Crop-area composition layer | `process_cropgrids.py` (CROPGRIDS v1.08 zonal sums) | `agriflow_crop_composition.csv` |
| 4. 2026 supply extension | `fetch_apy_gujarat.py` + `extend_supply_2026.py` (DES Agristat APY × RPR, calibrated to Shell.ai units) | `agriflow_district_residue_2010_2023.csv`, updated `agriflow_district_supply.csv` |
| 5. Seed database | `seed_agriflow_db.py` | `agriflow.db` (districts, plants, predictions, crop_composition, matches, route_economics) |
| 6. Matching & routing | `matching.py` (min-cost flow + pickup order) | optimal `matches` (computed live by the API, persistable with `--write`/default run) |
| 7. Economics | `profit_analysis.py` | per-route & network P&L (served at `/economics`) |
| 8. Impact | `impact.py` | CO₂-avoided metric (served at `/impact`) |
| 9. Assistant | `llm_assistant.py` | `/assistant/query`, `/assistant/insights` |
| 10. API + UI | `api.py` (FastAPI) + `frontend/` (React, Vite, Leaflet) | live dashboard & chat |

---

## The algorithm

### 1. Aggregation & district selection

The Shell.ai dataset is indexed by ~2,400 anonymous harvesting **sites**. AgriFlow
aggregates site-level observations to **district/year** level (sum of biomass,
cropland, precipitation, elevation means, site counts), then selects a spread of
20 Gujarat districts (7 lower-, 6 middle-, 7 higher-supply by 2017 baseline) so the
demo keeps visible low/medium/high contrast. This is a genuinely different unit of
analysis from the original challenge, not a renamed copy.

### 2. Forecasting

The forecast is deliberately **conservative** and honest about what it is:

```
forecast = 0.70 × trailing 3-year mean + 0.30 × linear-trend extrapolation
final    = clip(forecast, trailing mean ± 15%)
```

- `trend_r2` is retained as a **diagnostic**, never presented as a statistical
  confidence probability.
- `confidence_score_heuristic` combines recent 3-year stability and trend fit —
  surfaced in the UI only as **High / Moderate / Low**.
- **2026 extension:** official DES Agristat district Area/Production/Yield
  (2010-11 → 2022-23, all seasons) is converted to residue via standard
  Residue-to-Product Ratios (rice 1.5, wheat 1.5, jowar 1.8, bajra 2.0, maize 2.0,
  gram 1.2, arhar 1.5, groundnut 1.0, sesamum 1.5, rapeseed & mustard 1.5,
  castor 2.5, soyabean 1.5, cotton 3.0, sugarcane 0.3), calibrated per district to
  the Shell.ai dimensionless units at its 2017 baseline, then projected
  **iteratively** (each forecast year feeds the next) to 2024 → 2025 → 2026.
- **Validation:** the calibrated APY residue series reproduces the original
  Shell.ai 2015–17 rolling mean within ~±15% for all 20 districts — official
  production data and the challenge dataset tell the same story.

### 3. Matching — exact min-cost max-flow

The core insight: **greedy nearest-plant matching is *not* optimal.** Assigning each
district to its nearest plant in isolation lets a big district fill a plant a distant
district needs more, inflating total ton-km. AgriFlow instead solves the classic
transportation problem (20 districts × 6 plants = 120 continuous allocation variables)
to **proven optimality** with a hand-written successive-shortest-paths min-cost
max-flow:

- Objective: **minimize total haul ton-km** (equivalently haul cost, since the
  per-ton-km rate is a constant scale factor), among all flows that absorb every
  unit the plants can take.
- `min_alloc` (default 2,000 units) is the **economic lot threshold** — allocations
  below it are dropped as fragments and the leftover is re-solved against the freed
  capacity until nothing economically viable remains. This is the answer to "why is
  a plant not at 100% utilization?"
- Leftover supply is the difference between total supply and matched quantity —
  a **capacity limit, not a routing inefficiency**.
- `--solver greedy` / `--compare` runs the old nearest-first heuristic for an
  honest, numbers-based before/after comparison.

### 4. Route ordering

Nearest-first pickup ordering per plant — a simple, documented heuristic, not a full
VRP (vehicle routing is out of scope for the demo). Optional real road distances via
OSRM are stubbed in `precompute_road_distances.py` (`road_routes` table); pairs
without a cached route transparently fall back to haversine.

### 5. Route economics

```
revenue        = allocated_quantity × residue_price_per_tonne
transport_cost = distance_km × round_trip_factor × rate × allocated_quantity
profit         = revenue − transport_cost
margin_pct     = 100 × profit / revenue
```

- Defaults: residue ₹2,500/t (demo feedstock ballpark), haulage ₹10/t-km one-way,
  `round_trip_factor = 2.0` (empty return leg charged) → effective ₹20/t-km,
  **breakeven distance 125 km** one-way.
- No plant-side processing cost: a per-unit constant that shifts every route's
  profit equally and never changes which route wins.
- **Current demo state** (optimal matching): revenue ₹33.27 Cr, transport ₹5.39 Cr
  (16.2% of revenue), network profit ₹27.88 Cr, **83.8% margin**, avg haul
  20.3 km/unit — well inside breakeven.

### 6. Impact

```
CO₂_avoided = leftover_tonnes × 1.35 t/t        (Ni et al. 2015, measured combustion EF)
cars_off_road = CO₂_avoided / 4.6               (EPA GHG Equivalencies)
seedlings     = CO₂_avoided × 16.5              (EPA, seedlings grown 10 yrs)
```

Current demo: ~103,870 t leftover → **~140,224 t CO₂ avoided** (~30,500 cars off the
road for a year, ~2.3M seedlings). Gross combustion CO₂, policy framing — not IPCC
Tier 1 net-GHG accounting (stated in the code and API).

### 7. LLM assistant

`llm_assistant.py` implements a **function-calling agent loop** (no framework):

```
question ──► model picks tool(s) ──► function hits the real DB via api.py loaders
          ◄─ grounded tool results ──► model phrases answer (1–3 sentences)
```

- **10 tools:** `get_district_supply`, `get_top_supply_districts`,
  `get_unmatched_districts`, `get_underused_plants`, `get_nearest_plant`,
  `get_plant_details`, `get_district_matches`, `get_haul_stats`,
  `get_profit_analysis`, `simulate_plant`.
- **Grounding:** the system prompt forbids stating any number not present in a
  function result; unknown data → plain "I don't have that data"; fuzzy name matches
  are announced, not silently assumed; `functions_called` is returned with every
  answer for auditability.
- **Reliability & cost controls:** `MAX_TOOL_ITERATIONS = 5` (runaway-loop cap),
  `MAX_HISTORY_TURNS = 20`, single-shot `generate_insights` (deliberately *not* the
  agent loop — fixed payload, one call, JSON mode), deterministic LLM-free fallback
  insights, fail-soft structured errors (no raw 500s / no leaked paths).
- **Language:** EN / HI / GU — answers always in the language the user picked,
  regardless of how the question was asked.
- **One source of truth:** every tool uses the *same loaders* as the API endpoints,
  so the chat can never contradict the map.

### 8. Plant siting simulator

A hypothetical plant is just another `{plant_id, lat, lon, capacity}` appended to the
real plant list; `compute_matches()` runs twice (baseline vs. simulated) and the
response diffs the two runs — same algorithm, zero new logic. Exposed as
`POST /simulate/plant` and as the assistant's `simulate_plant` tool.

---

## Data sources & attribution

- **Biomass estimates** — Shell.ai 2023 Agricultural Waste Challenge dataset
  (EarthStat cropland, NASA-derived environmental inputs). Aggregated site → district,
  never reused as an offline depot-siting solution.
- **Crop-area composition** — CROPGRIDS v1.08 (Tang et al., 2024, *Scientific Data*,
  CC BY 4.0, https://doi.org/10.6084/m9.figshare.22491997), zonal-summed over
  geoBoundaries gbOpen ADM2 district boundaries (CC BY 4.0).
- **2026 extension** — DES Agristat portal (https://data.desagri.gov.in,
  Government of India) district APY, 2010-11 → 2022-23; RPR values from Indian biomass
  assessments (ICAR, NITI Aayog task force reports, Jain et al. 2018).
- **Impact factors** — Ni et al. 2015 (*Atmospheric Environment* 123(B), measured
  combustion EF), EPA Greenhouse Gas Equivalencies Calculator, Jain et al. 2014
  (India residue-burning inventory, base year 2008-09).
- **Plants** — six real operating reference facilities from the MNRE Biourja CBG
  plant list, GEDA generation reports, and public commissioning records. Capacities
  are demo rates in dataset biomass units/year.

**Judge-safe wording:** *"AgriFlow uses historical Shell.ai agricultural-waste data as
a reference dataset. We aggregate the original site-level observations to district
level, apply our own conservative prediction method, and then perform our own supply
matching and route optimization using synthetic processing facilities."*

> **Critical unit note:** the original challenge states *"all quantities/values
> provided in these datasets are dimensionless."* AgriFlow therefore labels biomass as
> **dataset biomass units**, not tonnes (except where `1 unit = 1 t` is explicitly
> assumed in `impact.py` / `profit_analysis.py`).

---

## Repository layout

```
agriflow-24hr-hackathon-plan-v2.md   build plan & pitch prep
api.py                               FastAPI backend (all endpoints, live matching cache)
llm_assistant.py                     function-calling assistant + proactive insights
matching.py                          exact min-cost-flow matching, routing, CLI (--compare)
profit_analysis.py                   route/network P&L (CLI + API source)
impact.py                            CO₂-avoided metric
seed_agriflow_db.py                  SQLite schema + seeding from CSVs
prepare_agriflow_data.py             site → district aggregation (needs biomass_long.csv)
extend_supply_2026.py                DES Agristat APY → 2026 forecast extension
fetch_apy_gujarat.py                 DES Agristat downloader (cached in data_cache/)
process_cropgrids.py                 CROPGRIDS v1.08 zonal sums → crop_composition.csv
precompute_road_distances.py         optional OSRM road-routes cache (needs routing.py)
api-contract.json                    generated API sample payloads
agriflow.db                          seeded SQLite database (local; gitignored — seed it locally or on deploy)
agriflow_*.csv                       validated reference data (committed evidence layers)
agriflow_reference_data_v2/          source dataset package (with its own README)
data_cache/                          downloaded raw data (gitignored)
frontend/                            React + Vite + Leaflet dashboard (EN/HI/GU)
test-ui.html                         single-file demo UI (no build step)
render.yaml                          Render Blueprint for the API
requirements.txt                     API runtime deps (minimal)
```

---

## Getting started

```bash
# 1. Backend
pip install -r requirements.txt
cp .env.example .env                # set OPENAI_API_KEY (assistant/insights need it; app still boots without)
python seed_agriflow_db.py          # build agriflow.db
python matching.py --dry-run        # preview the optimal plan without writing
python matching.py                  # persist matches (optional; API computes them live anyway)
python profit_analysis.py           # network P&L at default assumptions
uvicorn api:app --reload --port 8000

# 2. Frontend (separate terminal)
cd frontend
npm install
VITE_API_URL=http://127.0.0.1:8000 npm run dev     # point at local API, or omit for the deployed one

# 3. Rebuild data layers (only if regenerating reference data; these need
#    numpy/pandas/scikit-learn, plus netCDF4+shapely for process_cropgrids)
python prepare_agriflow_data.py     # needs biomass_long.csv in repo root
python process_cropgrids.py         # needs CROPGRIDS NetCDF in data_cache/cropgrids/
python fetch_apy_gujarat.py && python extend_supply_2026.py
```

Environment variables:

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | for assistant | LLM calls; app boots without it, chat fails soft |
| `VITE_API_URL` | frontend | override the default (deployed) API base URL |

---

## API reference

| Endpoint | Description |
|---|---|
| `GET /health` | DB presence check |
| `GET /districts` | all 20 districts + crop mix, forecasts to 2026, confidence labels |
| `GET /districts/{name}` | one district |
| `GET /crops` | CROPGRIDS crop-area composition table |
| `GET /predictions` · `GET /predictions/{district}` | forecast rows: 2018 forecast, 2019–22 actuals, 2024–26 projections |
| `GET /plants` · `GET /plants/{plant_id}` | plants with live utilization % + matched districts |
| `GET /matches` | optimal district→plant matches (cached per process) |
| `GET /economics` | network + per-plant + per-route P&L |
| `GET /impact` | CO₂-avoided metric |
| `POST /assistant/query` | chat: `{question, history[], language}` → grounded answer + `functions_called` |
| `GET /assistant/insights` | proactive dashboard bullets (TTL-cached, never raises) |
| `POST /simulate/plant` | hypothetical plant siting: baseline vs simulated diff |

Sample conversation:

```
Q: Which district has the highest biomass supply next year?
A: Amreli, with a predicted supply of 42,558 biomass units for 2026.
   [supporting_data.functions_called: get_top_supply_districts(1)]
```

---

## Deployment

`render.yaml` is a Render Blueprint (free tier):

- **API:** `pip install -r requirements.txt && python seed_agriflow_db.py`, start
  `uvicorn api:app --host 0.0.0.0 --port $PORT`.
- Set `OPENAI_API_KEY` as a Render environment secret.
- Frontend: static Vite build (`npm run build`), served from Render or any static
  host; point `VITE_API_URL` at the deployed API.

---

## Honesty notes

- All forecasts are **heuristics with documented recipes**, not tuned ML models —
  confidence is labeled High/Moderate/Low, never a probability.
- Residue price, haulage rate, and plant capacities are **demo assumptions**
  (ballpark CBG feedstock values), stated wherever they appear.
- The matching engine is the *provably optimal* piece; everything else is
  deliberately conservative and cited.

## License

Data and code are shared for the Hackverse 2.0 (Manipal Institute of Technology,
Bengaluru) demo. Third-party datasets retain their own licenses (CROPGRIDS CC BY 4.0,
geoBoundaries CC BY 4.0, DES Agristat Government of India open data, Shell.ai 2023
challenge dataset). Not for commercial use without attribution.
