"""SQLite Persistent Archival, Indexing, and Query Engine for Project Highball.

Provides durable storage, indexing, and restart survivability for rail operations:
- Encounters: Flyby sessions, trajectory, CPA, peak speed, rolling stock consist, defect reports
- Vision Detections: Trackside computer vision detections, bounding boxes, optical speed estimates
- GPS Breadcrumbs: Train position history for persistent GPS trails across restarts
- WAL journal mode, 5s busy timeout, and normal synchronous for zero-lock concurrency
- Dual-write integration with in-memory state and hydration on startup
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "highball.db"


def get_db_path(db_path: Optional[Union[Path, str]] = None) -> Path:
    """Resolve the active SQLite database path from argument or environment."""
    if db_path is not None:
        return Path(db_path)
    env_path = os.environ.get("HIGHBALL_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def get_db_connection(db_path: Optional[Union[Path, str]] = None) -> sqlite3.Connection:
    """Create and configure a SQLite connection with row factory, WAL mode, and busy timeouts."""
    resolved_path = get_db_path(db_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved_path), timeout=5.0)
    conn.row_factory = sqlite3.Row

    if "/tmp" in str(resolved_path) or "test" in str(resolved_path):
        conn.execute("PRAGMA synchronous = OFF;")
    else:
        conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def init_db(db_path: Optional[Union[Path, str]] = None) -> None:
    """Initialize SQLite tables, WAL journal mode, and performance indexes for Highball."""
    conn = get_db_connection(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        with conn:
            # 1. Encounters Table (Flybys & Intercept Sessions)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS encounters (
                    encounter_id TEXT PRIMARY KEY,
                    train_num TEXT NOT NULL,
                    route TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    location TEXT,
                    provider TEXT,
                    stream_url TEXT,
                    embed_url TEXT,
                    hls_manifest_url TEXT,
                    stream_resolution TEXT,
                    hls_stream_status TEXT,
                    start_time REAL NOT NULL,
                    start_time_iso TEXT NOT NULL,
                    last_seen REAL NOT NULL,
                    end_time REAL,
                    duration_seconds REAL DEFAULT 0.0,
                    closest_distance_miles REAL NOT NULL,
                    peak_speed_mph REAL NOT NULL,
                    trajectory_entry TEXT,
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    vision_confirmed INTEGER NOT NULL DEFAULT 0,
                    consist_json TEXT,
                    defect_report_json TEXT,
                    vision_detection_json TEXT,
                    metadata_json TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_encounters_cam_start
                ON encounters (camera_id, start_time DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_encounters_train_start
                ON encounters (train_num, start_time DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_encounters_status
                ON encounters (status, start_time DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_encounters_start_time
                ON encounters (start_time DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_encounters_vision
                ON encounters (vision_confirmed, start_time DESC);
                """
            )

            # 2. Vision Detections Table (Trackside CV frames & rolling stock detections)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_detections (
                    frame_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    timestamp_iso TEXT NOT NULL,
                    cam_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    location TEXT,
                    milepost TEXT,
                    subdivision TEXT,
                    stream_status TEXT,
                    resolution TEXT,
                    scene_classification TEXT NOT NULL,
                    track_status TEXT NOT NULL,
                    train_present INTEGER NOT NULL DEFAULT 0,
                    train_num TEXT,
                    route TEXT,
                    agency TEXT,
                    speed_mph REAL DEFAULT 0.0,
                    total_consist_units INTEGER DEFAULT 0,
                    total_axles INTEGER DEFAULT 0,
                    optical_speed_estimate_mph REAL DEFAULT 0.0,
                    optical_direction TEXT,
                    lead_unit TEXT,
                    lead_cab_number TEXT,
                    inference_time_ms REAL DEFAULT 0.0,
                    total_bounding_boxes INTEGER DEFAULT 0,
                    detected_units_json TEXT,
                    raw_json TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vision_cam_time
                ON vision_detections (cam_id, timestamp DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vision_time
                ON vision_detections (timestamp DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vision_train_present
                ON vision_detections (train_present, timestamp DESC);
                """
            )

            # 3. Breadcrumbs Table (Train GPS trails)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS breadcrumbs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    train_key TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    lon REAL NOT NULL,
                    lat REAL NOT NULL,
                    speed_mph REAL DEFAULT 0.0,
                    heading REAL DEFAULT 0.0,
                    agency TEXT,
                    route TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_breadcrumbs_train_time
                ON breadcrumbs (train_key, timestamp DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_breadcrumbs_time
                ON breadcrumbs (timestamp DESC);
                """
            )
    finally:
        conn.close()


# ============================================================================
# Encounters Persistence & Querying
# ============================================================================

def row_to_encounter_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert an encounters SQLite row into a rich Encounter dictionary."""
    consist = json.loads(row["consist_json"]) if row["consist_json"] else {}
    defect = json.loads(row["defect_report_json"]) if row["defect_report_json"] else None
    vision = json.loads(row["vision_detection_json"]) if row["vision_detection_json"] else None
    meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

    res = {
        "encounter_id": row["encounter_id"],
        "train_num": row["train_num"],
        "route": row["route"],
        "camera_id": row["camera_id"],
        "camera_name": row["camera_name"],
        "location": row["location"] or "",
        "provider": row["provider"] or "",
        "stream_url": row["stream_url"] or "",
        "embed_url": row["embed_url"] or "",
        "hls_manifest_url": row["hls_manifest_url"] or "",
        "stream_resolution": row["stream_resolution"] or "1080p60",
        "hls_stream_status": row["hls_stream_status"] or "active_live",
        "start_time": float(row["start_time"]),
        "start_time_iso": row["start_time_iso"],
        "last_seen": float(row["last_seen"]),
        "end_time": float(row["end_time"]) if row["end_time"] is not None else None,
        "duration_seconds": float(row["duration_seconds"]) if row["duration_seconds"] is not None else 0.0,
        "closest_distance_miles": float(row["closest_distance_miles"]),
        "peak_speed_mph": float(row["peak_speed_mph"]),
        "trajectory_entry": row["trajectory_entry"] or "unknown",
        "status": row["status"],
        "vision_confirmed": bool(row["vision_confirmed"]),
        "consist": consist,
        "defect_report": defect,
        "vision_detection": vision,
    }
    for k, v in meta.items():
        if k not in res:
            res[k] = v
    return res


def save_encounter(
    encounter: Dict[str, Any],
    db_path: Optional[Union[Path, str]] = None,
) -> bool:
    """Insert or update an encounter flyby session in SQLite."""
    encounter_id = str(encounter.get("encounter_id", ""))
    train_num = str(encounter.get("train_num", "unknown"))
    route = str(encounter.get("route", "Unknown Route"))
    camera_id = str(encounter.get("camera_id", "unknown"))
    camera_name = str(encounter.get("camera_name", camera_id))
    location = str(encounter.get("location", ""))
    provider = str(encounter.get("provider", "Trackside Host"))
    stream_url = str(encounter.get("stream_url", ""))
    embed_url = str(encounter.get("embed_url", ""))
    hls_manifest_url = str(encounter.get("hls_manifest_url", ""))
    stream_resolution = str(encounter.get("stream_resolution", "1080p60"))
    hls_stream_status = str(encounter.get("hls_stream_status", "active_live"))
    start_time = float(encounter.get("start_time", time.time()))
    start_time_iso = str(encounter.get("start_time_iso") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)))
    last_seen = float(encounter.get("last_seen", start_time))
    end_time = float(encounter["end_time"]) if encounter.get("end_time") is not None else None
    duration_seconds = float(encounter.get("duration_seconds", 0.0))
    closest_distance_miles = float(encounter.get("closest_distance_miles", 0.0))
    peak_speed_mph = float(encounter.get("peak_speed_mph", 0.0))
    trajectory_entry = str(encounter.get("trajectory_entry", "unknown"))
    status = str(encounter.get("status", "in_progress"))
    vision_confirmed = 1 if encounter.get("vision_confirmed") else 0

    consist_json = json.dumps(encounter.get("consist", {})) if encounter.get("consist") else None
    defect_report_json = json.dumps(encounter.get("defect_report", {})) if encounter.get("defect_report") else None
    vision_detection_json = json.dumps(encounter.get("vision_detection", {})) if encounter.get("vision_detection") else None

    # Capture extra metadata fields
    known_keys = {
        "encounter_id", "train_num", "route", "camera_id", "camera_name", "location",
        "provider", "stream_url", "embed_url", "hls_manifest_url", "stream_resolution",
        "hls_stream_status", "start_time", "start_time_iso", "last_seen", "end_time",
        "duration_seconds", "closest_distance_miles", "peak_speed_mph", "trajectory_entry",
        "status", "vision_confirmed", "consist", "defect_report", "vision_detection",
    }
    meta = {k: v for k, v in encounter.items() if k not in known_keys}
    metadata_json = json.dumps(meta) if meta else None

    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO encounters (
                    encounter_id, train_num, route, camera_id, camera_name,
                    location, provider, stream_url, embed_url, hls_manifest_url,
                    stream_resolution, hls_stream_status, start_time, start_time_iso,
                    last_seen, end_time, duration_seconds, closest_distance_miles,
                    peak_speed_mph, trajectory_entry, status, vision_confirmed,
                    consist_json, defect_report_json, vision_detection_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    encounter_id, train_num, route, camera_id, camera_name,
                    location, provider, stream_url, embed_url, hls_manifest_url,
                    stream_resolution, hls_stream_status, start_time, start_time_iso,
                    last_seen, end_time, duration_seconds, closest_distance_miles,
                    peak_speed_mph, trajectory_entry, status, vision_confirmed,
                    consist_json, defect_report_json, vision_detection_json, metadata_json,
                ),
            )
        return True
    except Exception as e:
        print(f"[db] error saving encounter {encounter_id}: {e}")
        return False
    finally:
        conn.close()


def get_encounter(
    encounter_id: str,
    db_path: Optional[Union[Path, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a single encounter session by its ID."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT * FROM encounters WHERE encounter_id = ?
            """,
            (encounter_id,),
        )
        row = cursor.fetchone()
        return row_to_encounter_dict(row) if row else None
    finally:
        conn.close()


def query_encounters(
    limit: int = 50,
    camera_id: Optional[str] = None,
    train_num: Optional[str] = None,
    status: Optional[str] = None,
    vision_confirmed: Optional[bool] = None,
    order: str = "desc",
    db_path: Optional[Union[Path, str]] = None,
) -> List[Dict[str, Any]]:
    """Query encounter sessions with indexed filtering and chronological ordering."""
    conn = get_db_connection(db_path)
    try:
        where_clauses = []
        params: List[Any] = []

        if camera_id:
            where_clauses.append("camera_id = ?")
            params.append(camera_id)
        if train_num:
            where_clauses.append("train_num = ?")
            params.append(str(train_num))
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        if vision_confirmed is not None:
            where_clauses.append("vision_confirmed = ?")
            params.append(1 if vision_confirmed else 0)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        order_direction = "DESC" if order.lower() == "desc" else "ASC"

        query_sql = f"""
            SELECT * FROM encounters
            {where_sql}
            ORDER BY start_time {order_direction}
            LIMIT ?
        """
        params.append(max(1, limit))

        cursor = conn.execute(query_sql, params)
        return [row_to_encounter_dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_encounter_analytics_db(db_path: Optional[Union[Path, str]] = None) -> Dict[str, Any]:
    """Calculate aggregate flyby analytics directly from persistent SQLite storage."""
    conn = get_db_connection(db_path)
    try:
        # Completed vs active count
        cursor_counts = conn.execute(
            """
            SELECT status, COUNT(*) as cnt FROM encounters GROUP BY status
            """
        )
        counts_map = {r["status"]: r["cnt"] for r in cursor_counts.fetchall()}
        total_completed = counts_map.get("completed", 0)
        active_count = counts_map.get("in_progress", 0)

        if total_completed == 0:
            return {
                "total_completed": 0,
                "active_count": active_count,
                "peak_speed_mph": 0.0,
                "fastest_train": None,
                "closest_cpa_miles": None,
                "closest_train": None,
                "avg_duration_seconds": 0.0,
                "busiest_camera": None,
                "busiest_cameras": [],
                "total_vision_confirmed": 0,
                "vision_confirmation_rate_pct": 0.0,
            }

        # Aggregate metrics for completed flybys
        cursor_agg = conn.execute(
            """
            SELECT
                MAX(peak_speed_mph) as max_speed,
                MIN(closest_distance_miles) as min_cpa,
                AVG(duration_seconds) as avg_duration,
                SUM(vision_confirmed) as vision_sum
            FROM encounters
            WHERE status = 'completed'
            """
        )
        agg_row = cursor_agg.fetchone()
        max_speed = float(agg_row["max_speed"] or 0.0)
        min_cpa = float(agg_row["min_cpa"] or 0.0)
        avg_dur = round(float(agg_row["avg_duration"] or 0.0), 1)
        vision_count = int(agg_row["vision_sum"] or 0)
        vision_pct = round(100.0 * vision_count / max(1, total_completed), 1)

        # Fastest train
        cursor_fastest = conn.execute(
            """
            SELECT train_num, route, camera_name, peak_speed_mph
            FROM encounters
            WHERE status = 'completed'
            ORDER BY peak_speed_mph DESC
            LIMIT 1
            """
        )
        fast_row = cursor_fastest.fetchone()
        fastest_train = {
            "train_num": fast_row["train_num"],
            "route": fast_row["route"],
            "camera_name": fast_row["camera_name"],
            "speed_mph": float(fast_row["peak_speed_mph"]),
        } if fast_row else None

        # Closest train
        cursor_closest = conn.execute(
            """
            SELECT train_num, route, camera_name, closest_distance_miles
            FROM encounters
            WHERE status = 'completed'
            ORDER BY closest_distance_miles ASC
            LIMIT 1
            """
        )
        close_row = cursor_closest.fetchone()
        closest_train = {
            "train_num": close_row["train_num"],
            "route": close_row["route"],
            "camera_name": close_row["camera_name"],
            "distance_miles": float(close_row["closest_distance_miles"]),
        } if close_row else None

        # Busiest cameras
        cursor_cams = conn.execute(
            """
            SELECT camera_id, camera_name as name, COUNT(*) as count
            FROM encounters
            WHERE status = 'completed'
            GROUP BY camera_id
            ORDER BY count DESC
            LIMIT 5
            """
        )
        busiest_cams = [dict(r) for r in cursor_cams.fetchall()]
        top_cam = busiest_cams[0] if busiest_cams else None

        return {
            "total_completed": total_completed,
            "active_count": active_count,
            "total_vision_confirmed": vision_count,
            "vision_confirmation_rate_pct": vision_pct,
            "peak_speed_mph": max_speed,
            "fastest_train": fastest_train,
            "closest_cpa_miles": min_cpa,
            "closest_train": closest_train,
            "avg_duration_seconds": avg_dur,
            "busiest_camera": top_cam,
            "busiest_cameras": busiest_cams,
        }
    finally:
        conn.close()


# ============================================================================
# Vision Detections Persistence & Querying
# ============================================================================

def row_to_vision_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a vision_detections SQLite row into a vision detection event dict."""
    detected_units = json.loads(row["detected_units_json"]) if row["detected_units_json"] else []
    raw = json.loads(row["raw_json"]) if row["raw_json"] else {}

    train_summary = None
    if row["train_present"]:
        train_summary = {
            "train_num": row["train_num"],
            "route": row["route"],
            "agency": row["agency"],
            "speed_mph": float(row["speed_mph"]),
            "total_consist_units": int(row["total_consist_units"]),
            "total_axles": int(row["total_axles"]),
        }

    res = {
        "frame_id": row["frame_id"],
        "timestamp": float(row["timestamp"]),
        "timestamp_iso": row["timestamp_iso"],
        "cam_id": row["cam_id"],
        "camera_name": row["camera_name"],
        "location": row["location"] or "",
        "milepost": row["milepost"] or "",
        "subdivision": row["subdivision"] or "",
        "stream_status": row["stream_status"] or "active_live",
        "resolution": row["resolution"] or "1080p60",
        "scene_classification": row["scene_classification"],
        "track_status": row["track_status"],
        "train_present": bool(row["train_present"]),
        "train_summary": train_summary,
        "total_bounding_boxes": int(row["total_bounding_boxes"]),
        "detected_units": detected_units,
        "optical_speed_estimate_mph": float(row["optical_speed_estimate_mph"]),
        "optical_direction": row["optical_direction"],
        "lead_unit": row["lead_unit"],
        "lead_cab_number": row["lead_cab_number"],
        "inference_time_ms": float(row["inference_time_ms"]),
    }
    for k, v in raw.items():
        if k not in res:
            res[k] = v
    return res


def save_vision_detection(
    detection: Dict[str, Any],
    db_path: Optional[Union[Path, str]] = None,
) -> bool:
    """Insert or update a trackside CV detection event in SQLite."""
    frame_id = str(detection.get("frame_id", ""))
    timestamp = float(detection.get("timestamp", time.time()))
    timestamp_iso = str(detection.get("timestamp_iso") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)))
    cam_id = str(detection.get("cam_id", ""))
    camera_name = str(detection.get("camera_name", cam_id))
    location = str(detection.get("location", ""))
    milepost = str(detection.get("milepost", ""))
    subdivision = str(detection.get("subdivision", ""))
    stream_status = str(detection.get("stream_status", "active_live"))
    resolution = str(detection.get("resolution", "1080p60"))
    scene_classification = str(detection.get("scene_classification", "TRAIN_IN_FRAME"))
    track_status = str(detection.get("track_status", "OCCUPIED"))
    train_present = 1 if detection.get("train_present") else 0

    ts = detection.get("train_summary") or {}
    train_num = str(ts.get("train_num", "")) if ts else None
    route = str(ts.get("route", "")) if ts else None
    agency = str(ts.get("agency", "")) if ts else None
    speed_mph = float(ts.get("speed_mph", 0.0)) if ts else 0.0
    total_consist_units = int(ts.get("total_consist_units", 0)) if ts else 0
    total_axles = int(ts.get("total_axles", 0)) if ts else 0

    optical_speed_estimate_mph = float(detection.get("optical_speed_estimate_mph", 0.0))
    optical_direction = detection.get("optical_direction")
    lead_unit = detection.get("lead_unit")
    lead_cab_number = detection.get("lead_cab_number")
    inference_time_ms = float(detection.get("inference_time_ms", 0.0))
    total_bounding_boxes = int(detection.get("total_bounding_boxes", 0))

    detected_units_json = json.dumps(detection.get("detected_units", []))
    raw_json = json.dumps(detection)

    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vision_detections (
                    frame_id, timestamp, timestamp_iso, cam_id, camera_name,
                    location, milepost, subdivision, stream_status, resolution,
                    scene_classification, track_status, train_present, train_num,
                    route, agency, speed_mph, total_consist_units, total_axles,
                    optical_speed_estimate_mph, optical_direction, lead_unit,
                    lead_cab_number, inference_time_ms, total_bounding_boxes,
                    detected_units_json, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    frame_id, timestamp, timestamp_iso, cam_id, camera_name,
                    location, milepost, subdivision, stream_status, resolution,
                    scene_classification, track_status, train_present, train_num,
                    route, agency, speed_mph, total_consist_units, total_axles,
                    optical_speed_estimate_mph, optical_direction, lead_unit,
                    lead_cab_number, inference_time_ms, total_bounding_boxes,
                    detected_units_json, raw_json,
                ),
            )
        return True
    except Exception as e:
        print(f"[db] error saving vision detection {frame_id}: {e}")
        return False
    finally:
        conn.close()


def get_vision_detection(
    frame_id: str,
    db_path: Optional[Union[Path, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a single vision detection frame by ID."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT * FROM vision_detections WHERE frame_id = ?
            """,
            (frame_id,),
        )
        row = cursor.fetchone()
        return row_to_vision_dict(row) if row else None
    finally:
        conn.close()


def query_vision_detections(
    limit: int = 50,
    cam_id: Optional[str] = None,
    train_present_only: bool = False,
    order: str = "desc",
    db_path: Optional[Union[Path, str]] = None,
) -> List[Dict[str, Any]]:
    """Query trackside computer vision detections with filtering and ordering."""
    conn = get_db_connection(db_path)
    try:
        where_clauses = []
        params: List[Any] = []

        if cam_id:
            where_clauses.append("cam_id = ?")
            params.append(cam_id)
        if train_present_only:
            where_clauses.append("train_present = 1")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        order_direction = "DESC" if order.lower() == "desc" else "ASC"

        query_sql = f"""
            SELECT * FROM vision_detections
            {where_sql}
            ORDER BY timestamp {order_direction}
            LIMIT ?
        """
        params.append(max(1, limit))

        cursor = conn.execute(query_sql, params)
        return [row_to_vision_dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================================
# Breadcrumbs Persistence & Querying
# ============================================================================

def save_breadcrumb(
    train_key: str,
    lon: float,
    lat: float,
    speed_mph: float = 0.0,
    heading: float = 0.0,
    agency: str = "",
    route: str = "",
    timestamp: Optional[float] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> bool:
    """Record a single train GPS coordinate fix into SQLite."""
    t = timestamp or time.time()
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO breadcrumbs (
                    train_key, timestamp, lon, lat, speed_mph, heading, agency, route
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (train_key, t, round(lon, 5), round(lat, 5), float(speed_mph), float(heading), agency, route),
            )
        return True
    except Exception as e:
        print(f"[db] error saving breadcrumb for {train_key}: {e}")
        return False
    finally:
        conn.close()


def save_breadcrumbs_batch(
    records: List[Dict[str, Any]],
    db_path: Optional[Union[Path, str]] = None,
) -> int:
    """Batch-insert multiple train coordinate fixes inside a single transaction."""
    if not records:
        return 0
    now = time.time()
    conn = get_db_connection(db_path)
    try:
        with conn:
            rows = [
                (
                    str(r["train_key"]),
                    float(r.get("timestamp", now)),
                    round(float(r["lon"]), 5),
                    round(float(r["lat"]), 5),
                    float(r.get("speed_mph", 0.0)),
                    float(r.get("heading", 0.0)),
                    str(r.get("agency", "")),
                    str(r.get("route", "")),
                )
                for r in records
            ]
            cursor = conn.executemany(
                """
                INSERT INTO breadcrumbs (
                    train_key, timestamp, lon, lat, speed_mph, heading, agency, route
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return cursor.rowcount
    except Exception as e:
        print(f"[db] error batch saving breadcrumbs: {e}")
        return 0
    finally:
        conn.close()


def get_breadcrumbs_for_train(
    train_key: str,
    limit: int = 15,
    db_path: Optional[Union[Path, str]] = None,
) -> List[List[float]]:
    """Retrieve the recent GPS breadcrumb trail [lon, lat] for a specific train in chronological order."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT lon, lat FROM breadcrumbs
            WHERE train_key = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (train_key, limit),
        )
        rows = cursor.fetchall()
        # Return oldest to newest to form continuous path
        coords = [[r["lon"], r["lat"]] for r in reversed(rows)]
        return coords
    finally:
        conn.close()


def load_all_recent_breadcrumbs(
    max_age_seconds: float = 1800.0,
    limit_per_train: int = 15,
    db_path: Optional[Union[Path, str]] = None,
) -> Dict[str, List[List[float]]]:
    """Hydrates active in-memory breadcrumbs for all trains seen in the last max_age_seconds."""
    cutoff = time.time() - max_age_seconds
    conn = get_db_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT train_key, lon, lat, timestamp
            FROM breadcrumbs
            WHERE timestamp >= ?
            ORDER BY train_key, timestamp ASC
            """,
            (cutoff,),
        )
        grouped: Dict[str, List[List[float]]] = {}
        for r in cursor.fetchall():
            tk = r["train_key"]
            if tk not in grouped:
                grouped[tk] = []
            grouped[tk].append([r["lon"], r["lat"]])

        # Cap each train to the most recent limit_per_train
        return {tk: pts[-limit_per_train:] for tk, pts in grouped.items()}
    finally:
        conn.close()


# ============================================================================
# DB Diagnostics, Maintenance, and Pruning
# ============================================================================

def get_db_stats(db_path: Optional[Union[Path, str]] = None) -> Dict[str, Any]:
    """Retrieve database metrics, file size, and record counts."""
    resolved_path = get_db_path(db_path)
    if not resolved_path.exists():
        return {
            "status": "uninitialized",
            "db_path": str(resolved_path),
            "total_encounters": 0,
            "active_encounters": 0,
            "completed_encounters": 0,
            "total_vision_detections": 0,
            "total_breadcrumbs": 0,
            "db_size_bytes": 0,
            "db_size_mb": 0.0,
        }

    conn = get_db_connection(db_path)
    try:
        # Encounters counts
        c_enc = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                MIN(start_time) as oldest,
                MAX(start_time) as newest
            FROM encounters
            """
        ).fetchone()

        # Vision detections count
        c_vis = conn.execute("SELECT COUNT(*) as total FROM vision_detections").fetchone()

        # Breadcrumbs count
        c_crumbs = conn.execute("SELECT COUNT(*) as total FROM breadcrumbs").fetchone()

        size_bytes = resolved_path.stat().st_size
        return {
            "status": "ready",
            "db_path": str(resolved_path),
            "total_encounters": c_enc["total"] if c_enc else 0,
            "active_encounters": c_enc["active"] or 0 if c_enc else 0,
            "completed_encounters": c_enc["completed"] or 0 if c_enc else 0,
            "total_vision_detections": c_vis["total"] if c_vis else 0,
            "total_breadcrumbs": c_crumbs["total"] if c_crumbs else 0,
            "db_size_bytes": size_bytes,
            "db_size_mb": round(size_bytes / (1024 * 1024), 2),
            "oldest_encounter_time": c_enc["oldest"] if c_enc else None,
            "newest_encounter_time": c_enc["newest"] if c_enc else None,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "db_path": str(resolved_path),
            "total_encounters": 0,
            "active_encounters": 0,
            "completed_encounters": 0,
            "total_vision_detections": 0,
            "total_breadcrumbs": 0,
            "db_size_bytes": 0,
            "db_size_mb": 0.0,
        }
    finally:
        conn.close()


def prune_db(
    max_age_days: float = 30.0,
    db_path: Optional[Union[Path, str]] = None,
) -> Dict[str, int]:
    """Prune encounter sessions, vision detections, and breadcrumbs older than max_age_days."""
    cutoff_time = time.time() - (max_age_days * 86400.0)
    conn = get_db_connection(db_path)
    try:
        with conn:
            c1 = conn.execute("DELETE FROM encounters WHERE start_time < ?", (cutoff_time,))
            deleted_enc = c1.rowcount

            c2 = conn.execute("DELETE FROM vision_detections WHERE timestamp < ?", (cutoff_time,))
            deleted_vis = c2.rowcount

            c3 = conn.execute("DELETE FROM breadcrumbs WHERE timestamp < ?", (cutoff_time,))
            deleted_crumbs = c3.rowcount

        return {
            "deleted_encounters": deleted_enc,
            "deleted_vision_detections": deleted_vis,
            "deleted_breadcrumbs": deleted_crumbs,
        }
    finally:
        conn.close()


def clear_all_tables(db_path: Optional[Union[Path, str]] = None) -> None:
    """Clear all records from all tables (used for test isolation)."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM encounters;")
            conn.execute("DELETE FROM vision_detections;")
            conn.execute("DELETE FROM breadcrumbs;")
    finally:
        conn.close()
