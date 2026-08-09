"""process_cropgrids.py — integrate CROPGRIDS v1.08 into AgriFlow.

CROPGRIDS (Tang et al., 2024, Scientific Data, https://doi.org/10.6084/m9.figshare.22491997,
CC BY 4.0) is a global gridded dataset of harvested/crop area for 173 crops circa 2020
at 0.05 deg (~5.6 km) resolution. It is a *cross-sectional* 2020 snapshot — it cannot
extend the 2010-2017 Shell.ai time series, but it supplies a genuinely new per-district
layer: real crop-area composition, which the demo currently fakes with "demo assumption"
residue labels.

What this script does
---------------------
1. Reads the downloaded NetCDF zip from data_cache/ (gitignored; see README for download).
2. Zonal-sums each crop's `croparea` (ha per cell) over the 20 AgriFlow Gujarat districts
   using district boundaries from agriflow_reference_data_v2/gujarat_districts_census2011.geojson
   (geoBoundaries ADM2, filtered to Gujarat).
3. Writes agriflow_crop_composition.csv: top crops per district with ha + % share, plus a
   TOTAL row per district (total physical cropped area, ha).

Usage:
    python process_cropgrids.py

Requires (pip): netCDF4, shapely  (xarray/pandas/numpy already used by the project)
"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import numpy as np
import xarray as xr
from shapely import contains as shapely_contains
from shapely import points as shapely_points
from shapely.geometry import shape

BASE_DIR = Path(__file__).resolve().parent
ZIP_PATH = BASE_DIR / "data_cache" / "cropgrids" / "CROPGRIDSv1.08_NC_maps.zip"
EXTRACT_DIR = BASE_DIR / "data_cache" / "cropgrids" / "CROPGRIDSv1.08_NC_maps"
GEOJSON_PATH = (
    BASE_DIR / "agriflow_reference_data_v2" / "gujarat_districts_census2011.geojson"
)
DISTRICT_CSV = BASE_DIR / "agriflow_district_supply.csv"
OUT_CSV = BASE_DIR / "agriflow_crop_composition.csv"

# Gujarat bounding box (with margin) — the only region we ever load from the
# global grids, which keeps memory/IO tiny (a few MB per crop instead of ~104 MB).
LAT_MIN, LAT_MAX = 20.0, 25.0
LON_MIN, LON_MAX = 68.0, 75.0

TOP_N = 8  # rows kept per district (plus the TOTAL row)


def extract_if_needed() -> None:
    """Unzip the NetCDF files once; subsequent runs read them from disk."""
    existing = list(EXTRACT_DIR.glob("CROPGRIDSv1.08_*.nc"))
    if len(existing) >= 100:  # 173 crop layers + Countries_2018.nc in the zip
        return
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH) as z:
        z.extractall(EXTRACT_DIR.parent)
    print(f"extracted CROPGRIDS NetCDF files to {EXTRACT_DIR}")


def load_district_polygons() -> dict[str, object]:
    """district name (geoBoundaries spelling, matches app districts) -> shapely polygon."""
    with open(GEOJSON_PATH, encoding="utf-8") as fh:
        fc = json.load(fh)
    polys = {}
    for f in fc["features"]:
        name = f["properties"]["shapeName"].strip()
        polys[name] = shape(f["geometry"])
    return polys


def load_app_districts() -> list[str]:
    """The 20 districts AgriFlow actually models (order preserved)."""
    with open(DISTRICT_CSV, newline="", encoding="utf-8") as fh:
        return [row["district"] for row in csv.DictReader(fh)]


def crop_area_for_bbox(ds: xr.Dataset) -> np.ndarray:
    """Load the croparea layer for the Gujarat bbox as a 2D float array."""
    # Ascending slices only — xarray returns an empty result for reversed slices.
    arr = (
        ds["croparea"]
        .sel(lat=slice(LAT_MIN, LAT_MAX), lon=slice(LON_MIN, LON_MAX))
        .load()
        .values
    )
    # Ocean = -1, not-assessed = -2; treat anything non-positive as no data.
    return np.where(arr > 0, arr, 0.0).astype(np.float64)


def main() -> None:
    if not ZIP_PATH.exists():
        raise SystemExit(
            f"{ZIP_PATH} not found. Download it first:\n"
            "  curl -L -o data_cache/cropgrids/CROPGRIDSv1.08_NC_maps.zip "
            "https://ndownloader.figshare.com/files/44950942\n"
            "(CROPGRIDS v1.08, CC BY 4.0, ~807 MB — kept out of git via data_cache/)"
        )

    extract_if_needed()

    districts = load_app_districts()
    polygons = load_district_polygons()
    missing = [d for d in districts if d not in polygons]
    if missing:
        raise SystemExit(f"no boundary for districts: {missing}")

    # Cell-center containment: for each district, the flat index (row-major over
    # the bbox subset) of every grid cell whose center falls inside the polygon.
    with xr.open_dataset(next(EXTRACT_DIR.glob("CROPGRIDSv1.08_*.nc"))) as ds:
        lat = ds["lat"].sel(lat=slice(LAT_MIN, LAT_MAX)).values
        lon = ds["lon"].sel(lon=slice(LON_MIN, LON_MAX)).values
    n_lat, n_lon = len(lat), len(lon)
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")

    pts = shapely_points(lon_grid.ravel(), lat_grid.ravel())
    cell_idx: dict[str, np.ndarray] = {}
    for dist in districts:
        poly = polygons[dist]
        inside = shapely_contains(poly, pts)
        cell_idx[dist] = np.flatnonzero(inside)
        print(f"  {dist:15s} {int(inside.sum()):4d} cells inside")

    # Sum croparea per district across all 173 crop layers.
    totals: dict[str, dict[str, float]] = {d: {} for d in districts}
    crop_files = sorted(EXTRACT_DIR.glob("CROPGRIDSv1.08_*.nc"))
    for i, path in enumerate(crop_files, 1):
        crop = path.stem.replace("CROPGRIDSv1.08_", "")
        with xr.open_dataset(path) as ds:
            arr = crop_area_for_bbox(ds)
        flat = arr.ravel()
        for dist in districts:
            totals[dist][crop] = float(flat[cell_idx[dist]].sum())
        if i % 25 == 0 or i == len(crop_files):
            print(f"  processed {i}/{len(crop_files)} crops")

    # Assemble output rows: top crops per district + a TOTAL row.
    rows: list[dict] = []
    for dist in districts:
        by_crop = totals[dist]
        total_ha = sum(by_crop.values())
        ranked = sorted(by_crop.items(), key=lambda kv: -kv[1])[:TOP_N]
        rows.append(
            {
                "district": dist,
                "crop": "TOTAL",
                "croparea_ha": round(total_ha, 1),
                "share_pct": 100.0,
            }
        )
        for crop, ha in ranked:
            rows.append(
                {
                    "district": dist,
                    "crop": crop,
                    "croparea_ha": round(ha, 1),
                    "share_pct": round(100.0 * ha / total_ha, 2) if total_ha else 0.0,
                }
            )

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["district", "crop", "croparea_ha", "share_pct"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nwrote {OUT_CSV} ({len(rows)} rows)")
    print("\ntop crop per district (CROPGRIDS 2020):")
    for dist in districts:
        ranked = sorted(totals[dist].items(), key=lambda kv: -kv[1])
        top = ", ".join(f"{c} ({round(100*h/sum(totals[dist].values()),1)}%)"
                        for c, h in ranked[:3])
        print(f"  {dist:15s} {top}")


if __name__ == "__main__":
    main()
