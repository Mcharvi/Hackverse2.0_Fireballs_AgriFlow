// ContinuousTabs — sliding-pill tab bar.
// Port of the watermelon.sh shadcn registry component
// (https://registry.watermelon.sh/r/continuous-tabs.json) to plain CSS,
// since this project has no Tailwind. Same spring "active pill" animation,
// restyled to the AgriFlow palette (dark green pill on a white bar).
import { useEffect, useState } from "react";
import { LayoutGroup, motion } from "framer-motion";

export default function ContinuousTabs({ tabs, defaultActiveId, onChange, className = "" }) {
  const [active, setActive] = useState(defaultActiveId ?? tabs[0]?.id);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // Wait one render before animating so the pill springs from the correct
  // tab instead of flashing in at the default position.
  if (!isMounted) return null;

  return (
    <LayoutGroup>
      <nav className={`ctabs ${className}`.trim()}>
        {tabs.map((tab) => {
          const isActive = active === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              className="ctab"
              onClick={() => {
                setActive(tab.id);
                onChange?.(tab.id);
              }}
            >
              {isActive && (
                <motion.div
                  layoutId="ctabs-pill"
                  transition={{ type: "spring", stiffness: 380, damping: 30, mass: 0.9 }}
                  className="ctab-pill"
                />
              )}
              <motion.span
                layout="position"
                className={`ctab-label${isActive ? " is-active" : ""}`}
              >
                {tab.label}
              </motion.span>
            </button>
          );
        })}
      </nav>
    </LayoutGroup>
  );
}
