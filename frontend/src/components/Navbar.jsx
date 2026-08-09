import { useEffect, useState } from "react";
import { useLanguage } from "../LanguageContext.jsx";
import LanguageDropdown from "./LanguageDropdown.jsx";

export default function Navbar({
  onSimulateClick,
  onAskClick,
  onDashboardClick,
  simActive,
  aiOpen,
}) {
  const { t } = useLanguage();
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
          Agri<em>Flow</em>
        </span>
      </button>

      <div className="nav-links">
        <LanguageDropdown />

        <button
          className={`nav-link ${simActive ? "active" : ""}`}
          onClick={onSimulateClick}
        >
          <span className="nav-icon">📍</span>
          <span className="nav-link-label">{t.simulateNewPlant}</span>
        </button>

        <button
          className={`nav-link primary ${aiOpen ? "active" : ""}`}
          onClick={onAskClick}
        >
          <span className="nav-icon">💬</span>
          <span className="nav-link-label">{t.talkToAssistant}</span>
        </button>
      </div>
    </nav>
  );
}