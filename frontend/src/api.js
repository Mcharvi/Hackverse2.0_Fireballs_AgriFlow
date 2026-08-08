// AgriFlow API client.
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
  // history: prior chat turns as [{ role: "user"|"assistant", content: str }, ...],
  // oldest first, NOT including the current question. Lets the assistant
  // resolve follow-ups like "how far is that from Amreli?"
  ask: async (question, history = []) => {
    const res = await fetch(`${API_BASE}/assistant/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    if (!res.ok) throw new Error(`/assistant/query -> HTTP ${res.status}`);
    return res.json();
  },
};