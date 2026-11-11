const nf0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });

export const km = (v) => `${v < 10 ? nf1.format(v) : nf0.format(v)} km`;

export const coords = (lat, lon) =>
  `${Math.abs(lat).toFixed(2)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(2)}° ${lon >= 0 ? "O" : "W"}`;

export const date = (iso) =>
  new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });

export const dateTime = (iso) =>
  new Date(iso).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " UTC";

/** Punkte entlang des Großkreises – Längengrade „entfaltet“, damit die Linie
 *  über die Datumsgrenze nicht quer über die Karte springt. */
export function greatCircle([lat1, lon1], [lat2, lon2], n = 96) {
  const r = Math.PI / 180;
  const [p1, l1, p2, l2] = [lat1 * r, lon1 * r, lat2 * r, lon2 * r];
  const d =
    2 * Math.asin(Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2));
  if (d < 1e-9) return [[lat1, lon1], [lat2, lon2]];
  const pts = [];
  let prev = lon1;
  for (let i = 0; i <= n; i++) {
    const f = i / n;
    const a = Math.sin((1 - f) * d) / Math.sin(d);
    const b = Math.sin(f * d) / Math.sin(d);
    const x = a * Math.cos(p1) * Math.cos(l1) + b * Math.cos(p2) * Math.cos(l2);
    const y = a * Math.cos(p1) * Math.sin(l1) + b * Math.cos(p2) * Math.sin(l2);
    const z = a * Math.sin(p1) + b * Math.sin(p2);
    let lon = Math.atan2(y, x) / r;
    while (lon - prev > 180) lon -= 360;
    while (lon - prev < -180) lon += 360;
    prev = lon;
    pts.push([Math.atan2(z, Math.hypot(x, y)) / r, lon]);
  }
  return pts;
}
