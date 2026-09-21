"""Highball GeoJSON Ingestion Worker

Fetches live Amtrak telemetry and outputs clean GeoJSON Point FeatureCollections
ready to mount directly into a Leaflet GeoJSON layer with custom train markers.
"""

import json
import time
import requests


def generate_train_geojson():
    url = "https://api-v3.amtraker.com/v3/trains"
    resp = requests.get(url, timeout=10)
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
                        "coordinates": [float(t["lon"]), float(t["lat"])]
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
                        "updated_at": t.get("updatedAt")
                    }
                }
                features.append(feature)

    return {
        "type": "FeatureCollection",
        "timestamp": time.time(),
        "total_active": len(features),
        "features": features
    }


if __name__ == "__main__":
    geojson = generate_train_geojson()
    print(f"[*] Generated GeoJSON with {geojson['total_active']} active trains.")
    print("Sample feature:", json.dumps(geojson["features"][0], indent=2))
