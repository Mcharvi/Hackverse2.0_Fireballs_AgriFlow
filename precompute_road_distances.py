"""precompute_road_distances.py — one-time (re-runnable) script that fetches
real road distance/duration/geometry for every district<->plant pair from
OSRM and caches it in agriflow.db's `road_routes` table.

Why precompute instead of calling OSRM live on every request:
  - The public OSRM demo server has no SLA and isn't meant for production
    traffic — a live call per district-plant pair on every dashboard load
    would be both slow (6 plants x N districts calls) and a bad citizen.
  - District/plant locations don't change between demo runs, so the road
    route between any pair is stable — compute it once, reuse it.

Run this once after seeding the DB, and again any time the district or
plant set changes:

    python seed_agriflow_db.py
    python precompute_road_distances.py

Safe to re-run: the table is cleared and rebuilt each time. Failed pairs
(network hiccup, OSRM couldn't find a route, etc.) are simply left out of
the table — matching.py's distance_lookup fallback means those specific
pairs transparently use haversine instead, nothing breaks.
"""

import json
import sqlite3
import time
from pathlib import Path

from routing import get_route

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agriflow.db"

# Be polite to the free public OSRM server — small delay between calls.
DELAY_BETWEEN_CALLS_SECONDS = 0.3

SCHEMA = """
CREATE TABLE IF NOT EXISTS road_routes (
    district      TEXT NOT NULL,
    plant_id      TEXT NOT NULL,
    distance_km   REAL,
    duration_min  REAL,
    geometry_json TEXT,
    PRIMARY KEY (district, plant_id)
);
"""


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH.name} not found — run seed_agriflow_db.py first.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    districts = [
        dict(r) for r in conn.execute("SELECT district, latitude, longitude FROM districts")
    ]
    plants = [
        dict(r) for r in conn.execute("SELECT plant_id, latitude, longitude FROM plants")
    ]

    total = len(districts) * len(plants)
    print(f"Fetching {total} district<->plant road routes from OSRM "
          f"({len(districts)} districts x {len(plants)} plants)...")

    conn.execute("DELETE FROM road_routes")

    ok, failed = 0, 0
    n = 0
    for d in districts:
        for p in plants:
            n += 1
            route = get_route(d["latitude"], d["longitude"], p["latitude"], p["longitude"])
            if route:
                conn.execute(
                    """INSERT OR REPLACE INTO road_routes
                       (district, plant_id, distance_km, duration_min, geometry_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        d["district"],
                        p["plant_id"],
                        route["distance_km"],
                        route["duration_min"],
                        json.dumps(route["geometry"]),
                    ),
                )
                ok += 1
                print(f"  [{n}/{total}] {d['district']:15s} -> {p['plant_id']}  "
                      f"{route['distance_km']:.1f} km  OK")
            else:
                failed += 1
                print(f"  [{n}/{total}] {d['district']:15s} -> {p['plant_id']}  "
                      f"FAILED (falls back to straight-line distance)")
            time.sleep(DELAY_BETWEEN_CALLS_SECONDS)

    conn.commit()
    conn.close()
    print(f"\nDone: {ok} road routes cached, {failed} failed / fell back to haversine.")


if __name__ == "__main__":
    main()