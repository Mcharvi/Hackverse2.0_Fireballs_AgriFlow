"""economics.py — biomass sale-profit vs transport-cost analysis.

A pure layer on top of matching.py's compute_matches(): every match already
has district, plant_id, allocated_quantity, and distance_km, so we can
attach money numbers without touching the matching or routing logic.

Per-match model (deliberately simple, deliberately explainable):

    revenue        = allocated_quantity * sale_price_per_unit
    transport_cost = distance_km * round_trip_factor
                     * cost_per_km_per_unit * allocated_quantity
    profit         = revenue - transport_cost
    margin_pct     = 100 * profit / revenue        (negative = route loses money)

Why these shapes:
  - Transport cost is linear in distance AND quantity: longer hauls cost
    more, and more volume costs more (more/bigger trips). A per-unit-km
    rate captures both effects with one parameter.
  - round_trip_factor (default 2.0) charges the return leg — a truck has to
    come back after dropping the load. One-way haversine distance alone
    would understate haulage cost by roughly half.
  - No fixed per-trip cost: matching.py's min_alloc economic-lot threshold
    already gates small loads; a second fixed-cost mechanism would
    double-count that exact decision.
  - No plant-side processing/handling cost: it's a per-unit constant applied
    identically to every route, so it shifts all profits equally and only
    moves the breakeven threshold — never changes which route wins.

Breakeven distance (one-way, round trip factored):
    profit = 0  =>  d = sale_price_per_unit / (round_trip_factor * cost_per_km_per_unit)
    With defaults (10.0 / (2.0 * 0.05)) that's 100 km — matches farther
    away than that lose money at these rates.

Everything is derived at request time — no new DB tables. All money values
are in abstract currency units computed from DEMO rates, not real market
prices. Rates are overridable so real buyer/haulage rates can be dropped in
without changing the analysis.

Usage:
    python economics.py                    # print summary + worst routes from the DB
    python economics.py --price 8 --rate 0.03 --round-trip 1.0
"""

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

from matching import compute_matches, haversine_km

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agriflow.db"

# Demo rates tuned so the analysis shows a believable mix (some routes
# profitable, some marginal) at Gujarat-scale hauls. With price 10 and
# rate 0.05 the breakeven is 100 km one-way — routes beyond that lose money.
DEFAULT_SALE_PRICE_PER_UNIT = 10.0
DEFAULT_COST_PER_KM_PER_UNIT = 0.05
DEFAULT_ROUND_TRIP_FACTOR = 2.0
DEFAULT_TOP_N = 5


def enrich_match(
    m: dict,
    *,
    sale_price_per_unit: float,
    cost_per_km_per_unit: float,
    round_trip_factor: float,
) -> dict:
    """Attach revenue / transport cost / profit / margin to one match."""
    qty = float(m["allocated_quantity"])
    one_way_km = float(m["distance_km"])
    revenue = qty * sale_price_per_unit
    transport_cost = one_way_km * round_trip_factor * cost_per_km_per_unit * qty
    profit = revenue - transport_cost
    return {
        "district": m["district"],
        "plant_id": m["plant_id"],
        "allocated_quantity": round(qty, 1),
        "distance_km": round(one_way_km, 1),
        "round_trip_km": round(one_way_km * round_trip_factor, 1),
        "revenue": round(revenue, 2),
        "transport_cost": round(transport_cost, 2),
        "profit": round(profit, 2),
        "margin_pct": round(100 * profit / revenue, 1) if revenue > 0 else 0.0,
        "profitable": profit > 0,
    }


def _aggregate(rows: list[dict]) -> dict:
    """Roll up a group of enriched routes into one summary row."""
    revenue = sum(r["revenue"] for r in rows)
    cost = sum(r["transport_cost"] for r in rows)
    profit = sum(r["profit"] for r in rows)
    return {
        "routes": len(rows),
        "allocated_quantity": round(sum(r["allocated_quantity"] for r in rows), 1),
        "revenue": round(revenue, 2),
        "transport_cost": round(cost, 2),
        "profit": round(profit, 2),
        "margin_pct": round(100 * profit / revenue, 1) if revenue > 0 else 0.0,
    }


def compute_economics(
    matches: list[dict],
    *,
    sale_price_per_unit: float = DEFAULT_SALE_PRICE_PER_UNIT,
    cost_per_km_per_unit: float = DEFAULT_COST_PER_KM_PER_UNIT,
    round_trip_factor: float = DEFAULT_ROUND_TRIP_FACTOR,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """Compute per-route economics plus totals, by-district, by-plant.

    `matches` are the raw output of matching.compute_matches() (plant_id /
    allocated_quantity / distance_km shape). Returns the same field names
    the matching layer uses so nothing else has to change.
    """
    if sale_price_per_unit <= 0:
        raise ValueError("sale_price_per_unit must be positive.")
    if cost_per_km_per_unit < 0:
        raise ValueError("cost_per_km_per_unit must be >= 0.")
    if round_trip_factor <= 0:
        raise ValueError("round_trip_factor must be positive.")

    rows = [
        enrich_match(
            m,
            sale_price_per_unit=sale_price_per_unit,
            cost_per_km_per_unit=cost_per_km_per_unit,
            round_trip_factor=round_trip_factor,
        )
        for m in matches
    ]

    by_district: dict[str, list[dict]] = defaultdict(list)
    by_plant: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_district[r["district"]].append(r)
        by_plant[r["plant_id"]].append(r)

    profitable = sum(1 for r in rows if r["profitable"])
    breakeven = (
        sale_price_per_unit / (round_trip_factor * cost_per_km_per_unit)
        if cost_per_km_per_unit > 0
        else None
    )

    worst = sorted(rows, key=lambda r: r["profit"])[:top_n]
    best = sorted(rows, key=lambda r: -r["profit"])[:top_n]

    return {
        "parameters": {
            "sale_price_per_unit": sale_price_per_unit,
            "cost_per_km_per_unit": cost_per_km_per_unit,
            "round_trip_factor": round_trip_factor,
            "currency_note": (
                "Abstract currency units from demo rates — not real market prices."
            ),
        },
        "breakeven_distance_km": round(breakeven, 2) if breakeven is not None else None,
        "summary": {
            **_aggregate(rows),
            "profitable_routes": profitable,
            "unprofitable_routes": len(rows) - profitable,
        },
        "by_district": {
            name: _aggregate(group) for name, group in sorted(by_district.items())
        },
        "by_plant": {
            pid: _aggregate(group) for pid, group in sorted(by_plant.items())
        },
        "worst_routes": worst,
        "best_routes": best,
    }


# ---------------------------------------------------------------------------
# CLI — print the analysis straight from the DB (read-only, mirrors
# matching.py's own DB path so the numbers match what /matches returns).
# ---------------------------------------------------------------------------
def _load_districts() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM districts").fetchall()]
    finally:
        conn.close()


def _load_plants() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM plants").fetchall()]
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AgriFlow route economics (read-only).")
    parser.add_argument("--price", type=float, default=DEFAULT_SALE_PRICE_PER_UNIT)
    parser.add_argument("--rate", type=float, default=DEFAULT_COST_PER_KM_PER_UNIT)
    parser.add_argument("--round-trip", type=float, default=DEFAULT_ROUND_TRIP_FACTOR)
    parser.add_argument("--min-alloc", type=float, default=2000.0)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args()

    districts = _load_districts()
    plants = _load_plants()
    matches = compute_matches(districts, plants, min_alloc=args.min_alloc)

    result = compute_economics(
        matches,
        sale_price_per_unit=args.price,
        cost_per_km_per_unit=args.rate,
        round_trip_factor=args.round_trip,
        top_n=args.top,
    )

    s = result["summary"]
    print(f"Routes analysed: {s['routes']}  (units: {s['allocated_quantity']:.0f})")
    print(
        f"Revenue {s['revenue']:.2f}  -  Transport {s['transport_cost']:.2f}  "
        f"=  Profit {s['profit']:.2f}  (margin {s['margin_pct']}%)"
    )
    print(
        f"Profitable: {s['profitable_routes']}  /  Unprofitable: {s['unprofitable_routes']}"
    )
    print(f"Breakeven distance (one-way): {result['breakeven_distance_km']} km")
    print("\nWorst routes (by profit):")
    for r in result["worst_routes"]:
        print(
            f"  {r['district']:16s} -> {r['plant_id']:3s}  "
            f"{r['distance_km']:6.1f} km  rev {r['revenue']:9.2f}  "
            f"cost {r['transport_cost']:9.2f}  profit {r['profit']:9.2f} "
            f"({r['margin_pct']:6.1f}%)"
        )


if __name__ == "__main__":
    main()
