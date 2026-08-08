import { useEffect, useState } from "react";

export default function Navbar({
  onSimulateClick,
  onAskClick,
  onDashboardClick,
  simActive,
  aiOpen,
}) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    function onScroll() {
      setScrolled(window.scrollY > 40);
    }

    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <nav className={`navbar ${scrolled ? "scrolled" : ""}`}>
      <button className="nav-brand" onClick={onDashboardClick}>
        <span
          className="nav-mark"
          style={{ background: "var(--flow-gradient)" }}
        >
          💧
        </span>

        <span className="nav-brand-text">
          Agri<span>Flow</span>
        </span>
      </button>

      <div className="nav-links">
        <button
          className={`nav-link ${!simActive && !aiOpen ? "active" : ""}`}
          onClick={onDashboardClick}
        >
          Dashboard
        </button>

        <button
          className={`nav-link ${simActive ? "active" : ""}`}
          onClick={onSimulateClick}
        >
          <span className="nav-icon">📍</span>
          <span className="nav-link-label">Simulate new plant</span>
        </button>

        <button
          className={`nav-link primary ${aiOpen ? "active" : ""}`}
          onClick={onAskClick}
        >
          <span className="nav-icon">💬</span>
          <span className="nav-link-label">Talk to AI assistant</span>
        </button>
      </div>
    </nav>
  );
}