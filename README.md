# ❄️ Wo liegt Schnee?

Eine Website, die weltweit das **nächstgelegene Gebiet mit einer frei wählbaren Mindestschneehöhe** findet – mit Luftlinie und Auto-Route über Google Maps.

> **Wichtig:** Die Schneehöhen stammen standardmäßig aus dem Wettermodell **NOAA GFS** (Analyse, alle 6 Stunden neu, ca. 25 × 25 km / 0,25°). Alternativ lässt sich das Reanalyse-Modell **Copernicus ERA5-Land** importieren (ca. 9 × 9 km, aber ~5 Tage Verzögerung). Beides sind modellierte Mittelwerte für Rasterzellen, keine Messungen an einem bestimmten Ort. Die Website zeigt das an, ebenso den Datenstand und ob die Daten veraltet oder Demo-Daten sind.

## Funktionen

- **Startpunkt:** GPS-Standort, Klick auf die Karte oder Adresse/Stadt (Nominatim/OpenStreetMap)
- **Mindestschneehöhe:** 5 / 10 / 20 / 50 / 100 cm oder beliebiger Wert
- **Suche:** nächste Rasterzelle ≥ Grenzwert (Großkreisentfernung, ~10 ms bei Millionen Schneezellen)
- **Ergebnis:** Schneehöhe, Koordinaten, Rasterzelle, Datenstand, Luftlinie (inkl. Großkreis-Linie auf der Karte)
- **Auto:** Google-Maps-Route per URL (keine API nötig)
- **Tagesauswahl:** alle gespeicherten vergangenen Tage, heute und 7 Tage Prognose (GFS); Datum auch per Kalender
- **Karte:** Schneedecken-Overlay mit Legende, teilbare Links (`?lat=…&lon=…&min=…&day=…`)
- **Kennzeichnung:** Demo-Daten und veraltete Daten (> 10 Tage) werden deutlich markiert
- Optimiert für Smartphone (Bottom-Sheet) und Desktop, Hell/Dunkel-Modus

## Aufbau

```
backend/                 Python (FastAPI)
  app/
    main.py              API: /api/days, /api/status, /api/nearest, /api/geocode, /api/overlay.png (jeweils ?day=YYYY-MM-DD)
    days.py              Tagesindex days.json (vergangen / heute / Prognose)
    snowdata.py          Schneeindex + Suche nach der nächsten Zelle
    grid.py              Rasterformat (uint16-cm in .npz), Web-Mercator-Overlay
    gfs.py               Download + Verarbeitung NOAA GFS (aktuell, ohne Konto)
    era5.py              Download + Verarbeitung ERA5-Land über die CDS-API
    geocode.py           Nominatim-Proxy mit Cache und Rate-Limit
    sync.py              Hintergrund-Aktualisierung (DATA_URL / Import im Server)
  scripts/
    ingest_gfs.py        Import GFS (Standard, alle 6 h)
    ingest_era5.py       Import ERA5-Land (optional)
    make_demo_data.py    Synthetische Demo-Daten (ohne CDS-Konto)
  data/                  erzeugte Schneedaten (nicht versioniert)
  tests/
frontend/                React + Leaflet (Vite)
.github/workflows/       CI + täglicher ERA5-Import
render.yaml              Backend auf Render
frontend/vercel.json     Frontend auf Vercel (leitet /api an Render weiter)
```

## Lokal starten

Voraussetzungen: Python 3.12+, Node 20+.

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m scripts.make_demo_data     # Demo-Daten erzeugen
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (zweites Terminal)
cd frontend
npm install
npm run dev                                    # http://localhost:5173
```

Tests: `cd backend && .venv/bin/pytest`

## Aktuelle Schneedaten (NOAA GFS) – Standard

Kein Konto nötig:

```bash
cd backend && .venv/bin/python -m scripts.ingest_gfs
```

Jeder Import erzeugt:

- **heute** – Analyse des jüngsten Laufs (klassische Dateien `snow_grid.npz`, `snow_overlay.png`, `snow_meta.json`)
- **Prognose** – die nächsten 7 Tage um 12 UTC aus demselben Lauf (`day-YYYY-MM-DD.npz`)
- **vergangene Tage** – fehlende Tage der letzten 10 Tage als 12-UTC-Analyse. Schon vorhandene Tage bleiben erhalten, die Historie wächst also mit jedem Tag. Ältere Tage lassen sich nachladen: `--backfill 2025-11-01` (AWS-Archiv ab 2021) bzw. in der Action unter *Run workflow → backfill*.

`days.json` listet alle Tage. Der Server synchronisiert nur den aktuellen Tag und diesen Index; einen anderen Tag lädt er erst, wenn jemand ihn auswählt (die letzten 6 bleiben im Speicher, das Overlay rendert er selbst).

Der Import nimmt für „heute“ den jüngsten fertigen GFS-Lauf (00/06/12/18 UTC, verfügbar ca. 4 h danach), lädt über den NOMADS-Filter nur die Felder `SNOD` (Schneehöhe, m) und `LAND` (Land-See-Maske, ~1 MB) – Fallback: AWS Open Data per Byte-Range –, blendet Wasser und Meereis aus und speichert das Raster wie oben. Daten gelten nach 2 Tagen als veraltet. Eine vorhandene GRIB2-Datei: `--file datei.grib2 --cycle 2026-11-10T00`.

## Geprüfte Schneedaten (ERA5-Land) – optional

1. Kostenloses Konto auf <https://cds.climate.copernicus.eu> anlegen.
2. Auf der Datensatzseite **ERA5-Land hourly data from 1950 to present** unter „Download“ die Lizenz akzeptieren.
3. API-Key aus dem Profil in `~/.cdsapirc` eintragen:
   ```
   url: https://cds.climate.copernicus.eu/api
   key: <dein-key>
   ```
4. Import starten:
   ```bash
   cd backend && .venv/bin/python -m scripts.ingest_era5
   ```

Der Import probiert die jüngsten Tage absteigend durch (ERA5-Land erscheint mit ca. 5 Tagen Verzögerung), lädt die Variable `snow_depth` (Meter) für 00:00 UTC, rechnet sie in Zentimeter um und speichert sie lokal als komprimiertes Raster (`data/snow_grid.npz`) plus Overlay-Bild und Metadaten. Der laufende Server lädt neue Daten automatisch, ohne Neustart. Eine bereits heruntergeladene NetCDF-Datei lässt sich mit `--file datei.nc --date YYYY-MM-DD` verarbeiten.

## Deployment (kostenlos): GitHub + Render + Vercel

```
GitHub Actions (täglicher Cron)  ──►  GitHub-Release „snow-data“
                                              │  Sync beim Start + alle 3 h (DATA_URL)
Vercel (Frontend)  ── /api/* ──►  Render (Python-Backend)
```

1. **GitHub – Import:** Die Action `.github/workflows/daily-snow-data.yml` läuft alle 6 Stunden (04:20/10:20/16:20/22:20 UTC), importiert NOAA GFS und veröffentlicht die Dateien als Release `snow-data`. Manuell kann unter *Run workflow* stattdessen `era5` gewählt werden.
   → Nur für ERA5: unter *Settings → Secrets and variables → Actions* das Secret `CDSAPI_KEY` anlegen.
   → Einmal manuell unter *Actions → Run workflow* starten, damit das Release existiert.
2. **Render – Backend:** *New → Blueprint* und dieses Repo wählen; `render.yaml` legt den Free-Web-Service `woliegtschnee-api` an. Beim Start und danach alle 3 Stunden holt er die Daten aus dem Release (bis dahin Demo-Daten, deutlich gekennzeichnet).
   → `NOMINATIM_USER_AGENT` mit Kontaktadresse setzen (Pflicht laut Nominatim-Richtlinie).
   → Falls Render eine andere URL vergibt, diese in `frontend/vercel.json` eintragen.
3. **Vercel – Frontend:** Repo importieren, *Root Directory* = `frontend`. `vercel.json` leitet `/api/*` an Render weiter, daher ist keine weitere Konfiguration nötig (kein CORS, keine API-URL im Build).

Hinweis: Render Free schläft nach 15 Minuten ohne Anfragen. Der erste Aufruf danach dauert bis zu ~1 Minute; das Frontend wartet und versucht es erneut.

Eine eigene Domain wird später in Vercel hinterlegt.

### Umgebungsvariablen

| Variable | Bedeutung | Standard |
|---|---|---|
| `DATA_URL` | Basis-URL mit `snow_meta.json`, `snow_grid.npz`, `snow_overlay.png` | – |
| `DATA_SYNC_HOURS` | Abfrageintervall für `DATA_URL` | `6` |
| `INGEST_ON_SERVER` | `1` = Import im Server-Prozess | `0` |
| `INGEST_SOURCE` | Quelle für den Server-Import: `gfs` oder `era5` | `gfs` |
| `STALE_AFTER_DAYS` | Ab wann Daten als veraltet gelten (wenn die Quelle keine eigene Grenze mitbringt; GFS: 2) | `10` |
| `NOMINATIM_USER_AGENT` | User-Agent mit Kontakt für die Adresssuche | Projekt-URL |
| `CORS_ORIGINS` | Erlaubte Origins, nur nötig ohne Vercel-Weiterleitung | `http://localhost:5173` |
| `VITE_API_BASE` | (Frontend-Build) API-URL, nur nötig ohne Vercel-Weiterleitung | gleiche Herkunft |

## Bekannte Grenzen

- **Modellwerte:** GFS-Zellen sind ~25 km, ERA5-Land-Zellen ~9 km groß; in Gebirgen liegen Gipfel und Täler in derselben Zelle, GFS unterschätzt dort oft. Gletscher und Eisschilde (Grönland, Antarktis) erscheinen mit sehr großen Schneehöhen.
- **Verzögerung:** GFS ist wenige Stunden alt (veraltet ab 2 Tagen), ERA5-Land ~5 Tage (veraltet ab 10 Tagen).
- **Historie im Release:** ein Asset pro Tag (~170 KB). GitHub erlaubt pro Release rund 1000 Assets, das reicht für gut 2½ Jahre – danach müsste die Historie z. B. auf mehrere Releases verteilt werden.
- **Auto-Route:** Google Maps entscheidet selbst, ob eine Route existiert (z. B. nicht über Ozeane).

## Datenquellen & Lizenzen

- Schneehöhe (Standard): NOAA/NCEP Global Forecast System (GFS), gemeinfrei.
- Schneehöhe (optional): Copernicus Climate Change Service, ERA5-Land (Muñoz Sabater, 2019). *Enthält modifizierte Copernicus-Climate-Change-Service-Informationen.*
- Karte & Geocoding: © OpenStreetMap-Mitwirkende (ODbL), Nominatim
