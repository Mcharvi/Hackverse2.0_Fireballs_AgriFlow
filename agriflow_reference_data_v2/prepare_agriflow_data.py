import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

INPUT = "biomass_long.csv"

raw = pd.read_csv(INPUT)
district_year = (
    raw.groupby(["distname", "year"])
       .agg(
           biomass=("biomass", "sum"),
           cropland=("cropland", "sum"),
           avg_precipitation=("cum_precipitation", "mean"),
           avg_elevation=("elevations", "mean"),
           site_count=("index", "nunique"),
           latitude=("lat", "mean"),
           longitude=("lon", "mean"),
       )
       .reset_index()
)

gujarat_districts = {
    "Ahmadabad","Amreli","Anand","Aravali","Banas Kantha","Batod","Bharuch",
    "Bhavnagar","Chhota Udaipur","Devbhumi Dwarka","Dohad","Gandhinagar",
    "Gir Somnath","Jamnagar","Junagadh","Kachchh","Kheda","Mahesana",
    "Mahisagar","Morbi","Narmada","Navsari","Panch Mahals","Patan","Porbandar",
    "Rajkot","Sabar Kantha","Surat","Surendranagar","Tapi","The Dangs",
    "Vadodara","Valsad"
}

g = district_year[district_year["distname"].isin(gujarat_districts)].copy()
latest = g[g["year"] == 2017].sort_values("biomass")

low = latest.iloc[:7]["distname"].tolist()
mid = latest.iloc[13:19]["distname"].tolist()
high = latest.iloc[-7:]["distname"].tolist()
selected = low + mid + high

residue_map = {
    "Rajkot": ("Groundnut shell / cotton stalk", "official crop profile"),
    "Amreli": ("Groundnut shell / cotton stalk", "official district crop profile"),
    "Jamnagar": ("Groundnut shell / cotton stalk", "official district crop profile"),
    "Bhavnagar": ("Groundnut shell", "official crop profile"),
    "Morbi": ("Mixed agricultural residue", "demo assumption"),
    "Surendranagar": ("Groundnut shell / cotton stalk", "official crop profile"),
    "Ahmadabad": ("Rice straw / mixed residue", "official crop profile"),
    "Surat": ("Rice straw", "official crop profile"),
    "Patan": ("Cumin/fennel residue", "official crop profile"),
    "Kheda": ("Rice straw", "official crop profile"),
    "Sabar Kantha": ("Castor stalk / mixed residue", "official crop profile"),
    "Gandhinagar": ("Mixed agricultural residue", "demo assumption"),
    "Chhota Udaipur": ("Pulse residue", "official crop profile"),
    "Porbandar": ("Mixed agricultural residue", "demo assumption"),
    "Tapi": ("Mixed agricultural residue", "demo assumption"),
    "Navsari": ("Rice straw", "official crop profile"),
    "Valsad": ("Rice straw", "official crop profile"),
    "Mahisagar": ("Pulse residue", "demo assumption"),
    "Dohad": ("Pulse residue", "official crop profile"),
    "The Dangs": ("Mixed agricultural residue", "demo assumption"),
}

rows = []
for dist in selected:
    h = g[g["distname"] == dist].sort_values("year")
    X, y = h[["year"]], h["biomass"]
    model = LinearRegression().fit(X, y)

    trend_forecast = float(model.predict(pd.DataFrame({"year": [2018]}))[0])
    rolling3 = float(h.tail(3)["biomass"].mean())
    blended = 0.70 * rolling3 + 0.30 * trend_forecast
    predicted = float(np.clip(blended, 0.85 * rolling3, 1.15 * rolling3))

    r2 = max(0.0, float(model.score(X, y)))
    cv3 = float(h.tail(3)["biomass"].std(ddof=1) / h.tail(3)["biomass"].mean())
    confidence_score = float(np.clip(
        100 * (0.60 * (1 / (1 + cv3)) + 0.40 * r2), 0, 100
    ))
    confidence_label = (
        "High" if confidence_score >= 75
        else "Moderate" if confidence_score >= 55
        else "Low"
    )

    latest_row = h[h["year"] == 2017].iloc[0]
    residue, residue_source = residue_map.get(
        dist, ("Mixed agricultural residue", "demo assumption")
    )

    rows.append({
        "district": dist,
        "latitude": round(float(h["latitude"].mean()), 6),
        "longitude": round(float(h["longitude"].mean()), 6),
        "baseline_supply_2017": round(float(latest_row["biomass"]), 3),
        "rolling_3yr_supply": round(rolling3, 3),
        "trend_forecast_2018": round(trend_forecast, 3),
        "predicted_supply_2018": round(predicted, 3),
        "trend_r2": round(r2, 3),
        "confidence_score_heuristic": round(confidence_score, 1),
        "confidence_label": confidence_label,
        "cropland_2017": round(float(latest_row["cropland"]), 3),
        "avg_precipitation_2017": round(float(latest_row["avg_precipitation"]), 3),
        "avg_elevation_2017": round(float(latest_row["avg_elevation"]), 3),
        "site_count_2017": int(latest_row["site_count"]),
        "residue_type": residue,
        "residue_type_source": residue_source,
        "harvest_window": "Sep–Nov (demo operational window)",
        "supply_tier": "High" if dist in high else "Medium" if dist in mid else "Low",
    })

districts_out = pd.DataFrame(rows).sort_values(
    "predicted_supply_2018", ascending=False
).reset_index(drop=True)
districts_out.to_csv("agriflow_district_supply.csv", index=False)

plant_specs = [
    ("P1", "AgriFlow Plant 1", "Rajkot", 30000),
    ("P2", "AgriFlow Plant 2", "Bhavnagar", 25000),
    ("P3", "AgriFlow Plant 3", "Ahmadabad", 22000),
    ("P4", "AgriFlow Plant 4", "Jamnagar", 22000),
    ("P5", "AgriFlow Plant 5", "Surat", 18000),
    ("P6", "AgriFlow Plant 6", "Kheda", 18000),
]

plants = []
for pid, name, district, cap in plant_specs:
    r = districts_out[districts_out["district"] == district].iloc[0]
    plants.append({
        "plant_id": pid,
        "plant_name": name,
        "representative_district": district,
        "latitude": r["latitude"],
        "longitude": r["longitude"],
        "annual_capacity": cap,
        "capacity_unit": "dataset biomass units/year",
        "facility_status": "synthetic demo facility",
    })

pd.DataFrame(plants).to_csv("agriflow_plants.csv", index=False)
