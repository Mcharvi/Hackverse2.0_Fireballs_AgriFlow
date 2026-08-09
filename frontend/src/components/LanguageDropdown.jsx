// LanguageDropdown — Untitled-UI-style selector: globe icon + current
// language + chevron trigger in the navbar, opening a small menu with the
// active language marked by a check. Plain CSS (no Tailwind), consistent
// with the rest of the app.
import { useState, useRef, useEffect } from "react";
import { useLanguage } from "../LanguageContext.jsx";
import { LANGUAGES } from "../translations.js";

function GlobeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

export default function LanguageDropdown() {
  const { lang, setLang } = useLanguage();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    function onKeyDown(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <div className={`lang-dd${open ? " is-open" : ""}`} ref={ref}>
      <button
        className="lang-dd-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Select language"
      >
        <GlobeIcon />
        <span className="lang-dd-label">{LANGUAGES[lang]}</span>
        <ChevronIcon />
      </button>

      {open && (
        <div className="lang-dd-menu" role="menu">
          {Object.entries(LANGUAGES).map(([code, label]) => (
            <button
              key={code}
              role="menuitemradio"
              aria-checked={code === lang}
              className={`lang-dd-item${code === lang ? " is-active" : ""}`}
              onClick={() => {
                setLang(code);
                setOpen(false);
              }}
            >
              <span className="lang-dd-check">{code === lang && <CheckIcon />}</span>
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
