"""Seed AgriFlow's SQLite database from the validated district/plant CSVs.

This is Person B's handoff to Person A: it turns the two reference CSVs into
real rows in `agriflow.db`, so the FastAPI endpoints can read from a database
instead of hardcoded stubs.

Tables created:
  - districts        : one row per district (from agriflow_district_supply.csv)
  - plants           : one row per synthetic plant (from agriflow_plants.csv)
  - predictions      : 2018 forecast plus 2019-2022 actuals and 2024-2026
                       projections per district (derived from supply_trend)
  - matches          : empty, reserved for the supply-demand matching module
  - crop_composition : per-district crop-area mix from CROPGRIDS v1.08 (2020),
                       produced by process_cropgrids.py; also fills the new
                       districts columns cropland_2020_ha / top_crop and upgrades
                       'demo assumption' residue labels to evidence-based ones.

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
CROP_COMPOSITION_CSV = BASE_DIR / "agriflow_crop_composition.csv"
DEFAULT_DB = BASE_DIR / "agriflow.db"

# CROPGRIDS v1.08 — Tang et al. 2024, Scientific Data, CC BY 4.0
CROP_MIX_SOURCE = "CROPGRIDS v1.08 (2020 crop area, Tang et al. 2024, CC BY 4.0)"

# Map dominant crop -> residue family, used only to upgrade districts whose
# residue label was a 'demo assumption' (official labels are left untouched).
CROP_TO_RESIDUE = {
    "groundnut": "Groundnut shell",
    "cotton": "Cotton stalk",
    "rice": "Rice straw",
    "wheat": "Wheat straw",
    "castor": "Castor stalk",
    "rapeseed": "Oilseed residue",
    "mustard": "Oilseed residue",
    "sunflower": "Oilseed residue",
    "sesame": "Oilseed residue",
    "sugarcane": "Sugarcane trash",
    "chickpea": "Pulse residue",
    "pulsenes": "Pulse residue",
    "legumenes": "Pulse residue",
    "bean": "Pulse residue",
    "broadbean": "Pulse residue",
    "greenbean": "Pulse residue",
    "stringbean": "Pulse residue",
    "pigeonpea": "Pulse residue",
    "maize": "Coarse cereal residue",
    "sorghum": "Coarse cereal residue",
    "millet": "Coarse cereal residue",
}
RESIDUE_MIN_SHARE_PCT = 30.0  # dominant crop must reach this share to drive the label

# Column order for inserts (matches the CSV headers).
DISTRICT_COLS = [
    "district", "latitude", "longitude", "baseline_supply_2017",
    "rolling_3yr_supply", "trend_forecast_2018", "predicted_supply_2018",
    "trend_r2", "confidence_score_heuristic", "confidence_label",
    "cropland_2017", "avg_precipitation_2017", "avg_elevation_2017",
    "site_count_2017", "residue_type", "residue_type_source",
    "harvest_window", "supply_tier",
    # 2026 extension (written by extend_supply_2026.py from DES Agristat APY)
    "predicted_supply_2024", "predicted_supply_2025", "predicted_supply_2026",
    "rolling_3yr_2022", "trend_forecast_2026", "trend_r2_2026",
    "confidence_score_2026", "confidence_label_2026", "supply_2026_change_pct",
    "supply_source", "supply_trend",
]
DISTRICT_FLOAT = {
    "latitude", "longitude", "baseline_supply_2017", "rolling_3yr_supply",
    "trend_forecast_2018", "predicted_supply_2018", "trend_r2",
    "confidence_score_heuristic", "cropland_2017", "avg_precipitation_2017",
    "avg_elevation_2017",
    "predicted_supply_2024", "predicted_supply_2025", "predicted_supply_2026",
    "rolling_3yr_2022", "trend_forecast_2026", "trend_r2_2026",
    "confidence_score_2026", "supply_2026_change_pct",
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
DROP TABLE IF EXISTS crop_composition;

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
    supply_tier                 TEXT,
    cropland_2020_ha            REAL,
    top_crop                    TEXT,
    crop_mix_source             TEXT,
    predicted_supply_2024       REAL,
    predicted_supply_2025       REAL,
    predicted_supply_2026       REAL,
    rolling_3yr_2022            REAL,
    trend_forecast_2026         REAL,
    trend_r2_2026               REAL,
    confidence_score_2026       REAL,
    confidence_label_2026       TEXT,
    supply_2026_change_pct      REAL,
    supply_source               TEXT,
    supply_trend                TEXT
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

CREATE TABLE crop_composition (
    district     TEXT NOT NULL,
    crop         TEXT NOT NULL,
    croparea_ha  REAL,
    share_pct    REAL,
    PRIMARY KEY (district, crop)
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


def read_composition(path: Path) -> dict[str, list[dict]]:
    """Read the CROPGRIDS composition CSV into {district: [crop rows...]}.

    TOTAL rows carry the district's total cropped area; the rest are individual
    crops ordered by share (descending, as written by process_cropgrids.py).
    """
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["district"], []).append(
                {
                    "crop": row["crop"],
                    "croparea_ha": float(row["croparea_ha"]),
                    "share_pct": float(row["share_pct"]),
                }
            )
    return out


def suggest_residue(mix: list[dict]) -> str | None:
    """Residue label driven by the dominant crop, or None if no crop dominates."""
    if not mix:
        return None
    top = max((r for r in mix if r["crop"] != "TOTAL"), key=lambda r: r["share_pct"])
    family = CROP_TO_RESIDUE.get(top["crop"])
    if family and top["share_pct"] >= RESIDUE_MIN_SHARE_PCT:
        return family
    return "Mixed agricultural residue"


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

    # CROPGRIDS layer: fill the new district columns from the composition CSV
    # and upgrade 'demo assumption' residue labels to evidence-based ones.
    composition = read_composition(CROP_COMPOSITION_CSV)
    for d in districts:
        mix = composition.get(d["district"], [])
        total = next((r for r in mix if r["crop"] == "TOTAL"), None)
        crops = [r for r in mix if r["crop"] != "TOTAL"]
        top_crop = crops[0]["crop"] if crops else None
        cur.execute(
            "UPDATE districts SET cropland_2020_ha = ?, top_crop = ?, crop_mix_source = ? "
            "WHERE district = ?",
            (total["croparea_ha"] if total else None, top_crop,
             CROP_MIX_SOURCE if mix else None, d["district"]),
        )
        cur.executemany(
            "INSERT INTO crop_composition (district, crop, croparea_ha, share_pct) "
            "VALUES (?, ?, ?, ?)",
            [(d["district"], r["crop"], r["croparea_ha"], r["share_pct"])
             for r in crops],
        )
        if mix and d["residue_type_source"] == "demo assumption":
            cur.execute(
                "UPDATE districts SET residue_type = ?, residue_type_source = ? "
                "WHERE district = ?",
                (suggest_residue(mix), CROP_MIX_SOURCE, d["district"]),
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

    # Extended series (DES Agristat APY residue, calibrated to Shell.ai units):
    # 2019-2022 are actuals from the calibrated series; 2024-2026 are the
    # iterative projections (2018 rows above keep the original model output).
    # The 2023 label is absent because DES district-level APY ends at 2022-23.
    forecast_years = {2024, 2025, 2026}
    for d in districts:
        pairs = dict(
            p.split(":", 1) for p in (d.get("supply_trend") or "").split(",") if ":" in p
        )
        for year in (2019, 2020, 2021, 2022, 2024, 2025, 2026):
            if str(year) not in pairs:
                continue
            is_forecast = year in forecast_years
            cur.execute(
                """INSERT INTO predictions
                   (district, year, predicted_supply, trend_r2,
                    confidence_score_heuristic, confidence_label,
                    harvest_window, supply_tier)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    d["district"],
                    year,
                    float(pairs[str(year)]),
                    float(d["trend_r2_2026"]) if is_forecast else None,
                    float(d["confidence_score_2026"]) if is_forecast else None,
                    d["confidence_label_2026"] if is_forecast else None,
                    d["harvest_window"],
                    d["supply_tier"],
                ),
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
            for table in ("districts", "plants", "predictions", "matches", "crop_composition")
        }
        top_districts = conn.execute(
            """SELECT district, COALESCE(predicted_supply_2026, predicted_supply_2018),
                      confidence_label_2026, supply_tier
               FROM districts ORDER BY predicted_supply_2026 DESC LIMIT 3"""
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
