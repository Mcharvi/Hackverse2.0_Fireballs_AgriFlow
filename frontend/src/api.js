// AgriFlow API client.
//this is api.js
// Defaults to the live Render backend; override locally with VITE_API_URL.
const API_BASE =
  import.meta.env.VITE_API_URL || "https://hackverse2-0-fireballs-agriflow.onrender.com";

async function get(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

export const api = {
  districts: () => get("/districts"),
  plants: () => get("/plants"),
  matches: () => get("/matches"),
  sustainability: () => get("/sustainability"),
  insights: () => get("/assistant/insights"),
  impact: () => get("/impact"),
  simulatePlant: async ({ latitude, longitude, annual_capacity, plant_name }) => {
    const res = await fetch(`${API_BASE}/simulate/plant`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ latitude, longitude, annual_capacity, plant_name }),
    });
    if (!res.ok) throw new Error(`/simulate/plant -> HTTP ${res.status}`);
    return res.json();
  },
  ask: async (question, history = [], language = "en") => {
    const res = await fetch(`${API_BASE}/assistant/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history, language }),
    });
    if (!res.ok) throw new Error(`/assistant/query -> HTTP ${res.status}`);
    return res.json();
  },
};
