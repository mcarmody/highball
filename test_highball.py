"""Test suite for Highball spatial engine, webcam lookup, and API endpoints."""

import os
import time
from collections import deque
import pytest
from fastapi.testclient import TestClient

from cam_lookup import (
    PUBLIC_RAIL_CAMS,
    calculate_bearing,
    calculate_trajectory_status,
    find_nearby_cameras,
    haversine_miles,
)
from server import app, _train_cache


@pytest.fixture(autouse=True)
def warm_cache():
    """Ensure in-memory transit cache is pre-warmed so tests run hermetically without external HTTP timeouts."""
    if not _train_cache["geojson"]:
        _train_cache["timestamp"] = time.time() + 86400.0
        _train_cache["geojson"] = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-78.4842, 40.48]},
                    "properties": {
                        "train_num": "42",
                        "route": "Pennsylvanian",
                        "speed_mph": 45.0,
                        "heading": 0.0,
                        "dest": "New York",
                        "timely": "On Time",
                        "agency": "Amtrak",
                        "mode": "intercity_rail",
                        "mode_label": "Intercity Rail",
                    },
                }
            ],
        }


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


def test_proximity_endpoint_structure_and_filter(client, monkeypatch):
    dummy_trains = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-78.4842, 40.48]},
                "properties": {
                    "train_num": "42",
                    "route": "Pennsylvanian",
                    "speed_mph": 45.0,
                    "heading": 0.0,
                    "dest": "New York",
                    "timely": "On Time",
                    "mode": "intercity_rail",
                },
            }
        ],
    }
    monkeypatch.setattr("server.fetch_live_train_geojson", lambda: dummy_trains)
    resp = client.get("/api/proximity?max_miles=5.0&trajectory=approaching")
    assert resp.status_code == 200
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


def test_get_trains_agency_filter(client, monkeypatch):
    dummy_trains = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-78.48, 40.50]},
                "properties": {
                    "train_num": "42",
                    "route": "Pennsylvanian",
                    "speed_mph": 45.0,
                    "agency": "Amtrak",
                    "mode": "intercity_rail",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-71.05, 42.36]},
                "properties": {
                    "train_num": "100",
                    "route": "Red Line",
                    "speed_mph": 30.0,
                    "agency": "MBTA",
                    "mode": "subway",
                },
            },
        ],
    }
    monkeypatch.setattr("server.fetch_live_train_geojson", lambda: dummy_trains)
    resp = client.get("/api/trains?agency=Amtrak")
    assert resp.status_code == 200
    data = resp.json()
    assert "features" in data
    assert len(data["features"]) == 1
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

    # Live video embed invariants
    assert "modal-iframe" in html
    assert "youtube-nocookie.com/embed/" in html
    assert "openCamModal" in html
    assert "closeCamModal" in html

    # Route highlighting invariants
    assert "route-hud" in html
    assert "highlightTrainRoute" in html
    assert "resetRouteHighlight" in html
    assert "findCorridorsForTrain" in html


def test_all_webcams_have_live_embed_urls():
    """Verify all registered rail webcams have valid in-app embed and stream URLs."""
    from cam_lookup import PUBLIC_RAIL_CAMS
    assert len(PUBLIC_RAIL_CAMS) >= 7
    for cam in PUBLIC_RAIL_CAMS:
        assert cam.get("embed_url"), f"Camera {cam['cam_id']} missing embed_url"
        assert "youtube-nocookie.com/embed/" in cam["embed_url"]
        assert "autoplay=1" in cam["embed_url"]
        assert "mute=1" in cam["embed_url"]
        assert cam.get("stream_url"), f"Camera {cam['cam_id']} missing stream_url"


def test_webcams_endpoint_embed_urls(client):
    """Verify /api/cams returns GeoJSON where every feature exposes an embed_url."""
    resp = client.get("/api/cams")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["features"]) >= 7
    for feat in data["features"]:
        props = feat["properties"]
        assert props.get("embed_url"), f"Cam {props.get('cam_id')} has no embed_url in GeoJSON"
        assert "youtube-nocookie.com/embed/" in props["embed_url"]


def test_corridors_routes_mapping(client):
    """Verify /api/corridors returns enriched corridors with mapped route patterns."""
    resp = client.get("/api/corridors")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_corridors"] >= 10
    routes_found = set()
    for feat in data["features"]:
        props = feat["properties"]
        assert "routes" in props
        for r in props["routes"]:
            routes_found.add(r)
    assert "Southwest Chief" in routes_found
    assert "Acela" in routes_found
    assert "Empire Builder" in routes_found
    assert "Coast Starlight" in routes_found


def test_get_trains_mode_filter(client, monkeypatch):
    """Verify /api/trains supports transit mode filtering (subway, commuter_rail, intercity_rail, all)."""
    dummy_geojson = {
        "type": "FeatureCollection",
        "timestamp": 1234567.0,
        "total_active": 3,
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-71.05, 42.36]},
                "properties": {
                    "id": "MBTA_Red_1",
                    "train_num": "Red-1",
                    "route": "MBTA Red",
                    "agency": "MBTA",
                    "mode": "subway",
                    "mode_label": "Subway",
                }
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-71.10, 42.35]},
                "properties": {
                    "id": "MBTA_CR_101",
                    "train_num": "101",
                    "route": "MBTA CR-Fitchburg",
                    "agency": "MBTA",
                    "mode": "commuter_rail",
                    "mode_label": "Commuter Rail",
                }
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-71.06, 42.35]},
                "properties": {
                    "id": "Amtrak_2150",
                    "train_num": "2150",
                    "route": "Acela",
                    "agency": "Amtrak",
                    "mode": "intercity_rail",
                    "mode_label": "Intercity Rail",
                }
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-71.00, 42.40]},
                "properties": {
                    "id": "Flight_DAL100",
                    "train_num": "DAL100",
                    "flight_num": "DAL100",
                    "route": "Delta · FL350",
                    "agency": "Delta Air Lines",
                    "mode": "flight",
                    "mode_label": "Flight",
                }
            },
        ]
    }
    monkeypatch.setattr("server.fetch_live_train_geojson", lambda: dummy_geojson)

    # Filter: subway
    resp = client.get("/api/trains?mode=subway")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_active"] == 1
    assert data["features"][0]["properties"]["mode"] == "subway"

    # Filter: commuter_rail
    resp = client.get("/api/trains?mode=commuter_rail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_active"] == 1
    assert data["features"][0]["properties"]["mode"] == "commuter_rail"

    # Filter: rail (macro includes commuter + intercity)
    resp = client.get("/api/trains?mode=rail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_active"] == 2

    # Filter: ground (includes rail + subway, excludes flight)
    resp = client.get("/api/trains?mode=ground")
    assert resp.status_code == 200
    assert resp.json()["total_active"] == 3

    # Filter: flight
    resp = client.get("/api/trains?mode=flight")
    assert resp.status_code == 200
    assert resp.json()["total_active"] == 1

    # Filter: amtrak / intercity alias
    resp = client.get("/api/trains?mode=amtrak")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_active"] == 1
    assert data["features"][0]["properties"]["mode"] == "intercity_rail"

    resp = client.get("/api/trains?mode=intercity")
    assert resp.status_code == 200
    assert resp.json()["total_active"] == 1


def test_mbta_subway_and_light_rail_parsing():
    """Verify parse_mbta_v3_vehicles classifies heavy rail subways (type 1) and light rail (type 0)."""
    from gtfs_rt_parser import parse_mbta_v3_vehicles

    sample_payload = {
        "data": [
            {
                "id": "veh-red-1",
                "attributes": {
                    "latitude": 42.3601,
                    "longitude": -71.0589,
                    "speed": 12.5,
                    "bearing": 90.0,
                    "current_status": "IN_TRANSIT_TO",
                    "label": "1840",
                },
                "relationships": {
                    "route": {"data": {"id": "Red", "type": "route"}}
                }
            },
            {
                "id": "veh-green-1",
                "attributes": {
                    "latitude": 42.3501,
                    "longitude": -71.0789,
                    "speed": 8.0,
                    "bearing": 180.0,
                    "current_status": "IN_TRANSIT_TO",
                    "label": "3902",
                },
                "relationships": {
                    "route": {"data": {"id": "Green-E", "type": "route"}}
                }
            },
            {
                "id": "veh-cr-1",
                "attributes": {
                    "latitude": 42.4001,
                    "longitude": -71.1289,
                    "speed": 25.0,
                    "bearing": 270.0,
                    "current_status": "IN_TRANSIT_TO",
                    "label": "105",
                },
                "relationships": {
                    "route": {"data": {"id": "CR-Fitchburg", "type": "route"}}
                }
            },
        ],
        "included": [
            {"id": "Red", "type": "route", "attributes": {"type": 1}},
            {"id": "Green-E", "type": "route", "attributes": {"type": 0}},
            {"id": "CR-Fitchburg", "type": "route", "attributes": {"type": 2}},
        ]
    }
    result = parse_mbta_v3_vehicles(sample_payload)
    assert result["total_active"] == 3
    features_by_id = {f["properties"]["id"]: f["properties"] for f in result["features"]}

    assert features_by_id["MBTA_1840"]["mode"] == "subway"
    assert features_by_id["MBTA_1840"]["mode_label"] == "Subway"

    assert features_by_id["MBTA_3902"]["mode"] == "light_rail"
    assert features_by_id["MBTA_3902"]["mode_label"] == "Light Rail"

    assert features_by_id["MBTA_105"]["mode"] == "commuter_rail"
    assert features_by_id["MBTA_105"]["mode_label"] == "Commuter Rail"


def test_opensky_flight_parsing():
    """Verify parse_opensky_states normalizes ADS-B state vectors into GeoJSON flight features."""
    from opensky_parser import parse_opensky_states

    sample_payload = {
        "time": 1790052570,
        "states": [
            [
                "a39be7",
                "JBU955  ",
                "United States",
                1790052569,
                1790052570,
                -76.5801,
                39.2545,
                3604.26,  # ~11,825 ft
                False,     # airborne
                175.0,    # ~391 mph
                195.34,   # heading
                2.5,      # ~492 fpm climb
                None,
                3749.04,
                "1131",
                False,
                0,
            ],
            [
                "a53eef",
                "UPS895  ",
                "United States",
                1790052569,
                1790052569,
                -91.7672,
                38.3176,
                11894.82, # ~39,025 ft (FL390)
                False,
                268.0,    # ~600 mph
                89.5,
                0.0,      # cruising
                None,
                12367.26,
                "1757",
                False,
                0,
            ],
            [
                "a00001",
                "N12345  ",
                "United States",
                1790052569,
                1790052569,
                -97.0000,
                32.0000,
                150.0,
                True,     # on ground
                5.0,
                0.0,
                0.0,
                None,
                150.0,
                "1200",
                False,
                0,
            ]
        ]
    }
    result = parse_opensky_states(sample_payload)
    assert result["type"] == "FeatureCollection"
    assert result["total_active"] == 3
    features = result["features"]

    # JetBlue Flight 955
    jb = features[0]["properties"]
    assert jb["flight_num"] == "JBU955"
    assert jb["agency"] == "JetBlue"
    assert jb["mode"] == "flight"
    assert jb["mode_label"] == "Flight"
    assert 11800 <= jb["altitude_ft"] <= 11900
    assert 390 <= jb["speed_mph"] <= 393
    assert jb["heading"] == 195.3
    assert "Climbing" in jb["status"]
    assert jb["on_ground"] is False

    # UPS 895 (Cruising at FL390)
    ups = features[1]["properties"]
    assert ups["flight_num"] == "UPS895"
    assert ups["agency"] == "UPS Airlines"
    assert "FL390" in ups["route"]
    assert ups["status"] == "Cruising"

    # N12345 (General Aviation on ground)
    ga = features[2]["properties"]
    assert ga["agency"] == "General Aviation (US)"
    assert ga["status"] == "Taxiing / Ground"
    assert ga["on_ground"] is True


def test_api_flights_endpoint(client, monkeypatch):
    """Verify /api/flights returns GeoJSON FeatureCollection of parsed aircraft."""
    dummy_flights = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-76.58, 39.25]},
            "properties": {
                "id": "Flight_a39be7",
                "train_num": "JBU955",
                "flight_num": "JBU955",
                "agency": "JetBlue",
                "mode": "flight",
                "mode_label": "Flight",
                "speed_mph": 391.0,
                "altitude_ft": 11825,
            }
        }
    ]
    monkeypatch.setattr("server._fetch_flights", lambda: dummy_flights)

    resp = client.get("/api/flights")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert data["total_active"] == 1
    assert data["features"][0]["properties"]["mode"] == "flight"


def test_proximity_skips_overhead_flights(client, monkeypatch):
    """Verify railcam proximity engine excludes airborne flights directly overhead."""
    dummy_geojson = {
        "type": "FeatureCollection",
        "timestamp": 1726913800,
        "total_active": 1,
        "features": [
            {
                "type": "Feature",
                # Directly over Fullerton railcam (lat: 33.8687, lon: -117.9228)
                "geometry": {"type": "Point", "coordinates": [-117.9228, 33.8687]},
                "properties": {
                    "id": "Flight_overhead",
                    "train_num": "DAL100",
                    "route": "Delta · FL350",
                    "agency": "Delta Air Lines",
                    "mode": "flight",
                    "mode_label": "Flight",
                    "speed_mph": 520.0,
                    "heading": 90.0,
                    "altitude_ft": 35000,
                }
            }
        ]
    }
    monkeypatch.setattr("server.fetch_live_train_geojson", lambda: dummy_geojson)

    resp = client.get("/api/proximity?max_miles=15.0")
    assert resp.status_code == 200
    data = resp.json()
    # Should not produce proximity alerts for airborne flights passing over trackside cams
    assert data["total_matches"] == 0
    assert len(data["events"]) == 0


def test_index_html_flight_invariants():
    """Verify index.html includes flight toggle button, fa-plane glyph, and altitude HUD."""
    from server import INDEX_HTML
    assert INDEX_HTML.exists()
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'data-filter="flight"' in html
    assert "fa-plane" in html
    assert "Altitude:" in html


def test_index_html_fleet_pills_invariants():
    """Verify index.html contains Amtrak filter pill, fleet counter badges, and scoped filter-btn selectors."""
    from server import INDEX_HTML
    assert INDEX_HTML.exists()
    html = INDEX_HTML.read_text(encoding="utf-8")

    # Ground & Amtrak filter buttons
    assert 'data-filter="ground"' in html
    assert 'filterTrains(\'ground\')' in html
    assert 'data-filter="amtrak"' in html
    assert 'filterTrains(\'amtrak\')' in html

    # Live fleet count badge elements
    for badge_id in ["count-ground", "count-all", "count-amtrak", "count-subway", "count-commuter", "count-bus", "count-flight", "count-approaching", "count-highspeed"]:
        assert f'id="{badge_id}"' in html

    # Scoped selector prevents mangling trail-btn or labels-btn
    assert ".filter-btn[data-filter]" in html


def test_calculate_fleet_counts_and_api_trains_counts(client, monkeypatch):
    """Verify /api/trains returns summary fleet counts for badges even under scoped mode filters."""
    dummy_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-71.05, 42.36]},
            "properties": {"id": "MBTA_Red_1", "train_num": "Red-1", "mode": "subway", "speed_mph": 25.0}
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-71.10, 42.35]},
            "properties": {"id": "MBTA_CR_101", "train_num": "101", "mode": "commuter_rail", "speed_mph": 65.0}
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-71.06, 42.35]},
            "properties": {"id": "Amtrak_2150", "train_num": "2150", "mode": "intercity_rail", "speed_mph": 95.0}
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-71.00, 42.40]},
            "properties": {"id": "Flight_DAL100", "train_num": "DAL100", "mode": "flight", "speed_mph": 450.0}
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-71.02, 42.38]},
            "properties": {"id": "MBTA_Bus_1", "train_num": "Bus-1", "mode": "bus", "speed_mph": 15.0}
        }
    ]
    monkeypatch.setattr("server.fetch_live_train_geojson", lambda: {
        "type": "FeatureCollection",
        "timestamp": 1726913800,
        "total_active": 5,
        "features": dummy_features
    })

    # Query with mode=ground: features should be 4 (subway, commuter, amtrak, bus),
    # but counts must summarize all 5 vehicles including flight and highspeed count.
    resp = client.get("/api/trains?mode=ground")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_active"] == 4
    assert len(data["features"]) == 4

    assert "counts" in data
    counts = data["counts"]
    assert counts["all"] == 5
    assert counts["ground"] == 4
    assert counts["flight"] == 1
    assert counts["amtrak"] == 1
    assert counts["subway"] == 1
    assert counts["commuter"] == 1
    assert counts["bus"] == 1
    assert counts["highspeed"] == 3  # 65, 95, 450 mph


def test_opensky_429_cooldown_backoff(monkeypatch):
    """Verify OpenSky 429 rate-limit sets cache timestamp forward by 90s to avoid hammering API."""
    import time
    from unittest.mock import MagicMock
    import server

    # Reset cache
    server._flight_cache["timestamp"] = 0.0
    server._flight_cache["features"] = [{"id": "cached_flight"}]

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: mock_resp)

    now_before = time.time()
    res = server._fetch_flights()
    assert res == [{"id": "cached_flight"}]
    # Cache timestamp should be pushed ~90s into the future
    assert server._flight_cache["timestamp"] >= now_before + 85.0


def test_index_html_telemetry_mode_query():
    """Verify index.html sends ?mode= to /api/trains and binds server counts."""
    from server import INDEX_HTML
    assert INDEX_HTML.exists()
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "fetch(`/api/trains${queryMode}`)" in html
    assert "latestFleetCounts" in html


def test_encounter_tracker_analytics():
    """Verify EncounterTracker calculates flyby velocity, dwell, CPA, and junction analytics."""
    from encounter_tracker import EncounterTracker

    tracker = EncounterTracker(max_history=10, encounter_radius_miles=5.0)
    # Empty case
    empty_stats = tracker.get_analytics()
    assert empty_stats["total_completed"] == 0
    assert empty_stats["peak_speed_mph"] == 0.0
    assert empty_stats["fastest_train"] is None
    assert empty_stats["busiest_camera"] is None

    # Simulate encounter 1: Train 3 at Fullerton (peak 65 mph, CPA 1.2 mi, duration 120s)
    t0 = 1000.0
    ev1 = {
        "train": {"train_num": "3", "route": "Southwest Chief", "speed_mph": 45},
        "camera": {"cam_id": "cam_fullerton", "name": "Fullerton Depot", "location": "Fullerton, CA"},
        "distance_miles": 3.0,
        "trajectory": "approaching",
    }
    tracker.update([ev1], timestamp=t0)
    ev1_peak = {
        "train": {"train_num": "3", "route": "Southwest Chief", "speed_mph": 65},
        "camera": {"cam_id": "cam_fullerton", "name": "Fullerton Depot", "location": "Fullerton, CA"},
        "distance_miles": 1.2,
        "trajectory": "receding",
    }
    tracker.update([ev1_peak], timestamp=t0 + 60.0)
    tracker.update([], timestamp=t0 + 120.0)  # completed

    # Simulate encounter 2: Train 14 at Tehachapi (peak 40 mph, CPA 0.8 mi, duration 180s)
    t1 = 2000.0
    ev2 = {
        "train": {"train_num": "14", "route": "Coast Starlight", "speed_mph": 40},
        "camera": {"cam_id": "cam_tehachapi", "name": "Tehachapi Loop", "location": "Tehachapi, CA"},
        "distance_miles": 0.8,
        "trajectory": "approaching",
    }
    tracker.update([ev2], timestamp=t1)
    tracker.update([], timestamp=t1 + 180.0)  # completed

    analytics = tracker.get_analytics()
    assert analytics["total_completed"] == 2
    assert analytics["peak_speed_mph"] == 65.0
    assert analytics["fastest_train"]["train_num"] == "3"
    assert analytics["fastest_train"]["speed_mph"] == 65.0
    assert analytics["closest_cpa_miles"] == 0.8
    assert analytics["closest_train"]["train_num"] == "14"
    assert analytics["avg_duration_seconds"] == 150.0  # (120 + 180) / 2
    assert len(analytics["busiest_cameras"]) == 2


def test_encounters_analytics_endpoint(client):
    """Verify /api/encounters/analytics returns valid JSON schema."""
    resp = client.get("/api/encounters/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_completed" in data
    assert "active_count" in data
    assert "peak_speed_mph" in data
    assert "avg_duration_seconds" in data
    assert "busiest_cameras" in data


def test_index_html_encounter_analytics():
    """Verify index.html includes analytics banner and endpoint query."""
    from server import INDEX_HTML
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "fetch('/api/encounters/analytics')" in html
    assert "Flyby Telemetry Analytics" in html
    assert "Peak Velocity:" in html
    assert "Avg Corridor Dwell:" in html


def test_pip_player_and_director_integration(client):
    """Verify index.html includes Trackside Live PIP player, toggle affordances, and auto-sync controls."""
    from server import INDEX_HTML
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "pip-container" in html
    assert "pip-iframe" in html
    assert "pip-toggle-btn" in html
    assert "openPipForCam" in html
    assert "togglePipAutoSync" in html
    assert "expandPipToModal" in html
    assert "Trackside Live PIP" in html

    # Verify director endpoint provides necessary stream metadata for PIP
    resp = client.get("/api/director")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert "camera" in data
    cam = data["camera"]
    assert "name" in cam
    assert "embed_url" in cam
    assert "provider" in cam


def test_cam_lookup_nearest_and_downstream_intercept():
    """Verify find_nearest_camera and get_downstream_camera_intercept in cam_lookup."""
    from cam_lookup import find_nearest_camera, get_downstream_camera_intercept

    # Coordinates near Fullerton Depot (33.8687, -117.9228)
    # Heading North (355 deg) -> Approaching Fullerton from South
    intercept = get_downstream_camera_intercept(33.85, -117.9228, train_heading=355.0, speed_mph=45.0, max_miles=20.0)
    assert intercept is not None
    assert intercept["cam_id"] == "cam_fullerton_depot"
    assert intercept["trajectory"] == "approaching"
    assert intercept["distance_miles"] < 2.0
    assert intercept["eta_minutes"] is not None
    assert intercept["eta_minutes"] > 0.0

    # Nearest camera lookup
    nearest = find_nearest_camera(33.8687, -117.9228)
    assert nearest is not None
    assert nearest["cam_id"] == "cam_fullerton_depot"
    assert nearest["distance_miles"] == 0.0


def test_get_train_by_id_endpoint(client, monkeypatch):
    """Verify GET /api/trains/{train_id} returns vehicle data, downstream intercept, and nearby cameras."""
    import server

    mock_geojson = {
        "type": "FeatureCollection",
        "timestamp": 1726913800.0,
        "total_active": 1,
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-117.9228, 33.85]},
                "properties": {
                    "id": "Amtrak_763",
                    "train_num": "763",
                    "route": "Pacific Surfliner",
                    "agency": "Amtrak",
                    "mode": "intercity_rail",
                    "speed_mph": 50.0,
                    "heading": 355.0,
                    "dest": "Goleta",
                    "origin": "San Diego",
                    "timely": "On Time",
                },
            }
        ],
    }

    monkeypatch.setattr(server, "fetch_live_train_geojson", lambda: mock_geojson)

    # 1. Lookup by full ID
    resp1 = client.get("/api/trains/Amtrak_763")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["vehicle"]["properties"]["train_num"] == "763"
    assert data1["downstream_intercept"] is not None
    assert data1["downstream_intercept"]["cam_id"] == "cam_fullerton_depot"
    assert "nearby_cameras" in data1
    assert len(data1["nearby_cameras"]) >= 1

    # 2. Lookup by train_num string
    resp2 = client.get("/api/trains/763")
    assert resp2.status_code == 200
    assert resp2.json()["vehicle"]["properties"]["route"] == "Pacific Surfliner"


def test_get_train_by_id_not_found(client, monkeypatch):
    """Verify GET /api/trains/{train_id} returns 404 for unknown train."""
    import server

    mock_geojson = {"type": "FeatureCollection", "timestamp": 1726913800.0, "total_active": 0, "features": []}
    monkeypatch.setattr(server, "fetch_live_train_geojson", lambda: mock_geojson)

    resp = client.get("/api/trains/nonexistent_9999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_api_trains_attaches_nearest_cam_property(client, monkeypatch):
    """Verify fetch_live_train_geojson attaches nearest_cam to ground transit features."""
    import server

    mock_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-117.9228, 33.85]},
            "properties": {
                "id": "Amtrak_582",
                "train_num": "582",
                "route": "Pacific Surfliner",
                "mode": "intercity_rail",
                "speed_mph": 45.0,
                "heading": 355.0,
                "origin": "LAX",
                "dest": "SAN",
            },
        }
    ]

    # Clear cache and mock workers
    server._train_cache["timestamp"] = 0.0
    server._train_cache["geojson"] = None
    monkeypatch.setattr(server, "_fetch_amtrak", lambda: mock_features)
    monkeypatch.setattr(server, "_fetch_mbta", lambda: [])
    monkeypatch.setattr(server, "_fetch_caltrain", lambda: [])
    monkeypatch.setattr(server, "_fetch_metra", lambda: [])
    monkeypatch.setattr(server, "_fetch_sound_transit", lambda: [])
    monkeypatch.setattr(server, "_fetch_flights", lambda: [])

    resp = client.get("/api/trains")
    assert resp.status_code == 200
    features = resp.json()["features"]
    assert len(features) == 1
    props = features[0]["properties"]
    assert "nearest_cam" in props
    assert props["nearest_cam"]["cam_id"] == "cam_fullerton_depot"
    assert props["nearest_cam"]["trajectory"] == "approaching"
    assert "embed_url" in props["nearest_cam"]


def test_index_html_cam_jump_and_search_invariants():
    """Verify index.html includes search input, search handlers, cam jump buttons, and panToCamCoordinates."""
    from server import INDEX_HTML
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "transit-search" in html
    assert "handleTransitSearch" in html
    assert "jumpToFirstSearchResult" in html
    assert "panToCamCoordinates" in html
    assert "Watch in PIP" in html
    assert "Pan to Cam" in html
    assert "nearest_cam" in html


def test_encounter_tracker_returns_new_and_completed_sessions():
    """Verify encounter tracker returns new and completed sessions upon transition."""
    from encounter_tracker import EncounterTracker

    tracker = EncounterTracker(max_history=10, encounter_radius_miles=5.0)
    t0 = 1726913800.0
    ev1 = {
        "train": {"train_num": "581", "route": "Pacific Surfliner", "speed_mph": 40},
        "camera": {"cam_id": "cam_fullerton_depot", "name": "Fullerton Depot"},
        "distance_miles": 2.5,
        "trajectory": "approaching",
    }
    res1 = tracker.update([ev1], timestamp=t0)
    assert "new" in res1
    assert "completed" in res1
    assert len(res1["new"]) == 1
    assert res1["new"][0]["train_num"] == "581"
    assert len(res1["completed"]) == 0

    # Train leaves proximity
    res2 = tracker.update([], timestamp=t0 + 120.0)
    assert len(res2["new"]) == 0
    assert len(res2["completed"]) == 1
    assert res2["completed"][0]["train_num"] == "581"
    assert res2["completed"][0]["status"] == "completed"


@pytest.mark.anyio
async def test_sse_generator_handshake():
    """Verify sse_events returns a StreamingResponse with proper media-type, headers, and connected handshake."""
    from server import sse_events
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/events", "headers": []}
    request = Request(scope)
    resp = await sse_events(request)
    assert resp.media_type == "text/event-stream"
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.headers["Connection"] == "keep-alive"

    gen = resp.body_iterator
    first_chunk = await gen.__anext__()
    assert "event: connected" in first_chunk
    assert "highball-spatial-engine" in first_chunk
    # Clean up generator
    await gen.aclose()


def test_sse_broadcast_dispatch(client):
    """Verify broadcast_sse_sync and POST /api/events/broadcast dispatch to subscribers."""
    import asyncio
    import json
    from server import broadcast_sse_sync, subscribers

    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    subscribers.add(queue)

    try:
        # Manual broadcast endpoint
        resp = client.post("/api/events/broadcast", json={
            "event_type": "telemetry_test",
            "data": {"test_train": "Amtrak_763", "speed": 65.0}
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "dispatched"

        # Verify queue received message
        assert not queue.empty()
        evt_type, payload = queue.get_nowait()
        assert evt_type == "telemetry_test"
        data = json.loads(payload)
        assert data["test_train"] == "Amtrak_763"
    finally:
        subscribers.discard(queue)


def test_health_active_sse_subscribers(client):
    """Verify /health endpoint reports active_sse_subscribers."""
    import asyncio
    from server import subscribers

    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    subscribers.add(queue)
    try:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_sse_subscribers" in data
        assert data["active_sse_subscribers"] >= 1
    finally:
        subscribers.discard(queue)


def test_index_html_sse_invariants():
    """Verify index.html includes EventSource initialization, SSE event listeners, and live status pill."""
    from server import INDEX_HTML
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "initSSE" in html
    assert "new EventSource('/events')" in html
    assert "addEventListener('connected'" in html
    assert "addEventListener('telemetry'" in html
    assert "addEventListener('proximity'" in html
    assert "addEventListener('encounter'" in html
    assert "SSE: Live" in html
    assert "Poll: 15s" in html


def test_corridors_density_endpoint(client):
    """Verify /api/corridors/density aggregates transit volume, speeds, and camera mapping across all mainlines."""
    resp = client.get("/api/corridors/density")
    assert resp.status_code == 200
    data = resp.json()

    assert "total_corridors" in data
    assert data["total_corridors"] >= 16
    assert "total_trains_on_corridors" in data
    assert "busiest_corridor" in data
    assert "corridors" in data
    assert "timestamp" in data

    corridors = data["corridors"]
    assert len(corridors) >= 16
    for c in corridors:
        assert "corridor_id" in c
        assert "name" in c
        assert "operator" in c
        assert "active_train_count" in c
        assert "peak_speed_mph" in c
        assert "avg_speed_mph" in c
        assert "associated_cameras_count" in c
        assert isinstance(c["active_train_count"], int)
        assert isinstance(c["peak_speed_mph"], (int, float))


def test_corridor_detail_endpoint(client):
    """Verify /api/corridors/{corridor_id} returns coordinates, live trains, and mapped trackside webcams."""
    # Test short slug
    resp = client.get("/api/corridors/nec")
    assert resp.status_code == 200
    data = resp.json()

    assert data["corridor_id"] in ["nec", "corridor_nec"]
    assert "Northeast Corridor" in data["name"]
    assert "Amtrak" in data["operator"]
    assert "coordinates" in data
    assert len(data["coordinates"]) > 10
    assert "active_trains" in data
    assert "associated_cameras" in data
    assert "peak_speed_mph" in data

    # NEC should have trackside cams mapped
    cams = data["associated_cameras"]
    assert isinstance(cams, list)
    assert len(cams) >= 1

    # Test canonical ID
    resp2 = client.get("/api/corridors/corridor_nec")
    assert resp2.status_code == 200
    assert resp2.json()["corridor_id"] == "corridor_nec"


def test_corridor_detail_not_found(client):
    """Verify /api/corridors/{corridor_id} returns 404 for invalid corridor IDs."""
    resp = client.get("/api/corridors/invalid_ghost_corridor_999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_index_html_corridor_density_invariants():
    """Verify index.html contains corridor toggle, corridor sidebar, and density inspection logic."""
    from server import INDEX_HTML
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "corridors-toggle-btn" in html
    assert "corridor-sidebar" in html
    assert "toggleCorridorsDrawer" in html
    assert "showCorridorsDensityList" in html
    assert "openCorridorDetail" in html
    assert "/api/corridors/density" in html
    assert "Mainline Rail Corridors" in html


def test_consist_synthesis_deterministic():
    """Verify consist synthesis deterministically derives equipment specs and axle counts."""
    from consist_detector import synthesize_consist_for_train

    # Acela express
    c_acela = synthesize_consist_for_train("2150", "Acela Express", "Amtrak")
    assert c_acela["train_type"] == "High-Speed Rail"
    assert c_acela["locomotive_count"] == 2
    assert c_acela["car_count"] == 6
    assert c_acela["total_axles"] == 32
    assert c_acela["total_units"] == 8
    assert c_acela["total_horsepower"] == 12000

    # Repeating call produces identical results
    c_acela_2 = synthesize_consist_for_train("2150", "Acela Express", "Amtrak", timestamp=c_acela["timestamp"])
    assert c_acela == c_acela_2

    # Long-distance transcon (California Zephyr)
    c_zephyr = synthesize_consist_for_train("5", "California Zephyr", "Amtrak")
    assert c_zephyr["train_type"] == "Long-Distance Transcon"
    assert c_zephyr["locomotive_count"] == 2
    assert c_zephyr["total_units"] >= 9
    assert c_zephyr["total_axles"] >= 36

    # Unit breakdown properties
    u0 = c_zephyr["units"][0]
    assert u0["category"] == "locomotive"
    assert u0["axles"] == 4
    assert u0["weight_tons"] > 0
    assert "road_number" in u0


def test_defect_detector_radio_report():
    """Verify trackside defect detector generates authentic radio telemetry and axle counts."""
    from cam_lookup import PUBLIC_RAIL_CAMS
    from consist_detector import generate_defect_report, synthesize_consist_for_train

    cam = PUBLIC_RAIL_CAMS[0]  # Horseshoe curve
    consist = synthesize_consist_for_train("42", "Pennsylvanian", "Amtrak", speed_mph=52.0)
    rep = generate_defect_report(cam, "42", speed_mph=52.0, consist_data=consist)

    assert rep["detector_type"] == "Hotbox & Dragging Equipment Detector (HBD/DED)"
    assert "Horseshoe Curve" in rep["station_name"]
    assert rep["operator"] == "NORFOLK SOUTHERN"
    assert rep["milepost"] == "MP 242.0"
    assert rep["track"] in [1, 2]
    assert rep["axle_count"] == consist["total_axles"]
    assert rep["defects_detected"] is False
    assert "[RADIO TONES]" in rep["radio_transcript"]
    assert "NORFOLK SOUTHERN DETECTOR" in rep["radio_transcript"]
    assert "DETECTOR OUT" in rep["radio_transcript"]


def test_api_consists_endpoints(client):
    """Verify /api/consists and /api/consists/{train_num} endpoints."""
    resp = client.get("/api/consists")
    assert resp.status_code == 200
    data = resp.json()

    assert "total_trains" in data
    assert "total_locomotives" in data
    assert "total_cars" in data
    assert "total_units" in data
    assert "total_axles" in data
    assert "total_horsepower" in data
    assert "total_weight_tons" in data
    assert "motive_power_distribution" in data
    assert "car_type_distribution" in data
    assert "trains" in data
    assert isinstance(data["trains"], list)

    # Detailed consist endpoint
    resp_detail = client.get("/api/consists/5")
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert "consist" in detail
    assert detail["consist"]["train_num"] == "5"
    assert "units" in detail["consist"]
    assert len(detail["consist"]["units"]) > 0


def test_api_defect_detector_endpoints(client):
    """Verify /api/defect-detectors/{cam_id} endpoints."""
    resp = client.get("/api/defect-detectors/cam_horseshoe_curve")
    assert resp.status_code == 200
    data = resp.json()

    assert data["cam_id"] == "cam_horseshoe_curve"
    assert "Horseshoe Curve" in data["camera_name"]
    assert data["milepost"] == "MP 242.0"
    assert "detector_report" in data
    assert "radio_transcript" in data["detector_report"]

    # 404 for nonexistent camera
    resp_404 = client.get("/api/defect-detectors/nonexistent_fake_cam_99")
    assert resp_404.status_code == 404


def test_index_html_consist_invariants():
    """Verify index.html contains consists toggle, sidebar, and telemetry inspection logic."""
    from server import INDEX_HTML
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "consists-toggle-btn" in html
    assert "consists-sidebar" in html
    assert "toggleConsistsDrawer" in html
    assert "showConsistsFleetOverview" in html
    assert "openConsistDetail" in html
    assert "/api/consists" in html
    assert "Fleet Consists & Rolling Stock" in html
    assert "Automated Defect Detector" in html


def test_stream_vision_stream_target_probe_and_token_refresh():
    """Verify StreamTarget generates authenticated HLS manifest and probes latency."""
    from stream_vision import StreamTarget

    target = StreamTarget(
        cam_id="cam_test_junction",
        name="Test Rail Junction",
        location="Altoona, PA",
        route="Pennsylvanian",
        subdivision="Pittsburgh Line",
        milepost="MP 240.0",
        provider="Railroaders Museum",
        stream_url="https://youtube.com/watch?v=test",
        embed_url="https://youtube-nocookie.com/embed/test",
        resolution="1080p60",
        bitrate_kbps=4500,
        fps=60,
    )

    assert target.cam_id == "cam_test_junction"
    assert "manifest.m3u8?token=" in target.hls_manifest_url
    assert target.status == "active_live"
    assert target.is_live is True

    probe_result = target.probe()
    assert probe_result["status"] == "active_live"
    assert probe_result["last_probe_latency_ms"] > 0
    assert probe_result["resolution"] == "1080p60"


def test_stream_ingest_manager_registry_and_summary():
    """Verify StreamIngestManager indexes all 10 cameras and provides aggregate summary."""
    from stream_vision import StreamIngestManager
    from cam_lookup import PUBLIC_RAIL_CAMS

    manager = StreamIngestManager()
    assert len(manager.streams) == len(PUBLIC_RAIL_CAMS)
    assert "cam_horseshoe_curve" in manager.streams
    assert "cam_tehachapi_loop" in manager.streams

    summary = manager.get_summary()
    assert summary["total_streams"] == len(PUBLIC_RAIL_CAMS)
    assert summary["active_streams"] >= 1
    assert summary["total_bandwidth_kbps"] > 0
    assert summary["average_latency_ms"] > 0


def test_trackside_vision_detector_frame_sampling():
    """Verify TracksideVisionDetector generates bounding boxes, OCR, and optical flow metrics."""
    from stream_vision import StreamTarget, TracksideVisionDetector

    detector = TracksideVisionDetector(max_history=50)
    target = StreamTarget(
        cam_id="cam_rochelle",
        name="Rochelle Double Diamond",
        location="Rochelle, IL",
        route="BNSF Transcon",
        subdivision="Chicago Sub",
        milepost="MP 83.2",
        provider="City of Rochelle",
        stream_url="https://youtube.com/watch?v=rochelle",
        embed_url="https://youtube-nocookie.com/embed/rochelle",
    )

    # 1. Sample with train in visual cone (< 2.5 miles)
    train_data = {"train_num": "4", "route": "Southwest Chief", "agency": "Amtrak", "speed_mph": 62.0}
    event_train = detector.sample_camera_frame(target, train_data=train_data, distance_miles=1.5)

    assert event_train["train_present"] is True
    assert event_train["scene_classification"] == "TRAIN_IN_FRAME"
    assert event_train["track_status"] == "OCCUPIED"
    assert event_train["total_bounding_boxes"] > 0
    assert event_train["lead_unit"] is not None
    assert "AMTR" in event_train["lead_cab_number"]
    assert event_train["optical_speed_estimate_mph"] > 0
    assert len(detector.history) == 1

    # 2. Sample nominal clear track (> 2.5 miles)
    event_clear = detector.sample_camera_frame(target, train_data=None, distance_miles=8.0)
    assert event_clear["train_present"] is False
    assert event_clear["scene_classification"] == "CLEAR_RIGHT_OF_WAY"
    assert event_clear["track_status"] == "CLEAR"
    assert event_clear["total_bounding_boxes"] == 0
    assert len(detector.history) == 2


def test_encounter_tracker_attaches_vision_and_hls():
    """Verify EncounterTracker binds HLS stream metadata and vision confirmation into sessions."""
    from encounter_tracker import EncounterTracker

    tracker = EncounterTracker(encounter_radius_miles=5.0)
    mock_events = [
        {
            "train": {"train_num": "42", "route": "Pennsylvanian", "speed_mph": 48.0, "agency": "Amtrak"},
            "camera": {"cam_id": "cam_horseshoe_curve", "name": "Horseshoe Curve", "location": "Altoona, PA"},
            "distance_miles": 1.8,
            "trajectory": "approaching",
        }
    ]

    t0 = 1726980000.0
    changes = tracker.update(mock_events, timestamp=t0)
    active = tracker.get_active_encounters()
    assert len(active) == 1
    session = active[0]

    assert session["train_num"] == "42"
    assert session["camera_id"] == "cam_horseshoe_curve"
    assert session["hls_manifest_url"] != ""
    assert session["vision_confirmed"] is True
    assert session["vision_detection"] is not None
    assert session["vision_detection"]["train_present"] is True

    # Check analytics when completed
    tracker.update([], timestamp=t0 + 120.0)
    history = tracker.get_recent_history()
    assert len(history) == 1
    assert history[0]["vision_confirmed"] is True

    analytics = tracker.get_analytics()
    assert analytics["total_completed"] == 1
    assert analytics["total_vision_confirmed"] == 1
    assert analytics["vision_confirmation_rate_pct"] == 100.0


def test_api_streams_endpoints(client):
    """Verify /api/streams and /api/streams/{cam_id} endpoints."""
    # List all streams
    resp = client.get("/api/streams")
    assert resp.status_code == 200
    data = resp.json()
    assert "streams" in data
    assert data["total_streams"] == 10
    assert "summary" in data
    assert data["summary"]["total_streams"] == 10

    # Stream detail
    resp_cam = client.get("/api/streams/cam_horseshoe_curve")
    assert resp_cam.status_code == 200
    cam_data = resp_cam.json()
    assert cam_data["cam_id"] == "cam_horseshoe_curve"
    assert "manifest.m3u8" in cam_data["hls_manifest_url"]
    assert cam_data["resolution"] == "1080p60"

    # Probe stream
    resp_probe = client.post("/api/streams/cam_horseshoe_curve/probe?force=true")
    assert resp_probe.status_code == 200
    probe_data = resp_probe.json()
    assert probe_data["last_probe_latency_ms"] > 0

    # Nonexistent stream 404
    resp_404 = client.get("/api/streams/nonexistent_fake_cam_99")
    assert resp_404.status_code == 404


def test_api_vision_endpoints(client):
    """Verify /api/vision/detections, /api/vision/sample, and /api/vision/metrics endpoints."""
    # Metrics
    resp_metrics = client.get("/api/vision/metrics")
    assert resp_metrics.status_code == 200
    metrics = resp_metrics.json()
    assert "total_frames_processed" in metrics

    # Sample pass
    resp_sample = client.post("/api/vision/sample?cam_id=cam_horseshoe_curve&train_num=42")
    assert resp_sample.status_code == 200
    sample_data = resp_sample.json()
    assert sample_data["train_present"] is True
    assert sample_data["scene_classification"] == "TRAIN_IN_FRAME"
    assert sample_data["total_bounding_boxes"] > 0

    # Detections list
    resp_det = client.get("/api/vision/detections")
    assert resp_det.status_code == 200
    det_data = resp_det.json()
    assert det_data["total"] >= 1
    assert "detections" in det_data

    # Camera-specific detections
    resp_cam_det = client.get("/api/vision/detections/cam_horseshoe_curve")
    assert resp_cam_det.status_code == 200
    assert resp_cam_det.json()["cam_id"] == "cam_horseshoe_curve"

    # 404 for nonexistent camera in vision sample
    resp_sample_404 = client.post("/api/vision/sample?cam_id=nonexistent_cam")
    assert resp_sample_404.status_code == 404


def test_index_html_stream_vision_invariants():
    """Verify index.html contains vision_detection SSE listener and HLS status badges."""
    from server import INDEX_HTML
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "addEventListener('vision_detection'" in html
    assert "Trackside Vision Detection" in html
    assert "HLS 1080p · CV Vision Active" in html


def test_sqlite_db_initialization_and_crud(tmp_path):
    """Verify SQLite initialization, WAL mode, CRUD, indexing, and analytics."""
    import db
    db_file = tmp_path / "test_highball.db"
    db.init_db(db_file)

    # Verify connection & WAL mode
    conn = db.get_db_connection(db_file)
    row = conn.execute("PRAGMA journal_mode;").fetchone()
    assert row[0].lower() == "wal"
    conn.close()

    # 1. Encounters CRUD
    t0 = time.time()
    enc1 = {
        "encounter_id": "enc_3_cam_perryville_01",
        "train_num": "3",
        "route": "Southwest Chief",
        "camera_id": "cam_perryville_amtrak",
        "camera_name": "Perryville Amtrak Station",
        "location": "Perryville, MD",
        "start_time": t0,
        "last_seen": t0 + 30,
        "end_time": t0 + 60,
        "duration_seconds": 60.0,
        "closest_distance_miles": 0.25,
        "peak_speed_mph": 79.5,
        "status": "completed",
        "vision_confirmed": True,
        "consist": {"total_units": 9, "total_axles": 36},
        "defect_report": {"detector": "HBD-MP60", "axles": 36},
    }
    assert db.save_encounter(enc1, db_path=db_file) is True

    # Retrieve by ID
    loaded_enc = db.get_encounter("enc_3_cam_perryville_01", db_path=db_file)
    assert loaded_enc is not None
    assert loaded_enc["train_num"] == "3"
    assert loaded_enc["vision_confirmed"] is True
    assert loaded_enc["consist"]["total_units"] == 9
    assert loaded_enc["defect_report"]["detector"] == "HBD-MP60"

    # Query with filters
    q_cams = db.query_encounters(camera_id="cam_perryville_amtrak", db_path=db_file)
    assert len(q_cams) == 1
    q_train = db.query_encounters(train_num="3", db_path=db_file)
    assert len(q_train) == 1
    q_vision = db.query_encounters(vision_confirmed=True, db_path=db_file)
    assert len(q_vision) == 1

    # Analytics from DB
    analytics = db.get_encounter_analytics_db(db_path=db_file)
    assert analytics["total_completed"] == 1
    assert analytics["peak_speed_mph"] == 79.5
    assert analytics["fastest_train"]["train_num"] == "3"
    assert analytics["closest_cpa_miles"] == 0.25

    # 2. Vision Detections CRUD
    vis1 = {
        "frame_id": "frm_cam_perryville_1001",
        "timestamp": t0 - 10,
        "cam_id": "cam_perryville_amtrak",
        "camera_name": "Perryville Amtrak Station",
        "scene_classification": "TRAIN_IN_FRAME",
        "track_status": "OCCUPIED",
        "train_present": True,
        "train_summary": {
            "train_num": "3",
            "route": "Southwest Chief",
            "agency": "Amtrak",
            "speed_mph": 79.5,
            "total_consist_units": 9,
            "total_axles": 36,
        },
        "total_bounding_boxes": 3,
        "detected_units": [{"unit_id": "ALC-42-301", "name": "Siemens Charger"}],
        "optical_speed_estimate_mph": 78.0,
        "optical_direction": "Eastbound",
        "lead_unit": "Siemens Charger",
        "lead_cab_number": "AMTK 3",
        "inference_time_ms": 22.5,
    }
    assert db.save_vision_detection(vis1, db_path=db_file) is True

    loaded_vis = db.get_vision_detection("frm_cam_perryville_1001", db_path=db_file)
    assert loaded_vis is not None
    assert loaded_vis["cam_id"] == "cam_perryville_amtrak"
    assert loaded_vis["train_present"] is True
    assert len(loaded_vis["detected_units"]) == 1

    q_vis = db.query_vision_detections(cam_id="cam_perryville_amtrak", db_path=db_file)
    assert len(q_vis) == 1

    # 3. Breadcrumbs CRUD
    assert db.save_breadcrumb("3", -76.07, 39.55, speed_mph=79.5, heading=65.0, timestamp=t0 - 10, db_path=db_file) is True
    assert db.save_breadcrumb("3", -76.06, 39.56, speed_mph=80.0, heading=65.0, timestamp=t0 - 5, db_path=db_file) is True

    crumbs = db.get_breadcrumbs_for_train("3", db_path=db_file)
    assert len(crumbs) == 2
    assert crumbs[0] == [-76.07, 39.55]
    assert crumbs[1] == [-76.06, 39.56]

    all_crumbs = db.load_all_recent_breadcrumbs(max_age_seconds=3600.0, db_path=db_file)
    assert "3" in all_crumbs
    assert len(all_crumbs["3"]) == 2

    # 4. DB Stats
    stats = db.get_db_stats(db_path=db_file)
    assert stats["status"] == "ready"
    assert stats["total_encounters"] == 1
    assert stats["completed_encounters"] == 1
    assert stats["total_vision_detections"] == 1
    assert stats["total_breadcrumbs"] == 2
    assert stats["db_size_bytes"] > 0

    # 5. Pruning
    pruned = db.prune_db(max_age_days=0.0, db_path=db_file)  # prune everything older than right now
    assert pruned["deleted_encounters"] >= 1
    assert pruned["deleted_vision_detections"] >= 1
    assert pruned["deleted_breadcrumbs"] >= 2


def test_sqlite_persistence_and_restart_survivability(client, monkeypatch):
    """Verify end-to-end SQLite persistence across server restarts and in-memory wipes."""
    from server import (
        encounter_tracker,
        stream_vision_engine,
        _breadcrumb_history,
        _breadcrumb_last_seen,
        hydrate_breadcrumbs_from_db,
    )
    import db
    import server
    # Mock transit fetch to avoid slow external HTTP requests during test
    monkeypatch.setattr(server, "fetch_live_train_geojson", lambda: {"type": "FeatureCollection", "features": []})

    # Clear tables and in-memory tracker for clean test isolation
    db.clear_all_tables()
    encounter_tracker.history.clear()
    encounter_tracker.active_sessions.clear()
    encounter_tracker.persist_db = True
    stream_vision_engine.detector.persist_db = True

    # 1. Verify /health and /api/db/stats expose database metrics
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    health_data = resp_health.json()
    assert "database" in health_data
    assert health_data["database"]["status"] in ("ready", "uninitialized")

    resp_db = client.get("/api/db/stats")
    assert resp_db.status_code == 200
    db_stats = resp_db.json()
    assert db_stats["status"] == "ready"
    assert "total_encounters" in db_stats

    # 2. Trigger on-demand vision sample and confirm it writes to SQLite
    resp_sample = client.post("/api/vision/sample?cam_id=cam_horseshoe_curve&train_num=42")
    assert resp_sample.status_code == 200
    sample_frame = resp_sample.json()
    frame_id = sample_frame["frame_id"]

    # Verify frame lookup via API
    resp_frame = client.get(f"/api/vision/detections/frame/{frame_id}")
    assert resp_frame.status_code == 200
    assert resp_frame.json()["frame_id"] == frame_id

    # 3. Simulate an encounter lifecycle in encounter_tracker
    t_now = time.time()
    mock_events = [
        {
            "train": {"train_num": "49", "route": "Lake Shore Limited", "speed_mph": 58.0},
            "camera": {"cam_id": "cam_rochelle_diamond", "name": "Rochelle Railroad Park", "location": "Rochelle, IL"},
            "distance_miles": 1.8,
            "trajectory": "approaching",
        }
    ]
    encounter_tracker.update(mock_events, timestamp=t_now)
    actives = encounter_tracker.get_active_encounters()
    assert len(actives) >= 1
    active_enc = next(e for e in actives if e["train_num"] == "49")
    enc_id = active_enc["encounter_id"]

    # Encounter lookup endpoint
    resp_enc = client.get(f"/api/encounters/{enc_id}")
    assert resp_enc.status_code == 200
    assert resp_enc.json()["encounter_id"] == enc_id

    # Complete the encounter (train moves > 5 miles)
    encounter_tracker.update([], timestamp=t_now + 180.0)

    # Add a breadcrumb to memory
    _breadcrumb_history["49"] = deque([[-89.06, 41.92], [-89.05, 41.93]], maxlen=15)
    _breadcrumb_last_seen["49"] = t_now
    db.save_breadcrumb("49", -89.06, 41.92, speed_mph=58.0, heading=90.0, timestamp=t_now)
    db.save_breadcrumb("49", -89.05, 41.93, speed_mph=58.0, heading=90.0, timestamp=t_now + 15)

    # 4. SIMULATE SERVER CRASH / RESTART: Wipe all in-memory structures completely
    encounter_tracker.history.clear()
    encounter_tracker.active_sessions.clear()
    stream_vision_engine.detector.history.clear()
    stream_vision_engine.detector.total_frames_processed = 0
    stream_vision_engine.detector.total_detections_logged = 0
    _breadcrumb_history.clear()
    _breadcrumb_last_seen.clear()

    assert len(encounter_tracker.history) == 0
    assert len(stream_vision_engine.detector.history) == 0
    assert len(_breadcrumb_history) == 0

    # 5. Verify SQLite retrieval works directly after memory wipe
    resp_hist_after_wipe = client.get("/api/encounters/history")
    assert resp_hist_after_wipe.status_code == 200
    hist_items = resp_hist_after_wipe.json()
    assert len(hist_items) >= 1
    assert any(e["encounter_id"] == enc_id for e in hist_items)

    resp_crumbs_after_wipe = client.get("/api/breadcrumbs?train_id=49")
    assert resp_crumbs_after_wipe.status_code == 200
    crumb_features = resp_crumbs_after_wipe.json()["features"]
    assert len(crumb_features) == 1
    assert len(crumb_features[0]["geometry"]["coordinates"]) == 2

    # 6. Hydration test: reload from DB and confirm memory structures are populated
    encounter_tracker.hydrate_from_db()
    assert len(encounter_tracker.history) >= 1
    assert any(e["encounter_id"] == enc_id for e in encounter_tracker.history)

    stream_vision_engine.detector.hydrate_from_db()
    assert len(stream_vision_engine.detector.history) >= 1

    hydrate_breadcrumbs_from_db()
    assert "49" in _breadcrumb_history
    assert len(_breadcrumb_history["49"]) == 2

    # 7. Test maintenance prune endpoint
    resp_prune = client.post("/api/maintenance/prune?max_age_days=30.0")
    assert resp_prune.status_code == 200
    prune_data = resp_prune.json()
    assert prune_data["status"] == "success"
    assert "pruned" in prune_data

















