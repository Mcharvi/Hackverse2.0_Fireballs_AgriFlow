import heroImg from "../assets/hero-biomass.png";

function fmt(n) {
  return (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

export default function Hero({ summary, leftover, onExplore, onSimulate }) {
  return (
    <section className="hero" style={{ backgroundImage: `url(${heroImg})` }}>
      <div className="hero-content">
        <div className="hero-eyebrow">Field to plant, in real time</div>
        <h1 className="hero-title">
          Agri<span className="flow">Flow</span>
        </h1>
        <p className="hero-tagline">
          AgriFlow turns crop residue that would otherwise be burned in the
          field into routed, matched, and dispatched biomass — tracked from
          district to plant on one live map.
        </p>
        <div className="hero-actions">
          <button className="hero-btn solid" onClick={onExplore}>
            View live map
          </button>
          <button className="hero-btn outline" onClick={onSimulate}>
            📍 Simulate a new plant
          </button>
        </div>
      </div>

      {summary && (
        <div className="hero-stats">
          <div className="hero-stat">
            <span className="hero-stat-label">Predicted supply</span>
            <span className="hero-stat-value">
              {fmt(summary.total_predicted_supply_units)}
              <span className="hero-stat-unit">units</span>
            </span>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Matched to plants</span>
            <span className="hero-stat-value accent-green">
              {fmt(summary.matched_units)}
              <span className="hero-stat-unit">units</span>
            </span>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Leftover — would burn</span>
            <span className="hero-stat-value accent-brown">
              {fmt(leftover)}
              <span className="hero-stat-unit">units</span>
            </span>
          </div>
        </div>
      )}
    </section>
  );
}
