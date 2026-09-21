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
- **Cam Intercepts:** Overlaps with Virtual Railfan's Palmer and Northeast Corridor webcams.

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
