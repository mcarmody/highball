"""FastAPI Server & Spatial Proximity Engine for Project Highball.

Provides:
- GET /: Highball Dark Leaflet Live Ops Map
- GET /api/trains: Live Amtrak train GeoJSON (cached 15s to respect upstream API)
- GET /api/cams: Curated railfan webcam GeoJSON
- GET /api/proximity: Live calculation of trains within proximity of webcams with trajectory and station stops
- GET /health: Telemetry and upstream status
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cam_lookup import (
    PUBLIC_RAIL_CAMS,
    calculate_trajectory_status,
    find_nearby_cameras,
    haversine_miles,
    parse_heading_degrees,
)
from encounter_tracker import EncounterTracker
from gtfs_rt_parser import parse_gtfs_rt_vehicle_positions, parse_mbta_v3_vehicles

BASE_DIR = Path(__file__).parent
INDEX_HTML = BASE_DIR / "index.html"
WEBCAMS_GEOJSON = BASE_DIR / "webcams.geojson"
CORRIDORS_GEOJSON = BASE_DIR / "corridors.geojson"

MBTA_API_KEY = os.getenv("MBTA_API_KEY", "ec4a5e0d15184cd3b22ff1b02a4f534f")
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

# Cache for upstream transit data to avoid hitting rate limits
_train_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "geojson": None,
}
CACHE_TTL_SECONDS = 15.0


def fetch_live_train_geojson() -> Dict[str, Any]:
    """Fetches live trains from Amtraker v3 API, MBTA, and Caltrain (511 SF Bay)."""
    now = time.time()
    if _train_cache["geojson"] and (now - _train_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _train_cache["geojson"]

    features = []

    # 1. Amtrak National Telemetry
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
                                # Amtraker returns a compass string ("NW", "SE"), not
                                # degrees — normalize here so every consumer (map arrows,
                                # cam-jump trajectory math) gets a clean float or None.
                                # Confirmed live 2026-09-21: the raw string reaching the
                                # frontend's `heading - 45` arrow-rotation math produced
                                # rotate(NaNdeg) on every single Amtrak train (37% of
                                # all trains on the map) — arrows never worked at all
                                # for Amtrak despite the icon-offset fix being correct.
                                "heading": parse_heading_degrees(t.get("heading")),
                                "timely": t.get("trainTimely"),
                                "status": t.get("statusMsg"),
                                "origin": t.get("origName"),
                                "dest": t.get("destName"),
                                "updated_at": t.get("updatedAt"),
                                "next_station": next_station,
                                "agency": "Amtrak",
                            },
                        })
    except Exception as exc:
        print(f"[Highball] Amtraker fetch warning: {exc}")

    # 2. MBTA Commuter Rail (Boston / Northeast Corridor)
    if MBTA_API_KEY:
        try:
            mbta_url = f"https://api-v3.mbta.com/vehicles?filter[route_type]=2&include=route&api_key={MBTA_API_KEY}"
            resp = requests.get(mbta_url, timeout=5.0)
            if resp.status_code == 200:
                mbta_geojson = parse_mbta_v3_vehicles(resp.json())
                features.extend(mbta_geojson.get("features", []))
        except Exception as exc:
            print(f"[Highball] MBTA fetch warning: {exc}")

    # 3. Caltrain Commuter Rail (511 SF Bay Area)
    if SF_511_API_KEY:
        try:
            sf_url = f"http://api.511.org/transit/vehiclepositions?api_key={SF_511_API_KEY}&agency=CT&format=json"
            resp = requests.get(sf_url, timeout=5.0)
            if resp.status_code == 200:
                sf_data = json.loads(resp.content.decode("utf-8-sig"))
                caltrain_geojson = parse_gtfs_rt_vehicle_positions(sf_data, agency_id="Caltrain")
                features.extend(caltrain_geojson.get("features", []))
        except Exception as exc:
            print(f"[Highball] 511 Caltrain fetch warning: {exc}")

    # 4. Chicago Metra Commuter Rail (via Transitland's GTFS-RT JSON proxy)
    # Onestop ID verified live 2026-09-21 — f-metra~rt is metrarr.com
    # (Chicago Metra). Do NOT confuse with f-metra~ga~rt, a same-named but
    # unrelated Columbus, Georgia transit agency that also matches "metra".
    if TRANSITLAND_API_KEY:
        try:
            metra_url = (
                "https://transit.land/api/v2/rest/feeds/f-metra~rt/"
                f"download_latest_rt/vehicle_positions.json?apikey={TRANSITLAND_API_KEY}"
            )
            resp = requests.get(metra_url, timeout=5.0)
            if resp.status_code == 200:
                metra_geojson = parse_gtfs_rt_vehicle_positions(resp.json(), agency_id="Metra")
                features.extend(metra_geojson.get("features", []))
        except Exception as exc:
            print(f"[Highball] Metra (Transitland) fetch warning: {exc}")

    # 5. Sound Transit Link Light Rail / Sounder (via Transitland's proxy)
    # Onestop ID verified live 2026-09-21 — f-soundtransit~rt, backed by
    # Puget Sound's OneBusAway GTFS-RT feed.
    if TRANSITLAND_API_KEY:
        try:
            st_url = (
                "https://transit.land/api/v2/rest/feeds/f-soundtransit~rt/"
                f"download_latest_rt/vehicle_positions.json?apikey={TRANSITLAND_API_KEY}"
            )
            resp = requests.get(st_url, timeout=5.0)
            if resp.status_code == 200:
                st_geojson = parse_gtfs_rt_vehicle_positions(resp.json(), agency_id="Sound Transit")
                features.extend(st_geojson.get("features", []))
        except Exception as exc:
            print(f"[Highball] Sound Transit (Transitland) fetch warning: {exc}")

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
    return geojson


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
    }


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



@app.get("/api/trains")
async def get_trains(agency: Optional[str] = Query(default=None)):
    """Returns live GeoJSON FeatureCollection of active trains, optionally filtered by agency."""
    geojson = fetch_live_train_geojson()
    if not agency or agency.lower() == "all":
        return geojson

    filtered = [f for f in geojson.get("features", []) if f["properties"].get("agency", "").lower() == agency.lower()]
    return {
        "type": "FeatureCollection",
        "timestamp": geojson.get("timestamp"),
        "total_active": len(filtered),
        "features": filtered,
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
        coords = feature["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]
        props = feature["properties"]

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
                        "stream_url": cam.get("stream_url", ""),
                        "embed_url": cam.get("embed_url", ""),
                    },
                    "distance_miles": round(dist, 2),
                    "trajectory": traj_status,
                    "bearing_to_cam": bearing_cam,
                    "eta_minutes": eta_minutes,
                })

    proximity_matches.sort(key=lambda x: x["distance_miles"])
    encounter_tracker.update(proximity_matches)
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


@app.get("/api/director")
async def get_director():
    """Returns Auto-Director's recommended camera to watch right now based on active encounters."""
    prox = await get_proximity_events(max_miles=15.0)
    events = prox.get("events", [])
    from auto_director import select_director_camera
    return select_director_camera(events)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)

