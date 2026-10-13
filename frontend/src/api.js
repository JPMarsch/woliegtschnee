// Leer = gleiche Herkunft (Produktivbetrieb bzw. Vite-Proxy im Dev-Modus).
export const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

async function getJson(path, params) {
  const url = `${API_BASE}${path}${params ? `?${new URLSearchParams(params)}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keine JSON-Antwort */
    }
    throw new Error(typeof detail === "string" ? detail : `Fehler ${res.status}`);
  }
  return res.json();
}

export const fetchStatus = () => getJson("/api/status");
export const fetchNearest = (lat, lon, minCm) =>
  getJson("/api/nearest", { lat: lat.toFixed(5), lon: lon.toFixed(5), min_cm: minCm });
export const geocode = (q) => getJson("/api/geocode", { q });
export const overlayUrl = (version) => `${API_BASE}/api/overlay.png?v=${encodeURIComponent(version)}`;
