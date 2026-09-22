"""Highball Railfan Webcam Spatial Indexer & Proximity Engine.

Indexes high-traffic public, municipal, and state DOT rail webcams
and calculates spatial proximity and directional trajectory to active train GPS telemetry.
Generates webcams.geojson for Leaflet dark canvas overlay.
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent

# Curated registry of verified, high-uptime public railfan webcams
PUBLIC_RAIL_CAMS = [
    {
        "cam_id": "cam_horseshoe_curve",
        "name": "Horseshoe Curve (Railroaders Memorial Museum)",
        "location": "Altoona, PA",
        "route": "Pennsylvanian",
        "subdivision": "NS Pittsburgh Line",
        "milepost": "MP 242.0",
        "lat": 40.4965,
        "lon": -78.4842,
        "provider": "Railroaders Memorial Museum / Virtual Railfan",
        "stream_url": "https://www.youtube.com/watch?v=ssuM6NJQ2no",
        "embed_url": "https://www.youtube-nocookie.com/embed/ssuM6NJQ2no?autoplay=1&mute=1",
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
        "provider": "Tehachapi Live Train Cams",
        "stream_url": "https://www.youtube.com/watch?v=COO-fe-r0nw",
        "embed_url": "https://www.youtube-nocookie.com/embed/COO-fe-r0nw?autoplay=1&mute=1",
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
        "provider": "City of Rochelle / Virtual Railfan",
        "stream_url": "https://www.youtube.com/watch?v=LhNpn9L5ndM",
        "embed_url": "https://www.youtube-nocookie.com/embed/LhNpn9L5ndM?autoplay=1&mute=1",
    },
    {
        "cam_id": "cam_fullerton_depot",
        "name": "Fullerton Historic Depot",
        "location": "Fullerton, CA",
        "route": "Pacific Surfliner / Southwest Chief",
        "subdivision": "BNSF San Bernardino Sub",
        "milepost": "MP 165.2",
        "lat": 33.8687,
        "lon": -117.9228,
        "provider": "RailStream / City of Fullerton",
        "stream_url": "https://www.youtube.com/watch?v=bzqVcwY04GA",
        "embed_url": "https://www.youtube-nocookie.com/embed/bzqVcwY04GA?autoplay=1&mute=1",
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
        "provider": "Virtual Railfan / City of Flagstaff",
        "stream_url": "https://www.youtube.com/watch?v=7xdHH9KMSVk",
        "embed_url": "https://www.youtube-nocookie.com/embed/7xdHH9KMSVk?autoplay=1&mute=1",
    },
    {
        "cam_id": "cam_galesburg_depot",
        "name": "Galesburg Railroad Museum Depot",
        "location": "Galesburg, IL",
        "route": "California Zephyr / Southwest Chief / Carl Sandburg",
        "subdivision": "BNSF Chillicothe / Mendota Sub",
        "milepost": "MP 162.0",
        "lat": 40.9431,
        "lon": -90.3664,
        "provider": "Virtual Railfan / Galesburg Railroad Museum",
        "stream_url": "https://www.youtube.com/watch?v=On1MRt0NqFs",
        "embed_url": "https://www.youtube-nocookie.com/embed/On1MRt0NqFs?autoplay=1&mute=1",
    },
    {
        "cam_id": "cam_east_greenwich",
        "name": "East Greenwich Depot (Amtrak NEC Mainline)",
        "location": "East Greenwich, RI",
        "route": "Acela / Northeast Regional",
        "subdivision": "Amtrak NEC",
        "milepost": "MP 168.0",
        "lat": 41.6608,
        "lon": -71.4988,
        "provider": "Railside Live / Amtrak NEC",
        "stream_url": "https://www.youtube.com/watch?v=sFCofJMI4ew",
        "embed_url": "https://www.youtube-nocookie.com/embed/sFCofJMI4ew?autoplay=1&mute=1",
    },
    {
        "cam_id": "cam_ashland_depot",
        "name": "Ashland Historic Station (Center Street)",
        "location": "Ashland, VA",
        "route": "Northeast Regional / Silver Meteor / Auto Train",
        "subdivision": "CSX RF&P Sub",
        "milepost": "MP 14.8",
        "lat": 37.7590,
        "lon": -77.4800,
        "provider": "Virtual Railfan",
        "stream_url": "https://www.youtube.com/watch?v=_Kk5anP-dQg",
        "embed_url": "https://www.youtube-nocookie.com/embed/_Kk5anP-dQg?autoplay=1&mute=1",
    },
    {
        "cam_id": "cam_folkston_funnel",
        "name": "Folkston Funnel Rail Viewing Platform",
        "location": "Folkston, GA",
        "route": "Silver Meteor / Silver Star / Floridian",
        "subdivision": "CSX Nahunta Sub",
        "milepost": "MP 602.0",
        "lat": 30.8327,
        "lon": -81.9772,
        "provider": "Virtual Railfan",
        "stream_url": "https://www.youtube.com/watch?v=FHYqepozgiQ",
        "embed_url": "https://www.youtube-nocookie.com/embed/FHYqepozgiQ?autoplay=1&mute=1",
    },
    {
        "cam_id": "cam_seattle_king_st",
        "name": "Seattle King Street Station",
        "location": "Seattle, WA",
        "route": "Amtrak Cascades / Coast Starlight / Empire Builder",
        "subdivision": "BNSF Seattle Sub",
        "milepost": "MP 0.0",
        "lat": 47.5985,
        "lon": -122.3297,
        "provider": "Virtual Railfan",
        "stream_url": "https://www.youtube.com/watch?v=pHqTDmH7H7c",
        "embed_url": "https://www.youtube-nocookie.com/embed/pHqTDmH7H7c?autoplay=1&mute=1",
    },
]

CAM_ALIASES = {
    "cam_chesapeake_city": "cam_east_greenwich",
}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great circle distance in miles between two coordinates."""
    r = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates initial compass bearing in degrees (0-360) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)

    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


COMPASS_POINTS = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}


def parse_heading_degrees(heading: Any) -> Optional[float]:
    """Normalizes heading to float degrees (0-360), handling compass strings like 'N' or 'SW'."""
    if heading is None:
        return None
    if isinstance(heading, (int, float)):
        return float(heading) % 360.0
    if isinstance(heading, str):
        h = heading.strip().upper()
        if h in COMPASS_POINTS:
            return COMPASS_POINTS[h]
        try:
            return float(h) % 360.0
        except ValueError:
            return None
    return None


def calculate_trajectory_status(
    train_lat: float,
    train_lon: float,
    train_heading: Any,
    cam_lat: float,
    cam_lon: float,
) -> Tuple[str, float]:
    """Determines if the train is approaching, receding, or passing the camera.

    Returns (trajectory_status, bearing_to_cam).
    - approaching: heading vector is within 60 degrees of camera bearing
    - receding: heading vector is >= 120 degrees away from camera bearing
    - passing: lateral/transverse angle (60-120 degrees)
    """
    bearing_to_cam = calculate_bearing(train_lat, train_lon, cam_lat, cam_lon)
    heading_deg = parse_heading_degrees(train_heading)
    if heading_deg is None:
        return "unknown", round(bearing_to_cam, 1)

    diff = abs((heading_deg - bearing_to_cam + 180.0) % 360.0 - 180.0)

    if diff <= 60.0:
        status = "approaching"
    elif diff >= 120.0:
        status = "receding"
    else:
        status = "passing"

    return status, round(bearing_to_cam, 1)


def find_nearby_cameras(
    train_lat: float,
    train_lon: float,
    train_heading: Optional[float] = None,
    max_miles: float = 10.0,
) -> List[Dict]:
    """Finds all registered rail cameras within max_miles of a train coordinate with trajectory."""
    nearby = []
    for cam in PUBLIC_RAIL_CAMS:
        dist = haversine_miles(train_lat, train_lon, cam["lat"], cam["lon"])
        if dist <= max_miles:
            cam_copy = dict(cam)
            cam_copy["distance_miles"] = round(dist, 2)
            status, bearing_cam = calculate_trajectory_status(
                train_lat, train_lon, train_heading, cam["lat"], cam["lon"]
            )
            cam_copy["trajectory"] = status
            cam_copy["bearing_to_cam"] = bearing_cam
            nearby.append(cam_copy)
    nearby.sort(key=lambda x: x["distance_miles"])
    return nearby


def export_webcams_geojson(out_path: Optional[str] = None):
    """Exports cameras as GeoJSON Point FeatureCollection for Leaflet."""
    if out_path is None:
        out_path = str(BASE_DIR / "webcams.geojson")
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
                "subdivision": cam["subdivision"],
                "milepost": cam["milepost"],
                "provider": cam["provider"],
                "stream_url": cam.get("stream_url", ""),
                "embed_url": cam.get("embed_url", ""),
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
    sample_lat, sample_lon, heading = 33.85, -117.92, 355.0  # Approaching Fullerton from South
    matches = find_nearby_cameras(sample_lat, sample_lon, train_heading=heading, max_miles=5.0)
    print(f"[*] Found {len(matches)} cam(s) near sample point:")
    for m in matches:
        print(f"  - {m['name']} ({m['distance_miles']} mi away) -> Status: {m['trajectory'].upper()}")
