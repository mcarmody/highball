"""Trackside YOLO Consist Perception & Automated Defect Detector Engine for Project Highball.

Identifies, catalogs, and simulates rolling stock consist composition and trackside
automated defect detector (HBD/DED) radio telemetry for continental rail operations:
- Classifies motive power (ALC-42 Charger, P42DC Genesis, ACS-64, ES44AC, SD70ACe, F40PH)
- Catalogs passenger coaches, sleepers, lounges, diners, and freight rolling stock
- Calculates total axles, estimated train length (ft), gross tonnage, and consist breakdown
- Generates authentic trackside Automated Defect Detector radio transcripts (Milepost, Track, Axles, Temp)
"""

import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple


# Known locomotive equipment specifications
LOCOMOTIVE_SPECS = {
    "ALC-42": {"name": "Siemens ALC-42 Charger", "axles": 4, "hp": 4400, "weight_tons": 134, "length_ft": 75, "category": "locomotive"},
    "P42DC": {"name": "GE P42DC Genesis", "axles": 4, "hp": 4250, "weight_tons": 134, "length_ft": 69, "category": "locomotive"},
    "ACS-64": {"name": "Siemens ACS-64 Cities Sprinter", "axles": 4, "hp": 6700, "weight_tons": 108, "length_ft": 67, "category": "locomotive"},
    "Acela_Power": {"name": "Avelia Liberty High-Speed Power Car", "axles": 4, "hp": 6000, "weight_tons": 102, "length_ft": 66, "category": "locomotive"},
    "ES44AC": {"name": "GE ES44AC GEVO Freight", "axles": 6, "hp": 4400, "weight_tons": 210, "length_ft": 73, "category": "locomotive"},
    "SD70ACe": {"name": "EMD SD70ACe Freight", "axles": 6, "hp": 4300, "weight_tons": 214, "length_ft": 74, "category": "locomotive"},
    "F40PH": {"name": "EMD F40PH Commuter", "axles": 4, "hp": 3000, "weight_tons": 130, "length_ft": 56, "category": "locomotive"},
}

# Known passenger and freight rolling stock specifications
CAR_SPECS = {
    "Amfleet_Coach": {"name": "Amfleet I/II Coach", "axles": 4, "weight_tons": 55, "length_ft": 85, "category": "coach", "glyph": "🚃"},
    "Amfleet_Cafe": {"name": "Amfleet I Cafe/Lounge", "axles": 4, "weight_tons": 56, "length_ft": 85, "category": "food_service", "glyph": "☕"},
    "Superliner_Coach": {"name": "Superliner II Coach (Bi-Level)", "axles": 4, "weight_tons": 74, "length_ft": 85, "category": "coach", "glyph": "🚃"},
    "Superliner_Sleeper": {"name": "Superliner II Sleeper (Bi-Level)", "axles": 4, "weight_tons": 75, "length_ft": 85, "category": "sleeper", "glyph": "🛏️"},
    "Superliner_Lounge": {"name": "Superliner Sightseer Lounge", "axles": 4, "weight_tons": 76, "length_ft": 85, "category": "lounge", "glyph": "🔭"},
    "Superliner_Diner": {"name": "Superliner Cross-Country Diner", "axles": 4, "weight_tons": 76, "length_ft": 85, "category": "food_service", "glyph": "🍽️"},
    "Viewliner_Sleeper": {"name": "Viewliner II Sleeper", "axles": 4, "weight_tons": 65, "length_ft": 85, "category": "sleeper", "glyph": "🛏️"},
    "Viewliner_Baggage": {"name": "Viewliner II Baggage Car", "axles": 4, "weight_tons": 50, "length_ft": 85, "category": "baggage", "glyph": "🧳"},
    "Acela_Coach": {"name": "Avelia Liberty High-Speed Coach", "axles": 4, "weight_tons": 52, "length_ft": 82, "category": "coach", "glyph": "🚅"},
    "Acela_Cafe": {"name": "Avelia Liberty Cafe Club", "axles": 4, "weight_tons": 54, "length_ft": 82, "category": "food_service", "glyph": "☕"},
    "Venture_Coach": {"name": "Siemens Venture Coach", "axles": 4, "weight_tons": 53, "length_ft": 85, "category": "coach", "glyph": "🚃"},
    "Gallery_BiLevel": {"name": "Gallery Bi-Level Commuter Coach", "axles": 4, "weight_tons": 62, "length_ft": 85, "category": "commuter", "glyph": "🚈"},
    "Caltrain_EMU": {"name": "Stadler KISS Electric Multiple Unit", "axles": 4, "weight_tons": 60, "length_ft": 85, "category": "commuter", "glyph": "⚡"},
    "Intermodal_Well": {"name": "Double-Stack Intermodal Well Car", "axles": 4, "weight_tons": 95, "length_ft": 65, "category": "freight_intermodal", "glyph": "📦"},
    "Autorack_TriLevel": {"name": "Enclosed Tri-Level Autorack", "axles": 4, "weight_tons": 50, "length_ft": 90, "category": "freight_auto", "glyph": "🚗"},
    "Covered_Hopper": {"name": "Grain / Mineral Covered Hopper", "axles": 4, "weight_tons": 125, "length_ft": 60, "category": "freight_bulk", "glyph": "🌾"},
    "Tank_Car": {"name": "DOT-117 General Service Tank Car", "axles": 4, "weight_tons": 130, "length_ft": 55, "category": "freight_tank", "glyph": "🛢️"},
    "Boxcar": {"name": "Standard 50ft Boxcar", "axles": 4, "weight_tons": 110, "length_ft": 55, "category": "freight_box", "glyph": "📦"},
}


def _derive_seed(train_num: str, route: str, agency: str) -> int:
    """Generate a deterministic seed based on train identity."""
    token = f"{train_num}:{route}:{agency}".lower().strip()
    h = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def synthesize_consist_for_train(
    train_num: str,
    route: Optional[str] = None,
    agency: Optional[str] = None,
    speed_mph: Optional[float] = None,
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """Generates a detailed, realistic rolling stock consist profile for a given train."""
    r_lower = (route or "").lower().strip()
    a_lower = (agency or "").lower().strip()
    t_str = str(train_num or "0").strip()
    seed = _derive_seed(t_str, r_lower, a_lower)

    locos = []
    cars = []
    train_type = "Intercity Passenger"

    # 1. Acela Express / Avelia High-Speed
    if "acela" in r_lower or "avelia" in r_lower:
        train_type = "High-Speed Rail"
        locos = ["Acela_Power"]
        cars = [
            "Acela_Coach", "Acela_Coach", "Acela_Cafe",
            "Acela_Coach", "Acela_Coach", "Acela_Coach"
        ]
        # Trailing power car
        locos.append("Acela_Power")

    # 2. Northeast Regional / Keystone / Shore Line
    elif "regional" in r_lower or "keystone" in r_lower or "northeast" in r_lower or "hartford" in r_lower:
        train_type = "Intercity Electric / Regional"
        loco_type = "ACS-64" if (seed % 2 == 0) else "ALC-42"
        locos = [loco_type]
        cars = [
            "Amfleet_Cafe",
            "Amfleet_Coach", "Amfleet_Coach", "Amfleet_Coach",
            "Amfleet_Coach", "Amfleet_Coach"
        ]
        if seed % 3 == 0:
            cars.append("Amfleet_Coach")

    # 3. Long-Distance Superliner Trains (Empire Builder, California Zephyr, Southwest Chief, etc.)
    elif any(ld in r_lower for ld in ["empire builder", "california zephyr", "southwest chief", "coast starlight", "sunset limited", "texas eagle"]):
        train_type = "Long-Distance Transcon"
        lead = "ALC-42" if (seed % 2 == 0) else "P42DC"
        locos = [lead, lead]
        cars = [
            "Viewliner_Baggage",
            "Superliner_Sleeper", "Superliner_Sleeper",
            "Superliner_Diner",
            "Superliner_Lounge",
            "Superliner_Coach", "Superliner_Coach", "Superliner_Coach"
        ]
        if "builder" in r_lower or "zephyr" in r_lower:
            cars.append("Superliner_Coach")

    # 4. Auto Train (World's Longest Passenger Consist)
    elif "auto train" in r_lower or "autorack" in r_lower:
        train_type = "Passenger Auto Express"
        locos = ["ALC-42", "ALC-42"]
        cars = [
            "Superliner_Sleeper", "Superliner_Sleeper", "Superliner_Diner",
            "Superliner_Lounge", "Superliner_Coach", "Superliner_Coach"
        ]
        # Append autoracks
        auto_count = 14 + (seed % 6)
        for _ in range(auto_count):
            cars.append("Autorack_TriLevel")

    # 5. Midwest / State-Supported Corridors (Hiawatha, Lincoln Service, Wolverine, Cascades)
    elif any(c in r_lower for c in ["hiawatha", "lincoln", "wolverine", "illini", "saluki", "cascades", "pere marquette"]):
        train_type = "State-Supported Corridor"
        locos = ["ALC-42"]
        cars = ["Venture_Coach", "Venture_Coach", "Venture_Coach", "Venture_Coach"]
        if seed % 2 == 0:
            cars.insert(2, "Amfleet_Cafe")

    # 6. Commuter Rail: Caltrain, Metra, MBTA
    elif "caltrain" in a_lower or "caltrain" in r_lower:
        train_type = "Commuter Rail"
        if seed % 2 == 0:
            locos = ["Caltrain_EMU"]
            cars = ["Caltrain_EMU", "Caltrain_EMU", "Caltrain_EMU", "Caltrain_EMU", "Caltrain_EMU"]
        else:
            locos = ["F40PH"]
            cars = ["Gallery_BiLevel", "Gallery_BiLevel", "Gallery_BiLevel", "Gallery_BiLevel", "Gallery_BiLevel"]

    elif "metra" in a_lower or "metra" in r_lower:
        train_type = "Commuter Rail"
        locos = ["F40PH"]
        num_cars = 5 + (seed % 4)
        cars = ["Gallery_BiLevel" for _ in range(num_cars)]

    elif "mbta" in a_lower or "mbta" in r_lower:
        train_type = "Commuter Rail"
        locos = ["F40PH"]
        num_cars = 5 + (seed % 3)
        cars = ["Amfleet_Coach" for _ in range(num_cars)]

    # 7. Freight & Default
    elif any(fr in a_lower or fr in r_lower for fr in ["bnsf", "union pacific", "up", "norfolk southern", "ns", "csx", "freight"]):
        train_type = "Class I Mainline Freight"
        lead_loco = "ES44AC" if (seed % 2 == 0) else "SD70ACe"
        locos = [lead_loco, lead_loco]
        if seed % 3 == 0:
            locos.append(lead_loco)

        freight_types = ["Intermodal_Well", "Covered_Hopper", "Tank_Car", "Boxcar", "Autorack_TriLevel"]
        num_freight = 25 + (seed % 35)
        for i in range(num_freight):
            cars.append(freight_types[(seed + i) % len(freight_types)])

    else:
        # Generic Amtrak fallback
        train_type = "Intercity Passenger"
        locos = ["P42DC"]
        cars = ["Amfleet_Cafe", "Amfleet_Coach", "Amfleet_Coach", "Amfleet_Coach", "Amfleet_Coach"]

    # Calculate consist metrics
    units_breakdown = []
    seq = 1
    total_axles = 0
    total_len = 0
    total_weight = 0

    for l_id in locos:
        spec = LOCOMOTIVE_SPECS.get(l_id, LOCOMOTIVE_SPECS["ALC-42"])
        total_axles += spec["axles"]
        total_len += spec["length_ft"]
        total_weight += spec["weight_tons"]
        road_num = 100 + ((seed * seq) % 899)
        units_breakdown.append({
            "sequence": seq,
            "unit_id": l_id,
            "road_number": f"{road_num}",
            "name": spec["name"],
            "category": "locomotive",
            "glyph": "🚂",
            "axles": spec["axles"],
            "length_ft": spec["length_ft"],
            "weight_tons": spec["weight_tons"],
        })
        seq += 1

    for c_id in cars:
        spec = CAR_SPECS.get(c_id, CAR_SPECS["Amfleet_Coach"])
        total_axles += spec["axles"]
        total_len += spec["length_ft"]
        total_weight += spec["weight_tons"]
        road_num = 1000 + ((seed * seq) % 8999)
        units_breakdown.append({
            "sequence": seq,
            "unit_id": c_id,
            "road_number": f"{road_num}",
            "name": spec["name"],
            "category": spec["category"],
            "glyph": spec.get("glyph", "🚃"),
            "axles": spec["axles"],
            "length_ft": spec["length_ft"],
            "weight_tons": spec["weight_tons"],
        })
        seq += 1

    estimated_hp = sum(LOCOMOTIVE_SPECS.get(l, {}).get("hp", 0) for l in locos)

    return {
        "train_num": str(train_num),
        "route": route or "Mainline Service",
        "agency": agency or "National Passenger",
        "train_type": train_type,
        "locomotive_count": len(locos),
        "car_count": len(cars),
        "total_units": len(units_breakdown),
        "total_axles": total_axles,
        "total_length_ft": total_len,
        "total_weight_tons": total_weight,
        "total_horsepower": estimated_hp,
        "units": units_breakdown,
        "timestamp": timestamp if timestamp is not None else time.time(),
    }


def generate_defect_report(
    camera: Dict[str, Any],
    train_num: str,
    speed_mph: float = 55.0,
    consist_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generates an authentic Automated Defect Detector (HBD/DED) inspection report."""
    if consist_data is None:
        consist_data = synthesize_consist_for_train(train_num, speed_mph=speed_mph)

    cam_props = camera.get("properties", camera)
    subdivision = cam_props.get("subdivision") or "Mainline Sub"
    milepost = cam_props.get("milepost") or "MP 100.0"
    cam_name = cam_props.get("name") or "Trackside Feed"

    # Parse operator prefix
    op_prefix = "BNSF"
    if "ns" in subdivision.lower() or "pittsburgh" in subdivision.lower():
        op_prefix = "NORFOLK SOUTHERN"
    elif "up" in subdivision.lower() or "mojave" in subdivision.lower() or "geneva" in subdivision.lower():
        op_prefix = "UNION PACIFIC"
    elif "csx" in subdivision.lower():
        op_prefix = "CSX"
    elif "amtrak" in subdivision.lower() or "nec" in subdivision.lower():
        op_prefix = "AMTRAK"

    axles = consist_data["total_axles"]
    spd = round(speed_mph, 1) if speed_mph and speed_mph > 0 else 54.0

    # Determine track number
    track_num = 1 if (int(hashlib.md5(train_num.encode()).hexdigest(), 16) % 2 == 0) else 2

    # Authentic radio defect broadcast transcript
    # Format: [Chime] <RR> DETECTOR, MILEPOST <MP>, TRACK <TRK> ... NO DEFECTS ... NO DEFECTS ... TOTAL AXLES <AXLES> ... TRAIN SPEED <SPD> ... TEMPERATURE <TEMP> ... DETECTOR OUT.
    temp_f = 64
    mp_clean = milepost.upper().replace("MP", "").strip()
    # Spell out digits for authentic synthetic voice representation
    mp_digits = " ".join(c for c in mp_clean if c.isalnum() or c == ".")
    axle_digits = " ".join(str(axles))
    spd_digits = " ".join(str(int(spd)))

    radio_transcript = (
        f"[RADIO TONES] ... {op_prefix} DETECTOR ... MILEPOST {mp_digits} ... "
        f"TRACK {track_num} ... NO DEFECTS ... NO DEFECTS ... "
        f"TOTAL AXLES: {axles} ... TRAIN SPEED: {int(spd)} MPH ... "
        f"TEMPERATURE: {temp_f} DEGREES ... DETECTOR OUT."
    )

    return {
        "detector_type": "Hotbox & Dragging Equipment Detector (HBD/DED)",
        "station_name": f"{cam_name} Detector",
        "operator": op_prefix,
        "subdivision": subdivision,
        "milepost": milepost,
        "track": track_num,
        "train_num": str(train_num),
        "axle_count": axles,
        "speed_mph": spd,
        "temperature_f": temp_f,
        "defects_detected": False,
        "defect_summary": "NO DEFECTS",
        "radio_transcript": radio_transcript,
        "timestamp": time.time(),
    }
