"""
Phase 4: Download LULC GeoTIFFs + MWS GeoJSON from GEE to local disk.

For each LULC year:
  - Export as GeoTIFF to GCS, then download
  - Validate: opens, has correct shape, valid raster values, not empty

MWS:
  - Download filtered_mws_kaimur_kudra_uid as GeoJSON

Outputs go to kudra_verification/lulc_downloads/
"""
import os, sys, json, re, time
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django; django.setup()
import ee
import rasterio
import numpy as np
import geopandas as gpd
from utilities.gee_utils import (
    ee_initialize, get_gee_asset_path, is_gee_asset_exists, gcs_config,
)
from nrm_app.settings import GCS_BUCKET_NAME

STATE    = "Bihar"
DISTRICT = "Kaimur"
BLOCK    = "Kudra"
YEARS    = [2018, 2019, 2020, 2021, 2022, 2023]

OUT_DIR  = os.path.join(BASE_DIR, "kudra_verification", "lulc_downloads")
LOG_DIR  = os.path.join(BASE_DIR, "kudra_verification", "logs")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

def valid(s):
    return re.sub(r"[^a-zA-Z0-9 ,:;_-]", "", s).replace(" ", "_")

def wait_for_tasks(task_ids, poll_sec=30, max_wait=3600):
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
            print(f"    Waiting on {len(pending)} task(s)...")
    for tid in pending:
        results[tid] = "TIMEOUT"
    return results

def validate_geotiff(path):
    result = {"path": path, "exists": os.path.exists(path)}
    if not result["exists"]:
        return result
    try:
        with rasterio.open(path) as src:
            result["driver"]    = src.driver
            result["crs"]       = str(src.crs)
            result["width"]     = src.width
            result["height"]    = src.height
            result["count"]     = src.count
            result["dtype"]     = str(src.dtypes[0])
            result["transform"] = list(src.transform)[:6]
            result["nodata"]    = src.nodata
            data = src.read(1)
            result["shape"]     = list(data.shape)
            result["min"]       = int(np.nanmin(data))
            result["max"]       = int(np.nanmax(data))
            unique_vals         = np.unique(data[data != (src.nodata or -9999)]).tolist()
            result["unique_values"] = unique_vals[:30]  # cap at 30
            result["pixel_count"]   = int(np.sum(data != (src.nodata or -9999)))
            result["is_empty"]      = result["pixel_count"] == 0
            result["valid"]         = (result["width"] > 0 and result["height"] > 0
                                       and not result["is_empty"])
    except Exception as e:
        result["error"]  = str(e)
        result["valid"]  = False
    return result

def main():
    print("=" * 60)
    print("Phase 4: Download LULC GeoTIFFs + MWS GeoJSON")
    print("=" * 60)

    ee_initialize(1)
    bucket = gcs_config(1)
    asset_base = get_gee_asset_path(STATE, DISTRICT, BLOCK)
    d = valid(DISTRICT.lower())
    b = valid(BLOCK.lower())

    log = {"lulc": {}, "mws": {}}
    export_tasks = {}

    # ── Export LULC rasters to GCS ────────────────────────────────────────────
    print(f"\n[1] Submitting LULC export tasks to GCS")
    for yr in YEARS:
        lulc_name     = f"{d}_{b}_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
        lulc_asset_id = asset_base + lulc_name
        local_tif     = os.path.join(OUT_DIR, f"{lulc_name}.tif")
        gcs_prefix    = f"kudra_lulc_download/{lulc_name}"

        log["lulc"][str(yr)] = {
            "asset_id": lulc_asset_id,
            "local_path": local_tif,
            "gcs_prefix": gcs_prefix,
        }

        if os.path.exists(local_tif):
            print(f"    [{yr}] Already downloaded: {local_tif}")
            log["lulc"][str(yr)]["status"] = "already_downloaded"
            continue

        if not is_gee_asset_exists(lulc_asset_id):
            print(f"    [{yr}] Asset missing: {lulc_asset_id}")
            log["lulc"][str(yr)]["status"] = "asset_missing"
            continue

        img = ee.Image(lulc_asset_id)
        task = ee.batch.Export.image.toCloudStorage(
            image          = img,
            description    = f"dl_{lulc_name}",
            bucket         = GCS_BUCKET_NAME,
            fileNamePrefix = gcs_prefix,
            scale          = 10,
            fileFormat     = "GeoTIFF",
            crs            = "EPSG:4326",
            maxPixels      = 1e13,
        )
        task.start()
        tid = task.status()["id"]
        export_tasks[yr] = tid
        log["lulc"][str(yr)]["export_task_id"] = tid
        log["lulc"][str(yr)]["status"] = "submitted"
        print(f"    [{yr}] Export task: {tid}")

    # ── Wait for exports ──────────────────────────────────────────────────────
    if export_tasks:
        print(f"\n    Waiting for {len(export_tasks)} export tasks...")
        results = wait_for_tasks(list(export_tasks.values()), poll_sec=30)
        for yr, tid in export_tasks.items():
            log["lulc"][str(yr)]["export_status"] = results.get(tid, "unknown")

    # ── Download from GCS ─────────────────────────────────────────────────────
    print(f"\n[2] Downloading from GCS")
    for yr in YEARS:
        lulc_name = f"{d}_{b}_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
        local_tif = os.path.join(OUT_DIR, f"{lulc_name}.tif")
        gcs_blob_name = f"kudra_lulc_download/{lulc_name}.tif"

        if os.path.exists(local_tif):
            print(f"    [{yr}] Already on disk.")
            continue

        export_status = log["lulc"][str(yr)].get("export_status", "")
        if export_status not in ("SUCCEEDED", "COMPLETED", "already_downloaded"):
            print(f"    [{yr}] Skipping download (export: {export_status})")
            continue

        print(f"    [{yr}] Downloading gs://{GCS_BUCKET_NAME}/{gcs_blob_name}")
        try:
            blob = bucket.blob(gcs_blob_name)
            blob.download_to_filename(local_tif)
            size_mb = os.path.getsize(local_tif) / 1e6
            print(f"           → {local_tif} ({size_mb:.1f} MB)")
            log["lulc"][str(yr)]["status"] = "downloaded"
        except Exception as e:
            print(f"           ERROR: {e}")
            log["lulc"][str(yr)]["download_error"] = str(e)

    # ── Validate downloaded GeoTIFFs ──────────────────────────────────────────
    print(f"\n[3] Validating downloaded GeoTIFFs")
    for yr in YEARS:
        lulc_name = f"{d}_{b}_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
        local_tif = os.path.join(OUT_DIR, f"{lulc_name}.tif")
        v = validate_geotiff(local_tif)
        log["lulc"][str(yr)]["validation"] = v
        if v.get("valid"):
            print(f"    [{yr}] ✓  {v['width']}×{v['height']} px, "
                  f"classes={v['unique_values'][:10]}, min={v['min']}, max={v['max']}")
        else:
            print(f"    [{yr}] ✗  {v.get('error','not valid')}")

    # ── Download MWS GeoJSON ──────────────────────────────────────────────────
    mws_asset_id = asset_base + f"filtered_mws_{d}_{b}_uid"
    mws_local    = os.path.join(OUT_DIR, f"filtered_mws_{d}_{b}_uid.geojson")
    print(f"\n[4] Downloading MWS GeoJSON")
    print(f"    Asset: {mws_asset_id}")

    if os.path.exists(mws_local):
        print(f"    Already on disk: {mws_local}")
        log["mws"]["status"] = "already_downloaded"
    elif not is_gee_asset_exists(mws_asset_id):
        print(f"    MWS asset missing!")
        log["mws"]["status"] = "asset_missing"
    else:
        try:
            fc   = ee.FeatureCollection(mws_asset_id)
            info = fc.getInfo()
            with open(mws_local, "w") as f:
                json.dump({"type": info["type"], "features": info["features"]}, f)
            mws_count = len(info["features"])
            print(f"    ✓ Saved {mws_count} MWS features → {mws_local}")
            log["mws"] = {
                "asset_id": mws_asset_id,
                "local_path": mws_local,
                "feature_count": mws_count,
                "status": "downloaded",
            }
            # Validate with geopandas
            gdf = gpd.read_file(mws_local)
            log["mws"]["columns"] = list(gdf.columns)
            log["mws"]["crs"]     = str(gdf.crs)
            print(f"    Columns: {list(gdf.columns)}")
        except Exception as e:
            print(f"    ERROR: {e}")
            log["mws"]["error"] = str(e)

    # ── Save log ──────────────────────────────────────────────────────────────
    out_path = os.path.join(LOG_DIR, "phase4_downloads.json")
    with open(out_path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\nPhase 4 complete. Log: {out_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n=== PHASE 4 SUMMARY ===")
    all_ok = True
    for yr in YEARS:
        r = log["lulc"].get(str(yr), {})
        v = r.get("validation", {})
        ok = v.get("valid", False)
        if not ok: all_ok = False
        print(f"  [{yr}] {'✓' if ok else '✗'}  {r.get('status','')}  "
              f"size={v.get('width','?')}×{v.get('height','?')}  classes={v.get('unique_values',[][:5])}")
    print(f"  MWS: {log['mws'].get('status','?')}  "
          f"features={log['mws'].get('feature_count','?')}")
    print(f"All OK: {all_ok}")

if __name__ == "__main__":
    main()
