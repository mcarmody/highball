"""Highball Rail Mainline Corridors GeoJSON Generator.

Defines high-priority US passenger and freight mainline rail corridors connecting
monitored webcam junctions for Leaflet track vector overlays.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

MAJOR_CORRIDORS: List[Dict[str, Any]] = [
    {
        "corridor_id": "corridor_nec",
        "name": "Northeast Corridor (NEC)",
        "operator": "Amtrak / Commuter Shared",
        "subdivision": "Mid-Atlantic & New England Div",
        "coordinates": [
            [-71.0589, 42.3519],  # Boston South Station
            [-71.4189, 41.8240],  # Providence
            [-72.9267, 41.3083],  # New Haven
            [-73.9935, 40.7505],  # New York Penn Station
            [-74.1724, 40.7357],  # Newark Penn
            [-74.7699, 40.2206],  # Trenton
            [-75.1820, 39.9558],  # Philadelphia 30th St
            [-75.5511, 39.7371],  # Wilmington
            [-76.0712, 39.5598],  # Perryville MARC / NEC Cam
            [-76.6169, 39.3072],  # Baltimore Penn Station
            [-77.0063, 38.8974],  # Washington Union Station
        ],
    },
    {
        "corridor_id": "corridor_bnsf_transcon",
        "name": "BNSF Southern Transcon & Southwest Corridor",
        "operator": "BNSF / Amtrak Southwest Chief & Zephyr",
        "subdivision": "Transcon Mainline",
        "coordinates": [
            [-87.6390, 41.8789],  # Chicago Union Station
            [-89.0664, 41.9168],  # Rochelle Double Diamond Cam
            [-90.3664, 40.9431],  # Galesburg Depot Cam
            [-91.3660, 40.3934],  # Fort Madison, IA
            [-94.5857, 39.0850],  # Kansas City Union Station
            [-97.3375, 37.6872],  # Wichita / Newton, KS
            [-101.8313, 35.2220], # Amarillo, TX
            [-106.6504, 35.0844], # Albuquerque, NM
            [-111.6483, 35.1977], # Flagstaff Historic Depot Cam
            [-114.0530, 35.1894], # Kingman, AZ
            [-117.0173, 34.8958], # Barstow Harvey House
            [-117.3117, 34.1083], # San Bernardino Depot
            [-117.9228, 33.8687], # Fullerton Depot Cam
            [-118.2365, 34.0562], # Los Angeles Union Station
        ],
    },
    {
        "corridor_id": "corridor_pittsburgh_line",
        "name": "NS Pittsburgh Line / Keystone Corridor",
        "operator": "Norfolk Southern / Amtrak Pennsylvanian",
        "subdivision": "NS Pittsburgh Division",
        "coordinates": [
            [-75.1820, 39.9558],  # Philadelphia 30th St
            [-76.3055, 40.0379],  # Lancaster
            [-76.8867, 40.2625],  # Harrisburg
            [-77.8600, 40.5934],  # Lewistown
            [-78.4011, 40.5187],  # Altoona Station
            [-78.4842, 40.4965],  # Horseshoe Curve Cam
            [-78.9225, 40.3267],  # Johnstown
            [-79.9959, 40.4406],  # Pittsburgh Union Station
        ],
    },
    {
        "corridor_id": "corridor_tehachapi",
        "name": "UP Mojave Subdivision (Tehachapi Pass)",
        "operator": "Union Pacific / BNSF Trackage Rights",
        "subdivision": "UP Mojave Sub",
        "coordinates": [
            [-119.0187, 35.3733], # Bakersfield
            [-118.6312, 35.2925], # Caliente
            [-118.5367, 35.2008], # Tehachapi Loop (Walong) Cam
            [-118.4489, 35.1322], # Tehachapi Summit
            [-118.1737, 35.0525], # Mojave Yard
        ],
    },
]


BASE_DIR = Path(__file__).resolve().parent


def generate_corridors_geojson(out_path: Optional[str] = None) -> Dict[str, Any]:
    """Generates GeoJSON FeatureCollection with LineString features for rail corridors."""
    if out_path is None:
        out_path = str(BASE_DIR / "corridors.geojson")
    features = []
    for corr in MAJOR_CORRIDORS:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": corr["coordinates"],
            },
            "properties": {
                "corridor_id": corr["corridor_id"],
                "name": corr["name"],
                "operator": corr["operator"],
                "subdivision": corr["subdivision"],
                "waypoints": len(corr["coordinates"]),
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "total_corridors": len(features),
        "features": features,
    }

    if out_path:
        with open(out_path, "w") as f:
            json.dump(geojson, f, indent=2)
        print(f"[*] Exported {len(features)} corridors to {out_path}")

    return geojson


if __name__ == "__main__":
    generate_corridors_geojson()
