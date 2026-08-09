"""profit_analysis.py — network profit analysis on the current optimal matching.

Standalone reporting tool AND the backend's economics source. Attaches money
to the same matches the map shows, using the same transport rate matching.py
already reports (COST_PER_TON_KM) plus a residue feedstock price.

The route-economics math lives here (compute_route_economics) and api.py
imports it, so the /economics endpoint, the LLM's get_profit_analysis tool,
and this CLI always agree on the numbers. Deliberately NOT shown in the
frontend UI — this is a data/chat layer only.

Model (per route):
    revenue         = allocated_quantity * residue_price_per_tonne
    transport_cost  = distance_km * round_trip_factor * rate * allocated_quantity
    profit          = revenue - transport_cost
    margin_pct      = 100 * profit / revenue

Why these shapes:
  - 1 dataset unit = 1 tonne (same assumption impact.py documents).
  - Transport is linear in distance and quantity at the haulage rate
    (matching.py's COST_PER_TON_KM = 10.0 INR/t-km one-way by default).
    round_trip_factor (default 2.0) charges the empty return leg.
  - No plant-side processing cost: it is a per-unit constant that shifts
    every route's profit equally and never changes which route wins.
  - Residue price is a demo assumption, not audited market data — override
    with --price. Ballpark for paddy straw / groundnut shell / cotton stalk
    bought by CBG plants in India is roughly INR 1,500-3,500/t.

Storage: `--write` persists the per-route rows (with the assumptions used)
into the `route_economics` table that seed_agriflow_db.py creates, mirroring
how matching.py writes the `matches` table. The API computes the same view
live from the cached matches, so it never depends on this write having run.

Usage:
    python profit_analysis.py                 # print the analysis (INR 2.5k/t, rate 2)
    python profit_analysis.py --price 1500 --round-trip 1.0 --rate 10
    python profit_analysis.py --write         # also store rows in agriflow.db
"""

import argparse
import sqlite3
from pathlib import Path

from matching import COST_PER_TON_KM, compute_matches

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agriflow.db"

DEFAULT_RESIDUE_PRICE_PER_TONNE = 2500.0  # INR/t, demo assumption (ballpark feedstock value)
DEFAULT_ROUND_TRIP_FACTOR = 2.0


def enrich(m: dict, *, price: float, round_trip: float, rate: float) -> dict:
    """Attach revenue / transport cost / profit / margin to one match row.

    `m` is a raw matching row: district, plant_id, allocated_quantity,
    distance_km.
    """
    qty = float(m["allocated_quantity"])
    one_way_km = float(m["distance_km"])
    revenue = qty * price
    transport = one_way_km * round_trip * rate * qty
    profit = revenue - transport
    return {
        "district": m["district"],
        "plant_id": m["plant_id"],
        "allocated_quantity": round(qty, 1),
        "distance_km": round(one_way_km, 1),
        "revenue": round(revenue, 2),
        "transport_cost": round(transport, 2),
        "profit": round(profit, 2),
        "margin_pct": round(100 * profit / revenue, 1) if revenue > 0 else 0.0,
        "profitable": profit > 0,
    }


def compute_route_economics(
    matches: list[dict],
    *,
    price: float = DEFAULT_RESIDUE_PRICE_PER_TONNE,
    round_trip: float = DEFAULT_ROUND_TRIP_FACTOR,
    rate: float = COST_PER_TON_KM,
    plant_names: dict[str, str] | None = None,
) -> dict:
    """Full profit-analysis view over a list of raw match rows.

    Single source of truth for the economics math — the CLI prints this and
    api.py serves it (endpoint + LLM tool), so every consumer agrees.
    """
    rows = [enrich(m, price=price, round_trip=round_trip, rate=rate) for m in matches]
    if plant_names:
        for r in rows:
            r["matched_plant_name"] = plant_names.get(r["plant_id"], r["plant_id"])

    revenue = sum(r["revenue"] for r in rows)
    transport = sum(r["transport_cost"] for r in rows)
    profit = revenue - transport
    matched_units = sum(r["allocated_quantity"] for r in rows)
    ton_km = sum(r["distance_km"] * r["allocated_quantity"] for r in rows)

    by_plant: dict[str, list[dict]] = {}
    for r in rows:
        by_plant.setdefault(r["plant_id"], []).append(r)
    plant_rows = []
    for pid, rs in sorted(by_plant.items(), key=lambda kv: -sum(x["profit"] for x in kv[1])):
        p_rev = sum(x["revenue"] for x in rs)
        p_tr = sum(x["transport_cost"] for x in rs)
        plant_rows.append(
            {
                "plant_id": pid,
                "allocated_quantity": round(sum(x["allocated_quantity"] for x in rs), 1),
                "revenue": round(p_rev, 2),
                "transport_cost": round(p_tr, 2),
                "profit": round(p_rev - p_tr, 2),
                "margin_pct": round(100 * (p_rev - p_tr) / p_rev, 1) if p_rev else 0.0,
            }
        )

    return {
        "assumptions": {
            "residue_price_inr_per_tonne": price,
            "haulage_rate_inr_per_t_km_one_way": rate,
            "round_trip_factor": round_trip,
            "effective_haulage_rate_inr_per_t_km": round(rate * round_trip, 2),
            "breakeven_distance_km": round(price / (round_trip * rate), 1) if round_trip * rate else None,
            "unit_to_tonnes": "1 dataset unit = 1 tonne",
            "note": "Demo assumptions: residue price is a ballpark feedstock value, not audited market data.",
        },
        "totals": {
            "matched_units": round(matched_units, 1),
            "revenue": round(revenue, 2),
            "transport_cost": round(transport, 2),
            "transport_pct_of_revenue": round(100 * transport / revenue, 2) if revenue else 0.0,
            "profit": round(profit, 2),
            "margin_pct": round(100 * profit / revenue, 1) if revenue else 0.0,
            "avg_haul_km_per_unit": round(ton_km / matched_units, 1) if matched_units else 0.0,
            "route_count": len(rows),
        },
        "by_plant": plant_rows,
        "worst_routes": sorted(rows, key=lambda r: r["margin_pct"])[:5],
        "best_routes": sorted(rows, key=lambda r: -r["margin_pct"])[:3],
        "routes": rows,
    }


def write_route_economics(
    matches: list[dict],
    *,
    price: float,
    round_trip: float,
    rate: float,
    db_path: Path = DB_PATH,
) -> int:
    """Persist the per-route economics into the route_economics table."""
    rows = [enrich(m, price=price, round_trip=round_trip, rate=rate) for m in matches]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM route_economics")
        conn.executemany(
            """INSERT INTO route_economics
               (district, plant_id, allocated_quantity, distance_km,
                revenue, transport_cost, profit, margin_pct,
                residue_price, haulage_rate, round_trip_factor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    r["district"], r["plant_id"], r["allocated_quantity"],
                    r["distance_km"], r["revenue"], r["transport_cost"],
                    r["profit"], r["margin_pct"], price, rate, round_trip,
                )
                for r in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Profit analysis on the current optimal matching.")
    parser.add_argument("--price", type=float, default=DEFAULT_RESIDUE_PRICE_PER_TONNE,
                        help="Residue feedstock price in INR/tonne (demo assumption).")
    parser.add_argument("--round-trip", type=float, default=DEFAULT_ROUND_TRIP_FACTOR,
                        help="Round-trip transport factor (2.0 charges the empty return leg).")
    parser.add_argument("--rate", type=float, default=COST_PER_TON_KM,
                        help=f"One-way haulage rate in INR/t-km (default {COST_PER_TON_KM}).")
    parser.add_argument("--write", action="store_true",
                        help="Also store the per-route rows in agriflow.db (route_economics table).")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        districts = [
            dict(r) for r in conn.execute(
                "SELECT district, latitude, longitude, predicted_supply_2018, "
                "predicted_supply_2024, predicted_supply_2026 FROM districts"
            )
        ]
        plants = [
            dict(r) for r in conn.execute(
                "SELECT plant_id, plant_name, latitude, longitude, annual_capacity FROM plants"
            )
        ]
    finally:
        conn.close()

    matches = compute_matches(districts, plants, min_alloc=2000.0, solver="optimal")
    econ = compute_route_economics(
        matches,
        price=args.price,
        round_trip=args.round_trip,
        rate=args.rate,
        plant_names={p["plant_id"]: p["plant_name"] for p in plants},
    )

    if args.write:
        n = write_route_economics(matches, price=args.price, round_trip=args.round_trip, rate=args.rate)
        print(f"wrote {n} rows to the route_economics table\n")

    a = econ["assumptions"]
    t = econ["totals"]
    print("=" * 72)
    print("AgriFlow network profit analysis (optimal min-cost-flow routing)")
    print("=" * 72)
    print(f"residue price      : INR {a['residue_price_inr_per_tonne']:,.0f}/t   (demo assumption)")
    print(f"haulage rate       : INR {a['haulage_rate_inr_per_t_km_one_way']:,.2f}/t-km one-way, "
          f"x{a['round_trip_factor']:g} round trip = INR {a['effective_haulage_rate_inr_per_t_km']:,.2f}/t-km effective")
    print(f"breakeven distance : {a['breakeven_distance_km']:,.0f} km one-way")
    print(f"units matched      : {t['matched_units']:,.1f}")
    print()
    print(f"revenue           : INR {t['revenue']:>15,.2f}")
    print(f"transport cost    : INR {t['transport_cost']:>15,.2f}  ({t['transport_pct_of_revenue']:.2f}% of revenue)")
    print(f"network profit    : INR {t['profit']:>15,.2f}")
    print(f"network margin    : {t['margin_pct']:.2f}%")
    print(f"avg haul          : {t['avg_haul_km_per_unit']:,.1f} km/unit")
    print()

    print("per-plant P&L:")
    print(f"  {'plant':<6}{'units':>10}{'revenue INR':>16}{'transport INR':>16}{'profit INR':>16}{'margin':>9}")
    for p in econ["by_plant"]:
        print(f"  {p['plant_id']:<6}{p['allocated_quantity']:>10,.1f}{p['revenue']:>16,.2f}"
              f"{p['transport_cost']:>16,.2f}{p['profit']:>16,.2f}{p['margin_pct']:>8.2f}%")
    print()

    print("worst 5 routes by margin:")
    for r in econ["worst_routes"]:
        print(f"  {r['district']:16s} -> {r['plant_id']}  {r['allocated_quantity']:>9,.1f} t  "
              f"{r['distance_km']:>6.1f} km  profit INR {r['profit']:>13,.2f}  margin {r['margin_pct']:6.2f}%")
    print()
    print("best 3 routes by margin:")
    for r in econ["best_routes"]:
        print(f"  {r['district']:16s} -> {r['plant_id']}  {r['allocated_quantity']:>9,.1f} t  "
              f"{r['distance_km']:>6.1f} km  profit INR {r['profit']:>13,.2f}  margin {r['margin_pct']:6.2f}%")
    print()

    # Sensitivity: price x effective haulage rate.
    print("sensitivity - network profit (INR millions) at price x effective haulage rate:")
    print(f"  {'price \\ rate':>14}", end="")
    for eff_rate in (2.0, 4.0, 6.0, 10.0, 20.0):
        print(f"{eff_rate:>13.1f}", end="")
    print()
    for price in (1500.0, 2000.0, 2500.0, 3500.0):
        print(f"  {price:>13,.0f}", end="")
        for eff_rate in (2.0, 4.0, 6.0, 10.0, 20.0):
            p = sum(
                r["allocated_quantity"] * price - r["distance_km"] * eff_rate * r["allocated_quantity"]
                for r in econ["routes"]
            )
            print(f"{p / 1e6:>13.1f}", end="")
        print()
    print()

    total_supply = sum(
        (d.get("predicted_supply_2026") if d.get("predicted_supply_2026") is not None
         else d.get("predicted_supply_2024") if d.get("predicted_supply_2024") is not None
         else d.get("predicted_supply_2018") or 0)
        for d in districts
    )
    leftover = total_supply - t["matched_units"]
    print(f"leftover supply    : {leftover:,.1f} t - potential revenue of INR {leftover * args.price:,.0f} "
          f"if plant capacity existed (would otherwise be burned)")


if __name__ == "__main__":
    main()
