//this is app.jsx
import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "./api.js";
import Navbar from "./components/Navbar.jsx";
import Hero from "./components/Hero.jsx";
import AIAssistantPanel from "./components/AIAssistantPanel.jsx";
import SupplyExplorer from "./components/SupplyExplorer.jsx";

// Simple 3-color supply-tier + map palette (matches styles.css tokens).
const TIER_COLORS = { High: "#1e5631", Medium: "#4caf50", Low: "#c9c9c9" };
const PLANT_COLOR = "#1e5631";
const SIM_COLOR = "#4caf50";

function fmt(n) {
  return (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

export default function App() {
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
  const [insights, setInsights] = useState([]);
  const [insightsLoading, setInsightsLoading] = useState(true);

  // Route economics (sale profit vs transport cost) — /economics.
  // Loaded in its own effect with its own loading/error state so a slow or
  // failing economics call never blocks the map/panel/chat.
  const [economics, setEconomics] = useState(null);
  const [economicsLoading, setEconomicsLoading] = useState(true);

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
        const totalSupply = d.reduce((s, x) => s + (x.predicted_supply_2018 || 0), 0);
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
    api
      .insights()
      .then((res) => setInsights(res.insights || []))
      .catch(() => setInsights([])) // fail silent — insights strip just won't render
      .finally(() => setInsightsLoading(false));
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

  // Route economics, separate from the main data load on purpose — same
  // rationale as insights: a slow/failed call shouldn't break the map.
  useEffect(() => {
    api
      .economics()
      .then(setEconomics)
      .catch(() => setEconomics(null)) // fail silent — section just won't render
      .finally(() => setEconomicsLoading(false));
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
        radius: 6 + Math.sqrt(d.predicted_supply_2018) / 45,
        color: TIER_COLORS[d.supply_tier] || "#888888",
        fillColor: TIER_COLORS[d.supply_tier] || "#888888",
        fillOpacity: 0.75,
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
        color: PLANT_COLOR,
        fillColor: "#4caf50",
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
          color: PLANT_COLOR,
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

        {/* Proactive insights strip — only renders once bullets arrive, and
            disappears entirely (not even a placeholder) if the call fails,
            so a slow/broken insights endpoint never leaves an empty box. */}
        {!insightsLoading && insights.length > 0 && (
          <div className="insights-strip">
            <span className="insights-label">AI insights</span>
            <ul>
              {insights.map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
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
                onClear={() => {
                  setSimMarker(null);
                  setSimResult(null);
                  setSimError(null);
                }}
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
                <h3>Click a district or plant</h3>
                <p>
                  Districts are colored by supply tier:{" "}
                  <span className="swatch" style={{ background: TIER_COLORS.High }} />
                  High
                  <span className="swatch" style={{ background: TIER_COLORS.Medium }} />
                  Medium
                  <span className="swatch" style={{ background: TIER_COLORS.Low }} />
                  Low. Green dots are plants; green lines show today's matched routes.
                </p>
                <p className="units-note">
                  All quantities are dimensionless dataset biomass units (not tonnes).
                </p>
              </div>
            )}
          </aside>
        </div>
      </section>

      <SupplyExplorer districts={districts} plants={plants} matches={matches} />

      <EconomicsSection economics={economics} loading={economicsLoading} />

      {aiOpen && (
        <AIAssistantPanel
          chat={chat}
          question={question}
          setQuestion={setQuestion}
          busy={busy}
          onAsk={ask}
          onClose={() => setAiOpen(false)}
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

// Route economics section — sale profit vs transport cost. Renders only
// when /economics responds; a failed/slow call leaves it out entirely
// (same fail-silent rule as the insights strip).
function EconomicsSection({ economics, loading }) {
  if (loading || !economics) return null;
  const s = economics.summary || {};
  const breakeven = economics.breakeven_distance_km;

  const money = (n) =>
    (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

  return (
    <section className="econ">
      <div className="econ-heading">
        <h2>Is it worth collecting?</h2>
        <p>
          Sale profit vs transport cost per matched route, at demo rates
          (price {money(economics.parameters?.sale_price_per_unit)} / unit,
          haulage {economics.parameters?.cost_per_km_per_unit} / km / unit,
          round trip ×{economics.parameters?.round_trip_factor}).
        </p>
      </div>

      <div className="econ-stats">
        <div className="econ-stat">
          <span className="econ-stat-label">Revenue</span>
          <b>{money(s.revenue)}</b>
        </div>
        <div className="econ-stat">
          <span className="econ-stat-label">Transport cost</span>
          <b>{money(s.transport_cost)}</b>
        </div>
        <div className="econ-stat">
          <span className="econ-stat-label">Net profit</span>
          <b className={s.profit >= 0 ? "econ-good" : "econ-bad"}>
            {money(s.profit)}
          </b>
        </div>
        <div className="econ-stat">
          <span className="econ-stat-label">Margin</span>
          <b>{s.margin_pct ?? 0}%</b>
        </div>
        <div className="econ-stat">
          <span className="econ-stat-label">Breakeven haul</span>
          <b>{breakeven != null ? `${breakeven} km` : "—"}</b>
        </div>
      </div>

    </section>
  );
}
