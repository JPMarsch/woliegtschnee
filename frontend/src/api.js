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

// day: "YYYY-MM-DD" oder null (= aktueller Stand)
const withDay = (params, day) => (day ? { ...params, day } : params);

export const fetchDays = () => getJson("/api/days");
export const fetchStatus = (day) => getJson("/api/status", day ? { day } : undefined);
export const fetchNearest = (lat, lon, minCm, day) =>
  getJson("/api/nearest", withDay({ lat: lat.toFixed(5), lon: lon.toFixed(5), min_cm: minCm }, day));
export const geocode = (q) => getJson("/api/geocode", { q });
export const overlayUrl = (version, day) =>
  `${API_BASE}/api/overlay.png?${new URLSearchParams(withDay({ v: version }, day))}`;
