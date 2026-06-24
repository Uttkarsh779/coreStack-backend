"""
Phase 2: Generate GEE assets for Bihar/Kaimur/Kudra.

Steps:
  A. Upload Kudra admin boundary (from kaimur.geojson TID=0007) to GEE
  B. Filter pan-India MWS by Kudra boundary → filtered_mws_kaimur_kudra_uid
  C. Clip pan-India LULC v3 for years 2018–2023 to Kudra boundary → per-year LULCmap assets

All assets are exported to GEE first (GEE tasks); we wait for completion.
Results are logged to logs/phase2_asset_generation.json
"""

import os, sys, json, re, time
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django; django.setup()

import ee
import geopandas as gpd
from utilities.gee_utils import (
    ee_initialize, is_gee_asset_exists, get_gee_asset_path,
    create_gee_directory, export_vector_asset_to_gee,
    export_raster_asset_to_gee, make_asset_public,
)
from utilities.constants import MWS_DATASET, PAN_INDIA_LULC_V3_DATASET

LOG_DIR = os.path.join(BASE_DIR, "kudra_verification", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

STATE    = "Bihar"
DISTRICT = "Kaimur"
BLOCK    = "Kudra"
YEARS    = [2018, 2019, 2020, 2021, 2022, 2023]

def valid(s):
    return re.sub(r"[^a-zA-Z0-9 ,:;_-]", "", s).replace(" ", "_")

def wait_for_tasks(task_ids, poll_sec=30, max_wait=3600):
    """Poll GEE until all task_ids are COMPLETED/SUCCEEDED/FAILED."""
    pending = list(task_ids)
    results = {}
    deadline = time.time() + max_wait
    while pending and time.time() < deadline:
        time.sleep(poll_sec)
        ops = ee.data.listOperations()
        for op in ops:
            tid = op["name"].split("/")[-1]
            if tid in pending:
                state = op["metadata"].get("state", "UNKNOWN")
                if state in ("SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED"):
                    results[tid] = state
                    pending.remove(tid)
                    print(f"    Task {tid}: {state}")
        if pending:
            print(f"    Still waiting on {len(pending)} task(s)...")
    for tid in pending:
        results[tid] = "TIMEOUT"
    return results

def main():
    print("=" * 60)
    print("Phase 2: Generate GEE Assets for Kudra")
    print("=" * 60)

    ee_initialize(1)
    asset_base = get_gee_asset_path(STATE, DISTRICT, BLOCK)
    d = valid(DISTRICT.lower())
    b = valid(BLOCK.lower())

    log = {
        "asset_base": asset_base,
        "admin_boundary": {},
        "filtered_mws": {},
        "lulc_assets": {},
    }

    # ── Ensure GEE folder exists ──────────────────────────────────────────────
    print(f"\n[0] Ensuring GEE folder: {asset_base}")
    create_gee_directory(STATE, DISTRICT, BLOCK)

    # ── A. Upload admin boundary ──────────────────────────────────────────────
    admin_asset_id = asset_base + f"admin_boundary_{d}_{b}"
    print(f"\n[A] Admin boundary → {admin_asset_id}")

    if is_gee_asset_exists(admin_asset_id):
        print(f"    Already exists. Skipping upload.")
        log["admin_boundary"] = {"asset_id": admin_asset_id, "status": "already_exists"}
    else:
        # Load Kudra villages (TID=0007) from kaimur.geojson
        kaimur_path = os.path.join(BASE_DIR, "data", "admin-boundary", "input", "bihar", "kaimur.geojson")
        gdf = gpd.read_file(kaimur_path)
        kudra_gdf = gdf[gdf["TID"] == "0007"].copy()
        print(f"    Loaded {len(kudra_gdf)} Kudra villages from kaimur.geojson")

        # Convert to EE FeatureCollection with minimal properties
        ee_features = []
        for _, row in kudra_gdf.iterrows():
            geom = ee.Geometry(row.geometry.__geo_interface__)
            feat = ee.Feature(geom, {
                "vill_ID":    str(row.get("pc11_village_id", "")),
                "vill_name":  str(row.get("NAME", "")),
                "block_cen":  str(row.get("pc11_subdistrict_id", "")),
                "tehsil":     str(row.get("TEHSIL", "")),
                "district":   str(row.get("district_name", "")),
                "state":      str(row.get("state_name", "")),
            })
            ee_features.append(feat)

        fc = ee.FeatureCollection(ee_features)
        desc = f"admin_boundary_{d}_{b}"
        print(f"    Exporting {len(ee_features)} features to GEE...")
        task_id = export_vector_asset_to_gee(fc, desc, admin_asset_id)
        if task_id:
            print(f"    Task ID: {task_id}. Waiting for completion...")
            results = wait_for_tasks([task_id])
            log["admin_boundary"] = {
                "asset_id": admin_asset_id,
                "task_id": task_id,
                "status": results.get(task_id, "unknown"),
                "features": len(ee_features),
            }
            if results.get(task_id) in ("SUCCEEDED", "COMPLETED"):
                make_asset_public(admin_asset_id)
                print(f"    Admin boundary exported successfully.")
            else:
                print(f"    Task status: {results.get(task_id)}")
        else:
            log["admin_boundary"] = {"asset_id": admin_asset_id, "status": "task_start_failed"}
            print(f"    ERROR: Failed to start export task.")

    # ── B. Generate filtered_mws_kaimur_kudra_uid ─────────────────────────────
    mws_asset_id = asset_base + f"filtered_mws_{d}_{b}_uid"
    print(f"\n[B] Filtered MWS → {mws_asset_id}")

    if is_gee_asset_exists(mws_asset_id):
        print(f"    Already exists. Skipping.")
        log["filtered_mws"] = {"asset_id": mws_asset_id, "status": "already_exists"}
    else:
        if not is_gee_asset_exists(admin_asset_id):
            print(f"    ERROR: admin_boundary not available. Cannot generate MWS.")
            log["filtered_mws"] = {"status": "skipped_no_admin_boundary"}
        else:
            admin_fc = ee.FeatureCollection(admin_asset_id)
            pan_mws  = ee.FeatureCollection(MWS_DATASET)
            filtered = pan_mws.filterBounds(admin_fc.geometry())

            mws_count = filtered.size().getInfo()
            print(f"    {mws_count} MWS features within Kudra boundary")

            desc = f"filtered_mws_{d}_{b}_uid"
            task_id = export_vector_asset_to_gee(filtered, desc, mws_asset_id)
            if task_id:
                print(f"    Task ID: {task_id}. Waiting...")
                results = wait_for_tasks([task_id])
                log["filtered_mws"] = {
                    "asset_id": mws_asset_id,
                    "task_id": task_id,
                    "status": results.get(task_id, "unknown"),
                    "mws_count": mws_count,
                }
                if results.get(task_id) in ("SUCCEEDED", "COMPLETED"):
                    make_asset_public(mws_asset_id)
                    print(f"    Filtered MWS exported successfully.")
            else:
                log["filtered_mws"] = {"status": "task_start_failed"}

    # ── C. Clip LULC for each year to Kudra boundary ──────────────────────────
    print(f"\n[C] LULC assets for years {YEARS}")
    lulc_task_ids = {}

    roi_fc = ee.FeatureCollection(admin_asset_id) if is_gee_asset_exists(admin_asset_id) else None

    if roi_fc is None:
        print(f"    ERROR: admin boundary not available for LULC clipping.")
        log["lulc_assets"]["error"] = "no admin boundary"
    else:
        roi_geom = roi_fc.geometry()

        for yr in YEARS:
            lulc_name     = f"{d}_{b}_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
            lulc_asset_id = asset_base + lulc_name
            pan_lulc_id   = f"{PAN_INDIA_LULC_V3_DATASET}{yr}_{yr+1}"

            log["lulc_assets"][str(yr)] = {
                "asset_id": lulc_asset_id,
                "pan_india_source": pan_lulc_id,
            }

            if is_gee_asset_exists(lulc_asset_id):
                print(f"    [{yr}] Already exists. Skipping.")
                log["lulc_assets"][str(yr)]["status"] = "already_exists"
                continue

            print(f"    [{yr}] Clipping {pan_lulc_id} → {lulc_asset_id}")
            try:
                pan_img = ee.Image(pan_lulc_id)
                # Get the band name (predicted_label or b1 etc.)
                band_names = pan_img.bandNames().getInfo()
                print(f"           Bands: {band_names}")
                # Use first band, rename to predicted_label
                clipped = pan_img.select([band_names[0]]).rename(["predicted_label"]).clip(roi_geom)
                proj    = pan_img.projection()
                clipped = clipped.reproject(proj)

                task_id = export_raster_asset_to_gee(
                    image       = clipped,
                    description = lulc_name,
                    asset_id    = lulc_asset_id,
                    scale       = 10,
                    region      = roi_geom,
                )
                if task_id:
                    lulc_task_ids[yr] = task_id
                    log["lulc_assets"][str(yr)]["task_id"] = task_id
                    log["lulc_assets"][str(yr)]["status"]  = "submitted"
                    print(f"           Task ID: {task_id}")
                else:
                    log["lulc_assets"][str(yr)]["status"] = "task_start_failed"
            except Exception as e:
                print(f"           ERROR: {e}")
                log["lulc_assets"][str(yr)]["status"] = f"error: {e}"

        # Wait for all LULC tasks
        if lulc_task_ids:
            print(f"\n    Waiting for {len(lulc_task_ids)} LULC tasks...")
            results = wait_for_tasks(list(lulc_task_ids.values()), poll_sec=60)
            for yr, tid in lulc_task_ids.items():
                state = results.get(tid, "unknown")
                log["lulc_assets"][str(yr)]["final_status"] = state
                print(f"    [{yr}] Task {tid}: {state}")
                if state in ("SUCCEEDED", "COMPLETED"):
                    lulc_asset_id = log["lulc_assets"][str(yr)]["asset_id"]
                    make_asset_public(lulc_asset_id)

    # ── Save log ──────────────────────────────────────────────────────────────
    log_path = os.path.join(LOG_DIR, "phase2_asset_generation.json")
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\nPhase 2 complete. Log: {log_path}")

    # Summary
    print("\n=== PHASE 2 SUMMARY ===")
    print(f"Admin boundary: {log['admin_boundary'].get('status','?')}")
    print(f"Filtered MWS:   {log['filtered_mws'].get('status','?')}")
    for yr in YEARS:
        s = log["lulc_assets"].get(str(yr), {})
        print(f"LULC {yr}: {s.get('final_status', s.get('status','?'))}")

if __name__ == "__main__":
    main()
