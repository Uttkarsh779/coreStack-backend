"""
Phase 1b: Deep audit — check folder structure, alternate names, pan-India LULC.
"""
import os, sys, json, re
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django; django.setup()
import ee
from utilities.gee_utils import ee_initialize, get_gee_asset_path
from utilities.constants import GEE_ASSET_PATH, PAN_INDIA_LULC_PATH, PAN_INDIA_LULC_V3_DATASET

STATE    = "Bihar"
DISTRICT = "Kaimur"
BLOCK    = "Kudra"

def valid(s):
    return re.sub(r"[^a-zA-Z0-9 ,:;_-]", "", s).replace(" ", "_")

def main():
    ee_initialize(1)
    asset_base = get_gee_asset_path(STATE, DISTRICT, BLOCK)
    d = valid(DISTRICT.lower())
    b = valid(BLOCK.lower())

    print("=" * 60)
    print("Phase 1b: Deep Audit")
    print("=" * 60)

    # ── 1. List all assets inside the kudra folder (if it exists) ────────────
    print(f"\n[1] Listing assets in: {asset_base}")
    try:
        assets = ee.data.listAssets({"parent": asset_base.rstrip("/")})
        items = assets.get("assets", [])
        print(f"    Found {len(items)} assets:")
        for item in items:
            print(f"      {item['name']} ({item.get('type','?')})")
    except Exception as e:
        print(f"    ERROR listing folder: {e}")

    # ── 2. Check kaimur folder (district level) ───────────────────────────────
    kaimur_path = get_gee_asset_path(STATE, DISTRICT).rstrip("/")
    print(f"\n[2] Listing assets in district folder: {kaimur_path}")
    try:
        assets = ee.data.listAssets({"parent": kaimur_path})
        items = assets.get("assets", [])
        print(f"    Found {len(items)} assets/folders:")
        for item in items[:20]:
            print(f"      {item['name']} ({item.get('type','?')})")
        if len(items) > 20:
            print(f"    ... and {len(items)-20} more")
    except Exception as e:
        print(f"    ERROR listing folder: {e}")

    # ── 3. Check Bihar state folder ───────────────────────────────────────────
    bihar_path = get_gee_asset_path(STATE).rstrip("/")
    print(f"\n[3] Listing Bihar state folder: {bihar_path}")
    try:
        assets = ee.data.listAssets({"parent": bihar_path})
        items = assets.get("assets", [])
        print(f"    Found {len(items)} entries:")
        for item in items[:10]:
            print(f"      {item['name']} ({item.get('type','?')})")
    except Exception as e:
        print(f"    ERROR: {e}")

    # ── 4. Check pan-India LULC v3 dataset for reference years ───────────────
    print(f"\n[4] Checking pan-India LULC v3 dataset for years 2018-2023")
    print(f"    Base path: {PAN_INDIA_LULC_V3_DATASET}")
    for yr in range(2018, 2024):
        lulc_id = f"{PAN_INDIA_LULC_V3_DATASET}{yr}_{yr+1}"
        try:
            info = ee.data.getAsset(lulc_id)
            print(f"    [{yr}] EXISTS — {lulc_id}")
        except:
            print(f"    [{yr}] MISSING — {lulc_id}")

    # ── 5. Check MWS pan-India dataset ────────────────────────────────────────
    from utilities.constants import MWS_DATASET
    print(f"\n[5] Checking pan-India MWS dataset")
    print(f"    Path: {MWS_DATASET}")
    try:
        info = ee.data.getAsset(MWS_DATASET)
        print(f"    EXISTS — type: {info.get('type','?')}")
        # Try to filter for Kudra to confirm we can query it
        fc = ee.FeatureCollection(MWS_DATASET).filterMetadata("block_name", "equals", BLOCK)
        count = fc.size().getInfo()
        print(f"    MWS features with block_name='{BLOCK}': {count}")
        if count > 0:
            sample = fc.first().getInfo()
            props = sample.get("properties", {})
            print(f"    Sample properties: {list(props.keys())[:10]}")
            print(f"    Sample values: { {k: props[k] for k in list(props.keys())[:5]} }")
    except Exception as e:
        print(f"    ERROR: {e}")

    # ── 6. Check if admin boundary data exists locally ────────────────────────
    admin_boundary_path = os.path.join(BASE_DIR, "data", "admin-boundary")
    print(f"\n[6] Local admin boundary files")
    if os.path.exists(admin_boundary_path):
        for root, dirs, files in os.walk(admin_boundary_path):
            for f in files:
                if "kaimur" in f.lower() or "kudra" in f.lower() or "bihar" in f.lower():
                    full = os.path.join(root, f)
                    size = os.path.getsize(full)
                    print(f"    {full} ({size} bytes)")
    else:
        print(f"    {admin_boundary_path} not found")

    # ── 7. Check LULC pipeline to understand how to generate ─────────────────
    print(f"\n[7] Production LULC pipeline location")
    lulc_files = [
        "computing/lulc/tehsil_level/lulc_v3.py",
        "computing/lulc/tehsil_level/lulc_v2.py",
        "computing/lulc/v4/lulc_v4.py",
    ]
    for lf in lulc_files:
        full = os.path.join(BASE_DIR, lf)
        print(f"    {'EXISTS' if os.path.exists(full) else 'NOT FOUND'}: {lf}")

if __name__ == "__main__":
    main()
