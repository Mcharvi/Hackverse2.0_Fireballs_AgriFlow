# AgriFlow — 24-Hour Execution Plan (v2)
### Team of 2 · AI/LLM person + ML person
### Revised to be structurally distinct from the Shell.ai Hackathon 2023 "Waste to Energy" solutions

---

## 0. Why This Version Is Different

All the reference repos you found solve the **same competition problem**: given ~2,400 fixed biomass sites and a distance matrix, forecast tonnage with XGBoost, then run an offline optimizer (Simulated Annealing / VNS / Gurobi) to pick **where to build depots** to minimize long-run cost. It's a *planning* problem, solved once, with no live interaction layer.

AgriFlow is not that. Keep this distinction sharp everywhere — README, pitch, live demo narration:

| Shell.ai repos | AgriFlow |
|---|---|
| "Where should we build depots?" (strategic, offline) | "Which existing plant should today's supply route to, right now?" (operational, live) |
| One-time optimization run | Continuous matching against current supply/demand |
| No user-facing interface | Interactive map + chat assistant a non-technical user can query |
| Forecast → optimize → report | Forecast → match → **ask it questions about why** |

The one-line pitch distinction, memorize it: *"They answer 'where to build.' We answer 'what to do today.'"*

---

## 1. Data Plan — Use the Real Dataset, Reframed

Instead of fully synthetic data, seed AgriFlow from the actual **Shell.ai 2023 dataset** (publicly available via those repos — `Biomass_History.csv`, `Distance_Matrix.csv`, district shapefiles, sourced from EarthStat cropland data and NASA elevation/rainfall data). This solves your "is this data fake" problem honestly and is a stronger answer than synthetic data.

**How to reframe it, not reuse it:**
- Their data is indexed by 2,418 anonymous harvesting *sites*. Aggregate it up to **district level** (15–20 districts) — this matches your heatmap UX and is a genuinely different unit of analysis, not just a renamed copy.
- Take one year of their historical biomass numbers as your "current supply" baseline, rather than running their forecasting pipeline. You're not competing on forecast accuracy; you don't need XGBoost re-trained from scratch under time pressure — a lightweight regression or bounded heuristic on top of real historical values is enough, and it's honest to say so.
- Generate your own 5–8 plant locations and capacities (fictional or representative) — the depots in their dataset are optimization *outputs*, not real facilities, so don't reuse those.
- Distance matrix: fine to reuse real inter-site distances if it saves time, or approximate with haversine distance between district centroids — simpler and defensible for a 24hr build.

**Citation line for your README/deck:** *"Biomass estimates informed by the Shell.ai 2023 Waste-to-Energy Challenge dataset (EarthStat cropland, NASA NEO). Forecasting, matching, and the query layer are our own implementation, built for real-time operational matching rather than depot-siting optimization."*

Do not open any of their notebooks and adapt code from them, even for logic reference — write your prediction and matching functions from your own understanding of the problem. If asked, you want to be able to say "we wrote this" without hedging.

---

## 2. Role Split

**Person A — AI/LLM (backend + LLM assistant + data ingestion)**
- FastAPI skeleton, SQLite models, seed script that loads and aggregates the real dataset to district level
- `/districts`, `/plants`, `/predictions`, `/matches` endpoints
- LLM assistant: function-calling layer over the SQLite data (same pattern as Task360 — query → structured lookup → generation)
- Backend deploy to Render

**Person B — ML (prediction + matching logic)**
- Data aggregation logic: site-level → district-level rollup from the real dataset
- Prediction heuristic/regression on top of real historical values → tonnage, confidence, harvest window
- Supply–demand matching: nearest viable plant by capacity + distance (your own simple algorithm, not their SA/VNS)
- Route ordering: nearest-neighbor heuristic (skip true VRP unless hour 14 checkpoint shows you're ahead)

**Frontend (shared, vibecoded)** — v0.dev / bolt.new for the map shell, detail panel, and chat UI; both wire real data in during integration blocks.

---

## 3. Hour-by-Hour

**Hour 0–1 · Lock scope, get the dataset, deploy skeleton**
- Together: download `Biomass_History.csv` + `Distance_Matrix.csv` from one of the reference repos' `dataset/` folders (or the original HackerEarth challenge page if still accessible)
- Agree on the API contract (exact JSON shape for districts/plants/predictions/matches)
- Push an empty FastAPI to Render and empty React app to Vercel, confirm one live fetch call works end to end

**Hour 1–5 · Sprint 1 (parallel)**
- Person B: write the site → district aggregation script against the real data; build the prediction heuristic on top of it, tested standalone
- Person A: SQLite schema, seed script (ingesting Person B's aggregated output), `/districts` + `/plants` endpoints live and deployed
- Frontend: vibecode map shell with Leaflet + district markers pointed at the real deployed API

**Hour 5–9 · Sprint 2 — Feature 1 + Feature 2 to working end-to-end**
- Person B: hand off prediction function → Person A wires `/predictions`; build matching + route-ordering logic
- Person A: `/matches` endpoint
- Frontend: heatmap coloring by tier, click-to-detail panel, route lines on map
- **Checkpoint at hour 9:** Features 1 and 2 must work live, end to end, on real (aggregated) data.

**Hour 9–13 · Feature 3 — LLM assistant**
- Person A: function-calling layer (`get_district_supply`, `get_plant_utilization`, `get_underused_plants`, etc.)
- Person B: define which query functions matter most for the demo script — you know the data
- Frontend: chat UI, vibecoded

**Hour 13–16 · Integration**
Merge into one cohesive app. Shared visual language, one nav, consistent loading states. Fix cross-feature bugs.

**Hour 16–18 · Deploy hardening**
Redeploy final versions. Run the full demo flow live, start to finish, 3+ times.

**Hour 18–20 · Buffer**
Sustainability summary card if ahead. Otherwise this is your slack for whatever broke.

**Hour 20–22 · Pitch**
Adapt your existing deck copy/voiceover script to what actually got built. Bake the differentiation line ("where to build" vs "what to do today") into the problem-statement slide, not just your back pocket for Q&A. Rehearse the live demo clicks.

**Hour 22–24 · Rest + final check**
Sleep matters more than a fourth feature. Final run-through, submit.

---

## 4. Pitch / Q&A Prep — Anticipate the Comparison Question

A judge who's seen a Shell.ai writeup may ask "isn't this the Shell.ai biomass problem?" Have this ready, near-verbatim:

*"We used the Shell.ai dataset for real biomass numbers instead of inventing synthetic data — but the problem we're solving is different. Shell.ai's challenge is a one-time strategic question: where should new depots be built to minimize long-run cost. AgriFlow answers an operational question that has to be re-solved every day: given today's supply and the plants that already exist, which district should route to which plant right now, and can a non-technical user just ask the system directly. That's why we built a matching engine instead of an offline optimizer, and why the LLM assistant is a core feature, not a bonus."*
