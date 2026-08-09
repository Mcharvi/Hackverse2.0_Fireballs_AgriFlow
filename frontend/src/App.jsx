//this is app.jsx
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "./LanguageContext.jsx";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "./api.js";
import Navbar from "./components/Navbar.jsx";
import Hero from "./components/Hero.jsx";
import AIAssistantPanel from "./components/AIAssistantPanel.jsx";
import SupplyExplorer from "./components/SupplyExplorer.jsx";

// Simple 3-color supply-tier + map palette (matches styles.css tokens).
// High = red, Medium = yellow, Low = green — reads as a risk/urgency heatmap.
const TIER_COLORS = { High: "#d32f2f", Medium: "#f2c94c", Low: "#1e5631" };
const PLANT_COLOR = "#2563eb";
const ROUTE_COLOR = "#1e5631";
const SIM_COLOR = "#4caf50";

function fmt(n) {
  return (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

// CROPGRIDS crop names are lowercase keys like "groundnut"/"cotton".
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const topCrop = (d) => (d?.crop_mix?.[0]?.crop ? cap(d.crop_mix[0].crop) : null);

// 2026 supply outlook (falls back to 2024/2018 forecasts for older backends).
const supply2026 = (d) =>
  (d.predicted_supply_2026 ?? d.predicted_supply_2024 ?? 0);

// Inline SVG sparkline for a "year:value,..." supply_trend string.
function TrendSpark({ trend }) {
  const pts = (trend || "")
    .split(",")
    .map((p) => p.split(":"))
    .filter((p) => p.length === 2 && !Number.isNaN(Number(p[1])))
    .map(([y, v]) => [Number(y), Number(v)]);
  if (pts.length < 2) return null;
  const w = 220;
  const h = 40;
  const vals = pts.map((p) => p[1]);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const rng = max - min || 1;
  const x = (i) => (i / (pts.length - 1)) * (w - 6) + 3;
  const y = (v) => h - 4 - ((v - min) / rng) * (h - 8);
  const path = pts
    .map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={w} height={h} className="trend-spark" role="img" aria-label="supply trend 2010 to 2026">
      <polyline points={path} fill="none" stroke="var(--green)" strokeWidth={1.6} />
      {pts.map((p, i) => (
        <circle
          key={p[0]}
          cx={x(i)}
          cy={y(p[1])}
          r={i === pts.length - 1 ? 2.8 : 1.4}
          fill={i === pts.length - 1 ? "var(--accent)" : "var(--green)"}
        />
      ))}
    </svg>
  );
}

export default function App() {
  const { t, lang } = useLanguage();
  const mapElRef = useRef(null);
  const mapRef = useRef(null);
  const layersRef = useRef({ districts: null, plants: null, routes: null });
  const dashboardRef = useRef(null);

  const [districts, setDistricts] = useState([]);
  const [plants, setPlants] = useState([]);
  const [matches, setMatches] = useState([]);
  const [summary, setSummary] = useState(null);
  const [selected, setSelected] = useState(null);
  const [chat, setChat] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // AI assistant popup open/closed.
  const [aiOpen, setAiOpen] = useState(false);

  // Proactive insight bullets — fetched once on load, independent of the
  // main dashboard data (see api.insights()). Kept as its own loading/error
  // state so a slow or failed insights call never blocks or breaks the map.
  const [insightsData, setInsightsData] = useState(null);
  const [insightsLoading, setInsightsLoading] = useState(true);

  // Environmental impact (CO2 avoided) — /impact. Loads in its own effect
  // with its own loading state so a slow/failing call never blocks the map.
  const [impact, setImpact] = useState(null);
  const [impactLoading, setImpactLoading] = useState(true);

  // Plant siting simulator state. simMode = user is in "click the map to
  // place a plant" mode. simMarker = the placed {lat, lng}, null until they
  // click. simResult = last /simulate/plant response, cleared whenever the
  // marker moves so stale numbers never linger on screen.
  const [simMode, setSimMode] = useState(false);
  const [simMarker, setSimMarker] = useState(null);
  const [simCapacity, setSimCapacity] = useState(20000);
  const [simName, setSimName] = useState("Simulated Plant");
  const [simRunning, setSimRunning] = useState(false);
  const [simResult, setSimResult] = useState(null);
  const [simError, setSimError] = useState(null);
  const simMarkerLayerRef = useRef(null);

  useEffect(() => {
    Promise.all([api.districts(), api.plants(), api.matches()])
      .then(([d, p, m]) => {
        setDistricts(d);
        setPlants(p);
        setMatches(m);
        // Stats computed client-side so the UI works against any backend
        // contract (no /sustainability dependency).
        const totalSupply = d.reduce((s, x) => s + supply2026(x), 0);
        const matched = m.reduce((s, x) => s + (x.matched_supply || 0), 0);
        setSummary({
          total_predicted_supply_units: totalSupply,
          matched_units: matched,
        });
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Separate effect (and separate try/catch) from the main data load above
  // on purpose — insights are a nice-to-have, and if this call is slow or
  // errors out, the map/panel/chat should still work fully.
  useEffect(() => {
    setInsightsLoading(true);
    api
      .insights()
      .then(setInsightsData)
      .catch(() => setInsightsData(null)) // fail silent — insights just won't render
      .finally(() => setInsightsLoading(false));
  }, []);

  // Impact loads independently, same fail-silent pattern.
  useEffect(() => {
    api
      .impact()
      .then(setImpact)
      .catch(() => setImpact(null))
      .finally(() => setImpactLoading(false));
  }, []);

  // Leaflet measures its container once, at L.map() construction time, and
  // caches that size — it does NOT auto-detect later layout/CSS changes.
  // Our map sits inside a card whose height depends on the surrounding page
  // (hero, fonts loading, etc.), so the very first measurement can lock in
  // a size smaller than the actual container, leaving a dead gap below the
  // tiles. A ResizeObserver + invalidateSize() keeps it honest whenever the
  // container's real size changes (mount, font load reflow, window resize).
  useEffect(() => {
    if (!mapElRef.current || !mapRef.current) return;
    const map = mapRef.current;
    const el = mapElRef.current;

    const ro = new ResizeObserver(() => {
      map.invalidateSize();
    });
    ro.observe(el);

    // Also catch the very first paint, in case the container's height
    // settles a frame or two after mount (e.g. while web fonts load).
    const raf = requestAnimationFrame(() => map.invalidateSize());

    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);

  // Draw the map once the data is loaded.
  useEffect(() => {
    if (!mapElRef.current) return;
    if (!mapRef.current) {
      mapRef.current = L.map(mapElRef.current, { center: [22.7, 71.5], zoom: 7 });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(mapRef.current);
      // Re-measure right after creation too — the container may not have
      // its final height in the same tick the map was constructed.
      requestAnimationFrame(() => mapRef.current.invalidateSize());
    }
    const map = mapRef.current;
    ["districts", "plants", "routes"].forEach((k) => {
      if (layersRef.current[k]) layersRef.current[k].clearLayers();
    });

    const districtLayer = L.layerGroup();
    districts.forEach((d) => {
      L.circleMarker([d.latitude, d.longitude], {
        radius: 6 + Math.sqrt(supply2026(d)) / 45,
        color: TIER_COLORS[d.supply_tier] || "#888888",
        fillColor: TIER_COLORS[d.supply_tier] || "#888888",
        fillOpacity: 0.75,
        weight: 1,
      })
        .bindTooltip(
          `${d.district} — ${fmt(supply2026(d))} units (2026)` +
            (topCrop(d) ? ` · ${topCrop(d)}` : "")
        )
        .on("click", () => setSelected({ kind: "district", data: d }))
        .addTo(districtLayer);
    });
    layersRef.current.districts = districtLayer.addTo(map);

    const plantLayer = L.layerGroup();
    plants.forEach((p) => {
      L.circleMarker([p.latitude, p.longitude], {
        radius: 9,
        color: PLANT_COLOR,
        fillColor: PLANT_COLOR,
        fillOpacity: 1,
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
          color: ROUTE_COLOR,
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

  // Sim-mode map click handler — placed in its own effect (dependent on
  // simMode) so the listener always sees the latest simMode without having
  // to reach into a ref. Runs after the map-creation effect above, so
  // mapRef.current is guaranteed to exist by the time this fires.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    function handleMapClick(e) {
      if (!simMode) return;
      setSimMarker({ lat: e.latlng.lat, lng: e.latlng.lng });
      setSimResult(null);
      setSimError(null);
    }
    map.on("click", handleMapClick);
    return () => map.off("click", handleMapClick);
  }, [simMode]);

  // Draw/clear the hypothetical plant marker itself.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (simMarkerLayerRef.current) {
      map.removeLayer(simMarkerLayerRef.current);
      simMarkerLayerRef.current = null;
    }
    if (simMarker) {
      simMarkerLayerRef.current = L.marker([simMarker.lat, simMarker.lng], {
        icon: L.divIcon({
          className: "sim-plant-icon",
          html: "🏭",
          iconSize: [28, 28],
        }),
      }).addTo(map);
    }
  }, [simMarker]);

  // Draw dashed routes for districts the simulation matched to the
  // hypothetical plant. Separate layer from the real routes above so
  // toggling/clearing the simulation never touches the real route lines.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (layersRef.current.simRoutes) {
      map.removeLayer(layersRef.current.simRoutes);
      layersRef.current.simRoutes = null;
    }
    if (simResult && simMarker) {
      const routeLayer = L.layerGroup();
      simResult.matches
        .filter((m) => m.matched_plant_id === "SIM")
        .forEach((m) => {
          const d = districts.find((x) => x.district === m.district);
          if (d) {
            L.polyline(
              [[d.latitude, d.longitude], [simMarker.lat, simMarker.lng]],
              { color: SIM_COLOR, weight: 3, opacity: 0.85, dashArray: "6 6" }
            )
              .bindTooltip(
                `${d.district} → simulated plant · ${fmt(m.matched_supply)} units · ${m.distance_km} km`
              )
              .addTo(routeLayer);
          }
        });
      layersRef.current.simRoutes = routeLayer.addTo(map);
    }
  }, [simResult, simMarker, districts]);

  function scrollToDashboard() {
    dashboardRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  function toggleSimMode() {
    setSimMode((wasOn) => {
      const next = !wasOn;
      if (!next) {
        // Turning the simulator off — clear everything so it doesn't
        // linger on the map or panel.
        setSimMarker(null);
        setSimResult(null);
        setSimError(null);
      }
      return next;
    });
  }

  // "Clear" closes the simulator completely (not just the marker): exit sim
  // mode so the map stops accepting placement clicks and the panel returns
  // to the normal district/plant view. Otherwise the app stays armed and the
  // very next map click re-opens the simulator — which reads as the sim
  // "restarting on its own" after a run.
  function clearSimulation() {
    setSimMode(false);
    setSimMarker(null);
    setSimResult(null);
    setSimError(null);
  }

  function handleSimulateClick() {
    if (!simMode) toggleSimMode();
    scrollToDashboard();
  }

  async function runSimulation() {
    if (!simMarker || simRunning) return;
    setSimRunning(true);
    setSimError(null);
    try {
      const result = await api.simulatePlant({
        latitude: simMarker.lat,
        longitude: simMarker.lng,
        annual_capacity: simCapacity,
        plant_name: simName,
      });
      setSimResult(result);
    } catch (e) {
      setSimError(String(e));
    }
    setSimRunning(false);
  }

  function newChat() {
    setChat([]);
    setQuestion("");
  }

  // `qArg` lets suggestion chips pass their text directly — `setQuestion` is
  // async, so reading `question` from state here would see the stale value.
  async function ask(qArg) {
    const q = (qArg ?? question).trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");

    // Build history from turns so far (oldest first), BEFORE adding this
    // question to `chat` state — this is what lets follow-ups like
    // "how far is that from Amreli?" resolve correctly.
    const history = chat.map((m) => ({ role: m.role, content: m.text }));

    setChat((c) => [...c, { role: "user", text: q }]);
    try {
      const { answer } = await api.ask(q, history, lang);
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
      <Navbar
        onSimulateClick={handleSimulateClick}
        onAskClick={() => setAiOpen((o) => !o)}
        onDashboardClick={scrollToDashboard}
        simActive={simMode}
        aiOpen={aiOpen}
      />

      <Hero
        summary={summary}
        leftover={leftover}
        onExplore={scrollToDashboard}
        onSimulate={handleSimulateClick}
      />

      <section className="dashboard" id="dashboard" ref={dashboardRef}>
        <div className="dashboard-heading">
          <h2>Live supply &amp; routing map</h2>
          <p>Click a district or plant to inspect it, or place a hypothetical plant.</p>
        </div>

        {error && (
          <div className="error-banner">⚠ Could not reach the API: {error}</div>
        )}

        {simMode && !simMarker && (
          <div className="sim-banner">
            📍 Click anywhere on the map to place a hypothetical plant.
          </div>
        )}

        <div className="layout">
          <div className="map-wrap">
            <div ref={mapElRef} className="map" />
          </div>

          <aside className="panel">
            {simMarker ? (
              <SimulatorCard
                marker={simMarker}
                capacity={simCapacity}
                setCapacity={setSimCapacity}
                name={simName}
                setName={setSimName}
                onRun={runSimulation}
                onClear={clearSimulation}
                running={simRunning}
                result={simResult}
                error={simError}
              />
            ) : selected ? (
              selected.kind === "district" ? (
                <DistrictCard d={selected.data} onClose={() => setSelected(null)} />
              ) : (
                <PlantCard p={selected.data} onClose={() => setSelected(null)} />
              )
            ) : (
              <div className="hint">
                <div className="hint-header">
                  <span className="hint-icon">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M9 20 3 17V4l6 3 6-3 6 3v13l-6-3-6 3Z" />
                      <path d="M9 7v13" />
                      <path d="M15 4v13" />
                    </svg>
                  </span>
                  <h3>Click a district or plant</h3>
                </div>
                <p>Districts are colored by supply tier:</p>
                <div className="hint-legend">
                  <span className="hint-legend-item">
                    <span className="hint-swatch" style={{ background: TIER_COLORS.High }} />
                    High
                  </span>
                  <span className="hint-legend-item">
                    <span className="hint-swatch" style={{ background: TIER_COLORS.Medium }} />
                    Medium
                  </span>
                  <span className="hint-legend-item">
                    <span className="hint-swatch" style={{ background: TIER_COLORS.Low }} />
                    Low
                  </span>
                </div>
                <p className="hint-routes">
                  <span
                    className="hint-plant-dot"
                    style={{ "--plant-color": PLANT_COLOR }}
                    aria-hidden="true"
                  />
                  Blue dots are plants; green lines show today's matched routes.
                </p>
                <hr className="hint-divider" />
                <p className="units-note">
                  All quantities are dimensionless dataset biomass units (not tonnes).
                </p>
              </div>
            )}
          </aside>
        </div>

        <InsightsSection data={insightsData} loading={insightsLoading} />
      </section>

      <ImpactSection impact={impact} loading={impactLoading} />

      <SupplyExplorer districts={districts} plants={plants} matches={matches} />

      {aiOpen && (
        <AIAssistantPanel
          chat={chat}
          question={question}
          setQuestion={setQuestion}
          busy={busy}
          onAsk={ask}
          onNewChat={newChat}
          onClose={() => setAiOpen(false)}
          suggestions={[
            t.suggestion1,
            t.suggestion2,
            t.suggestion3,
            t.suggestion4,
          ]}
        />
      )}
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
        <dt>Predicted supply (2026)</dt>
        <dd>{fmt(supply2026(d))} units</dd>
        {d.supply_trend && (
          <>
            <dt>Supply trend (2010 → 2026)</dt>
            <dd>
              <TrendSpark trend={d.supply_trend} />
            </dd>
          </>
        )}
        <dt>Confidence</dt>
        <dd>
          {d.confidence_score_2026 ?? d.confidence_score_2024}{" "}
          ({d.confidence_label_2026 ?? d.confidence_label_2024})
        </dd>
        <dt>Residue type</dt>
        <dd title={d.residue_type_source}>{d.residue_type}</dd>
        <dt>Harvest window</dt>
        <dd>{d.harvest_window}</dd>
        {d.crop_mix?.length > 0 && (
          <>
            <dt>Crop mix</dt>
            <dd>
              <ul className="crop-mix">
                {d.crop_mix.slice(0, 3).map((c) => (
                  <li key={c.crop} className="crop-mix-row">
                    <span className="crop-mix-name">{cap(c.crop)}</span>
                    <span className="crop-mix-bar">
                      <span style={{ width: `${Math.min(100, c.share_pct)}%` }} />
                    </span>
                    <span className="crop-mix-pct">{c.share_pct}%</span>
                  </li>
                ))}
              </ul>
              <span className="crop-mix-foot">
                {d.cropland_2020_ha != null
                  ? `${fmt(d.cropland_2020_ha)} ha cropped area · `
                  : ""}
                CROPGRIDS v1.08
              </span>
            </dd>
          </>
        )}
        <dt>2026 forecast change</dt>
        <dd>
          {d.supply_2026_change_pct != null
            ? `${d.supply_2026_change_pct > 0 ? "+" : ""}${d.supply_2026_change_pct}% vs prior forecast`
            : "—"}
        </dd>
      </dl>
      <button className="close" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

function SimulatorCard({
  marker,
  capacity,
  setCapacity,
  name,
  setName,
  onRun,
  onClear,
  running,
  result,
  error,
}) {
  return (
    <div className="card sim-card">
      <h3>Simulate new plant</h3>
      <span className="tier tier-plant">Hypothetical</span>
      <p className="sim-coords">
        📍 {marker.lat.toFixed(3)}, {marker.lng.toFixed(3)}
      </p>

      <label className="sim-label">
        Plant name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="sim-label">
        Annual capacity (units/yr)
        <input
          type="number"
          min={1000}
          step={1000}
          value={capacity}
          onChange={(e) => setCapacity(Number(e.target.value) || 0)}
        />
      </label>

      <div className="sim-actions">
        <button onClick={onRun} disabled={running}>
          {running ? "Running…" : "Run simulation"}
        </button>
        <button className="close" onClick={onClear}>
          Clear
        </button>
      </div>

      {error && <p className="sim-error">⚠ {error}</p>}

      {result && (
        <div className="sim-results">
          <h4>Impact</h4>
          <dl>
            <dt>Leftover before</dt>
            <dd>{fmt(result.baseline.leftover)} units</dd>
            <dt>Leftover after</dt>
            <dd>{fmt(result.simulated.leftover)} units</dd>
            <dt>Leftover reduced by</dt>
            <dd className="sim-good">{fmt(result.leftover_reduction)} units</dd>
            <dt>New plant utilization</dt>
            <dd>{result.simulated_plant_utilization_pct}%</dd>
          </dl>
          <p className="sim-note">
            Dashed green lines on the map show which districts this plant
            would absorb.
          </p>
        </div>
      )}
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

// Environmental impact — CO2 avoided by matching residue instead of burning.
function ImpactSection({ impact, loading }) {
  if (loading || !impact) return null;
  const money = (n) =>
    (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

  return (
    <section className="impact">
      <div className="impact-heading">
        <div>
          <h2>Environmental impact</h2>
          <p>
            CO₂ avoided by matching leftover residue instead of open burning,
            at 1.35 t CO₂ / t burned (Ni et al. 2015, measured combustion
            factor).
          </p>
        </div>
      </div>

      <div className="impact-stats">
        <div className="impact-stat">
          <span className="impact-card-icon">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z" />
              <path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12" />
            </svg>
          </span>
          <div className="impact-stat-body">
            <span className="impact-stat-label">Leftover residue</span>
            <b>{money(impact.leftover_tonnes)}</b>
            <span className="impact-unit">tonnes</span>
          </div>
        </div>
        <div className="impact-stat">
          <span className="impact-card-icon">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
              <path d="M8 15h8" />
              <path d="m9 18-1 2" />
              <path d="m15 18 1 2" />
            </svg>
          </span>
          <div className="impact-stat-body">
            <span className="impact-stat-label">CO₂ avoided</span>
            <b className="impact-good">{money(impact.co2_avoided_tonnes)}</b>
            <span className="impact-unit">tonnes</span>
          </div>
        </div>
        <div className="impact-stat">
          <span className="impact-card-icon">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M19 17H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1l2-3h6l2 3h1a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2Z" />
              <circle cx="7.5" cy="15.5" r="1" />
              <circle cx="16.5" cy="15.5" r="1" />
            </svg>
          </span>
          <div className="impact-stat-body">
            <span className="impact-stat-label">≈ Cars off the road</span>
            <b>{money(impact.equivalent_cars_off_road_for_a_year)}</b>
            <span className="impact-unit">for a year</span>
          </div>
        </div>
        <div className="impact-stat">
          <span className="impact-card-icon">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 22v-7" />
              <path d="M12 15c-4 0-6-2.5-6-6V3c3 0 5 1.5 6 4 1-2.5 3-4 6-4v6c0 3.5-2 6-6 6Z" />
              <path d="M7 22h10" />
            </svg>
          </span>
          <div className="impact-stat-body">
            <span className="impact-stat-label">≈ Tree seedlings</span>
            <b>{money(impact.equivalent_tree_seedlings_grown_10yr)}</b>
            <span className="impact-unit">grown 10 yrs</span>
          </div>
        </div>
        <div className="impact-stat">
          <span className="impact-card-icon">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <path d="M2 12h20" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
            </svg>
          </span>
          <div className="impact-stat-body">
            <span className="impact-stat-label">Share of India's burning CO₂</span>
            <b>{impact.pct_of_india_annual_residue_burning_co2}%</b>
            <span className="impact-unit">of national total</span>
          </div>
        </div>
      </div>

      <p className="impact-footnote">
        *National reference: 141.15 Mt CO₂ from crop residue burning across
        India, base year 2008–09 (Jain et al., Aerosol and Air Quality
        Research, 2014).
      </p>
    </section>
  );
}

// AI Insights — structured forecast cards. Numbers come straight from the
// /assistant/insights supporting_data payload (same figures the explorer
// and impact cards show), so the cards never drift from the rest of the UI.
function InsightsSection({ data, loading }) {
  if (loading || !data) return null;
  const sd = data.supporting_data || {};

  const top = sd.top_supply_districts || [];
  const unmatched = sd.unmatched_districts || [];
  const util = sd.plant_utilization_ascending || [];

  const fmt = (n) =>
    (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
  const totalSupply = sd.total_predicted_supply_units;
  const leftover = sd.leftover_unmatched_units;
  const maxUtil = util.length
    ? Math.max(...util.map((p) => p.utilization_pct ?? 0))
    : 0;
  const fullUtilCount = util.filter((p) => (p.utilization_pct ?? 0) >= 100).length;
  const minUtilPlant = util.length
    ? util.reduce((a, b) =>
        (a.utilization_pct ?? 0) <= (b.utilization_pct ?? 0) ? a : b
      )
    : null;

  const cards = [
    {
      key: "supply",
      icon: (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3 3v18h18" />
          <path d="m7 14 4-4 3 3 5-6" />
        </svg>
      ),
      label: "Predicted supply (2026)",
      value: fmt(totalSupply),
      unit: "units",
      desc: top.length
        ? `${top[0].district} leads predicted supply at ${fmt(top[0].predicted_supply)} units, closely followed by ${top[1]?.district ?? "the next district"} at ${fmt(top[1]?.predicted_supply)} units.`
        : "Predicted supply across all districts.",
    },
    {
      key: "unmatched",
      icon: (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
      ),
      label: "Unmatched supply",
      value: fmt(leftover),
      unit: "units",
      desc: `Total unmatched supply stands at ${fmt(leftover)} units across ${unmatched.length} districts, indicating gaps in the supply chain.`,
    },
    {
      key: "utilization",
      icon: (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2 20h20" />
          <path d="M4 20V9l5 3V9l5 3V9l5 3v8" />
        </svg>
      ),
      label: "Plant utilization",
      value: `${maxUtil}%`,
      unit: "",
      desc:
        fullUtilCount === util.length
          ? `All ${util.length} plants operate at full capacity, achieving ${maxUtil}% utilization.`
          : `${fullUtilCount} of ${util.length} plants run at full capacity; ${minUtilPlant?.plant_name ?? "the lowest"} is at ${fmt(minUtilPlant?.utilization_pct ?? 0)}% utilization.`,
    },
  ];

  return (
    <section className="ai-insights">
      <div className="ai-insights-head">
        <div>
          <h2>AI Insights</h2>
          <p>Analysis of supply, matching, and plant capacity.</p>
        </div>
      </div>

      <div className="ai-insights-cards">
        {cards.map((c) => (
          <div className="ai-card" key={c.key}>
            <span className="ai-card-icon">{c.icon}</span>
            <span className="ai-card-label">{c.label}</span>
            <b className="ai-card-value">
              {c.value}
              {c.unit && <span className="ai-card-unit"> {c.unit}</span>}
            </b>
            <p className="ai-card-desc">{c.desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

