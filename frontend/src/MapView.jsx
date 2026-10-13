import { useEffect, useMemo } from "react";
import L from "leaflet";
import { ImageOverlay, MapContainer, Marker, Polyline, Rectangle, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { overlayUrl } from "./api.js";
import { greatCircle, km } from "./format.js";

const OVERLAY_BOUNDS = [
  [-85.0511287798, -180],
  [85.0511287798, 180],
];

const startIcon = L.divIcon({ className: "pin pin-start", html: "<span>📍</span>", iconSize: [32, 32], iconAnchor: [16, 30] });
const snowIcon = L.divIcon({ className: "pin pin-snow", html: "<span>❄️</span>", iconSize: [36, 36], iconAnchor: [18, 18] });

function ClickHandler({ onPick }) {
  useMapEvents({ click: (e) => onPick({ lat: e.latlng.lat, lon: e.latlng.wrap().lng, label: "Punkt auf der Karte" }) });
  return null;
}

function FitView({ start, path }) {
  const map = useMap();
  useEffect(() => {
    const pad = window.innerWidth < 760 ? { paddingTopLeft: [30, 30], paddingBottomRight: [30, window.innerHeight * 0.62 + 20] } : { paddingTopLeft: [420, 40], paddingBottomRight: [40, 40] };
    if (path) map.fitBounds(L.latLngBounds(path), { ...pad, maxZoom: 9 });
    else if (start) map.setView([start.lat, start.lon], Math.max(map.getZoom(), 6));
  }, [map, start, path]);
  return null;
}

export default function MapView({ start, result, status, showOverlay, onPick }) {
  const found = result?.found ? result : null;

  // Großkreis-Linie; Schneemarker und Zelle auf die „entfaltete“ Länge schieben,
  // damit sie bei Routen über die Datumsgrenze am Linienende liegen.
  const { path, shift } = useMemo(() => {
    if (!found || !start) return { path: null, shift: 0 };
    const p = greatCircle([start.lat, start.lon], [found.snow.lat, found.snow.lon]);
    return { path: p, shift: p[p.length - 1][1] - found.snow.lon };
  }, [found, start]);

  const snowPos = found && [found.snow.lat, found.snow.lon + shift];
  const cell = found && found.snow.cell_bounds.map(([la, lo]) => [la, lo + shift]);

  return (
    <MapContainer className="map" center={[47, 10]} zoom={4} minZoom={2} worldCopyJump zoomControl={false}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {showOverlay && status && (
        <ImageOverlay url={overlayUrl(status.created_at)} bounds={OVERLAY_BOUNDS} opacity={0.85} />
      )}
      <ClickHandler onPick={onPick} />
      <FitView start={start} path={path} />

      {start && <Marker position={[start.lat, start.lon]} icon={startIcon}><Tooltip>Start</Tooltip></Marker>}
      {path && <Polyline positions={path} pathOptions={{ color: "#0369a1", weight: 3, dashArray: "6 8" }} />}
      {found && (
        <>
          <Rectangle bounds={cell} pathOptions={{ color: "#0284c7", weight: 2, fillOpacity: 0.25 }} />
          <Marker position={snowPos} icon={snowIcon}>
            <Tooltip direction="top" offset={[0, -14]} permanent>
              {found.snow.depth_cm} cm · {km(found.distance_km)}
            </Tooltip>
          </Marker>
        </>
      )}
    </MapContainer>
  );
}
