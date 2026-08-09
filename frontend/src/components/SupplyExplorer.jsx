// SupplyExplorer — tabbed deep-dive into the numbers behind the map.
// Tabs (via ContinuousTabs): Predicted Supply / Matched to Plants /
// Plants / Leftover. All data is passed in from App state, so it always
// agrees with what the map is showing.
import { useMemo, useState } from "react";
import ContinuousTabs from "./ContinuousTabs.jsx";

const fmt = (n) => (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });

const TIER_COLORS = { High: "#1e5631", Medium: "#4caf50", Low: "#c9c9c9" };

export default function SupplyExplorer({ districts, plants, matches }) {
  const [active, setActive] = useState("supply");

  const matchedDistricts = useMemo(
    () => new Set(matches.map((m) => m.district)),
    [matches]
  );
  const totalSupply = useMemo(
    () =>
      districts.reduce(
        (s, d) =>
          s +
          (d.predicted_supply_2026 ?? d.predicted_supply_2024 ?? d.predicted_supply_2018 ?? 0),
        0
      ),
    [districts]
  );
  const matchedUnits = useMemo(
    () => matches.reduce((s, m) => s + (m.matched_supply || 0), 0),
    [matches]
  );

  const tabs = [
    { id: "supply", label: "Predicted Supply" },
    { id: "matched", label: "Matched to Plants" },
    { id: "plants", label: "Plants" },
    { id: "leftover", label: "Leftover" },
  ];

  return (
    <section className="explorer">
      <div className="explorer-heading">
        <h2>Explore the numbers</h2>
        <p>Predicted supply, plant matching, and what's left over — dive into each view.</p>
      </div>

      <ContinuousTabs tabs={tabs} defaultActiveId="supply" onChange={setActive} />

      <div className="explorer-body">
        {active === "supply" && <SupplyTab districts={districts} total={totalSupply} />}
        {active === "matched" && <MatchedTab matches={matches} total={matchedUnits} />}
        {active === "plants" && <PlantsTab plants={plants} />}
        {active === "leftover" && (
          <LeftoverTab
            unmatched={districts.filter((d) => !matchedDistricts.has(d.district))}
            total={totalSupply - matchedUnits}
          />
        )}
      </div>
    </section>
  );
}

function SupplyTab({ districts, total }) {
  const supplyOf = (d) =>
    d.predicted_supply_2026 ?? d.predicted_supply_2024 ?? d.predicted_supply_2018 ?? 0;
  const rows = [...districts].sort((a, b) => supplyOf(b) - supplyOf(a));
  return (
    <>
      <div className="explorer-meta">
        <b>{fmt(total)}</b> units predicted across <b>{rows.length}</b> districts — the
        2026 forecast extends the original challenge-series trend with official district
        APY residue (DES Agristat 2010–2022), projected iteratively 2024 → 2026 with the
        same blend: 70% rolling mean + 30% trend, clipped ±15%.
      </div>
      <table className="explorer-table">
        <thead>
          <tr>
            <th>District</th>
            <th>Tier</th>
            <th>Predicted supply (2026)</th>
            <th>Confidence</th>
            <th>Harvest window</th>
            <th>Residue</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.district}>
              <td>
                <b>{d.district}</b>
              </td>
              <td>
                <span className="explorer-tier">
                  <span
                    className="explorer-dot"
                    style={{ background: TIER_COLORS[d.supply_tier] || "#999" }}
                  />
                  {d.supply_tier}
                </span>
              </td>
              <td>
                {fmt(
                  d.predicted_supply_2026 ?? d.predicted_supply_2024 ?? d.predicted_supply_2018
                )}{" "}
                units
              </td>
              <td>
                {d.confidence_score_2026 ?? d.confidence_score_2024 ?? d.confidence_score_heuristic}{" "}
                ({d.confidence_label_2026 ?? d.confidence_label_2024 ?? d.confidence_label})
              </td>
              <td>{d.harvest_window}</td>
              <td>{d.residue_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function MatchedTab({ matches, total }) {
  const rows = [...matches].sort((a, b) =>
    a.matched_plant_id === b.matched_plant_id
      ? (a.pickup_order || 0) - (b.pickup_order || 0)
      : a.matched_plant_id.localeCompare(b.matched_plant_id)
  );
  return (
    <>
      <div className="explorer-meta">
        <b>{rows.length}</b> districts matched, <b>{fmt(total)}</b> units allocated — greedy
        nearest-viable-plant matching by capacity, then distance.
      </div>
      <table className="explorer-table">
        <thead>
          <tr>
            <th>District</th>
            <th>Matched to</th>
            <th>Allocated</th>
            <th>Distance</th>
            <th>Pickup order</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m, i) => (
            <tr key={i}>
              <td>
                <b>{m.district}</b>
              </td>
              <td>
                <span className="explorer-arrow">→</span> {m.matched_plant_id}
              </td>
              <td>{fmt(m.matched_supply)} units</td>
              <td>{m.distance_km} km</td>
              <td>{m.pickup_order}</td>
              <td>
                <span className="explorer-badge is-matched">{m.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function PlantsTab({ plants }) {
  return (
    <>
      <div className="explorer-meta">
        <b>{plants.length}</b> processing plants — current load against annual capacity.
      </div>
      <table className="explorer-table">
        <thead>
          <tr>
            <th>Plant</th>
            <th>Capacity</th>
            <th>Current load</th>
            <th>Utilization</th>
            <th>Representative district</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {plants.map((p) => (
            <tr key={p.plant_id}>
              <td>
                <b>{p.plant_name}</b>
              </td>
              <td>{fmt(p.annual_capacity)} units/yr</td>
              <td>{fmt(p.current_utilization)} units</td>
              <td>
                <span className="util-bar">
                  <span style={{ width: `${Math.min(100, p.utilization_pct ?? 0)}%` }} />
                </span>
                <span className="util-num">{p.utilization_pct ?? 0}%</span>
              </td>
              <td>{p.representative_district}</td>
              <td>
                <span className="explorer-badge">{p.facility_status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function LeftoverTab({ unmatched, total }) {
  const supplyOf = (d) =>
    d.predicted_supply_2026 ?? d.predicted_supply_2024 ?? d.predicted_supply_2018 ?? 0;
  const rows = [...unmatched].sort((a, b) => supplyOf(b) - supplyOf(a));
  return (
    <>
      <div className="explorer-meta">
        <b>{rows.length}</b> districts unserved, <b>{fmt(total)}</b> units still uncollected —
        candidates for the plant siting simulator.
      </div>
      {rows.length === 0 ? (
        <p className="explorer-empty">Every district is matched — nothing left over. 🎉</p>
      ) : (
        <table className="explorer-table">
          <thead>
            <tr>
              <th>District</th>
              <th>Tier</th>
              <th>Predicted supply</th>
              <th>Residue</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.district}>
                <td>
                  <b>{d.district}</b>
                </td>
                <td>
                  <span className="explorer-tier">
                    <span
                      className="explorer-dot"
                      style={{ background: TIER_COLORS[d.supply_tier] || "#999" }}
                    />
                    {d.supply_tier}
                  </span>
                </td>
                <td>
                  {fmt(
                    d.predicted_supply_2026 ?? d.predicted_supply_2024 ?? d.predicted_supply_2018
                  )}{" "}
                  units
                </td>
                <td>{d.residue_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
