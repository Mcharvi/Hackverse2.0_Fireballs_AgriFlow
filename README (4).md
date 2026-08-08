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

7. The six plants are synthetic demo facilities. Their capacities are expressed
   in `dataset biomass units/year`.

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

## Attribution

"Biomass estimates informed by the Shell.ai 2023 Agricultural Waste Challenge
dataset, with EarthStat cropland and NASA-derived environmental inputs.
District aggregation, prediction stabilization, matching, routing, and the
query layer are our own implementation for operational biomass matching."
