"""Test suite for Highball spatial engine, webcam lookup, and API endpoints."""

import pytest
from fastapi.testclient import TestClient

from cam_lookup import (
    PUBLIC_RAIL_CAMS,
    calculate_bearing,
    calculate_trajectory_status,
    find_nearby_cameras,
    haversine_miles,
)
from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_haversine_distance():
    # Fullerton Depot to near Fullerton (~0.5 miles)
    fullerton_lat, fullerton_lon = 33.8687, -117.9228
    nearby_lat, nearby_lon = 33.875, -117.925
    dist = haversine_miles(fullerton_lat, fullerton_lon, nearby_lat, nearby_lon)
    assert 0.4 < dist < 0.6


def test_bearing_and_trajectory():
    # Point A due South of Point B (Bearing should be ~0 deg North)
    p_south_lat, p_south_lon = 33.0, -117.0
    p_north_lat, p_north_lon = 34.0, -117.0
    bearing = calculate_bearing(p_south_lat, p_south_lon, p_north_lat, p_north_lon)
    assert -1.0 <= bearing <= 1.0 or 359.0 <= bearing <= 360.0

    # Approaching case: heading north (5 deg) towards camera due north
    status, b = calculate_trajectory_status(p_south_lat, p_south_lon, 5.0, p_north_lat, p_north_lon)
    assert status == "approaching"

    # Receding case: heading south (180 deg) away from camera due north
    status, b = calculate_trajectory_status(p_south_lat, p_south_lon, 180.0, p_north_lat, p_north_lon)
    assert status == "receding"

    # Passing case: heading east (90 deg) transverse to camera
    status, b = calculate_trajectory_status(p_south_lat, p_south_lon, 90.0, p_north_lat, p_north_lon)
    assert status == "passing"


def test_find_nearby_cameras():
    # Coordinate right next to Horseshoe Curve
    hc_lat, hc_lon = 40.4965, -78.4842
    matches = find_nearby_cameras(hc_lat, hc_lon, train_heading=90.0, max_miles=5.0)
    assert len(matches) >= 1
    assert matches[0]["cam_id"] == "cam_horseshoe_curve"
    assert matches[0]["distance_miles"] < 0.1
    assert "trajectory" in matches[0]


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert data["service"] == "highball-spatial-engine"
    assert data["active_cams"] == len(PUBLIC_RAIL_CAMS)


def test_webcams_endpoint(client):
    resp = client.get("/api/cams")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 7


def test_root_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Project Highball" in resp.text


def test_proximity_endpoint_structure_and_filter(client):
    resp = client.get("/api/proximity?max_miles=5.0&trajectory=approaching")
    assert resp.status_code in [200, 502]
    if resp.status_code == 200:
        data = resp.json()
        assert "events" in data
        assert "total_matches" in data
        assert data["max_miles_threshold"] == 5.0
        assert data["filter_trajectory"] == "approaching"
        for ev in data["events"]:
            assert ev["trajectory"] == "approaching"


def test_gtfs_rt_parser():
    from gtfs_rt_parser import parse_gtfs_rt_vehicle_positions
    sample_feed = {
        "header": {"gtfs_realtime_version": "2.0", "timestamp": 1726913800},
        "entity": [
            {
                "id": "train_99",
                "vehicle": {
                    "trip": {"trip_id": "CR-Fitchburg-99", "route_id": "CR-Fitchburg"},
                    "position": {"latitude": 42.5, "longitude": -71.8, "bearing": 90.0, "speed": 20.0},
                    "current_status": "IN_TRANSIT_TO",
                },
            }
        ],
    }
    geojson = parse_gtfs_rt_vehicle_positions(sample_feed, agency_id="MBTA")
    assert geojson["type"] == "FeatureCollection"
    assert geojson["total_active"] == 1
    feat = geojson["features"][0]
    assert feat["geometry"]["coordinates"] == [-71.8, 42.5]
    assert feat["properties"]["agency"] == "MBTA"
    assert feat["properties"]["speed_mph"] > 40.0
    assert feat["properties"]["heading"] == 90.0


def test_get_trains_agency_filter(client):
    resp = client.get("/api/trains?agency=Amtrak")
    assert resp.status_code in [200, 502]
    if resp.status_code == 200:
        data = resp.json()
        assert "features" in data
        for f in data["features"]:
            assert f["properties"]["agency"] == "Amtrak"


def test_corridors_endpoint(client):
    resp = client.get("/api/corridors")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert data["total_corridors"] >= 4
    nec = next(f for f in data["features"] if f["properties"]["corridor_id"] == "corridor_nec")
    assert nec["geometry"]["type"] == "LineString"
    assert len(nec["geometry"]["coordinates"]) >= 5



