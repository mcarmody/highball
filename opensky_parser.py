"""Highball OpenSky Network ADS-B Flight Ingestion Parser.

Parses OpenSky Network state vectors (/api/states/all) into Highball's
standardized GeoJSON Point FeatureCollection format. Normalizes transponder
telemetry, altitude, velocity, and airline callsigns into live airspace markers.
"""

import time
from typing import Any, Dict, List, Optional

AIRLINE_ICAO_MAP = {
    "AAL": "American Airlines",
    "UAL": "United Airlines",
    "DAL": "Delta Air Lines",
    "SWA": "Southwest Airlines",
    "JBU": "JetBlue",
    "ASA": "Alaska Airlines",
    "SKW": "SkyWest Airlines",
    "FFT": "Frontier Airlines",
    "NKS": "Spirit Airlines",
    "UPS": "UPS Airlines",
    "FDX": "FedEx Express",
    "ENY": "Envoy Air",
    "RPA": "Republic Airways",
    "EDV": "Endeavor Air",
    "GJS": "GoJet Airlines",
    "PDT": "Piedmont Airlines",
    "PSA": "PSA Airlines",
    "CPZ": "Compass Airlines",
    "QXE": "Horizon Air",
    "WJA": "WestJet",
    "ACA": "Air Canada",
    "AMX": "Aeromexico",
    "BAW": "British Airways",
    "AFR": "Air France",
    "DLH": "Lufthansa",
    "KLM": "KLM",
    "VIR": "Virgin Atlantic",
    "VOZ": "Virgin Australia",
    "QFA": "Qantas",
    "ANA": "All Nippon Airways",
    "JAL": "Japan Airlines",
    "SIA": "Singapore Airlines",
    "CPA": "Cathay Pacific",
    "UAE": "Emirates",
    "QTR": "Qatar Airways",
    "ETH": "Ethiopian Airlines",
}


def resolve_airline(callsign: str, country: str) -> str:
    """Resolves human-readable airline from ICAO callsign prefix or country."""
    if not callsign:
        return country or "General Aviation"
    prefix = callsign[:3].upper()
    if prefix in AIRLINE_ICAO_MAP:
        return AIRLINE_ICAO_MAP[prefix]
    # Check 2-letter fallback if applicable or general aviation
    if callsign.startswith("N") and country == "United States":
        return "General Aviation (US)"
    return country or "Commercial / Cargo"


def parse_opensky_states(payload: Dict[str, Any], include_ground: bool = True) -> Dict[str, Any]:
    """Parses OpenSky Network /api/states/all payload into GeoJSON FeatureCollection.

    OpenSky state vector array indices:
    0: icao24 (str)
    1: callsign (str or None)
    2: origin_country (str)
    3: time_position (int or None)
    4: last_contact (int)
    5: longitude (float or None)
    6: latitude (float or None)
    7: baro_altitude (float or None, meters)
    8: on_ground (bool)
    9: velocity (float or None, m/s)
    10: true_track (float or None, degrees clockwise from north)
    11: vertical_rate (float or None, m/s)
    12: sensors (list or None)
    13: geo_altitude (float or None, meters)
    14: squawk (str or None)
    15: spi (bool)
    16: position_source (int)
    """
    states = payload.get("states") or []
    timestamp = payload.get("time") or time.time()
    features = []

    for s in states:
        if len(s) < 11:
            continue
        icao24 = s[0]
        lon = s[5]
        lat = s[6]
        if lat is None or lon is None:
            continue

        raw_callsign = s[1]
        callsign = raw_callsign.strip() if raw_callsign else ""
        country = s[2] or ""
        airline = resolve_airline(callsign, country)

        baro_m = s[7]
        geo_m = s[13] if len(s) > 13 else None
        alt_m = baro_m if baro_m is not None else geo_m
        alt_ft = round(alt_m * 3.28084) if alt_m is not None else 0

        on_ground = bool(s[8])
        if on_ground and not include_ground:
            continue
        vel_mps = s[9] or 0.0
        speed_mph = round(vel_mps * 2.23694, 1)
        track = s[10]
        heading = round(track, 1) if track is not None else 0.0

        vert_mps = s[11] if len(s) > 11 and s[11] is not None else 0.0
        vert_fpm = round(vert_mps * 196.85)

        squawk = s[14] if len(s) > 14 and s[14] else "N/A"

        if on_ground:
            status = "Taxiing / Ground"
            route_desc = f"{airline} (Ground)"
        elif vert_fpm > 300:
            status = f"Climbing (+{vert_fpm:,} fpm)"
            fl = alt_ft // 100
            route_desc = f"{airline} · FL{fl:03d} ({alt_ft:,} ft)" if alt_ft >= 18000 else f"{airline} · {alt_ft:,} ft"
        elif vert_fpm < -300:
            status = f"Descending ({vert_fpm:,} fpm)"
            fl = alt_ft // 100
            route_desc = f"{airline} · FL{fl:03d} ({alt_ft:,} ft)" if alt_ft >= 18000 else f"{airline} · {alt_ft:,} ft"
        else:
            status = "Cruising"
            fl = alt_ft // 100
            route_desc = f"{airline} · FL{fl:03d} ({alt_ft:,} ft)" if alt_ft >= 18000 else f"{airline} · {alt_ft:,} ft"

        display_name = callsign or icao24.upper()

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(lon), float(lat)],
            },
            "properties": {
                "id": f"Flight_{icao24}",
                "train_num": display_name,
                "flight_num": display_name,
                "callsign": callsign,
                "icao24": icao24,
                "route": route_desc,
                "agency": airline,
                "mode": "flight",
                "mode_label": "Flight",
                "speed_mph": speed_mph,
                "heading": heading,
                "altitude_ft": alt_ft,
                "vertical_rate_fpm": vert_fpm,
                "squawk": squawk,
                "on_ground": on_ground,
                "timely": "In Flight" if not on_ground else "On Ground",
                "status": status,
                "origin": airline,
                "dest": "En Route",
                "updated_at": s[4] if len(s) > 4 and s[4] else timestamp,
            },
        })

    return {
        "type": "FeatureCollection",
        "timestamp": timestamp,
        "total_active": len(features),
        "agency": "OpenSky Network",
        "features": features,
    }
