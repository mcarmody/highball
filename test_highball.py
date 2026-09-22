"""Test suite for Highball spatial engine, webcam lookup, and API endpoints."""

import os
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


def test_gtfs_rt_parser_stable_id_without_trip_object():
    """Regression test for the 2026-09-21 Metra breadcrumb bug: a real
    GTFS-RT entity with no `trip` object at all (confirmed live in
    Transitland's Metra proxy feed) must key off the persistent
    VehicleDescriptor.id, not the FeedEntity's own opaque per-message
    `id` — using the latter meant a different physical train could land
    on the same identifier every poll, silently merging unrelated
    trains' GPS histories into one nonsensical "breadcrumb trail"."""
    from gtfs_rt_parser import parse_gtfs_rt_vehicle_positions

    # Two separate polls, same entity index (2), two different real vehicles
    # — this is exactly the shape Transitland's Metra proxy returns.
    poll_1 = {
        "header": {"gtfs_realtime_version": "2.0", "timestamp": 1},
        "entity": [{"id": "2", "vehicle": {
            "vehicle": {"id": "8531"},
            "position": {"latitude": 41.5, "longitude": -88.0},
        }}],
    }
    poll_2 = {
        "header": {"gtfs_realtime_version": "2.0", "timestamp": 2},
        "entity": [{"id": "2", "vehicle": {
            "vehicle": {"id": "9042"},
            "position": {"latitude": 42.6, "longitude": -87.8},
        }}],
    }
    id_1 = parse_gtfs_rt_vehicle_positions(poll_1, agency_id="Metra")["features"][0]["properties"]["id"]
    id_2 = parse_gtfs_rt_vehicle_positions(poll_2, agency_id="Metra")["features"][0]["properties"]["id"]
    assert id_1 != id_2, (
        "Two different physical vehicles sharing a GTFS-RT entity index "
        "produced the same identity id — this is the exact bug that "
        "corrupted breadcrumb trails in production."
    )
    assert id_1 == "Metra_8531"
    assert id_2 == "Metra_9042"


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


def test_auto_director_logic():
    from auto_director import select_director_camera, score_encounter
    from cam_lookup import PUBLIC_RAIL_CAMS

    imminent_event = {
        "train": {"train_num": "4", "route": "Southwest Chief", "speed_mph": 60.0},
        "camera": PUBLIC_RAIL_CAMS[4],  # Flagstaff
        "distance_miles": 1.5,
        "trajectory": "approaching",
        "eta_minutes": 1.5,
    }
    score = score_encounter(imminent_event)
    assert score > 200.0

    decision = select_director_camera([imminent_event])
    assert decision["mode"] == "intercept"
    assert decision["camera"]["cam_id"] == "cam_flagstaff_depot"
    assert decision["is_passby"] is False

    # Imminent pass-by event (<1.0 mi)
    passby_event = dict(imminent_event)
    passby_event["distance_miles"] = 0.6
    passby_decision = select_director_camera([passby_event])
    assert passby_decision["mode"] == "intercept"
    assert passby_decision["is_passby"] is True

    # Quiet window falls back to scenic patrol
    empty_decision = select_director_camera([])
    assert empty_decision["mode"] == "scenic_patrol"
    assert empty_decision["is_passby"] is False
    assert "camera" in empty_decision


def test_director_endpoint(client):
    resp = client.get("/api/director")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert "camera" in data
    assert "reason" in data


def test_encounter_tracker_and_history_endpoints(client):
    from encounter_tracker import EncounterTracker

    tracker = EncounterTracker(max_history=10, encounter_radius_miles=5.0)
    t0 = 1726913800.0
    event1 = {
        "train": {"train_num": "4", "route": "Southwest Chief", "speed_mph": 55},
        "camera": {"cam_id": "cam_fullerton_depot", "name": "Fullerton Depot", "location": "Fullerton, CA"},
        "distance_miles": 3.0,
        "trajectory": "approaching",
    }
    tracker.update([event1], timestamp=t0)
    assert len(tracker.get_active_encounters()) == 1

    # Train departs (>5 mi)
    tracker.update([], timestamp=t0 + 180.0)
    assert len(tracker.get_active_encounters()) == 0
    assert len(tracker.get_recent_history()) == 1
    assert tracker.get_recent_history()[0]["status"] == "completed"

    # Query history API endpoint
    resp = client.get("/api/encounters/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp_active = client.get("/api/encounters/active")
    assert resp_active.status_code == 200
    assert isinstance(resp_active.json(), list)


def test_breadcrumbs_endpoint(client):
    from server import update_breadcrumbs

    # Populate sample train breadcrumb trail
    mock_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-104.99, 39.73]},
            "properties": {"id": "test_train_101", "train_num": "101", "speed_mph": 45.0}
        }
    ]
    update_breadcrumbs(mock_features, now=1000.0)
    assert mock_features[0]["properties"]["breadcrumbs"] == [[-104.99, 39.73]]

    # Second point with movement
    mock_features_2 = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-104.95, 39.75]},
            "properties": {"id": "test_train_101", "train_num": "101", "speed_mph": 48.0}
        }
    ]
    update_breadcrumbs(mock_features_2, now=1015.0)
    assert len(mock_features_2[0]["properties"]["breadcrumbs"]) == 2

    # Query /api/breadcrumbs endpoint with train_id filter
    resp = client.get("/api/breadcrumbs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert data["total_trails"] >= 1
    trail = next(f for f in data["features"] if f["properties"]["train_id"] == "test_train_101")
    assert trail["geometry"]["type"] == "LineString"
    assert len(trail["geometry"]["coordinates"]) == 2
    assert trail["properties"]["points_count"] == 2

    # Query with specific train_id filter
    resp_filtered = client.get("/api/breadcrumbs?train_id=test_train_101")
    assert resp_filtered.status_code == 200
    assert resp_filtered.json()["total_trails"] == 1

    resp_nonexistent = client.get("/api/breadcrumbs?train_id=nonexistent_999")
    assert resp_nonexistent.status_code == 200
    assert resp_nonexistent.json()["total_trails"] == 0

    # Test Null Island rejection (coords near 0, 0)
    glitch_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0.001, -0.002]},
            "properties": {"id": "glitch_null_island", "train_num": "000"}
        }
    ]
    update_breadcrumbs(glitch_features, now=1030.0)
    assert "breadcrumbs" not in glitch_features[0]["properties"]

    # Test teleport jump rejection (>2.0 degrees)
    teleport_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-90.0, 35.0]},
            "properties": {"id": "test_train_101", "train_num": "101"}
        }
    ]
    update_breadcrumbs(teleport_features, now=1045.0)
    # The jump from -104.95 to -90.0 should be rejected, preserving history length at 2
    assert len(teleport_features[0]["properties"]["breadcrumbs"]) == 2


def test_index_html_invariants():
    """Verify frontend static contract: essential constants and markers are defined."""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    assert os.path.exists(html_path)
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Regression check: ICON_REST_OFFSET_DEG must be defined to prevent NaN/ReferenceError in createTrainIcon
    assert "const ICON_REST_OFFSET_DEG" in html
    assert "createTrainIcon" in html
    assert "renderTrains" in html

    # Ops Radar mobile architecture invariants
    assert "Ops Radar" in html
    assert "mobile-bottom-sheet" in html
    assert "sheet-encounters-list" in html
    assert "toggleMobileBottomSheet" in html








