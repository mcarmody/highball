# Project Highball — Open Transit Data Research & Multi-Agency Ingestion

**Date:** 2026-09-21 03:20 PT  
**Author:** Zero  
**Scope:** Expanding Highball spatial telemetry beyond Amtrak to regional commuter, light rail, and freight corridors.

---

## 1. Executive Summary
Highball's Phase 1 prototype validates real-time spatial correlation using Amtraker's v3 API across 7 public rail webcams. To scale Highball into the definitive live railfan tracking canvas, we conducted an audit of open transit APIs, GTFS-RT (General Transit Feed Specification Realtime) feeds, and radio scanner networks.

---

## 2. High-Priority Open Transit Feeds

### A. Transitland v2 Platform
- **URL:** `https://www.transit.land/`
- **Protocol:** REST API / GeoJSON.
- **Coverage:** Aggregates GTFS schedule and GTFS-RT feeds for over 2,500 transit agencies globally.
- **Access:** Free API key required (10,000 queries/day free tier).
- **Utility:** Single normalized endpoint for querying regional passenger rail lines (Metra, Caltrain, MARC, SEPTA, SunRail, Tri-Rail, Sounder).

### B. MBTA V3 Realtime API (Massachusetts Bay Transportation Authority)
- **URL:** `https://api-v3.mbta.com/vehicles?filter[route_type]=2` (Route type 2 = Commuter Rail).
- **Protocol:** REST + Server-Sent Events (`Accept: text/event-stream`).
- **Data Attributes:** Lat/lon, bearing, current stop sequence, status, occupancy, multi-car train IDs.
- **Access:** Open / unauthenticated rate limit (20 req/min), free API key expands to 1,000 req/min.
- **Cam Intercepts:** Overlaps with trackside feeds along the Palmer and Northeast Corridor rail lines.

### C. 511 SF Bay Area Open Data API (Caltrain & BART)
- **URL:** `https://api.511.org/transit/vehiclepositions?api_key=...&agency=CT` (Caltrain).
- **Protocol:** GTFS-RT JSON & Protobuf.
- **Data Attributes:** Real-time EMU/diesel consist positions along the SF-San Jose-Gilroy corridor.
- **Cam Intercepts:** Pairs with Santa Clara Depot and San Jose Diridon railfan cams.

### D. Chicago Metra Open Data
- **URL:** Metra GTFS-RT Developer Portal (`https://metra.com/how-metra-works/metra-gtfs-api`).
- **Data Attributes:** Covers UP West, BNSF, and Milwaukee District corridors.
- **Cam Intercepts:** Directly intersects Rochelle Railroad Park (UP Geneva Sub) and Galesburg Depot (BNSF Chillicothe Sub).

---

## 3. Highball Unified Ingestion Architecture

```
[ Amtraker v3 (National) ] ──┐
[ MBTA SSE (Commuter) ]    ──┼──► [ Highball GTFS-RT Parser ] ──► [ Spatial Engine ] ──► [ Leaflet Canvas ]
[ Metra / 511 GTFS-RT ]    ──┘           (gtfs_rt_parser.py)            (server.py)             (index.html)
```

- Highball maps all incoming feeds into standardized GeoJSON Point FeatureCollections.
- Properties include: `id`, `train_num`, `route`, `agency`, `speed_mph`, `heading`, `timely`, `status`.
- Trajectory and proximity math runs uniformly regardless of whether a train is Amtrak, commuter rail, or freight.

---

## 4. Non-Rail Transit Modes (2026-09-21 20:45 PT, Amos)

Mike asked (#side-project, 20:43 PT) to start exploring buses, local subway
systems, and airplanes as additional modes. Everything in §1-3 above is
rail-only (Amtrak + GTFS-RT `route_type=2`, commuter rail). Scoped what it
takes to add the other two transit families:

### A. Bus & subway/light rail — cheap, same pipe already wired

`server.py`'s MBTA call is hardcoded to `filter[route_type]=2` (commuter
rail only). GTFS-RT's `route_type` enum also covers `0` (light rail /
subway/tram — e.g. the T's Green/Red/Orange/Blue Lines) and `3` (bus). The
**same MBTA feed, same API key, same parser** (`parse_mbta_v3_vehicles`)
already returns these if the filter is widened — this is a config change,
not a new integration. Same is true for the 511 Bay Area feed (BART is
`route_type=1`, AC Transit/Muni buses are `route_type=3`) and Transitland's
2,500-agency aggregator from §2.A, which was scoped for rail but carries
every mode.

What's genuinely new work, not just a filter change: the map currently has
one visual language for "train." Buses and subway cars need their own
marker glyphs/colors so the canvas doesn't read as "more trains" — this is
a design call, not an ingest one, and Highball's icon language is already
mid-redesign with Zero (per arbiter's "distinct design language per app"
direction earlier tonight). Recommend folding bus/subway iconography into
that same design pass rather than bolting on ad hoc markers.

### B. Airplanes — a real new data source, not a filter change

No existing pipe covers aircraft; GTFS-RT doesn't model air travel at all.
Candidate: **OpenSky Network** (`opensky-network.org`, REST API,
`/api/states/all`) — crowdsourced ADS-B, global live aircraft
position/altitude/heading/callsign, free anonymous tier (400 credits/day,
~1 query/10s), no ToS conflict (research/non-commercial use is the
documented intent, and this is exactly that). FlightAware AeroAPI is the
paid, higher-rate-limit alternative if OpenSky's anonymous tier turns out
too thin once the app has real traffic. Would need its own parser
(`opensky_parser.py`, mirroring `gtfs_rt_parser.py`'s shape) and its own
marker family (plane glyph, altitude as a possible third dimension the
current train/bus markers don't need).

### C. Open question for Mike/Ryan

Scope split: does "incorporate" mean overlay onto the existing single map
(one canvas, multiple mode toggles), or a separate view per mode? That's a
product call, not an engineering one — flagging rather than guessing.

### D. Unrelated finding while reading this code

`server.py:39` hardcodes a live MBTA API key as the `os.getenv` fallback
default, checked into the public `mcarmody/highball` repo. MBTA keys are
low-sensitivity (rate-limit only, no billing/PII behind them), so not
treating as urgent, but it should move to an env var with no hardcoded
fallback next time anyone touches that file.
