import requests
import json

overpass_url = "https://overpass-api.de/api/interpreter"

# Simple query
query = """
[out:json];
relation["name"="Mohania"];
out tags geom;
"""

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
}

print("Querying Overpass API...")
response = requests.get(overpass_url, params={'data': query}, headers=headers)
if response.status_code == 200:
    data = response.json()
    elements = data.get("elements", [])
    print(f"Found {len(elements)} elements.")
    for idx, el in enumerate(elements[:5]):
        tags = el.get("tags", {})
        print(f"[{idx}] Type: {el['type']}, ID: {el['id']}")
        print(f"  Name: {tags.get('name')}, admin_level: {tags.get('admin_level')}, boundary: {tags.get('boundary')}")
else:
    print("Failed to query Overpass:", response.status_code, response.text)
