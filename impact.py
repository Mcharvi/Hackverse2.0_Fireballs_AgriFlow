"""impact.py — CO2-avoided impact metric.

Converts "leftover supply that would otherwise be burned" into an
environmental impact number. Mirrors economics.py's structure: pure
function, demo-documented assumptions, no side effects.

SOURCES (state these if asked):
  - CO2_PER_TONNE_RESIDUE: measured combustion emission factor from
    Ni, H. et al. (2015), "Emission Characteristics of Carbonaceous
    Particles and Trace Gases from Open Burning of Crop Residues in
    China," Atmospheric Environment 123(B), 399-406. Lab-measured on
    wheat straw, rice straw, corn stalk (1351 g CO2/kg = 1.35 t/t).
    Reports GROSS combustion CO2, not IPCC Tier 1 net-GHG accounting
    (which treats residue-burning CO2 as biogenic/carbon-neutral and
    only counts CH4 + N2O). We use the gross figure because it matches
    how stubble-burning impact is communicated in Indian air-quality
    and policy contexts.
  - TREE_SEEDLINGS_PER_TONNE_CO2 / CAR_YEAR_TONNES_CO2: EPA Greenhouse
    Gas Equivalencies Calculator (epa.gov/energy/greenhouse-gas-
    equivalencies-calculator). Note the seedling figure is "grown for
    10 years," not absorbed in year one — a young sapling absorbs far
    less than a mature tree.
  - INDIA_ANNUAL_RESIDUE_BURNING_CO2_TONNES: Jain, N. et al. (2014),
    "Emission of Air Pollutants from Crop Residue Burning in India,"
    Aerosol and Air Quality Research 14, 422-430. State-wise IPCC-
    methodology inventory for base year 2008-09: 141.15 Mt CO2 from
    crop residue burning nationally. This is an older base year —
    stated explicitly as a scale reference, not a live/current figure.

ASSUMPTIONS:
  - 1 dataset biomass unit = 1 tonne.
"""

CO2_PER_TONNE_RESIDUE = 1.35              # Ni et al. 2015, measured
CAR_YEAR_TONNES_CO2 = 4.6                 # EPA, tonnes CO2e/vehicle/year
TREE_SEEDLINGS_PER_TONNE_CO2 = 16.5       # EPA, seedlings grown 10 yrs / tonne CO2
INDIA_ANNUAL_RESIDUE_BURNING_CO2_TONNES = 141_150_000  # Jain et al. 2014, base year 2008-09


def compute_impact(districts: list[dict], matches: list[dict]) -> dict:
    total_supply = sum(float(d["predicted_supply_2018"]) for d in districts)
    matched = sum(m["matched_supply"] for m in matches)
    leftover = max(0.0, total_supply - matched)

    co2_avoided_tonnes = leftover * CO2_PER_TONNE_RESIDUE
    pct_of_india_total = 100 * co2_avoided_tonnes / INDIA_ANNUAL_RESIDUE_BURNING_CO2_TONNES

    return {
        "leftover_tonnes": round(leftover, 1),
        "co2_avoided_tonnes": round(co2_avoided_tonnes, 1),
        "equivalent_cars_off_road_for_a_year": round(co2_avoided_tonnes / CAR_YEAR_TONNES_CO2, 1),
        "equivalent_tree_seedlings_grown_10yr": round(co2_avoided_tonnes * TREE_SEEDLINGS_PER_TONNE_CO2),
        "pct_of_india_annual_residue_burning_co2": round(pct_of_india_total, 3),
        "assumptions": {
            "unit_to_tonnes": "1 dataset unit = 1 tonne",
            "co2_per_tonne_residue": CO2_PER_TONNE_RESIDUE,
            "co2_source": "Ni et al. 2015, Atmospheric Environment 123(B) — measured combustion EF",
            "car_year_tonnes_co2": CAR_YEAR_TONNES_CO2,
            "tree_seedlings_per_tonne_co2": TREE_SEEDLINGS_PER_TONNE_CO2,
            "india_reference_year": "2008-09 (Jain et al. 2014)",
            "india_reference_tonnes": INDIA_ANNUAL_RESIDUE_BURNING_CO2_TONNES,
            "note": "Gross CO2 from open combustion — commonly-cited public/policy framing, not IPCC Tier 1 net-GHG accounting.",
        },
    }