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













