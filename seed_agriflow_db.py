"""Seed AgriFlow's SQLite database from the validated district/plant CSVs.

This is Person B's handoff to Person A: it turns the two reference CSVs into
real rows in `agriflow.db`, so the FastAPI endpoints can read from a database
instead of hardcoded stubs.

Tables created:
  - districts   : one row per district (from agriflow_district_supply.csv)
  - plants      : one row per synthetic plant (from agriflow_plants.csv)
  - predictions : 2018 forecast per district (derived from the district rows)
  - matches     : empty, reserved for the supply-demand matching module
  - terrain     : empty, populated by `python terrain.py` (terrain-aware cost)

Usage:
    python seed_agriflow_db.py [--db path/to/agriflow.db]

Re-runnable: the schema is dropped and recreated on every run.
"""

import argparse
import csv
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DISTRICT_CSV = BASE_DIR / "agriflow_district_supply.csv"
PLANTS_CSV = BASE_DIR / "agriflow_plants.csv"
DEFAULT_DB = BASE_DIR / "agriflow.db"

# Column order for inserts (matches the CSV headers).
DISTRICT_COLS = [
    "district", "latitude", "longitude", "baseline_supply_2017",
    "rolling_3yr_supply", "trend_forecast_2018", "predicted_supply_2018",
    "trend_r2", "confidence_score_heuristic", "confidence_label",
    "cropland_2017", "avg_precipitation_2017", "avg_elevation_2017",
    "site_count_2017", "residue_type", "residue_type_source",
    "harvest_window", "supply_tier",
]
DISTRICT_FLOAT = {
    "latitude", "longitude", "baseline_supply_2017", "rolling_3yr_supply",
    "trend_forecast_2018", "predicted_supply_2018", "trend_r2",
    "confidence_score_heuristic", "cropland_2017", "avg_precipitation_2017",
    "avg_elevation_2017",
}
DISTRICT_INT = {"site_count_2017"}

PLANT_COLS = [
    "plant_id", "plant_name", "representative_district", "latitude",
    "longitude", "annual_capacity", "capacity_unit", "facility_status",
]
PLANT_FLOAT = {"latitude", "longitude", "annual_capacity"}

SCHEMA = """
DROP TABLE IF EXISTS districts;
DROP TABLE IF EXISTS plants;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS terrain;

CREATE TABLE districts (
    district                    TEXT PRIMARY KEY,
    latitude                    REAL,
    longitude                   REAL,
    baseline_supply_2017        REAL,
    rolling_3yr_supply          REAL,
    trend_forecast_2018         REAL,
    predicted_supply_2018       REAL,
    trend_r2                    REAL,
    confidence_score_heuristic  REAL,
    confidence_label            TEXT,
    cropland_2017               REAL,
    avg_precipitation_2017      REAL,
    avg_elevation_2017          REAL,
    site_count_2017             INTEGER,
    residue_type                TEXT,
    residue_type_source         TEXT,
    harvest_window              TEXT,
    supply_tier                 TEXT
);

CREATE TABLE plants (
    plant_id                TEXT PRIMARY KEY,
    plant_name              TEXT,
    representative_district TEXT,
    latitude                REAL,
    longitude               REAL,
    annual_capacity         REAL,
    capacity_unit           TEXT,
    facility_status         TEXT
);

CREATE TABLE predictions (
    district                   TEXT NOT NULL,
    year                       INTEGER NOT NULL,
    predicted_supply           REAL,
    trend_r2                   REAL,
    confidence_score_heuristic REAL,
    confidence_label           TEXT,
    harvest_window             TEXT,
    supply_tier                TEXT,
    PRIMARY KEY (district, year)
);

CREATE TABLE matches (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    district           TEXT NOT NULL,
    plant_id           TEXT NOT NULL,
    allocated_quantity REAL,
    distance_km        REAL,
    pickup_order       INTEGER,
    status             TEXT DEFAULT 'proposed'
);

-- Terrain-aware transport cost per district x plant pair.
-- Populated by `python terrain.py` (Open-Elevation / NASA SRTM, or --offline).
CREATE TABLE terrain (
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


def read_csv(path: Path) -> list[dict]:
    """Read a CSV into a list of row dicts, failing loudly if missing."""
    if not path.exists():
        raise FileNotFoundError(f"Missing input CSV: {path}")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def to_row(row: dict, cols: list[str], floats: set[str], ints: set[str]) -> tuple:
    """Build an insert tuple, casting numeric columns so SQLite stores
    REAL/INTEGER instead of TEXT (which would break ORDER BY on numbers)."""
    out = []
    for col in cols:
        value = row[col]
        if col in ints:
            out.append(int(float(value)))
        elif col in floats:
            out.append(float(value))
        else:
            out.append(value)
    return tuple(out)


def seed(conn: sqlite3.Connection, districts: list[dict], plants: list[dict]) -> None:
    cur = conn.cursor()

    cur.executemany(
        "INSERT INTO districts ({}) VALUES ({})".format(
            ", ".join(DISTRICT_COLS), ", ".join("?" * len(DISTRICT_COLS))
        ),
        [to_row(d, DISTRICT_COLS, DISTRICT_FLOAT, DISTRICT_INT) for d in districts],
    )

    cur.executemany(
        "INSERT INTO plants ({}) VALUES ({})".format(
            ", ".join(PLANT_COLS), ", ".join("?" * len(PLANT_COLS))
        ),
        [to_row(p, PLANT_COLS, PLANT_FLOAT, set()) for p in plants],
    )

    # Predictions are the 2018 forecast baked into each district row.
    cur.executemany(
        """INSERT INTO predictions
           (district, year, predicted_supply, trend_r2, confidence_score_heuristic,
            confidence_label, harvest_window, supply_tier)
           VALUES (?, 2018, ?, ?, ?, ?, ?, ?)""",
        [
            (
                d["district"],
                float(d["predicted_supply_2018"]),
                float(d["trend_r2"]),
                float(d["confidence_score_heuristic"]),
                d["confidence_label"],
                d["harvest_window"],
                d["supply_tier"],
            )
            for d in districts
        ],
    )

    # matches stays empty — it is populated by the matching module later.
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed AgriFlow's SQLite DB from the reference CSVs."
    )
    parser.add_argument(
        "--db", default=str(DEFAULT_DB), help="Path to the SQLite database file."
    )
    args = parser.parse_args()

    districts = read_csv(DISTRICT_CSV)
    plants = read_csv(PLANTS_CSV)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    top_districts: list[tuple] = []
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        seed(conn, districts, plants)

        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("districts", "plants", "predictions", "matches", "terrain")
        }
        top_districts = conn.execute(
            """SELECT district, predicted_supply_2018, confidence_label, supply_tier
               FROM districts ORDER BY predicted_supply_2018 DESC LIMIT 3"""
        ).fetchall()
    finally:
        conn.close()

    print(f"Seeded {db_path}:")
    for table, n in counts.items():
        print(f"  {table:12s} {n} rows")
    print("\nTop 3 districts by predicted supply:")
    for district, supply, conf, tier in top_districts:
        print(f"  {district:15s} {supply:10.1f} units  {conf:8s}  {tier}")


if __name__ == "__main__":
    main()
