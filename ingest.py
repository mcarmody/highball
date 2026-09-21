#!/usr/bin/env python3
"""
Highball ingest worker.

Polls the Amtraker unofficial Amtrak API (free, no key required) and
normalizes live train positions into a GeoJSON FeatureCollection the
Leaflet frontend can render directly.

Amtraker docs/source: https://api-v3.amtraker.com/v3/trains
"""
import json
import sys
import time
import urllib.request

AMTRAKER_URL = "https://api-v3.amtraker.com/v3/trains"
USER_AGENT = "highball-ingest/0.1 (+https://github.com/mcarmody/highball)"


def fetch_trains():
    req = urllib.request.Request(AMTRAKER_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def to_geojson(raw):
    """Amtraker returns {trainNum: [instance, ...]}. Flatten to GeoJSON."""
    features = []
    for train_num, instances in raw.items():
        for inst in instances:
            lat, lon = inst.get("lat"), inst.get("lon")
            if lat is None or lon is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "train_num": train_num,
                    "train_id": inst.get("trainID"),
                    "route": inst.get("routeName"),
                    "heading": inst.get("heading"),
                    "velocity": inst.get("velocity"),
                    "status": inst.get("trainTimely"),
                    "origin": (inst.get("stations") or [{}])[0].get("name"),
                    "destination": (inst.get("stations") or [{}])[-1].get("name"),
                    "updated_at": inst.get("lastValTS"),
                },
            })
    return {"type": "FeatureCollection", "features": features}


def main():
    raw = fetch_trains()
    geojson = to_geojson(raw)
    out_path = sys.argv[1] if len(sys.argv) > 1 else "trains.geojson"
    with open(out_path, "w") as f:
        json.dump(geojson, f)
    print(f"Wrote {len(geojson['features'])} live train positions to {out_path} "
          f"at {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
