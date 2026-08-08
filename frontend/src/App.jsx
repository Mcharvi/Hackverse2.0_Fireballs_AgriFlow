import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "./api.js";

const TIER_COLORS = { High: "#ef4444", Medium: "#f59e0b", Low: "#22c55e" };

function fmt(n) {
  return (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

export default function App() {
  const mapElRef = useRef(null);
  const mapRef = useRef(null);
  const layersRef = useRef({ districts: null, plants: null, routes: null });

  const [districts, setDistricts] = useState([]);
  const [plants, setPlants] = useState([]);
  const [matches, setMatches] = useState([]);
  const [summary, setSummary] = useState(null);
  const [selected, setSelected] = useState(null);
  const [chat, setChat] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.districts(), api.plants(), api.matches()])
      .then(([d, p, m]) => {
        setDistricts(d);
        setPlants(p);
        setMatches(m);
        // Stats computed client-side so the UI works against any backend
        // contract (no /sustainability dependency).
        const totalSupply = d.reduce((s, x) => s + (x.predicted_supply_2018 || 0), 0);
        const matched = m.reduce((s, x) => s + (x.matched_supply || 0), 0);
        setSummary({
          total_predicted_supply_units: totalSupply,
          matched_units: matched,
        });
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Draw the map once the data is loaded.
  useEffect(() => {
    if (!mapElRef.current) return;
    if (!mapRef.current) {
      mapRef.current = L.map(mapElRef.current, { center: [22.7, 71.5], zoom: 7 });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(mapRef.current);
    }
    const map = mapRef.current;
    ["districts", "plants", "routes"].forEach((k) => {
      if (layersRef.current[k]) layersRef.current[k].clearLayers();
    });

    const districtLayer = L.layerGroup();
    districts.forEach((d) => {
      L.circleMarker([d.latitude, d.longitude], {
        radius: 6 + Math.sqrt(d.predicted_supply_2018) / 45,
        color: TIER_COLORS[d.supply_tier] || "#888888",
        fillColor: TIER_COLORS[d.supply_tier] || "#888888",
        fillOpacity: 0.7,
        weight: 1,
      })
        .bindTooltip(`${d.district} — ${fmt(d.predicted_supply_2018)} units`)
        .on("click", () => setSelected({ kind: "district", data: d }))
        .addTo(districtLayer);
    });
    layersRef.current.districts = districtLayer.addTo(map);

    const plantLayer = L.layerGroup();
    plants.forEach((p) => {
      L.circleMarker([p.latitude, p.longitude], {
        radius: 9,
        color: "#3b82f6",
        fillColor: "#3b82f6",
        fillOpacity: 0.9,
        weight: 2,
      })
        .bindTooltip(`${p.plant_name} — ${fmt(p.annual_capacity)} units/yr`)
        .on("click", () => setSelected({ kind: "plant", data: p }))
        .addTo(plantLayer);
    });
    layersRef.current.plants = plantLayer.addTo(map);

    const routeLayer = L.layerGroup();
    const plantPos = Object.fromEntries(
      plants.map((p) => [p.plant_id, [p.latitude, p.longitude]])
    );
    matches.forEach((m) => {
      const d = districts.find((x) => x.district === m.district);
      const ppos = plantPos[m.matched_plant_id];
      if (d && ppos) {
        L.polyline([[d.latitude, d.longitude], ppos], {
          color: "#3b82f6",
          weight: 2,
          opacity: 0.55,
        })
          .bindTooltip(
            `${d.district} → ${m.matched_plant_id} · ${fmt(m.matched_supply)} units · ${m.distance_km} km`
          )
          .addTo(routeLayer);
      }
    });
    layersRef.current.routes = routeLayer.addTo(map);
  }, [districts, plants, matches]);

// Replace the existing `ask` function in App.jsx with this version.
  // Only this one function changes — everything else in App.jsx stays the same.
  async function ask() {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");

    // Build history from turns so far (oldest first), BEFORE adding this
    // question to `chat` state — this is what lets follow-ups like
    // "how far is that from Amreli?" resolve correctly.
    const history = chat.map((m) => ({ role: m.role, content: m.text }));

    setChat((c) => [...c, { role: "user", text: q }]);
    try {
      const { answer } = await api.ask(q, history);
      setChat((c) => [...c, { role: "assistant", text: answer }]);
    } catch (e) {
      setChat((c) => [...c, { role: "assistant", text: `Error: ${e}` }]);
    }
    setBusy(false);
  }

  const leftover = summary
    ? summary.total_predicted_supply_units - summary.matched_units
    : null;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>
            AgriFlow <span className="accent">AI</span>
          </h1>
          <p className="tagline">Biomass intelligence — from fields to plants, today.</p>
        </div>
        {summary && (
          <div className="stats">
            <div>
              <span className="stat-label">Predicted supply</span>
              <b>{fmt(summary.total_predicted_supply_units)}</b>
              <small>units</small>
            </div>
            <div>
              <span className="stat-label">Matched</span>
              <b>{fmt(summary.matched_units)}</b>
              <small>units</small>
            </div>
            <div>
              <span className="stat-label">Leftover</span>
              <b className="warn">{fmt(leftover)}</b>
              <small>would otherwise burn</small>
            </div>
          </div>
        )}
      </header>

      {error && (
        <div className="error-banner">⚠ Could not reach the API: {error}</div>
      )}

      <div className="layout">
        <div className="map-wrap">
          <div ref={mapElRef} className="map" />
        </div>

        <aside className="panel">
          {selected ? (
            selected.kind === "district" ? (
              <DistrictCard d={selected.data} onClose={() => setSelected(null)} />
            ) : (
              <PlantCard p={selected.data} onClose={() => setSelected(null)} />
            )
          ) : (
            <div className="hint">
              <h3>Click a district or plant</h3>
              <p>
                Districts are colored by supply tier:{" "}
                <span className="swatch" style={{ background: TIER_COLORS.High }} />
                High
                <span className="swatch" style={{ background: TIER_COLORS.Medium }} />
                Medium
                <span className="swatch" style={{ background: TIER_COLORS.Low }} />
                Low. Blue dots are plants; blue lines show today's matched routes.
              </p>
              <p className="units-note">
                All quantities are dimensionless dataset biomass units (not tonnes).
              </p>
            </div>
          )}
        </aside>

        <div className="chat">
          <div className="chat-log">
            {chat.length === 0 && (
              <p className="chat-empty">
                Ask the AI assistant — e.g. “Which district has the highest biomass?”
              </p>
            )}
            {chat.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                {m.text}
              </div>
            ))}
          </div>
          <div className="chat-input">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask()}
              placeholder="Ask about biomass, plants, or routing…"
            />
            <button onClick={ask} disabled={busy}>
              {busy ? "…" : "Ask"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DistrictCard({ d, onClose }) {
  return (
    <div className="card">
      <h3>{d.district}</h3>
      <span className={`tier tier-${d.supply_tier.toLowerCase()}`}>
        {d.supply_tier} supply
      </span>
      <dl>
        <dt>Predicted supply (2018)</dt>
        <dd>{fmt(d.predicted_supply_2018)} units</dd>
        <dt>Confidence</dt>
        <dd>
          {d.confidence_score_heuristic} ({d.confidence_label})
        </dd>
        <dt>Residue type</dt>
        <dd>{d.residue_type}</dd>
        <dt>Harvest window</dt>
        <dd>{d.harvest_window}</dd>
        <dt>Baseline (2017)</dt>
        <dd>{fmt(d.baseline_supply_2017)} units</dd>
        <dt>Sites aggregated</dt>
        <dd>{d.site_count_2017}</dd>
      </dl>
      <button className="close" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

function PlantCard({ p, onClose }) {
  return (
    <div className="card">
      <h3>{p.plant_name}</h3>
      <span className="tier tier-plant">Plant</span>
      <dl>
        <dt>Capacity</dt>
        <dd>{fmt(p.annual_capacity)} units/yr</dd>
        <dt>Utilization</dt>
        <dd>{p.utilization_pct ?? 0}%</dd>
        <dt>Representative district</dt>
        <dd>{p.representative_district}</dd>
        <dt>Status</dt>
        <dd>{p.facility_status}</dd>
      </dl>
      <button className="close" onClick={onClose}>
        Close
      </button>
    </div>
  );
}
