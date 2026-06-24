"""
Phase 1: GEE Asset Audit for Bihar / Kaimur / Kudra

Checks existence of:
  - Admin boundary (filtered MWS)
  - LULC assets for years 2018-2023
  - Change detection rasters (if any pre-exist)

Writes results to logs/phase1_asset_audit.json
"""

import os
import sys
import json
import re

# ── Django / GEE bootstrap ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")

import django
django.setup()

import ee
from utilities.gee_utils import ee_initialize, is_gee_asset_exists, get_gee_asset_path
from utilities.constants import GEE_ASSET_PATH

# ── Config ────────────────────────────────────────────────────────────────────
STATE    = "Bihar"
DISTRICT = "Kaimur"
BLOCK    = "Kudra"
YEARS    = [2018, 2019, 2020, 2021, 2022, 2023]  # 6 years → Then=18-20, Now=21-23
START_YEAR = YEARS[0]
END_YEAR   = YEARS[-1]

LOG_DIR = os.path.join(BASE_DIR, "kudra_verification", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def valid_gee_text(s):
    s = re.sub(r"[^a-zA-Z0-9 ,:;_-]", "", s)
    return s.replace(" ", "_")

def main():
    print("=" * 60)
    print("Phase 1: GEE Asset Audit — Bihar / Kaimur / Kudra")
    print("=" * 60)

    ee_initialize(1)  # account_id=1

    asset_base = get_gee_asset_path(STATE, DISTRICT, BLOCK)
    print(f"\nAsset base path: {asset_base}")

    results = {
        "asset_base": asset_base,
        "mws_asset": {},
        "lulc_assets": {},
        "change_detection_assets": {},
        "change_vector_assets": {},
    }

    # ── 1. MWS / Admin boundary ───────────────────────────────────────────────
    d = valid_gee_text(DISTRICT.lower())
    b = valid_gee_text(BLOCK.lower())

    mws_asset_id = asset_base + f"filtered_mws_{d}_{b}_uid"
    exists = is_gee_asset_exists(mws_asset_id)
    results["mws_asset"] = {"asset_id": mws_asset_id, "exists": exists}

    if exists:
        try:
            info = ee.data.getAsset(mws_asset_id)
            results["mws_asset"]["type"] = info.get("type", "unknown")
        except Exception as e:
            results["mws_asset"]["info_error"] = str(e)
    print(f"\n[MWS] {mws_asset_id}")
    print(f"      EXISTS: {exists}")

    # ── 2. LULC assets ────────────────────────────────────────────────────────
    print("\n[LULC Assets]")
    for yr in YEARS:
        lulc_name = f"{d}_{b}_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
        lulc_id   = asset_base + lulc_name
        exists    = is_gee_asset_exists(lulc_id)
        asset_info = {"asset_id": lulc_id, "exists": exists}

        if exists:
            try:
                info = ee.data.getAsset(lulc_id)
                asset_info["type"] = info.get("type", "unknown")
                # Get band / projection info
                img = ee.Image(lulc_id)
                proj = img.projection().getInfo()
                asset_info["crs"] = proj.get("crs", "unknown")
                dims = img.getInfo()
                asset_info["bands"] = [b_info.get("id") for b_info in dims.get("bands", [])]
            except Exception as e:
                asset_info["info_error"] = str(e)

        results["lulc_assets"][str(yr)] = asset_info
        status = "✓" if exists else "✗ MISSING"
        print(f"  [{yr}] {status}  →  {lulc_id}")

    # ── 3. Change detection rasters (pre-existing) ────────────────────────────
    print("\n[Change Detection Rasters (pre-existing)]")
    params = ["Urbanization", "Degradation", "Deforestation", "Afforestation", "CropIntensity"]
    description = f"change_{d}_{b}"

    for yr_end in range(START_YEAR + 5, END_YEAR + 1):  # any multi-year window
        yr_start = yr_end - 5
        for param in params:
            ch_desc  = f"{description}_{param}_{yr_start}_{yr_end}"
            ch_asset = asset_base + ch_desc
            if is_gee_asset_exists(ch_asset):
                results["change_detection_assets"][ch_desc] = {
                    "asset_id": ch_asset, "exists": True
                }
                print(f"  FOUND: {ch_asset}")

    # Also check for specific standard window (first 3 years vs last 3 years)
    for param in params:
        ch_desc  = f"{description}_{param}_{START_YEAR}_{END_YEAR}"
        ch_asset = asset_base + ch_desc
        e = is_gee_asset_exists(ch_asset)
        results["change_detection_assets"][ch_desc] = {
            "asset_id": ch_asset, "exists": e
        }
        status = "✓" if e else "✗ MISSING"
        print(f"  [{START_YEAR}-{END_YEAR}] {param}: {status}")

    # ── 4. Change detection vectors (pre-existing) ────────────────────────────
    print("\n[Change Detection Vectors (pre-existing)]")
    for param in params:
        vec_desc  = f"change_vector_{d}_{b}_{param}_{START_YEAR}_{END_YEAR}"
        vec_asset = asset_base + vec_desc
        e = is_gee_asset_exists(vec_asset)
        results["change_vector_assets"][vec_desc] = {
            "asset_id": vec_asset, "exists": e
        }
        status = "✓" if e else "✗ MISSING"
        print(f"  [{START_YEAR}-{END_YEAR}] {param}: {status}")

    # ── Save results ──────────────────────────────────────────────────────────
    out_path = os.path.join(LOG_DIR, "phase1_asset_audit.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n\nAudit complete. Results saved to: {out_path}")

    # Summary
    lulc_missing = [yr for yr, info in results["lulc_assets"].items() if not info["exists"]]
    mws_exists   = results["mws_asset"]["exists"]
    print(f"\n=== SUMMARY ===")
    print(f"MWS/Boundary: {'EXISTS' if mws_exists else 'MISSING'}")
    print(f"LULC years present: {[yr for yr, info in results['lulc_assets'].items() if info['exists']]}")
    print(f"LULC years missing: {lulc_missing}")
    ch_present = [k for k, v in results["change_detection_assets"].items() if v["exists"]]
    print(f"Change detection rasters found: {len(ch_present)}")

    return results

if __name__ == "__main__":
    main()
