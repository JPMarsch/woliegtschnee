import { useCallback, useEffect, useRef, useState } from "react";
import { fetchNearest, fetchStatus, geocode } from "./api.js";
import { coords, date, dateTime, km } from "./format.js";
import MapView from "./MapView.jsx";

const PRESETS = [5, 10, 20, 50, 100];
const LEGEND = [
  ["1", "#bae6fd"],
  ["5", "#7dd3fc"],
  ["10", "#38bdf8"],
  ["20", "#0ea5e9"],
  ["50", "#0369a1"],
  ["100+", "#1e3a8a"],
];

// Startpunkt und Mindesthöhe aus der URL lesen, damit Suchen teilbar sind.
function readUrl() {
  const p = new URLSearchParams(window.location.search);
  const lat = parseFloat(p.get("lat"));
  const lon = parseFloat(p.get("lon"));
  const min = parseInt(p.get("min"), 10);
  const valid = Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
  return {
    start: valid ? { lat, lon, label: p.get("label") || "Geteilter Startpunkt" } : null,
    minCm: min >= 1 ? Math.min(min, 5000) : 10,
  };
}

export default function App() {
  const initial = useRef(readUrl()).current;
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [start, setStart] = useState(initial.start);
  const [minCm, setMinCm] = useState(initial.minCm);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showOverlay, setShowOverlay] = useState(true);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    // Render Free schläft bei Inaktivität; das Aufwachen dauert bis ~1 Minute.
    let cancelled = false;
    const load = async (attempt = 1) => {
      try {
        const s = await fetchStatus();
        if (!cancelled) setStatus(s);
      } catch (e) {
        if (cancelled) return;
        if (attempt < 6) setTimeout(() => load(attempt + 1), 5000);
        else setStatusError(e.message);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Suche automatisch, sobald Startpunkt oder Mindesthöhe sich ändern.
  const requestId = useRef(0);
  useEffect(() => {
    if (!start || !(minCm >= 1)) return;
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      fetchNearest(start.lat, start.lon, minCm)
        .then((r) => id === requestId.current && setResult(r))
        .catch((e) => id === requestId.current && setError(e.message))
        .finally(() => id === requestId.current && setLoading(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [start, minCm]);

  useEffect(() => {
    const p = new URLSearchParams();
    if (start) {
      p.set("lat", start.lat.toFixed(4));
      p.set("lon", start.lon.toFixed(4));
      p.set("label", start.label);
    }
    if (minCm >= 1) p.set("min", minCm);
    window.history.replaceState(null, "", `${window.location.pathname}?${p}`);
  }, [start, minCm]);

  const pickStart = useCallback((s) => {
    setStart(s);
    setCollapsed(false);
  }, []);

  return (
    <div className="app">
      <MapView start={start} result={result} status={status} showOverlay={showOverlay} onPick={pickStart} />

      <aside className={`panel ${collapsed ? "collapsed" : ""}`}>
        <button className="grip" onClick={() => setCollapsed((c) => !c)} aria-label={collapsed ? "Panel ausklappen" : "Panel einklappen"}>
          <span />
        </button>

        <header>
          <h1>❄️ Wo liegt Schnee?</h1>
          <p className="sub">Das nächste Schneegebiet – weltweit.</p>
        </header>

        <DataBadge status={status} error={statusError} />

        <section>
          <h2>1 · Startpunkt</h2>
          <StartPicker onPick={pickStart} />
          <p className="hint">
            {start ? (
              <>
                <strong>{start.label}</strong> · {coords(start.lat, start.lon)}
              </>
            ) : (
              "…oder einfach auf die Karte tippen."
            )}
          </p>
        </section>

        <section>
          <h2>2 · Mindest-Schneehöhe</h2>
          <div className="chips">
            {PRESETS.map((v) => (
              <button key={v} className={`chip ${minCm === v ? "active" : ""}`} onClick={() => setMinCm(v)}>
                {v} cm
              </button>
            ))}
            <label className="custom">
              <input
                type="number"
                min="1"
                max="5000"
                inputMode="numeric"
                value={Number.isFinite(minCm) ? minCm : ""}
                onChange={(e) => setMinCm(Math.min(5000, Math.max(0, parseInt(e.target.value, 10))))}
                aria-label="Eigene Mindesthöhe in cm"
              />
              cm
            </label>
          </div>
        </section>

        <section className="result-section">
          <h2>3 · Ergebnis</h2>
          <Result start={start} result={result} loading={loading} error={error} />
        </section>

        <footer>
          <label className="toggle">
            <input type="checkbox" checked={showOverlay} onChange={(e) => setShowOverlay(e.target.checked)} />
            Schneedecke auf der Karte anzeigen
          </label>
          {showOverlay && (
            <div className="legend" aria-label="Legende Schneehöhe in cm">
              {LEGEND.map(([label, color]) => (
                <span key={label}>
                  <i style={{ background: color }} />
                  {label}
                </span>
              ))}
              <span className="unit">cm</span>
            </div>
          )}
          <p className="disclaimer">
            <strong>Hinweis:</strong> Die Schneehöhen stammen aus dem Reanalyse-Modell{" "}
            <a href="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land" target="_blank" rel="noreferrer">
              Copernicus ERA5-Land
            </a>
            . Es sind modellierte Mittelwerte für Rasterzellen von ca. 9 × 9 km, keine Messungen an einem
            bestimmten Ort. Vor Ort kann die Schneelage deutlich abweichen – besonders in steilem Gelände.
          </p>
          <p className="credits">
            Enthält modifizierte Copernicus-Climate-Change-Service-Informationen. Adresssuche & Karte: ©
            OpenStreetMap-Mitwirkende.
          </p>
        </footer>
      </aside>
    </div>
  );
}

function DataBadge({ status, error }) {
  if (error) return <div className="banner error">Schneedaten nicht verfügbar: {error}</div>;
  if (!status) return <div className="banner muted">Lade Datenstand … (der Server startet ggf. erst, das kann bis zu einer Minute dauern)</div>;
  return (
    <>
      <div className="databadge" title={`Erzeugt: ${dateTime(status.created_at)}`}>
        <span>Datenstand</span>
        <strong>{date(status.valid_time)}</strong>
        <span className="src">{status.source}</span>
      </div>
      {status.demo && (
        <div className="banner warn">
          <strong>Demo-Daten:</strong> Die angezeigten Schneehöhen sind erfunden. Für echte Werte den ERA5-Import
          einrichten.
        </div>
      )}
      {status.stale && (
        <div className="banner warn">
          <strong>Veraltete Daten:</strong> Der Datenstand ist {Math.round(status.age_days)} Tage alt (Grenze:{" "}
          {status.stale_after_days} Tage). Die tatsächliche Schneelage kann sich geändert haben.
        </div>
      )}
    </>
  );
}

function StartPicker({ onPick }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);

  const locate = () => {
    if (!navigator.geolocation) return setMsg("Dein Browser unterstützt keine Standortbestimmung.");
    setBusy("gps");
    setMsg(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setBusy(null);
        onPick({ lat: pos.coords.latitude, lon: pos.coords.longitude, label: "Mein Standort" });
      },
      (err) => {
        setBusy(null);
        setMsg(err.code === 1 ? "Standortfreigabe wurde abgelehnt." : "Standort konnte nicht ermittelt werden.");
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 },
    );
  };

  const search = async (e) => {
    e.preventDefault();
    if (query.trim().length < 2) return;
    setBusy("search");
    setMsg(null);
    try {
      const { results } = await geocode(query.trim());
      setResults(results);
      if (!results.length) setMsg("Nichts gefunden – versuch es mit einer anderen Schreibweise.");
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(null);
    }
  };

  const choose = (r) => {
    setResults(null);
    setQuery(r.name.split(",")[0]);
    onPick({ lat: r.lat, lon: r.lon, label: r.name.split(",").slice(0, 2).join(",") });
  };

  return (
    <div className="startpicker">
      <button className="btn primary" onClick={locate} disabled={busy === "gps"}>
        {busy === "gps" ? "Ortung läuft …" : "📍 Meinen Standort verwenden"}
      </button>
      <form className="search" onSubmit={search}>
        <input
          type="search"
          placeholder="Adresse oder Stadt"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Adresse oder Stadt suchen"
        />
        <button className="btn" type="submit" disabled={busy === "search"}>
          {busy === "search" ? "…" : "Suchen"}
        </button>
      </form>
      {results?.length > 0 && (
        <ul className="results">
          {results.map((r, i) => (
            <li key={i}>
              <button onClick={() => choose(r)}>{r.name}</button>
            </li>
          ))}
        </ul>
      )}
      {msg && <p className="msg">{msg}</p>}
    </div>
  );
}

function Result({ start, result, loading, error }) {
  if (!start) return <p className="hint">Wähle zuerst einen Startpunkt.</p>;
  if (error) return <div className="banner error">{error}</div>;
  if (!result) return <p className="hint">{loading ? "Suche läuft …" : ""}</p>;
  if (!result.found)
    return (
      <div className={`banner warn ${loading ? "loading" : ""}`}>
        Weltweit gibt es laut aktuellem Datenstand keine Rasterzelle mit mindestens {result.min_cm} cm Schnee
        (Maximum: {result.max_depth_cm} cm).
      </div>
    );

  const { snow, distance_km, car } = result;
  return (
    <div className={`result ${loading ? "loading" : ""}`}>
      {result.at_start && <div className="banner ok">Du stehst schon im Schnee! ☃️</div>}
      <div className="stats">
        <div>
          <span className="big">{snow.depth_cm} cm</span>
          <span className="label">Schneehöhe (Modell)</span>
        </div>
        <div>
          <span className="big">{km(distance_km)}</span>
          <span className="label">Luftlinie</span>
        </div>
      </div>
      <dl className="facts">
        <dt>Koordinaten</dt>
        <dd>{coords(snow.lat, snow.lon)}</dd>
        <dt>Rasterzelle</dt>
        <dd>
          {snow.resolution_deg}° × {snow.resolution_deg}° (≈ {Math.round(snow.resolution_deg * 111)} km)
        </dd>
        <dt>Datenstand</dt>
        <dd>
          {dateTime(result.data.valid_time)}
          {result.data.stale && <span className="tag warn">veraltet</span>}
          {result.data.demo && <span className="tag warn">Demo</span>}
        </dd>
        <dt>Gesucht</dt>
        <dd>≥ {result.min_cm} cm</dd>
      </dl>

      <h3>🚗 Mit dem Auto</h3>
      <a className="btn primary block" href={car.google_maps_url} target="_blank" rel="noreferrer">
        Route in Google Maps öffnen
      </a>
    </div>
  );
}
