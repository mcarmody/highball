"""Highball Historical Encounter Tracker & Flyby Logger.

Tracks active camera encounters and persists completed flybys to a ring buffer:
- Tracks closest point of approach (CPA)
- Records peak transit speed through camera visual zone (<5 miles)
- Computes encounter duration and direction
"""

import time
from collections import deque
from typing import Any, Dict, List, Optional


class EncounterTracker:
    def __init__(self, max_history: int = 50, encounter_radius_miles: float = 5.0):
        self.max_history = max_history
        self.radius = encounter_radius_miles
        # Key: f"{train_num}:{cam_id}" -> active session dict
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.history: deque = deque(maxlen=max_history)

    def _session_key(self, train_num: str, cam_id: str) -> str:
        return f"{train_num}:{cam_id}"

    def update(self, current_proximity_events: List[Dict[str, Any]], timestamp: Optional[float] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Updates active encounter sessions and closes sessions when trains leave zone."""
        now = timestamp or time.time()
        seen_keys = set()
        new_sessions = []
        completed_sessions = []

        for ev in current_proximity_events:
            dist = ev.get("distance_miles", 99.0)
            if dist > self.radius:
                continue

            train = ev.get("train", {})
            cam = ev.get("camera", {})
            train_num = str(train.get("train_num", "unknown"))
            cam_id = str(cam.get("cam_id", "unknown"))
            key = self._session_key(train_num, cam_id)
            seen_keys.add(key)

            speed = float(train.get("speed_mph", 0.0))

            if key not in self.active_sessions:
                # Initiate new encounter session
                sess = {
                    "encounter_id": f"enc_{train_num}_{cam_id}_{int(now)}",
                    "train_num": train_num,
                    "route": train.get("route", "Unknown Route"),
                    "camera_id": cam_id,
                    "camera_name": cam.get("name", cam_id),
                    "location": cam.get("location", ""),
                    "provider": cam.get("provider", "Trackside Host"),
                    "stream_url": cam.get("stream_url", ""),
                    "embed_url": cam.get("embed_url", ""),
                    "start_time": now,
                    "start_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                    "last_seen": now,
                    "closest_distance_miles": dist,
                    "peak_speed_mph": speed,
                    "trajectory_entry": ev.get("trajectory", "unknown"),
                    "status": "in_progress",
                }
                self.active_sessions[key] = sess
                new_sessions.append(sess)
            else:
                # Update existing session
                sess = self.active_sessions[key]
                sess["last_seen"] = now
                if dist < sess["closest_distance_miles"]:
                    sess["closest_distance_miles"] = dist
                if speed > sess["peak_speed_mph"]:
                    sess["peak_speed_mph"] = speed

        # Finalize sessions that left the proximity zone or timed out (> 5 min unseen)
        completed_keys = []
        for key, sess in self.active_sessions.items():
            if key not in seen_keys or (now - sess["last_seen"] > 300.0):
                sess["status"] = "completed"
                sess["end_time"] = now
                sess["duration_seconds"] = round(now - sess["start_time"], 1)
                self.history.append(sess)
                completed_sessions.append(sess)
                completed_keys.append(key)

        for k in completed_keys:
            del self.active_sessions[k]

        return {"new": new_sessions, "completed": completed_sessions}

    def get_recent_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Returns completed encounter history ordered newest-first."""
        return list(self.history)[-limit:][::-1]

    def get_active_encounters(self) -> List[Dict[str, Any]]:
        """Returns all encounters currently in progress."""
        return list(self.active_sessions.values())

    def get_analytics(self) -> Dict[str, Any]:
        """Calculates aggregate flyby analytics across completed encounter history and active sessions."""
        all_completed = list(self.history)
        total_completed = len(all_completed)

        if total_completed == 0:
            return {
                "total_completed": 0,
                "active_count": len(self.active_sessions),
                "peak_speed_mph": 0.0,
                "fastest_train": None,
                "closest_cpa_miles": None,
                "closest_train": None,
                "avg_duration_seconds": 0.0,
                "busiest_camera": None,
                "busiest_cameras": [],
            }

        fastest = max(all_completed, key=lambda s: s.get("peak_speed_mph", 0.0))
        closest = min(all_completed, key=lambda s: s.get("closest_distance_miles", 99.0))
        durations = [s.get("duration_seconds", 0.0) for s in all_completed if s.get("duration_seconds", 0.0) > 0]
        avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

        # Tally cam counts
        cam_counts: Dict[str, Dict[str, Any]] = {}
        for s in all_completed:
            cid = s.get("camera_id", "unknown")
            if cid not in cam_counts:
                cam_counts[cid] = {
                    "camera_id": cid,
                    "name": s.get("camera_name", cid),
                    "count": 0,
                }
            cam_counts[cid]["count"] += 1

        sorted_cams = sorted(cam_counts.values(), key=lambda c: c["count"], reverse=True)
        top_cam = sorted_cams[0] if sorted_cams else None

        return {
            "total_completed": total_completed,
            "active_count": len(self.active_sessions),
            "peak_speed_mph": fastest.get("peak_speed_mph", 0.0),
            "fastest_train": {
                "train_num": fastest.get("train_num"),
                "route": fastest.get("route"),
                "camera_name": fastest.get("camera_name"),
                "speed_mph": fastest.get("peak_speed_mph"),
            },
            "closest_cpa_miles": closest.get("closest_distance_miles"),
            "closest_train": {
                "train_num": closest.get("train_num"),
                "route": closest.get("route"),
                "camera_name": closest.get("camera_name"),
                "distance_miles": closest.get("closest_distance_miles"),
            },
            "avg_duration_seconds": avg_duration,
            "busiest_camera": top_cam,
            "busiest_cameras": sorted_cams[:5],
        }


if __name__ == "__main__":
    tracker = EncounterTracker(encounter_radius_miles=5.0)
    t0 = time.time()
    mock_events = [
        {
            "train": {"train_num": "4", "route": "Southwest Chief", "speed_mph": 60.0},
            "camera": {"cam_id": "cam_flagstaff_depot", "name": "Flagstaff Historic Depot", "location": "Flagstaff, AZ"},
            "distance_miles": 2.5,
            "trajectory": "approaching",
        }
    ]
    tracker.update(mock_events, timestamp=t0)
    print("[*] Active Sessions:", tracker.get_active_encounters())

    # Simulate train passing and departing (>5 miles)
    tracker.update([], timestamp=t0 + 120.0)
    print("[*] Completed History:", tracker.get_recent_history())
