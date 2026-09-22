"""Highball Rail Mainline Corridors GeoJSON Generator.

Defines high-priority US passenger and freight mainline rail corridors connecting
monitored webcam junctions and transit networks for Leaflet track vector overlays.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

MAJOR_CORRIDORS: List[Dict[str, Any]] = [
    {
        "corridor_id": "corridor_nec",
        "name": "Northeast Corridor (NEC)",
        "operator": "Amtrak / Commuter Shared",
        "subdivision": "Mid-Atlantic & New England Div",
        "routes": [
            "Northeast Regional",
            "Acela",
            "Vermonter",
            "Hartford Line",
            "Valley Flyer",
            "Pennsylvanian",
            "Keystone",
            "MBTA CR-Providence",
        ],
        "coordinates": [
            [-71.0589, 42.3519],  # Boston South Station
            [-71.4189, 41.8240],  # Providence
            [-71.4988, 41.6608],  # East Greenwich Cam
            [-72.0995, 41.3557],  # New London
            [-72.9267, 41.3083],  # New Haven
            [-73.5387, 41.0534],  # Stamford
            [-73.9935, 40.7505],  # New York Penn Station
            [-74.1724, 40.7357],  # Newark Penn
            [-74.7699, 40.2206],  # Trenton
            [-75.1820, 39.9558],  # Philadelphia 30th St
            [-75.5511, 39.7371],  # Wilmington
            [-76.0712, 39.5598],  # Perryville MARC
            [-76.6169, 39.3072],  # Baltimore Penn Station
            [-77.0063, 38.8974],  # Washington Union Station
        ],
    },
    {
        "corridor_id": "corridor_bnsf_transcon",
        "name": "BNSF Southern Transcon & Southwest Corridor",
        "operator": "BNSF / Amtrak Southwest Chief",
        "subdivision": "Transcon Mainline",
        "routes": [
            "Southwest Chief",
            "Illinois Zephyr",
            "Carl Sandburg",
        ],
        "coordinates": [
            [-87.6390, 41.8789],  # Chicago Union Station
            [-88.0817, 41.5250],  # Joliet Union Station
            [-89.0664, 41.9168],  # Rochelle Double Diamond Cam
            [-90.3664, 40.9431],  # Galesburg Depot Cam
            [-91.3660, 40.3934],  # Fort Madison, IA
            [-94.5857, 39.0850],  # Kansas City Union Station
            [-95.6780, 39.0473],  # Topeka, KS
            [-97.3375, 37.6872],  # Newton / Wichita, KS
            [-100.0171, 37.7528], # Dodge City, KS
            [-103.5438, 37.9847], # La Junta, CO
            [-104.4292, 36.9034], # Raton, NM
            [-105.2242, 35.5939], # Las Vegas, NM
            [-105.9067, 35.4856], # Lamy (Santa Fe), NM
            [-106.6504, 35.0844], # Albuquerque, NM
            [-108.7426, 35.5281], # Gallup, NM
            [-110.6974, 35.0242], # Winslow, AZ
            [-111.6483, 35.1977], # Flagstaff Historic Depot Cam
            [-112.1871, 35.2495], # Williams Jct, AZ
            [-114.0530, 35.1894], # Kingman, AZ
            [-114.6142, 34.8481], # Needles, CA
            [-117.0173, 34.8958], # Barstow Harvey House
            [-117.3117, 34.1083], # San Bernardino Depot
            [-117.9228, 33.8687], # Fullerton Depot Cam
            [-118.2365, 34.0562], # Los Angeles Union Station
        ],
    },
    {
        "corridor_id": "corridor_pittsburgh_line",
        "name": "NS Pittsburgh Line / Keystone Corridor",
        "operator": "Norfolk Southern / Amtrak Pennsylvanian",
        "subdivision": "NS Pittsburgh Division",
        "routes": [
            "Pennsylvanian",
            "Keystone",
            "Keystone Service",
        ],
        "coordinates": [
            [-75.1820, 39.9558],  # Philadelphia 30th St
            [-75.4828, 40.0350],  # Paoli
            [-76.3055, 40.0379],  # Lancaster
            [-76.8867, 40.2625],  # Harrisburg
            [-77.5714, 40.5992],  # Lewistown
            [-78.0125, 40.4853],  # Huntingdon
            [-78.2372, 40.6714],  # Tyrone
            [-78.4011, 40.5187],  # Altoona Station
            [-78.4842, 40.4965],  # Horseshoe Curve Cam
            [-78.6014, 40.4614],  # Cresson
            [-78.9225, 40.3267],  # Johnstown
            [-79.3828, 40.3214],  # Latrobe
            [-79.5442, 40.3014],  # Greensburg
            [-79.9959, 40.4406],  # Pittsburgh Union Station
        ],
    },
    {
        "corridor_id": "corridor_tehachapi",
        "name": "UP Mojave Subdivision (Tehachapi Pass)",
        "operator": "Union Pacific / BNSF Trackage Rights",
        "subdivision": "UP Mojave Sub",
        "routes": [
            "San Joaquins",
        ],
        "coordinates": [
            [-119.7871, 36.7468], # Fresno
            [-119.6456, 36.3275], # Hanford
            [-119.0187, 35.3733], # Bakersfield
            [-118.6312, 35.2925], # Caliente
            [-118.5367, 35.2008], # Tehachapi Loop (Walong) Cam
            [-118.4489, 35.1322], # Tehachapi Summit
            [-118.1737, 35.0525], # Mojave Yard
            [-118.1367, 34.6981], # Lancaster
            [-118.1165, 34.5794], # Palmdale
        ],
    },
    {
        "corridor_id": "corridor_empire_builder",
        "name": "Empire Builder Northern Transcon (BNSF)",
        "operator": "BNSF / Amtrak Empire Builder",
        "subdivision": "Northern Transcon",
        "routes": [
            "Empire Builder",
        ],
        "coordinates": [
            [-87.6390, 41.8789],  # Chicago Union
            [-87.9065, 43.0389],  # Milwaukee
            [-91.2519, 43.8014],  # La Crosse, WI
            [-93.0899, 44.9537],  # St. Paul / Minneapolis
            [-94.1632, 45.5579],  # St. Cloud, MN
            [-96.7898, 46.8772],  # Fargo, ND
            [-97.0329, 47.9253],  # Grand Forks, ND
            [-101.2923, 48.2330], # Minot, ND
            [-103.6246, 48.1470], # Williston, ND
            [-106.6345, 48.1950], # Glasgow, MT
            [-109.6847, 48.5500], # Havre, MT
            [-111.8586, 48.5050], # Shelby, MT
            [-113.3134, 48.3317], # East Glacier Park, MT
            [-114.3418, 48.4111], # Whitefish, MT
            [-115.5552, 48.3938], # Libby, MT
            [-116.5535, 48.2766], # Sandpoint, ID
            [-117.4260, 47.6588], # Spokane, WA
            [-119.2845, 46.2304], # Pasco, WA
            [-121.5000, 47.3000], # Cascade Mountain Passes
            [-122.1956, 47.9789], # Everett, WA
            [-122.3297, 47.5985], # Seattle King St Station Cam
        ],
    },
    {
        "corridor_id": "corridor_california_zephyr",
        "name": "California Zephyr Overland Route (UP/BNSF)",
        "operator": "Union Pacific / BNSF / Amtrak",
        "subdivision": "Overland Route",
        "routes": [
            "California Zephyr",
        ],
        "coordinates": [
            [-87.6390, 41.8789],  # Chicago Union
            [-89.0664, 41.9168],  # Rochelle Double Diamond Cam
            [-90.3664, 40.9431],  # Galesburg Depot Cam
            [-90.5776, 41.5236],  # Burlington / Quad Cities
            [-93.6091, 41.0336],  # Osceola / Des Moines
            [-95.9345, 41.2565],  # Omaha, NE
            [-96.7026, 40.8136],  # Lincoln, NE
            [-100.7654, 41.1359], # North Platte, NE
            [-104.9903, 39.7392], # Denver Union Station
            [-105.8000, 39.9000], # Winter Park / Moffat Tunnel
            [-107.3248, 39.5505], # Glenwood Springs, CO
            [-108.5506, 39.0639], # Grand Junction, CO
            [-110.8118, 39.5994], # Helper, UT
            [-111.6585, 40.2338], # Provo, UT
            [-111.8910, 40.7608], # Salt Lake City, UT
            [-114.9817, 40.8324], # Elko, NV
            [-117.7357, 40.9730], # Winnemucca, NV
            [-119.8138, 39.5296], # Reno, NV
            [-120.1833, 39.3280], # Truckee / Donner Pass, CA
            [-121.0744, 38.8966], # Auburn, CA
            [-121.4944, 38.5816], # Sacramento, CA
            [-122.0400, 38.2494], # Fairfield-Suisun, CA
            [-122.1341, 38.0194], # Martinez, CA
            [-122.2853, 37.8313], # Emeryville (San Francisco)
        ],
    },
    {
        "corridor_id": "corridor_coast_starlight",
        "name": "Coast Starlight Pacific Coast Line (UP)",
        "operator": "Union Pacific / Amtrak Coast Starlight",
        "subdivision": "I-5 & Coast Line",
        "routes": [
            "Coast Starlight",
        ],
        "coordinates": [
            [-122.3297, 47.5985], # Seattle King St Station Cam
            [-122.4443, 47.2529], # Tacoma, WA
            [-122.9007, 47.0379], # Olympia-Lacey, WA
            [-122.6784, 45.5152], # Portland Union Station
            [-123.0868, 44.0521], # Eugene, OR
            [-121.7817, 42.2249], # Klamath Falls, OR
            [-122.3106, 41.3100], # Dunsmuir / Mt Shasta, CA
            [-122.3917, 40.5865], # Redding, CA
            [-121.8375, 39.7285], # Chico, CA
            [-121.4944, 38.5816], # Sacramento, CA
            [-122.2711, 37.8044], # Oakland Jack London
            [-121.9022, 37.3382], # San Jose Diridon
            [-121.6555, 36.6777], # Salinas, CA
            [-120.6596, 35.6269], # Paso Robles, CA
            [-120.6596, 35.2828], # San Luis Obispo, CA
            [-119.6982, 34.4208], # Santa Barbara, CA
            [-118.2365, 34.0562], # Los Angeles Union Station
        ],
    },
    {
        "corridor_id": "corridor_sunset_limited",
        "name": "Sunset Limited / Texas Eagle Corridor (UP)",
        "operator": "Union Pacific / Amtrak",
        "subdivision": "Sunset Route",
        "routes": [
            "Sunset Limited",
            "Texas Eagle",
        ],
        "coordinates": [
            [-90.0715, 29.9511],  # New Orleans
            [-91.8749, 30.2241],  # Lafayette, LA
            [-93.2174, 30.2266],  # Lake Charles, LA
            [-94.1018, 30.0802],  # Beaumont, TX
            [-95.3698, 29.7604],  # Houston, TX
            [-98.4936, 29.4241],  # San Antonio, TX
            [-100.8968, 29.3627], # Del Rio, TX
            [-103.2504, 30.2113], # Marathon, TX
            [-103.6379, 30.3585], # Alpine, TX
            [-106.4850, 31.7619], # El Paso, TX
            [-108.6575, 32.2687], # Deming, NM
            [-109.8312, 32.2534], # Lordsburg, NM
            [-110.9747, 32.2226], # Tucson, AZ
            [-112.0476, 33.0581], # Maricopa (Phoenix), AZ
            [-114.6277, 32.6927], # Yuma, AZ
            [-116.5453, 33.8303], # Palm Springs, CA
            [-117.3117, 34.1083], # San Bernardino, CA
            [-118.2365, 34.0562], # Los Angeles Union Station
        ],
    },
    {
        "corridor_id": "corridor_pacific_surfliner",
        "name": "Pacific Surfliner Coastal Corridor (LOSSAN)",
        "operator": "Amtrak / Metrolink / BNSF",
        "subdivision": "LOSSAN Rail Corridor",
        "routes": [
            "Pacific Surfliner",
        ],
        "coordinates": [
            [-120.6596, 35.2828], # San Luis Obispo
            [-120.4578, 34.9530], # Santa Maria
            [-119.6982, 34.4208], # Santa Barbara
            [-119.2945, 34.2746], # Ventura
            [-118.5361, 34.1808], # Van Nuys / Burbank
            [-118.2365, 34.0562], # Los Angeles Union Station
            [-117.9228, 33.8687], # Fullerton Depot Cam
            [-117.8765, 33.8033], # Anaheim ARTIC
            [-117.8311, 33.7455], # Santa Ana
            [-117.7320, 33.6570], # Irvine
            [-117.6625, 33.5017], # San Juan Capistrano
            [-117.3795, 33.1959], # Oceanside Transit Center
            [-117.2930, 33.0489], # Encinitas
            [-117.2662, 32.9628], # Solana Beach
            [-117.1699, 32.7165], # San Diego Santa Fe Depot
        ],
    },
    {
        "corridor_id": "corridor_cascades",
        "name": "Amtrak Cascades & Puget Sound Corridor (BNSF)",
        "operator": "BNSF / WSDOT / Sound Transit",
        "subdivision": "BNSF Seattle & Scenic Sub",
        "routes": [
            "Cascades",
            "Amtrak Cascades",
            "Sound Transit",
            "Sounder",
            "Sound Transit Regional Rail",
            "Sound Transit 100511",
        ],
        "coordinates": [
            [-123.1207, 49.2827], # Vancouver BC Pacific Central
            [-122.4786, 48.7519], # Bellingham, WA
            [-122.3331, 48.4218], # Mount Vernon, WA
            [-122.1956, 47.9789], # Everett, WA
            [-122.3789, 47.8107], # Edmonds, WA
            [-122.3297, 47.5985], # Seattle King St Station Cam
            [-122.2307, 47.3809], # Kent / Auburn, WA
            [-122.4443, 47.2529], # Tacoma Dome, WA
            [-122.9007, 47.0379], # Olympia-Lacey, WA
            [-122.9555, 46.7162], # Centralia, WA
            [-122.9082, 46.1415], # Kelso-Longview, WA
            [-122.6784, 45.6264], # Vancouver, WA
            [-122.6784, 45.5152], # Portland Union Station
            [-122.9898, 44.9429], # Salem, OR
            [-123.0868, 44.0521], # Eugene, OR
        ],
    },
    {
        "corridor_id": "corridor_city_of_new_orleans",
        "name": "City of New Orleans Mainline (CN)",
        "operator": "Canadian National / Amtrak",
        "subdivision": "CN Chicago-New Orleans Sub",
        "routes": [
            "City of New Orleans",
            "Illini",
            "Saluki",
        ],
        "coordinates": [
            [-87.6390, 41.8789],  # Chicago Union
            [-87.8631, 41.1200],  # Kankakee, IL
            [-88.2434, 40.1164],  # Champaign-Urbana, IL
            [-88.5434, 39.1225],  # Effingham, IL
            [-89.1765, 38.2698],  # Centralia, IL
            [-89.2168, 37.7273],  # Carbondale, IL
            [-90.0490, 35.1495],  # Memphis Central Station
            [-90.5841, 33.5162],  # Greenwood, MS
            [-90.1848, 32.2988],  # Jackson, MS
            [-90.4682, 31.2827],  # Brookhaven, MS
            [-90.4651, 30.5044],  # Hammond, LA
            [-90.0715, 29.9511],  # New Orleans Union Terminal
        ],
    },
    {
        "corridor_id": "corridor_auto_train",
        "name": "Auto Train CSX Mainline",
        "operator": "CSX Transportation / Amtrak",
        "subdivision": "CSX RF&P / Florence / Nahunta Sub",
        "routes": [
            "Auto Train",
            "Silver Meteor",
            "Silver Star",
            "Floridian",
            "Palmetto",
        ],
        "coordinates": [
            [-77.2065, 38.7185],  # Lorton, VA (Auto Train North)
            [-77.4605, 38.3032],  # Fredericksburg, VA
            [-77.4800, 37.7590],  # Ashland Historic Station Cam
            [-77.4360, 37.5407],  # Richmond Main St, VA
            [-77.4019, 37.2279],  # Petersburg, VA
            [-77.6536, 36.4385],  # Weldon, NC
            [-77.9158, 35.7213],  # Wilson, NC
            [-78.8986, 35.0527],  # Fayetteville, NC
            [-79.7626, 34.1954],  # Florence, SC
            [-80.3448, 33.5435],  # Summerton, SC
            [-80.8431, 32.0809],  # Savannah, GA
            [-81.4939, 31.1499],  # Jesup, GA
            [-81.9772, 30.8327],  # Folkston Funnel Cam
            [-81.6557, 30.3322],  # Jacksonville, FL
            [-81.3031, 29.8947],  # Palatka, FL
            [-81.3323, 29.0286],  # DeLand, FL
            [-81.2798, 28.7997],  # Sanford, FL (Auto Train South)
            [-81.3792, 28.5383],  # Orlando, FL
            [-81.9535, 28.0395],  # Lakeland / Tampa, FL
            [-80.1918, 25.7617],  # Miami, FL
        ],
    },
    {
        "corridor_id": "corridor_lake_shore_limited",
        "name": "Lake Shore Limited Water Level Route (CSX)",
        "operator": "CSX Transportation / Amtrak",
        "subdivision": "Water Level Route / Chicago Line",
        "routes": [
            "Lake Shore Limited",
            "Wolverine",
            "Blue Water",
        ],
        "coordinates": [
            [-87.6390, 41.8789],  # Chicago Union
            [-86.2520, 41.6764],  # South Bend, IN
            [-84.9778, 41.6348],  # Bryan, OH
            [-83.5552, 41.6528],  # Toledo, OH
            [-82.6841, 41.4287],  # Sandusky, OH
            [-81.6944, 41.4993],  # Cleveland, OH
            [-80.0851, 42.1292],  # Erie, PA
            [-78.8784, 42.8864],  # Buffalo Depew, NY
            [-77.6109, 43.1566],  # Rochester, NY
            [-76.1474, 43.0481],  # Syracuse, NY
            [-75.2327, 43.1009],  # Utica, NY
            [-73.9441, 42.8142],  # Schenectady, NY
            [-73.7413, 42.6426],  # Albany-Rensselaer, NY
            [-73.9935, 40.7505],  # New York Penn
            [-71.0589, 42.3519],  # Boston South
        ],
    },
    {
        "corridor_id": "corridor_caltrain",
        "name": "Caltrain Peninsula Corridor",
        "operator": "Caltrain / JPB",
        "subdivision": "Peninsula Corridor Mainline",
        "routes": [
            "Caltrain",
            "Caltrain Local Weekday",
            "Caltrain Limited",
            "Caltrain Express",
            "Caltrain Local",
        ],
        "coordinates": [
            [-122.3949, 37.7764], # San Francisco 4th & King
            [-122.3925, 37.7570], # 22nd St
            [-122.4018, 37.6846], # Bayshore
            [-122.4042, 37.6548], # South San Francisco
            [-122.3867, 37.6003], # Millbrae Transit Center
            [-122.3592, 37.5797], # Burlingame
            [-122.3248, 37.5683], # San Mateo
            [-122.2747, 37.5276], # San Carlos
            [-122.2316, 37.4855], # Redwood City
            [-122.1945, 37.4549], # Menlo Park
            [-122.1646, 37.4431], # Palo Alto
            [-122.0792, 37.3944], # Mountain View
            [-122.0309, 37.3784], # Sunnyvale
            [-121.9367, 37.3531], # Santa Clara
            [-121.9022, 37.3382], # San Jose Diridon
            [-121.5661, 37.0058], # Gilroy
        ],
    },
    {
        "corridor_id": "corridor_metra",
        "name": "Metra Chicago Commuter Network",
        "operator": "Metra / Chicago Regional",
        "subdivision": "Metra Regional Lines",
        "routes": [
            "Metra",
            "Metra BNSF",
            "Metra UP-N",
            "Metra UP-NW",
            "Metra UP-W",
            "Metra MD-N",
            "Metra MD-W",
            "Metra RI",
            "Metra ME",
            "Metra SWS",
            "Metra NCS",
            "Metra HC",
        ],
        "coordinates": [
            [-88.3100, 41.7580],  # Aurora (BNSF West)
            [-88.1480, 41.7770],  # Naperville
            [-88.0100, 41.7940],  # Downers Grove
            [-87.7850, 41.8310],  # Berwyn
            [-87.6390, 41.8789],  # Chicago Union / Ogilvie Hub
            [-87.6800, 42.0450],  # Evanston (UP-N)
            [-87.7500, 42.1500],  # Highland Park
            [-87.8300, 42.3600],  # Waukegan
            [-87.8100, 42.5000],  # Kenosha
        ],
    },
    {
        "corridor_id": "corridor_mbta_commuter",
        "name": "MBTA Commuter Rail Network",
        "operator": "MBTA / Keolis",
        "subdivision": "Boston Commuter Lines",
        "routes": [
            "MBTA",
            "MBTA CR-Fitchburg",
            "MBTA CR-Franklin",
            "MBTA CR-Haverhill",
            "MBTA CR-Kingston",
            "MBTA CR-Lowell",
            "MBTA CR-Middleborough",
            "MBTA CR-Needham",
            "MBTA CR-Newburyport",
            "MBTA CR-Providence",
            "MBTA CR-Worcester",
            "MBTA CR-Fairmount",
        ],
        "coordinates": [
            [-71.8000, 42.5800],  # Fitchburg
            [-71.4000, 42.5000],  # Acton / Concord
            [-71.2000, 42.3700],  # Waltham
            [-71.0589, 42.3519],  # Boston South / North Hub
            [-71.1200, 42.2400],  # Readville / Route 128
            [-71.3000, 42.0800],  # Franklin
            [-71.4189, 41.8240],  # Providence Line
        ],
    },
]

BASE_DIR = Path(__file__).resolve().parent


def generate_corridors_geojson(out_path: Optional[str] = None) -> Dict[str, Any]:
    """Generates GeoJSON FeatureCollection with LineString features for rail corridors."""
    if out_path is None:
        out_path = str(BASE_DIR / "corridors.geojson")
    features = []
    for corr in MAJOR_CORRIDORS:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": corr["coordinates"],
            },
            "properties": {
                "corridor_id": corr["corridor_id"],
                "name": corr["name"],
                "operator": corr["operator"],
                "subdivision": corr["subdivision"],
                "routes": corr.get("routes", []),
                "waypoints": len(corr["coordinates"]),
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "total_corridors": len(features),
        "features": features,
    }

    if out_path:
        with open(out_path, "w") as f:
            json.dump(geojson, f, indent=2)
        print(f"[*] Exported {len(features)} corridors to {out_path}")

    return geojson


if __name__ == "__main__":
    generate_corridors_geojson()
