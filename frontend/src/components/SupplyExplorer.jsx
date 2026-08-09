import { useMemo, useState } from "react";
import ContinuousTabs from "./ContinuousTabs.jsx";
import { useLanguage } from "../LanguageContext.jsx";

const fmt = (n) => (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });

const TIER_COLORS = { High: "#1e5631", Medium: "#4caf50", Low: "#c9c9c9" };

export default function SupplyExplorer({ districts, plants, matches }) {
  const { t } = useLanguage();
  const [active, setActive] = useState("supply");

  const matchedDistricts = useMemo(
    () => new Set(matches.map((m) => m.district)),
    [matches]
  );
  const totalSupply = useMemo(
    () => districts.reduce((s, d) => s + (d.predicted_supply_2018 || 0), 0),
    [districts]
  );
  const matchedUnits = useMemo(
    () => matches.reduce((s, m) => s + (m.matched_supply || 0), 0),
    [matches]
  );

  const tabs = [
    { id: "supply", label: t.tabSupply },
    { id: "matched", label: t.tabMatched },
    { id: "plants", label: t.tabPlants },
    { id: "leftover", label: t.tabLeftover },
  ];

  return (
    <section className="explorer">
      <div className="explorer-heading">
        <h2>{t.explorerHeading}</h2>
        <p>{t.explorerSubheading}</p>
      </div>

      <ContinuousTabs tabs={tabs} defaultActiveId="supply" onChange={setActive} />

      <div className="explorer-body">
        {active === "supply" && <SupplyTab districts={districts} total={totalSupply} t={t} />}
        {active === "matched" && <MatchedTab matches={matches} total={matchedUnits} t={t} />}
        {active === "plants" && <PlantsTab plants={plants} t={t} />}
        {active === "leftover" && (
          <LeftoverTab
            unmatched={districts.filter((d) => !matchedDistricts.has(d.district))}
            total={totalSupply - matchedUnits}
            t={t}
          />
        )}
      </div>
    </section>
  );
}

function SupplyTab({ districts, total, t }) {
  const rows = [...districts].sort(
    (a, b) => (b.predicted_supply_2018 || 0) - (a.predicted_supply_2018 || 0)
  );
  return (
    <>
      <div className="explorer-meta">{t.supplyMeta(fmt(total), rows.length)}</div>
      <table className="explorer-table">
        <thead>
          <tr>
            <th>{t.colDistrict}</th>
            <th>{t.colTier}</th>
            <th>{t.colPredictedSupply}</th>
            <th>{t.colConfidence}</th>
            <th>{t.colHarvestWindow}</th>
            <th>{t.colResidue}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.district}>
              <td><b>{d.district}</b></td>
              <td>
                <span className="explorer-tier">
                  <span className="explorer-dot" style={{ background: TIER_COLORS[d.supply_tier] || "#999" }} />
                  {d.supply_tier}
                </span>
              </td>
              <td>{fmt(d.predicted_supply_2018)} units</td>
              <td>{d.confidence_score_heuristic} ({d.confidence_label})</td>
              <td>{d.harvest_window}</td>
              <td>{d.residue_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function MatchedTab({ matches, total, t }) {
  const rows = [...matches].sort((a, b) =>
    a.matched_plant_id === b.matched_plant_id
      ? (a.pickup_order || 0) - (b.pickup_order || 0)
      : a.matched_plant_id.localeCompare(b.matched_plant_id)
  );
  return (
    <>
      <div className="explorer-meta">{t.matchedMeta(rows.length, fmt(total))}</div>
      <table className="explorer-table">
        <thead>
          <tr>
            <th>{t.colDistrict}</th>
            <th>{t.colMatchedTo}</th>
            <th>{t.colAllocated}</th>
            <th>{t.colDistance}</th>
            <th>{t.colPickupOrder}</th>
            <th>{t.colStatus}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m, i) => (
            <tr key={i}>
              <td><b>{m.district}</b></td>
              <td><span className="explorer-arrow">→</span> {m.matched_plant_id}</td>
              <td>{fmt(m.matched_supply)} units</td>
              <td>{m.distance_km} km</td>
              <td>{m.pickup_order}</td>
              <td><span className="explorer-badge is-matched">{m.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function PlantsTab({ plants, t }) {
  return (
    <>
      <div className="explorer-meta">{t.plantsMeta(plants.length)}</div>
      <table className="explorer-table">
        <thead>
          <tr>
            <th>{t.colPlant}</th>
            <th>{t.colCapacity}</th>
            <th>{t.colCurrentLoad}</th>
            <th>{t.colUtilization}</th>
            <th>{t.colRepDistrict}</th>
            <th>{t.colStatus}</th>
          </tr>
        </thead>
        <tbody>
          {plants.map((p) => (
            <tr key={p.plant_id}>
              <td><b>{p.plant_name}</b></td>
              <td>{fmt(p.annual_capacity)} units/yr</td>
              <td>{fmt(p.current_utilization)} units</td>
              <td>
                <span className="util-bar">
                  <span style={{ width: `${Math.min(100, p.utilization_pct ?? 0)}%` }} />
                </span>
                <span className="util-num">{p.utilization_pct ?? 0}%</span>
              </td>
              <td>{p.representative_district}</td>
              <td><span className="explorer-badge">{p.facility_status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function LeftoverTab({ unmatched, total, t }) {
  const rows = [...unmatched].sort(
    (a, b) => (b.predicted_supply_2018 || 0) - (a.predicted_supply_2018 || 0)
  );
  return (
    <>
      <div className="explorer-meta">{t.leftoverMeta(rows.length, fmt(total))}</div>
      {rows.length === 0 ? (
        <p className="explorer-empty">{t.leftoverEmpty}</p>
      ) : (
        <table className="explorer-table">
          <thead>
            <tr>
              <th>{t.colDistrict}</th>
              <th>{t.colTier}</th>
              <th>{t.colPredictedSupply}</th>
              <th>{t.colResidue}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.district}>
                <td><b>{d.district}</b></td>
                <td>
                  <span className="explorer-tier">
                    <span className="explorer-dot" style={{ background: TIER_COLORS[d.supply_tier] || "#999" }} />
                    {d.supply_tier}
                  </span>
                </td>
                <td>{fmt(d.predicted_supply_2018)} units</td>
                <td>{d.residue_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}