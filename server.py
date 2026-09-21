"""FastAPI Server & Spatial Proximity Engine for Project Highball.

Provides:
- GET /: Highball Dark Leaflet Live Ops Map
- GET /api/trains: Live Amtrak train GeoJSON (cached 15s to respect upstream API)
- GET /api/cams: Curated railfan webcam GeoJSON
- GET /api/proximity: Live calculation of trains within proximity of webcams (<15 miles)
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

from cam_lookup import PUBLIC_RAIL_CAMS, find_nearby_cameras, haversine_miles

BASE_DIR = Path(__file__).parent
INDEX_HTML = BASE_DIR / "index.html"
WEBCAMS_GEOJSON = BASE_DIR / "webcams.geojson"

app = FastAPI(
    title="Highball Railfan Transit & Webcam Engine",
    description="Spatial telemetry engine correlating live Amtrak trains with public railfan webcams",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache for Amtraker upstream data to avoid hitting rate limits
_train_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "geojson": None,
}
CACHE_TTL_SECONDS = 15.0


def fetch_live_train_geojson() -> Dict[str, Any]:
    """Fetches live trains from Amtraker v3 API or returns cached copy."""
    now = time.time()
    if _train_cache["geojson"] and (now - _train_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _train_cache["geojson"]

    url = "https://api-v3.amtraker.com/v3/trains"
    try:
        resp = requests.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()

        features = []
        for train_id, instances in data.items():
            for t in instances:
                if t.get("trainState") == "Active" and t.get("lat") and t.get("lon"):
                    feature = {
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
                            "heading": t.get("heading"),
                            "timely": t.get("trainTimely"),
                            "status": t.get("statusMsg"),
                            "origin": t.get("origName"),
                            "dest": t.get("destName"),
                            "updated_at": t.get("updatedAt"),
                        },
                    }
                    features.append(feature)

        geojson = {
            "type": "FeatureCollection",
            "timestamp": now,
            "total_active": len(features),
            "features": features,
        }
        _train_cache["timestamp"] = now
        _train_cache["geojson"] = geojson
        return geojson
    except Exception as exc:
        if _train_cache["geojson"]:
            return _train_cache["geojson"]
        raise HTTPException(status_code=502, detail=f"Amtraker upstream error: {exc}")


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


@app.get("/api/trains")
async def get_trains():
    """Returns live GeoJSON FeatureCollection of active Amtrak trains."""
    return fetch_live_train_geojson()


@app.get("/api/proximity")
async def get_proximity_events(max_miles: float = Query(default=15.0, ge=1.0, le=50.0)):
    """Correlates active trains with webcams and returns proximity events sorted by distance."""
    trains_geo = fetch_live_train_geojson()
    proximity_matches = []

    for feature in trains_geo.get("features", []):
        coords = feature["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]
        props = feature["properties"]

        for cam in PUBLIC_RAIL_CAMS:
            dist = haversine_miles(lat, lon, cam["lat"], cam["lon"])
            if dist <= max_miles:
                proximity_matches.append({
                    "train": {
                        "train_num": props["train_num"],
                        "route": props["route"],
                        "speed_mph": props["speed_mph"],
                        "heading": props["heading"],
                        "dest": props["dest"],
                    },
                    "camera": {
                        "cam_id": cam["cam_id"],
                        "name": cam["name"],
                        "location": cam["location"],
                        "milepost": cam["milepost"],
                        "provider": cam["provider"],
                        "youtube_live_id": cam["youtube_live_id"],
                        "embed_url": f"https://www.youtube.com/embed/{cam['youtube_live_id']}?autoplay=1",
                    },
                    "distance_miles": round(dist, 2),
                    "eta_minutes": round((dist / max(props["speed_mph"], 1.0)) * 60, 1) if props["speed_mph"] > 5 else None,
                })

    proximity_matches.sort(key=lambda x: x["distance_miles"])
    return {
        "timestamp": time.time(),
        "total_matches": len(proximity_matches),
        "max_miles_threshold": max_miles,
        "events": proximity_matches,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)
