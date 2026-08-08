"""matching.py — AgriFlow supply–demand matching + route ordering.

Person B's operational layer: given predicted district supply and plant
capacities, assign each district's supply to the nearest plant that can take
it, splitting oversupply across plants and recording what can't be absorbed.

Design choices (documented so we can answer "why this algorithm?" honestly):
  - Deterministic greedy, written from first principles — NOT a port of the
    Shell.ai depot-siting optimizer (that answers "where to build"; this
    answers "what to do today").
  - Districts are processed largest-supply first, so the biggest hotspots get
    served before smaller ones; ties broken by name for determinism.
  - Each district draws from its nearest plant with remaining capacity,
    splitting across plants when one plant can't take the whole supply
    (e.g. Amreli exceeds any single plant's capacity).
  - Unabsorbed supply is NOT stored in `matches` — it is the difference
    between total predicted supply and matched quantity, visible to the
    frontend and the LLM assistant as "leftover that would otherwise burn".
  - Route ordering is nearest-first per plant (a simple, honest heuristic,
    not a full VRP).
  - Allocations below an economic lot threshold (default 2,000 units) are
    skipped: dispatching a pickup for a fragment costs more than it's worth,
    so that capacity sits idle instead. This is why plants can end up under
    100% utilized, and it's a defensible answer in Q&A.

Usage:
    python matching.py                     # recompute matches and write them into agriflow.db
    python matching.py --dry-run           # print the plan without writing anything
    python matching.py --min-alloc 1000    # tune the economic lot threshold
"""

import argparse
import math
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agriflow.db"
EARTH_RADIUS_KM = 6371.0

# Demo transport-rate assumption (currency per unit-km). The dataset units are
# dimensionless biomass units, so this is a labelled estimate, not a real rupee
# cost. Tune freely; every number in /analysis traces back to this constant.
TRANSPORT_RATE_PER_UNIT_KM = 0.05


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def load_districts(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [
        dict(r)
        for r in conn.execute(
            "SELECT district, latitude, longitude, predicted_supply_2018 FROM districts"
        )
    ]


def load_plants(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [
        dict(r)
        for r in conn.execute(
            "SELECT plant_id, latitude, longitude, annual_capacity FROM plants"
        )
    ]


def load_terrain(conn: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """Terrain cost lookups keyed by (district, plant_id). Empty if the
    terrain table doesn't exist yet (matcher falls back to haversine)."""
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT district, plant_id, elevation_gain_m, slope_pct, "
            "terrain_multiplier, effective_km FROM terrain"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {(r["district"], r["plant_id"]): dict(r) for r in rows}


def _route_cost(district: dict, plant: dict, qty: float, effective_km: float) -> dict:
    """Cost fields for one match row (labelled demo-rate estimate)."""
    cost_index = qty * effective_km          # unit-km, assumption-free
    est_cost = cost_index * TRANSPORT_RATE_PER_UNIT_KM
    return {
        "cost_index": round(cost_index, 1),
        "estimated_cost": round(est_cost, 1),
    }


def compute_matches(
    districts: list[dict],
    plants: list[dict],
    min_alloc: float = 2000.0,
    terrain: dict[tuple[str, str], dict] | None = None,
) -> list[dict]:
    """Greedy supply–demand matching. Returns a list of match rows.

    `min_alloc` is the economic lot threshold: allocations below it are
    skipped so we don't dispatch pickups for fragments.

    `terrain` is an optional {(district, plant_id): {...}} lookup from
    load_terrain(); when present, plants are ranked by terrain-adjusted
    effective_km instead of raw haversine, and each row carries
    effective_distance_km / terrain_multiplier / cost fields.
    """
    terrain = terrain or {}

    def eff_km(district: dict, plant: dict) -> tuple[float, dict | None]:
        key = (district["district"], plant["plant_id"])
        t = terrain.get(key)
        if t:
            return float(t["effective_km"]), t
        return haversine_km(
            district["latitude"], district["longitude"],
            plant["latitude"], plant["longitude"],
        ), None

    remaining = {p["plant_id"]: float(p["annual_capacity"]) for p in plants}
    matches: list[dict] = []

    for district in sorted(
        districts,
        key=lambda d: (-float(d["predicted_supply_2018"]), d["district"]),
    ):
        supply = float(district["predicted_supply_2018"])
        to_assign = supply

        # Cheapest (terrain-adjusted) plants first; haversine tie-break by id.
        candidates = sorted(
            plants,
            key=lambda p: (eff_km(district, p)[0], p["plant_id"]),
        )
        for plant in candidates:
            if to_assign <= 1e-6:
                break
            capacity_left = remaining[plant["plant_id"]]
            if capacity_left <= 1e-6:
                continue
            qty = min(to_assign, capacity_left)
            if qty < min_alloc:
                # Below the economic threshold — leave this capacity idle
                # rather than dispatch a pickup for a fragment.
                continue
            raw_km = haversine_km(
                district["latitude"], district["longitude"],
                plant["latitude"], plant["longitude"],
            )
            eff, t = eff_km(district, plant)
            row = {
                "district": district["district"],
                "plant_id": plant["plant_id"],
                "allocated_quantity": round(qty, 1),
                "distance_km": round(raw_km, 1),
                "effective_distance_km": round(eff, 1),
                "terrain_multiplier": round(t["terrain_multiplier"], 4) if t else 1.0,
                "elevation_gain_m": round(t["elevation_gain_m"], 1) if t else None,
                "slope_pct": round(t["slope_pct"], 3) if t else None,
                "pickup_order": None,
                "status": "matched",
                **_route_cost(district, plant, qty, eff),
            }
            matches.append(row)
            remaining[plant["plant_id"]] -= qty
            to_assign -= qty
        # to_assign > 0 means unabsorbed supply — intentionally not stored;
        # it shows up as the gap between total supply and matched quantity.

    # Cheapest-first pickup order per plant (uses terrain-adjusted distance).
    by_plant: dict[str, list[dict]] = {}
    for m in matches:
        by_plant.setdefault(m["plant_id"], []).append(m)
    for rows in by_plant.values():
        for order, m in enumerate(
            sorted(rows, key=lambda r: r["effective_distance_km"]), start=1
        ):
            m["pickup_order"] = order

    return matches


def summarize(
    matches: list[dict], districts: list[dict], plants: list[dict]
) -> dict:
    total_supply = sum(float(d["predicted_supply_2018"]) for d in districts)
    matched = sum(m["allocated_quantity"] for m in matches)
    utilization = {}
    for p in plants:
        allocated = sum(
            m["allocated_quantity"] for m in matches if m["plant_id"] == p["plant_id"]
        )
        utilization[p["plant_id"]] = round(100 * allocated / p["annual_capacity"], 1)
    return {
        "total_supply": round(total_supply, 1),
        "matched": round(matched, 1),
        "leftover": round(total_supply - matched, 1),
        "absorbed_pct": round(100 * matched / total_supply, 1),
        "utilization": utilization,
        "match_count": len(matches),
    }


def cost_summary(matches: list[dict]) -> dict:
    """Aggregate transport cost across all matches (terrain-aware).

    Every figure is derived from TRANSPORT_RATE_PER_UNIT_KM, so it's an
    estimate with a labelled rate — not a claim of real spend.
    """
    if not matches:
        return {
            "total_cost_index": 0.0, "total_estimated_cost": 0.0,
            "flat_estimated_cost": 0.0, "terrain_penalty_pct": 0.0,
            "avg_terrain_multiplier": 1.0, "routes": 0,
        }
    total_cost_index = sum(m["cost_index"] for m in matches)
    total_est = sum(m["estimated_cost"] for m in matches)
    flat_est = sum(
        m["allocated_quantity"] * m["distance_km"] * TRANSPORT_RATE_PER_UNIT_KM
        for m in matches
    )
    avg_mult = sum(m["terrain_multiplier"] for m in matches) / len(matches)
    return {
        "total_cost_index": round(total_cost_index, 1),
        "total_estimated_cost": round(total_est, 1),
        "flat_estimated_cost": round(flat_est, 1),
        "terrain_penalty_pct": round(100 * (total_est - flat_est) / flat_est, 2)
        if flat_est else 0.0,
        "avg_terrain_multiplier": round(avg_mult, 4),
        "routes": len(matches),
        "transport_rate_per_unit_km": TRANSPORT_RATE_PER_UNIT_KM,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute AgriFlow supply-demand matches.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan without writing anything to the database.",
    )
    parser.add_argument(
        "--min-alloc", type=float, default=2000.0,
        help="Skip allocations below this many units (economic lot threshold).",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        districts = load_districts(conn)
        plants = load_plants(conn)
        terrain = load_terrain(conn)
        matches = compute_matches(
            districts, plants, min_alloc=args.min_alloc, terrain=terrain
        )
        summary = summarize(matches, districts, plants)
        costs = cost_summary(matches)

        if not args.dry_run:
            conn.execute("DELETE FROM matches")
            conn.executemany(
                """INSERT INTO matches
                   (district, plant_id, allocated_quantity, distance_km,
                    pickup_order, status)
                   VALUES (:district, :plant_id, :allocated_quantity,
                           :distance_km, :pickup_order, :status)""",
                matches,
            )
            conn.commit()

        print(f"total supply : {summary['total_supply']:>11,.1f} units")
        print(f"matched      : {summary['matched']:>11,.1f} units  ({summary['match_count']} match rows)")
        print(f"leftover     : {summary['leftover']:>11,.1f} units  ({100 - summary['absorbed_pct']:.1f}% unabsorbed)")
        print("\nutilization per plant:")
        for pid, pct in summary["utilization"].items():
            print(f"  {pid}: {pct:>5.1f}%")
        print("\nterrain-aware cost summary (rate = "
              f"{TRANSPORT_RATE_PER_UNIT_KM} per unit-km):")
        print(f"  total est. cost : {costs['total_estimated_cost']:>10,.1f}")
        print(f"  flat-only cost  : {costs['flat_estimated_cost']:>10,.1f}")
        print(f"  terrain penalty : {costs['terrain_penalty_pct']:>6.2f}%")
        print(f"  avg multiplier  : {costs['avg_terrain_multiplier']:.4f}")
        print("\nsample matches (top 6 by allocated quantity):")
        for m in sorted(matches, key=lambda r: -r["allocated_quantity"])[:6]:
            print(
                f"  {m['district']:15s} -> {m['plant_id']}  "
                f"{m['allocated_quantity']:>9,.1f} units  "
                f"{m['distance_km']:>6.1f} km (eff {m['effective_distance_km']:>6.1f})  "
                f"pickup #{m['pickup_order']}"
            )
        print("\n" + ("DRY RUN — database not modified" if args.dry_run else
                      f"wrote {len(matches)} rows to the matches table"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
