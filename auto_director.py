"""Highball Auto-Director & Intelligent Cam-Switching Engine.

Ranks active spatial encounters to determine the single most compelling live webcam feed
for automated railfan viewing, prioritizing imminent closing encounters (<3 miles).
Rotates scenic landmark webcams during quiet track windows.
"""

import time
from typing import Any, Dict, List, Optional
from cam_lookup import PUBLIC_RAIL_CAMS

# Scenic fallback cams for quiet track windows
SCENIC_ROTATION = ["cam_horseshoe_curve", "cam_tehachapi_loop", "cam_rochelle_diamond"]


def score_encounter(event: Dict[str, Any]) -> float:
    """Scores a proximity encounter based on trajectory, distance, and speed.

    Higher score indicates higher priority for live viewing.
    """
    trajectory = event.get("trajectory", "unknown")
    dist = event.get("distance_miles", 99.0)
    speed = event.get("train", {}).get("speed_mph", 0.0)

    score = 0.0
    # Trajectory base weighting
    if trajectory == "approaching":
        score += 100.0
    elif trajectory == "passing":
        score += 40.0
    elif trajectory == "receding":
        score += 10.0

    # Distance penalty: closer is much better
    score += max(0.0, (15.0 - dist) * 5.0)

    # Imminent arrival bonus (< 3.0 miles closing in)
    if trajectory == "approaching" and dist <= 3.0:
        score += 60.0

    # High-speed action bonus
    if speed >= 50.0:
        score += 15.0

    return round(score, 1)


def select_director_camera(proximity_events: List[Dict[str, Any]], timestamp: Optional[float] = None) -> Dict[str, Any]:
    """Selects the highest priority camera to watch right now based on active encounters."""
    now = timestamp or time.time()

    if proximity_events:
        scored_events = []
        for ev in proximity_events:
            s = score_encounter(ev)
            scored_events.append((s, ev))

        scored_events.sort(key=lambda x: x[0], reverse=True)
        top_score, best_event = scored_events[0]

        # Only trigger intercept mode if score is sufficiently compelling (> 50 pts)
        if top_score >= 50.0:
            cam = best_event["camera"]
            train = best_event["train"]
            dist = best_event["distance_miles"]
            traj = best_event["trajectory"]
            eta = best_event.get("eta_minutes")

            reason = (
                f"Train #{train['train_num']} ({train['route']}) is {dist} mi away "
                f"{traj.upper()} {cam['name']} at {train['speed_mph']} mph"
            )
            if eta:
                reason += f" (ETA ~{eta}m)"

            return {
                "mode": "intercept",
                "priority_score": top_score,
                "camera": cam,
                "encounter": best_event,
                "reason": reason,
                "timestamp": now,
            }

    # Quiet window: fallback to scenic rotation (switches every 10 minutes)
    rotation_index = int((now // 600) % len(SCENIC_ROTATION))
    chosen_id = SCENIC_ROTATION[rotation_index]
    scenic_cam = next((c for c in PUBLIC_RAIL_CAMS if c["cam_id"] == chosen_id), PUBLIC_RAIL_CAMS[0])

    return {
        "mode": "scenic_patrol",
        "priority_score": 0.0,
        "camera": scenic_cam,
        "encounter": None,
        "reason": f"No imminent rail encounters; auto-patrolling scenic landmark: {scenic_cam['name']}",
        "timestamp": now,
    }


if __name__ == "__main__":
    sample_events = [
        {
            "train": {"train_num": "3", "route": "Southwest Chief", "speed_mph": 65.0},
            "camera": PUBLIC_RAIL_CAMS[4],  # Flagstaff
            "distance_miles": 2.1,
            "trajectory": "approaching",
            "eta_minutes": 1.9,
        }
    ]
    res = select_director_camera(sample_events)
    print("[*] Director Decision:")
    print("  Mode:", res["mode"])
    print("  Camera:", res["camera"]["name"])
    print("  Reason:", res["reason"])
