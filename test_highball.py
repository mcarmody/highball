"""Test suite for Highball spatial engine, webcam lookup, and API endpoints."""

import pytest
from fastapi.testclient import TestClient

from cam_lookup import PUBLIC_RAIL_CAMS, find_nearby_cameras, haversine_miles
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


def test_find_nearby_cameras():
    # Coordinate right next to Horseshoe Curve
    hc_lat, hc_lon = 40.4965, -78.4842
    matches = find_nearby_cameras(hc_lat, hc_lon, max_miles=5.0)
    assert len(matches) >= 1
    assert matches[0]["cam_id"] == "cam_horseshoe_curve"
    assert matches[0]["distance_miles"] < 0.1


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


def test_proximity_endpoint_structure(client):
    # Proximity endpoint returns structured events even if no trains are within threshold
    resp = client.get("/api/proximity?max_miles=5.0")
    assert resp.status_code in [200, 502]
    if resp.status_code == 200:
        data = resp.json()
        assert "events" in data
        assert "total_matches" in data
        assert data["max_miles_threshold"] == 5.0
