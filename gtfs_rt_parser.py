"""Highball GTFS-RT (General Transit Feed Specification Realtime) Ingestion Worker.

Normalizes GTFS-RT VehiclePositions feeds (MBTA, Metra, Caltrain, Transitland)
into Highball's standardized GeoJSON Point FeatureCollection format.
Enables expanding Highball beyond Amtrak to regional commuter and passenger rail.
"""

import time
from typing import Any, Dict, List, Optional


def parse_gtfs_rt_vehicle_positions(feed_data: Dict[str, Any], agency_id: str = "MBTA") -> Dict[str, Any]:
    """Parses a GTFS-RT VehiclePositions feed (JSON format) into Highball GeoJSON.

    Standard GTFS-RT JSON format follows:
    {
      "header": { "gtfs_realtime_version": "2.0", "timestamp": 1726913800 },
      "entity": [
        {
          "id": "vehicle_101",
          "vehicle": {
            "trip": { "trip_id": "CR-Fitchburg-101", "route_id": "CR-Fitchburg" },
            "position": { "latitude": 42.3601, "longitude": -71.0589, "bearing": 285.0, "speed": 18.5 },
            "current_status": "IN_TRANSIT_TO",
            "stop_id": "place-FR-0045",
            "timestamp": 1726913795
          }
        }
      ]
    }
    """
    entities = feed_data.get("entity", [])
    features = []

    for ent in entities:
        v = ent.get("vehicle")
        if not v:
            continue

        pos = v.get("position", {})
        lat = pos.get("latitude")
        lon = pos.get("longitude")

        if lat is None or lon is None:
            continue

        trip = v.get("trip", {})
        trip_id = trip.get("trip_id", ent.get("id"))
        route_id = trip.get("route_id", "Regional Rail")
        speed_mps = pos.get("speed", 0.0)  # meters per second in GTFS-RT spec
        speed_mph = round(speed_mps * 2.23694, 1) if speed_mps is not None else 0.0
        bearing = pos.get("bearing")
        status = v.get("current_status", "IN_TRANSIT_TO").replace("_", " ").title()

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(lon), float(lat)],
            },
            "properties": {
                "id": f"{agency_id}_{trip_id}",
                "train_num": trip_id,
                "route": f"{agency_id} {route_id}",
                "agency": agency_id,
                "speed_mph": speed_mph,
                "heading": bearing,
                "timely": "On Time",
                "status": status,
                "origin": "Terminal",
                "dest": "Outbound",
                "updated_at": v.get("timestamp"),
            },
        })

    return {
        "type": "FeatureCollection",
        "timestamp": time.time(),
        "agency": agency_id,
        "total_active": len(features),
        "features": features,
    }


if __name__ == "__main__":
    sample_feed = {
        "header": {"gtfs_realtime_version": "2.0", "timestamp": int(time.time())},
        "entity": [
            {
                "id": "CR-104",
                "vehicle": {
                    "trip": {"trip_id": "104", "route_id": "Providence/Stoughton"},
                    "position": {"latitude": 42.352, "longitude": -71.055, "bearing": 210.0, "speed": 22.3},
                    "current_status": "IN_TRANSIT_TO",
                },
            }
        ],
    }
    res = parse_gtfs_rt_vehicle_positions(sample_feed, agency_id="MBTA")
    print(f"[*] Normalized {res['total_active']} vehicles from GTFS-RT feed:")
    for feat in res["features"]:
        print(f"  - {feat['properties']['route']} (#{feat['properties']['train_num']}): {feat['properties']['speed_mph']} mph heading {feat['properties']['heading']} deg")
