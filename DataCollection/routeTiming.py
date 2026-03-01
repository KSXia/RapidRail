import requests
import re
from rapidfuzz import process, fuzz

API_KEY = "REDACTED"
HEADERS = {"api_key": API_KEY}

# Common abbreviation expansions
ABBREVIATIONS = {
    "st": "street",
    "ave": "avenue",
    "blvd": "boulevard",
    "rd": "road",
    "dr": "drive",
    "hwy": "highway",
    "ctr": "center",
    "plz": "plaza",
    "nw": "",
    "ne": "",
    "sw": "",
    "se": "",
    "&": "and",
    "mt": "mount"
}

def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)  # Remove punctuation
    words = text.split()
    expanded = [ABBREVIATIONS.get(word, word) for word in words]
    return " ".join(expanded)

# Load WMATA station info
def get_station_data():
    url = "https://api.wmata.com/Rail.svc/json/jStations"
    response = requests.get(url, headers=HEADERS)
    stations = response.json()["Stations"]
    name_to_code = {s["Name"]: s["Code"] for s in stations}
    return name_to_code

# Fuzzy match with normalization
def find_best_match(user_input, name_to_code):
    normalized_input = normalize(user_input)
    normalized_names = {normalize(name): name for name in name_to_code}

    best_match, score, _ = process.extractOne(
        normalized_input,
        normalized_names.keys(),
        scorer=fuzz.token_sort_ratio
    )

    if score < 60:
        return None  # Too poor match

    return normalized_names[best_match]

# Get travel info between two stations
def get_travel_info(from_code, to_code):
    url = f"https://api.wmata.com/Rail.svc/json/jSrcStationToDstStationInfo?FromStationCode={from_code}&ToStationCode={to_code}"
    response = requests.get(url, headers=HEADERS)
    info = response.json().get("StationToStationInfos", [])
    if not info:
        return None
    return info[0]

# Main function
def get_train_schedule(from_input, to_input):
    name_to_code = get_station_data()

    from_name = find_best_match(from_input, name_to_code)
    to_name = find_best_match(to_input, name_to_code)

    if not from_name or not to_name:
        print("❌ Could not confidently match station names. Please try again.")
        return

    from_code = name_to_code[from_name]
    to_code = name_to_code[to_name]

    travel_info = get_travel_info(from_code, to_code)
    if not travel_info:
        print(f"⚠️ No schedule info found between {from_name} and {to_name}.")
        return

    print(f"📍 From: {from_name} ({from_code})")
    print(f"📍 To:   {to_name} ({to_code})")
    print(f"⏱️ Estimated Rail Time: {travel_info['RailTime']} min")

# --- Example usage ---
while True:
    from_station = input("Enter FROM station name: ")
    to_station = input("Enter TO station name: ")
    get_train_schedule(from_station.strip(), to_station.strip())
