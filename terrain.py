"""terrain.py — elevation-aware transport cost for AgriFlow.

Bakes a `terrain` table into agriflow.db so routing accounts for terrain,
not just straight-line (haversine) distance:

    elevation_gain_m   total uphill climb along the district->plant path (m)
    slope_pct          average uphill grade = gain / path length, in %
    terrain_multiplier = 1 + TERRAIN_WEIGHT * slope_pct   (documented heuristic)
    effective_km       = haversine_km * terrain_multiplier

The matcher (matching.py) then ranks plants by `effective_km` instead of raw
haversine, and the API reports per-route terrain + cost. The multiplier is a
simple, tunable, explainable heuristic — not a road-routing engine. On a flat
coastal route terrain barely moves the number; on a route climbing into the
eastern hills it adds a few percent. That honesty is the feature.

Two data modes:
  - online (default): sample NASA SRTM elevations along each path via the
    free Open-Elevation API (https://api.open-elevation.com, no key).
  - --offline: use the avg_elevation_2017 already baked into the district
    CSV (endpoint-to-endpoint difference). Zero network, slightly coarser.

If the online fetch fails partway, the script degrades to offline mode for
the whole table rather than writing partial data.

Usage:
    python terrain.py            # fetch elevations + write the terrain table
    python terrain.py --offline  # no network (endpoint elevations only)
    python terrain.py --dry-run  # print the table without writing anything

Run AFTER `python seed_agriflow_db.py` (needs districts/plants populated).
"""

import argparse
import csv
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

from matching import haversine_km  # one distance implementation, no duplication

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agriflow.db"
DISTRICT_CSV = BASE_DIR / "agriflow_district_supply.csv"

# Each 1% of average uphill grade adds 10% to effective distance. That's
# above the fuel-only rule of thumb for loaded trucks but defensible when
# you fold in time, wear and handling on graded roads. Tunable; the point
# of the layer is to make hilly routes cost more than flat ones, honestly.
TERRAIN_WEIGHT = 10.0
# Elevation samples per path, including both endpoints.
SAMPLES_PER_PATH = 9
# Open-Elevation batch size (their API tolerates ~100 locations per request).
BATCH_SIZE = 50
API_URL = "https://api.open-elevation.com/api/v1/lookup"
API_RETRIES = 2
API_TIMEOUT = 30

TERRAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS terrain (
    district           TEXT NOT NULL,
    plant_id           TEXT NOT NULL,
    haversine_km       REAL,
    elevation_gain_m   REAL,
    slope_pct          REAL,
    terrain_multiplier REAL,
    effective_km       REAL,
    source             TEXT,
    PRIMARY KEY (district, plant_id)
);
"""


# ---------------------------------------------------------------------------
# Elevation fetching
# ---------------------------------------------------------------------------
def interpolate_path(lat1: float, lon1: float, lat2: float, lon2: float, n: int):
    """n points linearly interpolated along the district->plant line."""
    return [
        (lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t)
        for t in (i / (n - 1) for i in range(n))
    ]


def fetch_elevations(points: list[tuple[float, float]]) -> list[float] | None:
    """Batch-fetch elevations for `points`; None if the API can't be reached."""
    locs = "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points)
    url = f"{API_URL}?locations={locs}"
    for attempt in range(API_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=API_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [res["elevation"] for res in data["results"]]
        except Exception:
            if attempt == API_RETRIES - 1:
                return None
            time.sleep(1.0)
    return None


def endpoint_elevations() -> dict[str, float]:
    """avg_elevation_2017 per district from the CSV (zero-network fallback)."""
    with open(DISTRICT_CSV, newline="", encoding="utf-8") as fh:
        return {
            r["district"]: float(r["avg_elevation_2017"])
            for r in csv.DictReader(fh)
        }


# ---------------------------------------------------------------------------
# Terrain table builder
# ---------------------------------------------------------------------------
def build_terrain(conn: sqlite3.Connection, offline: bool = False) -> list[tuple]:
    """Compute terrain rows for every district x plant pair.

    Returns list of (district, plant_id, haversine_km, elevation_gain_m,
    slope_pct, terrain_multiplier, effective_km, source) tuples.
    """
    conn.row_factory = sqlite3.Row
    districts = [dict(r) for r in conn.execute(
        "SELECT district, latitude, longitude FROM districts")]
    plants = [dict(r) for r in conn.execute(
        "SELECT plant_id, latitude, longitude, representative_district FROM plants")]

    if not districts or not plants:
        raise SystemExit("No districts/plants in DB — run seed_agriflow_db.py first.")

    pairs = []  # (district, plant_id, points)
    for d in districts:
        for p in plants:
            pts = interpolate_path(
                d["latitude"], d["longitude"], p["latitude"], p["longitude"],
                SAMPLES_PER_PATH,
            )
            pairs.append((d["district"], p["plant_id"], pts))

    elev_by_district = endpoint_elevations()
    rep_elev = {
        p["plant_id"]: elev_by_district.get(p["representative_district"])
        for p in plants
    }

    if offline:
        # Endpoint-to-endpoint |delta| only — no network, coarser.
        rows = []
        for district, plant_id, pts in pairs:
            e1 = elev_by_district.get(district)
            e2 = rep_elev.get(plant_id)
            if e1 is None or e2 is None:
                continue
            dist = haversine_km(*pts[0], *pts[-1])
            rows.append((district, plant_id, dist, abs(e2 - e1), "offline-endpoint"))
        return _finalize(rows)

    # Online: fetch all sample points in batches.
    all_pts = [pt for _, _, pts in pairs for pt in pts]
    elevs: list[float] = []
    for i in range(0, len(all_pts), BATCH_SIZE):
        chunk = all_pts[i:i + BATCH_SIZE]
        res = fetch_elevations(chunk)
        if res is None:
            print("Open-Elevation unreachable — degrading to offline mode.")
            return build_terrain(conn, offline=True)
        elevs.extend(res)
        time.sleep(0.2)  # be polite to the free API

    rows = []
    idx = 0
    for district, plant_id, pts in pairs:
        path_elevs = elevs[idx:idx + len(pts)]
        idx += len(pts)
        dist = haversine_km(*pts[0], *pts[-1])
        gain = sum(
            max(0.0, path_elevs[i] - path_elevs[i - 1])
            for i in range(1, len(path_elevs))
        )
        rows.append((district, plant_id, dist, gain, "open-elevation-path"))
    return _finalize(rows)


def _finalize(rows: list[tuple]) -> list[tuple]:
    """Attach slope_pct / terrain_multiplier / effective_km to each row."""
    out = []
    for district, plant_id, dist, gain, source in rows:
        slope = 100.0 * gain / (dist * 1000.0) if dist > 0 else 0.0  # average grade, %
        mult = 1.0 + TERRAIN_WEIGHT * slope / 100.0  # weight applies to the fraction
        out.append((
            district, plant_id, round(dist, 1), round(gain, 1),
            round(slope, 3), round(mult, 4), round(dist * mult, 1), source,
        ))
    return out


def write_terrain(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executescript(TERRAIN_SCHEMA)
    conn.execute("DELETE FROM terrain")
    conn.executemany(
        """INSERT INTO terrain
           (district, plant_id, haversine_km, elevation_gain_m, slope_pct,
            terrain_multiplier, effective_km, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build AgriFlow's terrain-aware transport cost table."
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Use endpoint elevations from the district CSV (no network).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the table without writing to the database.",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = build_terrain(conn, offline=args.offline)
        if not args.dry_run:
            write_terrain(conn, rows)

        print(f"terrain rows : {len(rows)}  (mode: {rows[0][7] if rows else 'none'})")
        print(f"{'district':15s} {'plant':5s} {'hav km':>7s} {'gain m':>7s} "
              f"{'slope%':>7s} {'mult':>7s} {'eff km':>8s}")
        for r in sorted(rows, key=lambda r: -r[5])[:12]:
            print(f"{r[0]:15s} {r[1]:5s} {r[2]:7.1f} {r[3]:7.1f} {r[4]:7.3f} "
                  f"{r[5]:7.3f} {r[6]:8.1f}")
        worst = max(rows, key=lambda r: r[5])
        print(f"\nsteepest route: {worst[0]} -> {worst[1]}  "
              f"{worst[5]:.3f}x multiplier ({worst[3]:.0f} m climb)")
        print("\n" + ("DRY RUN — database not modified" if args.dry_run
                      else f"wrote {len(rows)} rows to the terrain table"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
