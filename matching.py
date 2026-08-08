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


def compute_matches(
    districts: list[dict], plants: list[dict], min_alloc: float = 2000.0
) -> list[dict]:
    """Greedy supply–demand matching. Returns a list of match rows.

    `min_alloc` is the economic lot threshold: allocations below it are
    skipped so we don't dispatch pickups for fragments.
    """
    remaining = {p["plant_id"]: float(p["annual_capacity"]) for p in plants}
    matches: list[dict] = []

    for district in sorted(
        districts,
        key=lambda d: (-float(d["predicted_supply_2018"]), d["district"]),
    ):
        supply = float(district["predicted_supply_2018"])
        to_assign = supply

        # Nearest plants first (distance tie-break by plant id).
        candidates = sorted(
            plants,
            key=lambda p: (
                haversine_km(
                    district["latitude"], district["longitude"],
                    p["latitude"], p["longitude"],
                ),
                p["plant_id"],
            ),
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
            matches.append(
                {
                    "district": district["district"],
                    "plant_id": plant["plant_id"],
                    "allocated_quantity": round(qty, 1),
                    "distance_km": round(
                        haversine_km(
                            district["latitude"], district["longitude"],
                            plant["latitude"], plant["longitude"],
                        ),
                        1,
                    ),
                    "pickup_order": None,
                    "status": "matched",
                }
            )
            remaining[plant["plant_id"]] -= qty
            to_assign -= qty
        # to_assign > 0 means unabsorbed supply — intentionally not stored;
        # it shows up as the gap between total supply and matched quantity.

    # Nearest-first pickup order per plant.
    by_plant: dict[str, list[dict]] = {}
    for m in matches:
        by_plant.setdefault(m["plant_id"], []).append(m)
    for rows in by_plant.values():
        for order, m in enumerate(sorted(rows, key=lambda r: r["distance_km"]), start=1):
            m["pickup_order"] = order

    return matches


def summarize(matches: list[dict], districts: list[dict], plants: list[dict]) -> dict:
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
        matches = compute_matches(districts, plants, min_alloc=args.min_alloc)
        summary = summarize(matches, districts, plants)

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
        print("\nsample matches (top 6 by allocated quantity):")
        for m in sorted(matches, key=lambda r: -r["allocated_quantity"])[:6]:
            print(
                f"  {m['district']:15s} -> {m['plant_id']}  "
                f"{m['allocated_quantity']:>9,.1f} units  "
                f"{m['distance_km']:>6.1f} km  pickup #{m['pickup_order']}"
            )
        print("\n" + ("DRY RUN — database not modified" if args.dry_run else
                      f"wrote {len(matches)} rows to the matches table"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
