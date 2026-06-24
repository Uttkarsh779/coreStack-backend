#!/usr/bin/env python3
"""Check what GEE assets already exist for our test regions."""
import os, sys
sys.path.insert(0, '/home/uttkarsh/core-stack-backend')
os.chdir('/home/uttkarsh/core-stack-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nrm_app.settings')
import django
django.setup()

from utilities.gee_utils import ee_initialize, get_gee_asset_path, valid_gee_text
import ee

ee_initialize(1)

print("=== GEE Asset Root ===")
roots = ee.data.getAssetRoots()
for r in roots:
    print(f"  {r['id']}")

def list_assets(path):
    try:
        result = ee.data.listAssets({'parent': path})
        return result.get('assets', [])
    except Exception as e:
        return []

def check_region(state, district, block):
    base = get_gee_asset_path(state, district, block)
    print(f"\n=== {state}/{district}/{block} ===")
    print(f"  GEE base path: {base}")
    assets = list_assets(base)
    if not assets:
        # Try parent dir
        parent = '/'.join(base.rstrip('/').split('/')[:-1])
        print(f"  (no assets at base, checking parent: {parent})")
        assets = list_assets(parent)
    for a in assets:
        name = a['id'].split('/')[-1]
        atype = a.get('type', '?')
        print(f"    [{atype}] {name}")
    if not assets:
        print("    (empty / does not exist)")
    return assets

# Test region 1: Tamil Nadu / Chennai / Guindy
check_region('tamil nadu', 'chennai', 'guindy')

# Test region 2: Bihar / Kaimur / Kaimur (block)
check_region('bihar', 'kaimur', 'kaimur')

# Also check what the Assam/Baksa structure looks like
check_region('assam', 'baksa', 'baska')
