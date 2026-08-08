// AgriFlow API client.
// Defaults to the live Render backend; override locally with VITE_API_URL.
const API_BASE =
  import.meta.env.VITE_API_URL || "//localhost:8000";

async function get(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

export const api = {
  districts: () => get("/districts"),
  plants: () => get("/plants"),
  matches: () => get("/matches"),
  ask: async (question) => {
    const res = await fetch(`${API_BASE}/assistant/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!res.ok) throw new Error(`/assistant/query -> HTTP ${res.status}`);
    return res.json();
  },
};
