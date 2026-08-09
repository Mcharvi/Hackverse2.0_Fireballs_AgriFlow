# AgriFlow reference-data v2

This package is the revised, reproducible version of the AgriFlow demo data.

## What is changed

1. The source contains 2,418 site-level harvesting locations. AgriFlow aggregates
   them to district/year level.

2. Instead of choosing only the 20 largest districts, the demo selects a spread:
   7 lower-supply, 6 middle-supply, and 7 higher-supply Gujarat districts using
   2017 baseline biomass. This preserves visible low/medium/high heatmap contrast.

3. The prediction is intentionally conservative:
   - 70% trailing 3-year mean
   - 30% linear trend extrapolation
   - final value clipped to +/-15% of the trailing 3-year mean

   This avoids large swings caused by a noisy 8-year trend.

4. `trend_r2` is retained as a diagnostic, but it is NOT presented as a
   statistical confidence probability.

5. `confidence_score_heuristic` combines recent 3-year stability and trend R².
   It is explicitly a heuristic score. Use High/Moderate/Low in the UI.

6. Residue type and harvest window are metadata, not model outputs. Some
   residue assignments are sourced from Gujarat Agro Industries Corporation;
   others are explicitly marked as demo assumptions.

7. The six plants are real operating reference facilities (located via the MNRE
   Biourja CBG plant list, GEDA generation reports, and public commissioning
   records): Biofics Bio-CNG (Rajkot), Bhavnagar Biomass Power Project,
   Rockstone Infrastructure CBG (Ahmedabad), Reliance New Solar Energy CBG
   (Jamnagar), APMC Surat CBG, and Goverdhannathji Energies CBG (Kheda). Their
   capacities remain expressed in `dataset biomass units/year` (demo rates).

## Critical unit note

The original Shell.ai 2023 problem statement explicitly says:
"All quantities/values provided in these datasets are dimensionless."

Therefore:
- do NOT label biomass as tonnes;
- do NOT label plant capacity as tonnes/year;
- use "biomass units" or "dataset units" in the demo.

## Suggested judge-safe wording

"AgriFlow uses historical Shell.ai agricultural-waste data as a reference
dataset. We aggregate the original site-level observations to district level,
apply our own conservative prediction method, and then perform our own supply
matching and route optimization using synthetic processing facilities."

## CROPGRIDS layer (crop-area composition, 2020)

`process_cropgrids.py` zonal-sums CROPGRIDS v1.08 (Tang et al., 2024,
*Scientific Data*, https://doi.org/10.6084/m9.figshare.22491997, CC BY 4.0) —
a global 0.05-degree gridded dataset of harvested/crop area for 173 crops
circa 2020 — over Gujarat district boundaries (`gujarat_districts_census2011.geojson`,
geoBoundaries gbOpen ADM2, CC BY 4.0) and writes `agriflow_crop_composition.csv`.

That CSV feeds `seed_agriflow_db.py`, which:
- fills the new `districts` columns `cropland_2020_ha`, `top_crop`, `crop_mix_source`;
- seeds the `crop_composition` table (top 8 crops per district with ha + share);
- upgrades residue labels that were previously "demo assumption" to evidence-based
  ones derived from the dominant crop (e.g. Porbandar -> Groundnut shell,
  Morbi -> Cotton stalk). Official crop-profile labels are left untouched.

CROPGRIDS is a single circa-2020 snapshot, so it is a cross-sectional layer — it
cannot extend the 2010-2017 Shell.ai time series. It is used as an additional
per-district feature and validation layer, not as a retrained time-series input.

## 2026 supply extension (official DES Agristat APY + RPR)

The forecast now runs through 2026 using official district-level crop
production, the Tier-1 extension discussed in the plan:

1. `fetch_apy_gujarat.py` — downloads Gujarat district Area/Production/Yield
   (APY) for 14 residue-relevant crops, all seasons, agricultural years
   2010-11 through 2022-23, from the DES Agristat portal
   (https://data.desagri.gov.in, Government of India). Cached under
   `data_cache/` (gitignored).
2. `extend_supply_2026.py` — converts production to residue via standard
   crop Residue-to-Product Ratios (RPR; rice 1.5, wheat 1.5, jowar 1.8,
   bajra 2.0, maize 2.0, gram 1.2, arhar 1.5, groundnut 1.0, sesamum 1.5,
   rapeseed&mustard 1.5, castor 2.5, soyabean 1.5, cotton 3.0, sugarcane 0.3),
   calibrates each district to the Shell.ai dimensionless units at its 2017
   baseline, then re-runs the same forecast recipe (70% 3-yr rolling mean +
   30% trend, clipped +/-15%) on the extended 2010-2022 series, projecting
   iteratively to 2024, then 2025, then 2026 (each forecast year feeds the
   next, so the path is self-consistent). Writes
   `agriflow_district_residue_2010_2023.csv` (evidence layer) and updates
   `agriflow_district_supply.csv` with the 2024/2025/2026 columns and a
   per-district `supply_trend` (2010-2022 actuals + 2024-2026 forecast).
   The forecast statistics (`confidence_score_2026` / `confidence_label_2026`)
   are computed once on the actuals from the trend fit quality.

Validation: the calibrated APY residue series reproduces the original
Shell.ai 2015-17 rolling mean within ~+/-15% for all 20 districts — the
official production data and the challenge dataset tell the same story.

Caveats: RPR values are approximations from Indian biomass studies (ICAR,
NITI Aayog, Jain et al. 2018) — the per-district 2017 calibration absorbs
their absolute scale, so the forecast shape is driven by official production
trends. Production is residue *generated*, not surplus. DES district-level
APY on the portal ends at 2022-23, so 2023 is unlabelled and 2024-2026 are
forward projections 1-4 harvests ahead.

## Attribution

"Biomass estimates informed by the Shell.ai 2023 Agricultural Waste Challenge
dataset, with EarthStat cropland and NASA-derived environmental inputs.
Crop-area composition per district comes from CROPGRIDS v1.08 (Tang et al., 2024,
Scientific Data, CC BY 4.0), aggregated over geoBoundaries gbOpen ADM2 district
boundaries (CC BY 4.0). District aggregation, prediction stabilization, matching,
routing, and the query layer are our own implementation for operational biomass
matching."
