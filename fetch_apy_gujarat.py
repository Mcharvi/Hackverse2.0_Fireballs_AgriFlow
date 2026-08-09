"""fetch_apy_gujarat.py — download Gujarat district-level crop Area/Production/Yield
(APY) from the DES Agristat portal (https://data.desagri.gov.in) into data_cache/.

This is the Tier-1 official source for extending AgriFlow's supply forecast past
2017: district × crop × year *production* (tonnes) for the crops whose residue
feeds the model. Data currently covers agricultural years 2010-11 through 2022-23
(as published by DES; the portal's most recent district-level APY year).

Method (reverse-engineered from the portal's own AJAX contract):
  1. GET the report page to obtain a session cookie + CSRF token.
  2. GET the Gujarat district list (postReq type=getsubBycode&codetype=fltrstates&code=24).
  3. For each crop × season, POST /report/crop/horizontal_crop_vertical_year with
     fltrdistricts[]=all and parse the returned HTML table into rows.

Output: data_cache/apy_gujarat_raw.csv  (district, year, crop, season, area_ha,
production_tonnes, yield_per_ha) — one row per crop-season-district-year.

This is a data-fetch script: results are cached under data_cache/ (gitignored).
The cleaned, residue-converted series used by the model lives in
agriflow_district_residue_2010_2023.csv (committed).
"""

from __future__ import annotations

import csv
import re
import time
from pathlib import Path

import requests
import urllib3

# data.desagri.gov.in serves an incomplete TLS chain that Python's certifi
# bundle does not trust (curl works because it uses the OS store). This is a
# read-only public data fetch — nothing sensitive is exchanged — so we accept
# the untrusted chain rather than fail the whole pipeline.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).resolve().parent
CACHE = BASE_DIR / "data_cache"
OUT_CSV = CACHE / "apy_gujarat_raw.csv"

REPORT_URL = "https://data.desagri.gov.in/report/crop/horizontal_crop_vertical_year"
POSTREQ_URL = "https://data.desagri.gov.in/postReq"
PAGE_URL = "https://data.desagri.gov.in/website/crops-apy-report-web"

STATE_GUJARAT = "24"

# Crop ids from the portal's state crop list (crop_name -> id), for the crops
# whose residue matters to AgriFlow (RPR conversion happens downstream).
CROPS = [
    (1, "rice"),
    (2, "wheat"),
    (3, "jowar"),
    (4, "bajra"),
    (5, "maize"),
    (13, "gram"),
    (14, "arhar_tur"),
    (15, "groundnut"),
    (16, "sesamum"),
    (17, "rapeseed_mustard"),
    (19, "castor"),
    (24, "soyabean"),
    (26, "cotton"),
    (62, "sugarcane"),
]

SEASONS = ["K", "R", "S", "A", "W", "Y"]  # Kharif, Rabi, Summer, Autumn, Winter, Whole Year
START_YEAR, END_YEAR = 2010, 2022

REQUEST_DELAY_S = 0.4  # be polite to the portal


def get_session() -> tuple[requests.Session, str]:
    """Return (session with cookies, csrf _token)."""
    s = requests.Session()
    s.verify = False  # see module note: portal TLS chain is broken
    r = s.get(PAGE_URL, timeout=60)
    r.raise_for_status()
    m = re.search(r'name="_token" value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("no CSRF token found on DES Agristat page")
    return s, m.group(1)


def fetch_districts(s: requests.Session, token: str) -> dict[str, str]:
    """districtcode -> normalized district name for Gujarat."""
    r = s.post(
        f"{POSTREQ_URL}?type=getsubBycode&codetype=fltrstates&code={STATE_GUJARAT}",
        data={"_token": token},
        timeout=60,
    )
    r.raise_for_status()
    payload = r.json()
    return {
        str(d["districtcode"]): re.sub(r"^\d+\.\s*", "", d["districtname"]).strip()
        for d in payload.get("dtlist", [])
    }


def fetch_report(
    s: requests.Session, token: str, crop_id: int, season: str
) -> str:
    """Fetch the APY report HTML for Gujarat, all districts, one crop+season."""
    r = s.post(
        REPORT_URL,
        data={
            "reportformat": "horizontal_crop_vertical_year",
            "fltrstates[]": STATE_GUJARAT,
            "fltrdistricts[]": "all",
            "fltrcrops[]": str(crop_id),
            "fltrseason[]": season,
            "fltrstartyear": str(START_YEAR),
            "fltrendyear": str(END_YEAR),
            "fltrrptformat": "scrview",
            "_token": token,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.text


def parse_report(html: str, districts: dict[str, str]) -> list[dict]:
    """Parse the report table into row dicts (district, year, area, prod, yield)."""
    tables = re.findall(r"<table.*?</table>", html, re.S)
    if not tables or "No Data Found" in html:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tables[0], re.S)

    out: list[dict] = []
    current_district: str | None = None
    for r in rows:
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
        ]
        # The state cell is rowspan'd across the whole table, so the FIRST
        # district header has 6 cells [state, district, year, A, P, Y] and
        # every later district header has 5 [district, year, A, P, Y]; both
        # are distinguished from year rows by containing a year in cell 1/2.
        if len(cells) >= 6 and re.match(r"^\d{4}", cells[2]):
            name = re.sub(r"^\d+\.\s*", "", cells[1]).strip()
            year, area, prod, yld = cells[2], cells[3], cells[4], cells[5]
        elif len(cells) == 5 and re.match(r"^\d{4}", cells[1]):
            name = re.sub(r"^\d+\.\s*", "", cells[0]).strip()
            year, area, prod, yld = cells[1], cells[2], cells[3], cells[4]
        elif len(cells) == 4 and re.match(r"^\d{4}", cells[0]):
            year, area, prod, yld = cells[0], cells[1], cells[2], cells[3]
        else:
            continue
        current_district = name
        if current_district is None:
            continue
        ym = re.match(r"(\d{4})", year)
        if not ym:
            continue
        try:
            area_f = float(area.replace(",", ""))
            prod_f = float(prod.replace(",", ""))
            yld_f = float(yld.replace(",", ""))
        except ValueError:
            continue
        out.append(
            {
                "district": current_district,
                "year": int(ym.group(1)),
                "area_ha": area_f,
                "production_tonnes": prod_f,
                "yield_per_ha": yld_f,
            }
        )
    return out


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    print("logging into DES Agristat...")
    s, token = get_session()
    districts = fetch_districts(s, token)
    print(f"  {len(districts)} Gujarat districts listed")

    rows: list[dict] = []
    for crop_id, crop in CROPS:
        for season in SEASONS:
            try:
                html = fetch_report(s, token, crop_id, season)
            except requests.RequestException as e:
                print(f"  !! {crop}/{season} request failed: {e}")
                continue
            parsed = parse_report(html, districts)
            for p in parsed:
                rows.append({"crop": crop, "season": season, **p})
            print(
                f"  {crop:16s} season {season}: {len(parsed):4d} rows"
                + ("" if parsed else " (no data)")
            )
            time.sleep(REQUEST_DELAY_S)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "district", "year", "crop", "season",
                "area_ha", "production_tonnes", "yield_per_ha",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nwrote {OUT_CSV} ({len(rows)} rows)")
    years = sorted({r["year"] for r in rows})
    crops = sorted({r["crop"] for r in rows})
    print(f"years: {years[0]}-{years[-1]} ({len(years)}), crops: {len(crops)}")


if __name__ == "__main__":
    main()
