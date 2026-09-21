# Project Highball — National Rail & Transit Telemetry

Status: draft, pending repo shell (brockventures/highball) and Mike/Ryan greenlight.
Owners: Amos (data ingest, map canvas, route/cam graph), Zero (trackside cam
locator, YOLO consist detection, defect-detector audio transcription).

## 1. Goal

A live, dark-mode "Mini Metro"-style map of US passenger/freight rail and
transit movement, cross-linked to trackside camera feeds so a user can jump
from a moving train to the nearest downstream junction camera.

## 2. Data Sources

- **Amtrak:** Amtraker unofficial REST API (`api-v3.amtraker.com/v3/trains`)
  — free, no key, real-time Amtrak train positions/status.
- **Transit:** GTFS-RT feeds, per-agency (most major US transit agencies
  publish these; feed URLs vary by agency, need per-agency onboarding).
- **Trackside cams:** state DOT grade-crossing cameras (candidates: Iowa DOT,
  Ohio DOT, Caltrans) and open municipal rail-junction streams. Excludes
  Virtual Railfan — their ToS prohibits automated/recording use without
  consent. **Open item:** confirm actual usage terms on each DOT feed before
  building against it; "state DOT" is not automatically public-domain.

## 3. Architecture

- **Ingest worker:** polls Amtraker + onboarded GTFS-RT feeds on an interval,
  normalizes to a common position schema, republishes over SSE (same wire
  pattern as the airspace/Outpost projects — one relay style across all
  Crab Cavern builds).
- **Spatial graph:** nodes = route + milepost markers; camera feeds attach
  to their nearest node. Lookup only (nearest downstream cam), not a
  routing engine — no full GIS stack needed.
- **Frontend:** Leaflet, dark-mode tile style, smoothed interpolation
  between position ticks so trains don't visibly jump between polls.
- **Cam integration:** clicking a train shows its position; a "jump to
  nearest cam" action opens the linked trackside feed (Zero's ingest).

## 4. Task Breakdown (Sprint 1, ~48h)

**Phase 1 (0-24h) — pipelines:**
- [ ] Amos: Amtraker polling worker + normalized position schema
- [ ] Amos: GTFS-RT onboarding for 1-2 pilot agencies
- [ ] Zero: identify and vet 2-3 open trackside cam sources (non-VRF)
- [ ] Zero: single-camera YOLO consist detector, proof of concept

**Phase 2 (24-48h) — integration:**
- [ ] Amos: Leaflet dark canvas consuming the SSE position stream
- [ ] Amos: route/milepost graph + nearest-cam lookup
- [ ] Zero: HLS ingest wired to detection loop, results over SSE
- [ ] Joint: cam-jump UI wired end to end

## 5. Cadence & UAT

- 48-hour sprint cycles, matching Outpost.
- Daily 7:00 PM PT review drop: live URL + whatever's verifiably working,
  for Mike/Ryan to poke at.

## 6. Open Risks

- GTFS-RT feed quality/coverage varies wildly by agency — pilot with 1-2
  known-good feeds before promising broad transit coverage.
- Trackside cam legal terms are the biggest unknown; do not scrape/ingest
  any feed before its terms are actually read, DOT or otherwise.
