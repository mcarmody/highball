"""Highball Railfan Webcam Spatial Indexer & Proximity Engine.

Indexes high-traffic public rail webcams (Virtual Railfan, YouTube Live, RailStream)
and calculates spatial proximity to active train GPS telemetry.
Generates webcams.geojson for Leaflet dark canvas overlay.
"""

import json
import math
from typing import Dict, List, Optional, Tuple

# Curated registry of verified, high-uptime public railfan webcams
PUBLIC_RAIL_CAMS = [
    {
        "cam_id": "cam_horseshoe_curve",
        "name": "Horseshoe Curve (Kittanning Point)",
        "location": "Altoona, PA",
        "route": "Pennsylvanian",
        "subdivision": "NS Pittsburgh Line",
        "milepost": "MP 242.0",
        "lat": 40.4965,
        "lon": -78.4842,
        "youtube_live_id": "8G4RkIeL2Uo",
        "provider": "Virtual Railfan",
    },
    {
        "cam_id": "cam_tehachapi_loop",
        "name": "Tehachapi Loop (Walong)",
        "location": "Tehachapi, CA",
        "route": "San Joaquins (Bus/Freight Interconnect)",
        "subdivision": "UP Mojave Sub",
        "milepost": "MP 351.6",
        "lat": 35.2008,
        "lon": -118.5367,
        "youtube_live_id": "cK18H93lJmQ",
        "provider": "RailStream",
    },
    {
        "cam_id": "cam_rochelle_diamond",
        "name": "Rochelle Railroad Park (Double Diamond)",
        "location": "Rochelle, IL",
        "route": "Illinois Zephyr / Southwest Chief corridor",
        "subdivision": "UP Geneva Sub / BNSF Aurora Sub",
        "milepost": "MP 75.2",
        "lat": 41.9168,
        "lon": -89.0664,
        "youtube_live_id": "rX_5N6W6_1c",
        "provider": "City of Rochelle",
    },
    {
        "cam_id": "cam_fullerton_depot",
        "name": "Fullerton Depot",
        "location": "Fullerton, CA",
        "route": "Pacific Surfliner / Southwest Chief",
        "subdivision": "BNSF San Bernardino Sub",
        "milepost": "MP 165.2",
        "lat": 33.8687,
        "lon": -117.9228,
        "youtube_live_id": "qQ1j0l9Z-wM",
        "provider": "Virtual Railfan",
    },
    {
        "cam_id": "cam_flagstaff_depot",
        "name": "Flagstaff Historic Depot",
        "location": "Flagstaff, AZ",
        "route": "Southwest Chief",
        "subdivision": "BNSF Seligman Sub",
        "milepost": "MP 344.0",
        "lat": 35.1977,
        "lon": -111.6483,
        "youtube_live_id": "F9jW7q1Z8m0",
        "provider": "Virtual Railfan",
    },
    {
        "cam_id": "cam_galesburg_depot",
        "name": "Galesburg Depot",
        "location": "Galesburg, IL",
        "route": "California Zephyr / Southwest Chief / Carl Sandburg",
        "subdivision": "BNSF Chillicothe / Mendota Sub",
        "milepost": "MP 162.0",
        "lat": 40.9431,
        "lon": -90.3664,
        "youtube_live_id": "Jk7P0mX-L4w",
        "provider": "Virtual Railfan",
    },
    {
        "cam_id": "cam_chesapeake_city",
        "name": "Perryville MARC / Northeast Corridor",
        "location": "Perryville, MD",
        "route": "Northeast Regional / Acela",
        "subdivision": "Amtrak Mid-Atlantic Division",
        "milepost": "MP 60.1",
        "lat": 39.5598,
        "lon": -76.0712,
        "youtube_live_id": "Pz7M9kQ2L1o",
        "provider": "Virtual Railfan",
    },
]


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great circle distance in miles between two coordinates."""
    r = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def find_nearby_cameras(train_lat: float, train_lon: float, max_miles: float = 10.0) -> List[Dict]:
    """Finds all registered rail cameras within max_miles of a train coordinate."""
    nearby = []
    for cam in PUBLIC_RAIL_CAMS:
        dist = haversine_miles(train_lat, train_lon, cam["lat"], cam["lon"])
        if dist <= max_miles:
            cam_copy = dict(cam)
            cam_copy["distance_miles"] = round(dist, 2)
            nearby.append(cam_copy)
    nearby.sort(key=lambda x: x["distance_miles"])
    return nearby


def export_webcams_geojson(out_path: str = "/workspace/scratch/highball/webcams.geojson"):
    """Exports cameras as GeoJSON Point FeatureCollection for Leaflet."""
    features = []
    for cam in PUBLIC_RAIL_CAMS:
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [cam["lon"], cam["lat"]],
            },
            "properties": {
                "cam_id": cam["cam_id"],
                "name": cam["name"],
                "location": cam["location"],
                "route": cam["route"],
                "milepost": cam["milepost"],
                "provider": cam["provider"],
                "embed_url": f"https://www.youtube.com/embed/{cam['youtube_live_id']}?autoplay=1",
            },
        }
        features.append(feature)

    data = {
        "type": "FeatureCollection",
        "total_cams": len(features),
        "features": features,
    }

    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[*] Exported {len(features)} webcams to {out_path}")


if __name__ == "__main__":
    export_webcams_geojson()
    # Test proximity with a coordinate near Fullerton, CA
    sample_lat, sample_lon = 33.875, -117.925
    matches = find_nearby_cameras(sample_lat, sample_lon, max_miles=5.0)
    print(f"[*] Found {len(matches)} cam(s) near ({sample_lat}, {sample_lon}):")
    for m in matches:
        print(f"  - {m['name']} ({m['distance_miles']} mi away) -> {m['milepost']}")
