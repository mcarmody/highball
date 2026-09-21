# 🚂 Project Highball — Spatial Rail Transit Correlator & Cam-Director

[![Tests](https://img.shields.io/badge/tests-13%2F13%20passing-brightgreen)](#test-suite-verification)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9.4-199900.svg)](https://leafletjs.com)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#)

Project Highball is an automated spatial rail telemetry observation platform and intelligent live camera director. It correlates live continental passenger and freight train GPS positions (Amtraker v3 and GTFS-RT) against verified public rail webcams in real time, calculating approach trajectories, compass bearings, and estimated time of arrival (ETA), with mainline rail corridor overlays and automated camera switching.

---

## 🏗️ Architecture

```
[Amtraker v3 API / GTFS-RT] ──> [15s In-Memory Cache]
                                       │
                                       ▼
                       [FastAPI Spatial Correlator]
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
[7 Public Rail Cams]        [Rail Corridor Vectors]       [Auto-Director Engine]
  webcams.geojson             corridors.geojson             Heuristic Scorer
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       ▼
                         [Flyby Encounter Tracker]
                             /api/encounters
                                       │
                                       ▼
                         [Dark Leaflet Map & Drawer]
                            http://localhost:8001
```

---

## 🚀 Quickstart

### 1. Install Dependencies
```bash
pip install fastapi uvicorn requests pytest anyio
```

### 2. Launch Spatial Telemetry Server
```bash
python3 -m uvicorn server:app --host 0.0.0.0 --port 8001
```

### 3. Open Interactive Canvas
Open [http://localhost:8001](http://localhost:8001) in your web browser.

---

## 📡 API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dark Leaflet transit canvas and live encounter drawer |
| `GET` | `/health` | Spatial engine health and cache status |
| `GET` | `/api/trains` | Live train positions in GeoJSON (supports `?agency=Amtrak`) |
| `GET` | `/api/cams` | Registered public rail webcams GeoJSON FeatureCollection |
| `GET` | `/api/proximity` | Spatial correlation filtering trains within `max_miles` of cameras |
| `GET` | `/api/corridors` | GeoJSON `LineString` vectors for mainline rail corridors |
| `GET` | `/api/director` | Auto-Director's recommended camera to watch right now |
| `GET` | `/api/encounters/active` | Active encounter sessions currently in camera visual zones |
| `GET` | `/api/encounters/history` | Completed flyby encounters ring buffer with CPA and peak speed |

---

## 📹 Registered Public Webcams

1. **Horseshoe Curve** — Altoona, PA (NS Pittsburgh Line)
2. **Tehachapi Loop** — Tehachapi, CA (UP Mojave Sub)
3. **Rochelle Railroad Park Diamond** — Rochelle, IL (BNSF/UP Crossing)
4. **Fullerton Depot** — Fullerton, CA (BNSF Southern Transcon / Pacific Surfliner)
5. **Flagstaff Historic Depot** — Flagstaff, AZ (BNSF Southern Transcon / Southwest Chief)
6. **Galesburg Railcam** — Galesburg, IL (BNSF Mainline Hub)
7. **Perryville Amtrak Station** — Perryville, MD (Amtrak Northeast Corridor)

---

## 🧪 Test Suite Verification

Run the automated test suite:
```bash
pytest
```
Covers spatial math, compass bearing normalization, corridor overlays, GTFS-RT parser, Auto-Director heuristic scoring, and encounter session lifecycle. **13/13 tests passing green**.

---

## 📄 Documentation

- [STANDUP_7AM_REPORT.md](STANDUP_7AM_REPORT.md) — Comprehensive overnight prototype sprint briefing and demo instructions.
- [OPEN_TRANSIT_RESEARCH.md](OPEN_TRANSIT_RESEARCH.md) — Evaluation of open data transit APIs (Transitland v2, MBTA, 511 SF Bay Area, Metra).
