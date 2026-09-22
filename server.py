"""FastAPI Server & Spatial Proximity Engine for Project Highball.

Provides:
- GET /: Highball Dark Leaflet Live Ops Map
- GET /api/trains: Live Amtrak train GeoJSON (cached 15s to respect upstream API)
- GET /api/cams: Curated railfan webcam GeoJSON
- GET /api/proximity: Live calculation of trains within proximity of webcams with trajectory and station stops
- GET /health: Telemetry and upstream status
"""

import asyncio
import concurrent.futures
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cam_lookup import (
    PUBLIC_RAIL_CAMS,
    calculate_trajectory_status,
    find_nearby_cameras,
    find_nearest_camera,
    get_downstream_camera_intercept,
    haversine_miles,
    parse_heading_degrees,
)
from encounter_tracker import EncounterTracker
from gtfs_rt_parser import parse_gtfs_rt_vehicle_positions, parse_mbta_v3_vehicles
from opensky_parser import parse_opensky_states
from consist_detector import synthesize_consist_for_train, generate_defect_report

BASE_DIR = Path(__file__).parent
INDEX_HTML = BASE_DIR / "index.html"
WEBCAMS_GEOJSON = BASE_DIR / "webcams.geojson"
CORRIDORS_GEOJSON = BASE_DIR / "corridors.geojson"

# Upstream Transit API Keys (MBTA requires no key for public tier; others use developer endpoints)
MBTA_API_KEY = os.getenv("MBTA_API_KEY", "")
SF_511_API_KEY = os.getenv("SF_511_API_KEY", "5727dbc7-a646-44b2-b8e5-b5ffe95f9cea")
TRANSITLAND_API_KEY = os.getenv("TRANSITLAND_API_KEY", "iwa_live_tlv2api_280ad7fdff73b31d7326fa84725f34428d0a9cd1aa7209621Z7Vl4")

encounter_tracker = EncounterTracker(max_history=50, encounter_radius_miles=5.0)

app = FastAPI(
    title="Highball Railfan Transit & Webcam Engine",
    description="Spatial telemetry engine correlating live Amtrak trains with public railfan webcams",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active Server-Sent Events (SSE) subscriber queues
subscribers: Set[asyncio.Queue] = set()


def broadcast_sse_sync(event_type: str, data: Any):
    """Synchronously puts an event into all connected SSE queues without blocking."""
    if not subscribers:
        return
    payload = json.dumps(data) if not isinstance(data, str) else data
    dead_queues = set()
    for q in list(subscribers):
        try:
            q.put_nowait((event_type, payload))
        except asyncio.QueueFull:
            dead_queues.add(q)
        except Exception:
            dead_queues.add(q)
    for dq in dead_queues:
        subscribers.discard(dq)


# Cache for upstream transit data to avoid hitting rate limits
_train_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "geojson": None,
}
CACHE_TTL_SECONDS = 15.0

# In-memory GPS breadcrumb history per train: train_key -> deque([[lon, lat], ...], maxlen=15)
_breadcrumb_history: Dict[str, deque] = {}
_breadcrumb_last_seen: Dict[str, float] = {}


def update_breadcrumbs(features: List[Dict[str, Any]], now: float):
    """Updates historical GPS breadcrumb trails for active trains with geographic sanitization."""
    global _breadcrumb_history, _breadcrumb_last_seen
    for feat in features:
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        try:
            lon, lat = round(float(coords[0]), 5), round(float(coords[1]), 5)
        except (ValueError, TypeError):
            continue

        # Reject Null Island / near-zero glitches and missing fixes
        if abs(lon) < 1.0 and abs(lat) < 1.0:
            continue
        # Restrict to North American transit corridor envelope (lat 18° to 75°, lon -175° to -50°)
        if not (18.0 <= lat <= 75.0 and -175.0 <= lon <= -50.0):
            continue

        key = str(props.get("id") or props.get("train_num") or "")
        if not key:
            continue
        _breadcrumb_last_seen[key] = now

        if key not in _breadcrumb_history:
            _breadcrumb_history[key] = deque(maxlen=15)

        history = _breadcrumb_history[key]
        # Reject teleport jumps > 2.0 degrees (~120 miles in 15-30 seconds)
        is_teleport = False
        if history:
            prev_lon, prev_lat = history[-1]
            if abs(prev_lon - lon) > 2.0 or abs(prev_lat - lat) > 2.0:
                is_teleport = True

        if not is_teleport and (not history or (abs(history[-1][0] - lon) > 0.0001 or abs(history[-1][1] - lat) > 0.0001)):
            history.append([lon, lat])

        props["breadcrumbs"] = list(history)

    # Prune trains unseen for > 1 hour
    stale_keys = [k for k, last_ts in _breadcrumb_last_seen.items() if now - last_ts > 3600.0]
    for k in stale_keys:
        _breadcrumb_history.pop(k, None)
        _breadcrumb_last_seen.pop(k, None)


def _fetch_amtrak() -> List[Dict[str, Any]]:
    """Fetches live national passenger trains from Amtraker v3."""
    features = []
    url_amtrak = "https://api-v3.amtraker.com/v3/trains"
    try:
        resp = requests.get(url_amtrak, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            for train_id, instances in data.items():
                for t in instances:
                    if t.get("trainState") == "Active" and t.get("lat") and t.get("lon"):
                        stations = t.get("stations", [])
                        next_station = None
                        for stn in stations:
                            if stn.get("status") in ["Enroute", "Station"]:
                                next_station = {
                                    "name": stn.get("name"),
                                    "code": stn.get("code"),
                                    "status": stn.get("status"),
                                    "arr": stn.get("arr") or stn.get("schArr"),
                                    "dep": stn.get("dep") or stn.get("schDep"),
                                }
                                break

                        features.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [float(t["lon"]), float(t["lat"])],
                            },
                            "properties": {
                                "id": t.get("trainID"),
                                "train_num": t.get("trainNum"),
                                "route": t.get("routeName"),
                                "speed_mph": round(float(t.get("velocity", 0.0)), 1),
                                "heading": parse_heading_degrees(t.get("heading")),
                                "timely": t.get("trainTimely"),
                                "status": t.get("statusMsg"),
                                "origin": t.get("origName"),
                                "dest": t.get("destName"),
                                "updated_at": t.get("updatedAt"),
                                "next_station": next_station,
                                "agency": "Amtrak",
                                "mode": "intercity_rail",
                                "mode_label": "Intercity Rail",
                            },
                        })
    except Exception as exc:
        print(f"[Highball] Amtraker fetch warning: {exc}")
    return features


def _fetch_mbta() -> List[Dict[str, Any]]:
    """Fetches live MBTA vehicles: Subways (Red/Orange/Blue), Light Rail (Green), Commuter Rail, and Bus.

    Mike, 2026-09-21 21:36 PT asked for bus specifically (alongside subway,
    which already had support) — parse_mbta_v3_vehicles already resolves
    route_type=3 to mode="bus", but this fetch's own filter excluded it, so
    no bus vehicle ever reached the parser. Widened to include it.
    """
    url = "https://api-v3.mbta.com/vehicles?filter[route_type]=0,1,2,3&include=route"
    if MBTA_API_KEY:
        url += f"&api_key={MBTA_API_KEY}"
    try:
        resp = requests.get(url, timeout=5.0)
        if resp.status_code == 200:
            mbta_geojson = parse_mbta_v3_vehicles(resp.json())
            return mbta_geojson.get("features", [])
    except Exception as exc:
        print(f"[Highball] MBTA fetch warning: {exc}")
    return []


def _fetch_caltrain() -> List[Dict[str, Any]]:
    """Fetches live Caltrain commuter trains from 511 SF Bay Area."""
    if not SF_511_API_KEY:
        return []
    try:
        sf_url = f"http://api.511.org/transit/vehiclepositions?api_key={SF_511_API_KEY}&agency=CT&format=json"
        resp = requests.get(sf_url, timeout=5.0)
        if resp.status_code == 200:
            sf_data = json.loads(resp.content.decode("utf-8-sig"))
            caltrain_geojson = parse_gtfs_rt_vehicle_positions(sf_data, agency_id="Caltrain")
            return caltrain_geojson.get("features", [])
    except Exception as exc:
        print(f"[Highball] 511 Caltrain fetch warning: {exc}")
    return []


def _fetch_metra() -> List[Dict[str, Any]]:
    """Fetches Chicago Metra commuter rail via Transitland proxy."""
    if not TRANSITLAND_API_KEY:
        return []
    try:
        metra_url = (
            "https://transit.land/api/v2/rest/feeds/f-metra~rt/"
            f"download_latest_rt/vehicle_positions.json?apikey={TRANSITLAND_API_KEY}"
        )
        resp = requests.get(metra_url, timeout=5.0)
        if resp.status_code == 200:
            metra_geojson = parse_gtfs_rt_vehicle_positions(resp.json(), agency_id="Metra")
            return metra_geojson.get("features", [])
    except Exception as exc:
        print(f"[Highball] Metra (Transitland) fetch warning: {exc}")
    return []


def _fetch_sound_transit() -> List[Dict[str, Any]]:
    """Fetches Puget Sound Transit Link & Sounder via Transitland proxy."""
    if not TRANSITLAND_API_KEY:
        return []
    try:
        st_url = (
            "https://transit.land/api/v2/rest/feeds/f-soundtransit~rt/"
            f"download_latest_rt/vehicle_positions.json?apikey={TRANSITLAND_API_KEY}"
        )
        resp = requests.get(st_url, timeout=5.0)
        if resp.status_code == 200:
            st_geojson = parse_gtfs_rt_vehicle_positions(resp.json(), agency_id="Sound Transit")
            return st_geojson.get("features", [])
    except Exception as exc:
        print(f"[Highball] Sound Transit (Transitland) fetch warning: {exc}")
    return []


_flight_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "features": [],
}
FLIGHT_CACHE_TTL_SECONDS = 20.0  # OpenSky anonymous tier cache guard (~400 requests/day)


def _fetch_flights() -> List[Dict[str, Any]]:
    """Fetches live North American airspace flights from OpenSky Network ADS-B feed."""
    now = time.time()
    if _flight_cache["features"] and (now - _flight_cache["timestamp"] < FLIGHT_CACHE_TTL_SECONDS):
        return _flight_cache["features"]

    # US continental bounding box (lat 24.39 to 49.38, lon -125.0 to -66.93)
    url = (
        "https://opensky-network.org/api/states/all?"
        "lamin=24.396308&lomin=-125.0&lamax=49.384358&lomax=-66.93457"
    )
    try:
        resp = requests.get(url, headers={"User-Agent": "HighballTransitTracker/1.0"}, timeout=4.0)
        if resp.status_code == 200:
            parsed = parse_opensky_states(resp.json(), include_ground=False)
            features = parsed.get("features", [])
            _flight_cache["timestamp"] = now
            _flight_cache["features"] = features
            return features
        elif resp.status_code == 429:
            print("[Highball] OpenSky 429 rate limit hit, applying 90s backoff and returning cached flights")
            _flight_cache["timestamp"] = now + 90.0
            return _flight_cache["features"]
    except Exception as exc:
        print(f"[Highball] OpenSky flight fetch warning: {exc}")
        _flight_cache["timestamp"] = now + 30.0

    return _flight_cache["features"]


def calculate_fleet_counts(features: List[Dict[str, Any]]) -> Dict[str, int]:
    """Tallies fleet counts across all transit modes and highspeed vehicles."""
    counts = {
        "ground": 0,
        "amtrak": 0,
        "subway": 0,
        "commuter": 0,
        "bus": 0,
        "flight": 0,
        "all": len(features),
        "highspeed": 0,
    }
    for f in features:
        props = f.get("properties", {})
        m = props.get("mode", "")
        if m == "intercity_rail":
            counts["amtrak"] += 1
            counts["ground"] += 1
        elif m in ["subway", "light_rail"]:
            counts["subway"] += 1
            counts["ground"] += 1
        elif m == "commuter_rail":
            counts["commuter"] += 1
            counts["ground"] += 1
        elif m == "bus":
            counts["bus"] += 1
            counts["ground"] += 1
        elif m == "flight":
            counts["flight"] += 1

        if props.get("speed_mph", 0.0) >= 60.0:
            counts["highspeed"] += 1
    return counts


def fetch_live_train_geojson() -> Dict[str, Any]:
    """Fetches live multi-agency transit concurrently (Amtrak, MBTA Subway/Rail, Caltrain, Metra, Sound Transit, OpenSky Flights)."""
    now = time.time()
    if _train_cache["geojson"] and (now - _train_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _train_cache["geojson"]

    features = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(_fetch_amtrak),
            executor.submit(_fetch_mbta),
            executor.submit(_fetch_caltrain),
            executor.submit(_fetch_metra),
            executor.submit(_fetch_sound_transit),
            executor.submit(_fetch_flights),
        ]
        for fut in concurrent.futures.as_completed(futures):
            try:
                batch = fut.result()
                if batch:
                    features.extend(batch)
            except Exception as exc:
                print(f"[Highball] Concurrent transit fetch worker error: {exc}")

    if features:
        for f in features:
            props = f.get("properties", {})
            if props.get("mode") != "flight":
                coords = f.get("geometry", {}).get("coordinates", [])
                if len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
                    intercept = get_downstream_camera_intercept(
                        lat, lon,
                        train_heading=props.get("heading"),
                        speed_mph=props.get("speed_mph", 0.0),
                        max_miles=50.0,
                    )
                    if intercept:
                        props["nearest_cam"] = {
                            "cam_id": intercept["cam_id"],
                            "name": intercept["name"],
                            "location": intercept["location"],
                            "distance_miles": intercept["distance_miles"],
                            "trajectory": intercept["trajectory"],
                            "eta_minutes": intercept.get("eta_minutes"),
                            "embed_url": intercept.get("embed_url"),
                            "stream_url": intercept.get("stream_url"),
                            "provider": intercept.get("provider"),
                            "lat": intercept["lat"],
                            "lon": intercept["lon"],
                        }
        update_breadcrumbs(features, now)

    if not features and _train_cache["geojson"]:
        return _train_cache["geojson"]

    geojson = {
        "type": "FeatureCollection",
        "timestamp": now,
        "total_active": len(features),
        "features": features,
    }
    _train_cache["timestamp"] = now
    _train_cache["geojson"] = geojson

    broadcast_sse_sync("telemetry", {
        "timestamp": now,
        "total_active": len(features),
        "counts": calculate_fleet_counts(features),
    })
    return geojson


@app.get("/api/breadcrumbs")
async def get_breadcrumbs(train_id: Optional[str] = None):
    """Returns GeoJSON FeatureCollection of historical GPS breadcrumb polylines for active trains."""
    features = []
    for key, trail in _breadcrumb_history.items():
        if train_id and key != train_id:
            continue
        if len(trail) >= 2:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": list(trail),
                },
                "properties": {
                    "train_id": key,
                    "points_count": len(trail),
                }
            })
    return {"type": "FeatureCollection", "total_trails": len(features), "features": features}


@app.get("/", response_class=FileResponse)
async def root():
    """Serves the Highball Leaflet Ops Canvas."""
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return JSONResponse({"status": "Highball Transit Engine Online", "docs": "/docs"})


@app.get("/health")
async def health():
    """System health check and tracking statistics."""
    train_count = len(_train_cache["geojson"]["features"]) if _train_cache["geojson"] else 0
    return {
        "status": "online",
        "service": "highball-spatial-engine",
        "active_cams": len(PUBLIC_RAIL_CAMS),
        "cached_trains": train_count,
        "cache_age_sec": round(time.time() - _train_cache["timestamp"], 1) if _train_cache["timestamp"] else None,
        "active_sse_subscribers": len(subscribers),
    }


@app.get("/events")
@app.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events stream delivering live train telemetry and proximity encounter updates."""
    client_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    subscribers.add(client_queue)

    async def event_generator():
        try:
            train_count = len(_train_cache["geojson"]["features"]) if _train_cache["geojson"] else 0
            handshake = {
                "message": "Connected to Highball SSE spatial telemetry bus",
                "service": "highball-spatial-engine",
                "active_cams": len(PUBLIC_RAIL_CAMS),
                "cached_trains": train_count,
                "timestamp": time.time(),
            }
            yield f"event: connected\ndata: {json.dumps(handshake)}\n\n"

            while True:
                try:
                    event_type, payload = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                    yield f"event: {event_type}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            subscribers.discard(client_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/events/broadcast")
async def broadcast_manual_event(payload: Dict[str, Any]):
    """Dispatches a custom or simulation event over the Highball SSE bus."""
    event_type = payload.get("event_type", "message")
    data = payload.get("data", {})
    broadcast_sse_sync(event_type, data)
    return {"status": "dispatched", "subscribers": len(subscribers), "event_type": event_type}


@app.get("/api/cams")
async def get_webcams():
    """Returns GeoJSON FeatureCollection of public rail webcams."""
    if WEBCAMS_GEOJSON.exists():
        with open(WEBCAMS_GEOJSON, "r") as f:
            return json.load(f)
    return {"type": "FeatureCollection", "features": []}


@app.get("/api/corridors")
async def get_corridors():
    """Returns GeoJSON FeatureCollection of mainline rail corridors."""
    if CORRIDORS_GEOJSON.exists():
        with open(CORRIDORS_GEOJSON, "r") as f:
            return json.load(f)
    from rail_corridors import generate_corridors_geojson
    return generate_corridors_geojson(str(CORRIDORS_GEOJSON))


@app.get("/api/corridors/density")
async def get_corridors_density():
    """Returns aggregated real-time transit density, speed metrics, and camera distribution across all mainline rail corridors."""
    from rail_corridors import MAJOR_CORRIDORS, get_all_corridors_density
    geojson = fetch_live_train_geojson()
    features = geojson.get("features", [])
    density_data = get_all_corridors_density(MAJOR_CORRIDORS, features, PUBLIC_RAIL_CAMS)
    density_data["timestamp"] = time.time()
    return density_data


@app.get("/api/corridors/{corridor_id}")
async def get_corridor_details(corridor_id: str):
    """Returns detailed corridor metadata, line coordinates, associated trackside cameras, and active trains on corridor."""
    from rail_corridors import get_corridor_by_id, get_corridor_cameras, match_trains_to_corridor
    corr = get_corridor_by_id(corridor_id)
    if not corr:
        raise HTTPException(status_code=404, detail=f"Rail corridor '{corridor_id}' not found.")

    geojson = fetch_live_train_geojson()
    features = geojson.get("features", [])
    active_trains = match_trains_to_corridor(corr, features)
    cams = get_corridor_cameras(corr, PUBLIC_RAIL_CAMS)

    speeds = [t.get("properties", {}).get("speed_mph", 0.0) for t in active_trains]
    peak_speed = max(speeds) if speeds else 0.0

    return {
        "corridor_id": corr["corridor_id"],
        "name": corr["name"],
        "operator": corr["operator"],
        "subdivision": corr["subdivision"],
        "routes": corr.get("routes", []),
        "coordinates": corr.get("coordinates", []),
        "waypoints": len(corr.get("coordinates", [])),
        "active_train_count": len(active_trains),
        "peak_speed_mph": peak_speed,
        "active_trains": active_trains,
        "associated_cameras": cams,
        "timestamp": time.time(),
    }


@app.get("/api/trains")
async def get_trains(
    agency: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None, description="Filter by transit mode: intercity_rail, commuter_rail, subway, light_rail, flight, ground, or all"),
):
    """Returns live GeoJSON FeatureCollection of active trains, optionally filtered by agency and/or mode."""
    geojson = fetch_live_train_geojson()
    all_features = geojson.get("features", [])
    counts = calculate_fleet_counts(all_features)
    filtered = all_features

    if agency and agency.lower() != "all":
        filtered = [f for f in filtered if f["properties"].get("agency", "").lower() == agency.lower()]

    if mode and mode.lower() != "all":
        mode_target = mode.lower()
        if mode_target == "rail":
            filtered = [f for f in filtered if f["properties"].get("mode", "") in ["intercity_rail", "commuter_rail"]]
        elif mode_target == "ground":
            filtered = [f for f in filtered if f["properties"].get("mode", "") in ["intercity_rail", "commuter_rail", "subway", "light_rail", "bus"]]
        elif mode_target in ["subway", "metro"]:
            filtered = [f for f in filtered if f["properties"].get("mode", "") in ["subway", "light_rail"]]
        elif mode_target in ["amtrak", "intercity"]:
            filtered = [f for f in filtered if f["properties"].get("mode", "") == "intercity_rail"]
        elif mode_target in ["flight", "flights"]:
            filtered = [f for f in filtered if f["properties"].get("mode", "") == "flight"]
        elif mode_target in ["highspeed", "fast"]:
            filtered = [f for f in filtered if f["properties"].get("speed_mph", 0.0) >= 60.0]
        else:
            filtered = [f for f in filtered if f["properties"].get("mode", "").lower() == mode_target]

    return {
        "type": "FeatureCollection",
        "timestamp": geojson.get("timestamp"),
        "total_active": len(filtered),
        "counts": counts,
        "features": filtered,
    }


@app.get("/api/trains/{train_id}")
async def get_train_by_id(train_id: str):
    """Retrieve full telemetry, proximity graph, and downstream camera intercept for a specific train or transit vehicle."""
    trains_geo = fetch_live_train_geojson()
    target_id = train_id.strip().lower()

    matched = None
    for feature in trains_geo.get("features", []):
        props = feature["properties"]
        feat_id = str(props.get("id", "")).lower()
        train_num = str(props.get("train_num", "")).lower()
        callsign = str(props.get("callsign", "")).lower()
        if target_id in (feat_id, train_num, callsign) or feat_id.endswith(f"_{target_id}"):
            matched = feature
            break

    if not matched:
        raise HTTPException(status_code=404, detail=f"Transit vehicle '{train_id}' not found in active telemetry.")

    coords = matched["geometry"]["coordinates"]
    lon, lat = coords[0], coords[1]
    props = matched["properties"]
    speed = props.get("speed_mph", 0.0)
    heading = props.get("heading")

    nearby_cams = find_nearby_cameras(lat, lon, train_heading=heading, max_miles=150.0)
    downstream = get_downstream_camera_intercept(lat, lon, train_heading=heading, speed_mph=speed, max_miles=150.0)

    return {
        "vehicle": matched,
        "coordinates": {"lat": lat, "lon": lon},
        "downstream_intercept": downstream,
        "nearby_cameras": nearby_cams[:5],
        "timestamp": time.time(),
    }


@app.get("/api/flights")
async def get_flights():
    """Returns live GeoJSON FeatureCollection of active North American flights via OpenSky Network."""
    flights = _fetch_flights()
    return {
        "type": "FeatureCollection",
        "timestamp": _flight_cache["timestamp"] or time.time(),
        "total_active": len(flights),
        "agency": "OpenSky Network",
        "features": flights,
    }


@app.get("/api/proximity")
async def get_proximity_events(
    max_miles: float = Query(default=15.0, ge=1.0, le=50.0),
    trajectory: Optional[str] = Query(default=None, description="Filter by approaching, receding, or passing"),
):
    """Correlates active trains with webcams and returns proximity events with trajectory and ETA."""
    trains_geo = fetch_live_train_geojson()
    proximity_matches = []

    for feature in trains_geo.get("features", []):
        props = feature["properties"]
        # Railcams track ground rail corridors; skip flights passing overhead
        if props.get("mode") == "flight":
            continue

        coords = feature["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]

        for cam in PUBLIC_RAIL_CAMS:
            dist = haversine_miles(lat, lon, cam["lat"], cam["lon"])
            if dist <= max_miles:
                traj_status, bearing_cam = calculate_trajectory_status(
                    lat, lon, props.get("heading"), cam["lat"], cam["lon"]
                )

                if trajectory and traj_status != trajectory:
                    continue

                speed = props["speed_mph"]
                eta_minutes = None
                if traj_status == "approaching" and speed > 5:
                    eta_minutes = round((dist / speed) * 60, 1)

                proximity_matches.append({
                    "train": {
                        "train_num": props["train_num"],
                        "route": props["route"],
                        "agency": props.get("agency", "Amtrak"),
                        "mode": props.get("mode", "intercity_rail"),
                        "mode_label": props.get("mode_label", "Intercity Rail"),
                        "speed_mph": speed,
                        "heading": props["heading"],
                        "dest": props["dest"],
                        "timely": props["timely"],
                        "next_station": props.get("next_station"),
                    },
                    "camera": {
                        "cam_id": cam["cam_id"],
                        "name": cam["name"],
                        "location": cam["location"],
                        "milepost": cam["milepost"],
                        "provider": cam["provider"],
                        "lat": cam["lat"],
                        "lon": cam["lon"],
                        "stream_url": cam.get("stream_url", ""),
                        "embed_url": cam.get("embed_url", ""),
                    },
                    "distance_miles": round(dist, 2),
                    "trajectory": traj_status,
                    "bearing_to_cam": bearing_cam,
                    "eta_minutes": eta_minutes,
                })

    proximity_matches.sort(key=lambda x: x["distance_miles"])
    encounter_changes = encounter_tracker.update(proximity_matches)
    if proximity_matches:
        broadcast_sse_sync("proximity", {
            "timestamp": time.time(),
            "total_matches": len(proximity_matches),
            "events": proximity_matches[:10],
        })
    if encounter_changes.get("new"):
        for new_enc in encounter_changes["new"]:
            broadcast_sse_sync("encounter", new_enc)
    return {
        "timestamp": time.time(),
        "total_matches": len(proximity_matches),
        "max_miles_threshold": max_miles,
        "filter_trajectory": trajectory,
        "events": proximity_matches,
    }


@app.get("/api/encounters/history")
async def get_encounter_history(limit: int = 20):
    """Returns completed flyby encounters history."""
    return encounter_tracker.get_recent_history(limit=limit)


@app.get("/api/encounters/active")
async def get_active_encounters():
    """Returns active proximity encounter sessions in progress."""
    return encounter_tracker.get_active_encounters()


@app.get("/api/encounters/analytics")
async def get_encounter_analytics():
    """Returns aggregated trackside flyby analytics (peak transit speeds, visual dwell, and busiest junctions)."""
    return encounter_tracker.get_analytics()


@app.get("/api/director")
async def get_director():
    """Returns Auto-Director's recommended camera to watch right now based on active encounters."""
    prox = await get_proximity_events(max_miles=15.0)
    events = prox.get("events", [])
    from auto_director import select_director_camera
    return select_director_camera(events)


@app.get("/api/consists")
async def get_consists_summary():
    """Returns fleet-wide rolling stock inventory and consist metrics across active rail services."""
    trains_geo = fetch_live_train_geojson()
    rail_features = [
        f for f in trains_geo.get("features", [])
        if f.get("properties", {}).get("mode") != "flight"
    ]

    total_locomotives = 0
    total_cars = 0
    total_axles = 0
    total_horsepower = 0
    total_tonnage = 0
    motive_power_dist: Dict[str, int] = {}
    car_type_dist: Dict[str, int] = {}
    train_summaries = []

    longest_consist = None
    heaviest_consist = None

    for feat in rail_features:
        props = feat.get("properties", {})
        t_num = str(props.get("train_num") or props.get("id") or "0")
        route = props.get("route") or props.get("route_name") or ""
        agency = props.get("agency") or "Amtrak"
        speed = float(props.get("speed_mph") or 0.0)

        consist = synthesize_consist_for_train(t_num, route=route, agency=agency, speed_mph=speed)

        total_locomotives += consist["locomotive_count"]
        total_cars += consist["car_count"]
        total_axles += consist["total_axles"]
        total_horsepower += consist["total_horsepower"]
        total_tonnage += consist["total_weight_tons"]

        for u in consist["units"]:
            cat = u["category"]
            uid = u["unit_id"]
            if cat == "locomotive":
                motive_power_dist[uid] = motive_power_dist.get(uid, 0) + 1
            else:
                car_type_dist[cat] = car_type_dist.get(cat, 0) + 1

        summary_entry = {
            "train_num": t_num,
            "route": route,
            "agency": agency,
            "train_type": consist["train_type"],
            "locomotive_count": consist["locomotive_count"],
            "car_count": consist["car_count"],
            "total_units": consist["total_units"],
            "total_axles": consist["total_axles"],
            "total_length_ft": consist["total_length_ft"],
            "total_weight_tons": consist["total_weight_tons"],
            "total_horsepower": consist["total_horsepower"],
            "lead_locomotive": consist["units"][0]["name"] if consist["units"] else "Unknown",
            "speed_mph": speed,
        }
        train_summaries.append(summary_entry)

        if not longest_consist or consist["total_units"] > longest_consist["total_units"]:
            longest_consist = summary_entry
        if not heaviest_consist or consist["total_weight_tons"] > heaviest_consist["total_weight_tons"]:
            heaviest_consist = summary_entry

    return {
        "timestamp": time.time(),
        "total_trains": len(rail_features),
        "total_locomotives": total_locomotives,
        "total_cars": total_cars,
        "total_units": total_locomotives + total_cars,
        "total_axles": total_axles,
        "total_horsepower": total_horsepower,
        "total_weight_tons": total_tonnage,
        "motive_power_distribution": motive_power_dist,
        "car_type_distribution": car_type_dist,
        "longest_consist": longest_consist,
        "heaviest_consist": heaviest_consist,
        "trains": train_summaries,
    }


@app.get("/api/consists/{train_num}")
async def get_train_consist(train_num: str):
    """Retrieve detailed rolling stock consist breakdown and car inventory for a specific train."""
    trains_geo = fetch_live_train_geojson()
    target = train_num.strip().lower()

    matched_props = None
    for feat in trains_geo.get("features", []):
        props = feat.get("properties", {})
        t_num = str(props.get("train_num") or "").lower()
        t_id = str(props.get("id") or "").lower()
        if target in (t_num, t_id) or t_id.endswith(f"_{target}"):
            matched_props = props
            break

    if matched_props:
        t_num = str(matched_props.get("train_num") or train_num)
        route = matched_props.get("route") or matched_props.get("route_name") or ""
        agency = matched_props.get("agency") or "Amtrak"
        speed = float(matched_props.get("speed_mph") or 0.0)
    else:
        t_num = train_num
        route = "Mainline Service"
        agency = "Amtrak"
        speed = 55.0

    consist = synthesize_consist_for_train(t_num, route=route, agency=agency, speed_mph=speed)

    # Attach any active encounter defect report if train is currently passing a camera
    active_encounters = encounter_tracker.get_active_encounters()
    attached_encounter = None
    for enc in active_encounters:
        if str(enc.get("train_num", "")).lower() == target:
            attached_encounter = enc
            break

    return {
        "consist": consist,
        "active_encounter": attached_encounter,
        "defect_report": attached_encounter.get("defect_report") if attached_encounter else None,
        "timestamp": time.time(),
    }


@app.get("/api/defect-detectors/{cam_id}")
async def get_defect_detector_report(cam_id: str):
    """Returns trackside Automated Defect Detector (HBD/DED) radio report for a camera junction."""
    cam = None
    for c in PUBLIC_RAIL_CAMS:
        if c.get("cam_id") == cam_id:
            cam = c
            break

    if not cam:
        raise HTTPException(status_code=404, detail=f"Webcam / junction '{cam_id}' not found.")

    # Check for active encounter on this camera
    active_encounters = encounter_tracker.get_active_encounters()
    matched_enc = None
    for enc in active_encounters:
        if enc.get("camera_id") == cam_id:
            matched_enc = enc
            break

    if matched_enc:
        defect_rep = matched_enc.get("defect_report")
        if not defect_rep:
            defect_rep = generate_defect_report(cam, str(matched_enc.get("train_num", "100")), speed_mph=float(matched_enc.get("peak_speed_mph", 55.0)))
        status = "train_present"
        train_num = matched_enc.get("train_num")
    else:
        # Check recent completed history for this camera
        recent_history = encounter_tracker.get_recent_history(limit=50)
        recent_cam_enc = next((e for e in recent_history if e.get("camera_id") == cam_id), None)
        if recent_cam_enc and recent_cam_enc.get("defect_report"):
            defect_rep = recent_cam_enc["defect_report"]
            status = "recent_inspection"
            train_num = recent_cam_enc.get("train_num")
        else:
            defect_rep = generate_defect_report(cam, "100", speed_mph=54.0)
            status = "nominal_standby"
            train_num = None

    return {
        "cam_id": cam_id,
        "camera_name": cam.get("name", cam_id),
        "milepost": cam.get("milepost", "MP 100.0"),
        "subdivision": cam.get("subdivision", "Mainline Sub"),
        "status": status,
        "train_num": train_num,
        "detector_report": defect_rep,
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)

