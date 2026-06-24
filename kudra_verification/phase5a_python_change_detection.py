"""
Phase 5A: Python change detection on local LULC GeoTIFFs.

Replicates computing/change_detection/change_detection.py logic
using numpy/rasterio instead of GEE, so we can run it on local files
and compare with OCaml output.

Key steps replicated from GEE Python:
  1. Load 6 LULC rasters (years 2018–2023)
  2. Remap each with parameter-specific function
  3. Compute mode of Then (first 3) and Now (last 3) periods
  4. Apply temporal smoothing for Deforestation / Afforestation
  5. Compute transition codes per pixel
  6. Write output GeoTIFFs and GeoJSONs (per-watershed areas)

Output → kudra_verification/python_output/
"""
import os, sys, json, re
import numpy as np
import rasterio
from rasterio.features import geometry_mask
import geopandas as gpd
from shapely.geometry import shape
import copy

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATE    = "Bihar"
DISTRICT = "Kaimur"
BLOCK    = "Kudra"
YEARS    = [2018, 2019, 2020, 2021, 2022, 2023]

LULC_DIR  = os.path.join(BASE_DIR, "kudra_verification", "lulc_int32")
OUT_DIR   = os.path.join(BASE_DIR, "kudra_verification", "python_output")
LOG_DIR   = os.path.join(BASE_DIR, "kudra_verification", "logs")
os.makedirs(OUT_DIR,  exist_ok=True)
os.makedirs(LOG_DIR,  exist_ok=True)

def valid(s):
    return re.sub(r"[^a-zA-Z0-9 ,:;_-]", "", s).replace(" ", "_")

d = valid(DISTRICT.lower())
b = valid(BLOCK.lower())

# ── REMAP FUNCTIONS (exact from change_detection.py) ─────────────────────────
REMAP_URB = {1:1, 2:2, 3:2, 4:2, 6:3, 7:4, 8:3, 9:3, 10:3, 11:3, 12:4}
REMAP_DEG = {1:1, 2:2, 3:2, 4:2, 6:4, 7:5, 8:3, 9:3, 10:3, 11:3, 12:6}
REMAP_FOR = {1:1, 2:2, 3:2, 4:2, 6:3, 7:5, 8:4, 9:4, 10:4, 11:4, 12:6}
REMAP_CRP = {1:1, 2:2, 3:2, 4:2, 6:3, 7:4, 8:5, 9:5, 10:6, 11:7, 12:8}

def apply_remap(arr, remap_dict):
    """Apply a class-remap dictionary to a numpy array; 0 = background."""
    out = np.zeros_like(arr, dtype=np.int32)
    for src, dst in remap_dict.items():
        out[arr == src] = dst
    return out

def pixel_mode(stack):
    """Element-wise mode across a list of exactly 3 arrays (GEE Then/Now periods).
    Ties resolve to the first element (mirrors GEE ImageCollection.mode() behavior).
    Uses pure numpy — scipy.stats.mode would OOM on large rasters."""
    if len(stack) != 3:
        raise ValueError("pixel_mode expects exactly 3 arrays (got %d)" % len(stack))
    a0, a1, a2 = stack[0], stack[1], stack[2]
    out = a0.copy()
    # a1==a2 and a0 disagrees → a1 wins
    mask = (a0 != a1) & (a0 != a2) & (a1 == a2)
    out[mask] = a1[mask]
    return out.astype(np.int32)

# ── TEMPORAL SMOOTHING (Deforestation / Afforestation) ───────────────────────
def anomaly_count(b_arr, m_arr, a_arr):
    """Count anomaly conditions per pixel (11 conditions, same as OCaml)."""
    is_crop  = lambda v: ((v == 8) | (v == 9) | (v == 10) | (v == 11))
    is_water = lambda v: ((v == 2) | (v == 3) | (v == 4))
    is_for   = lambda v: (v == 6)
    counts   = np.zeros_like(b_arr, dtype=np.int32)
    counts += ((b_arr == 12) & (a_arr == 12) & (is_for(m_arr) | is_crop(m_arr))).astype(np.int32)
    counts += (is_water(b_arr) & is_water(a_arr) & (is_for(m_arr) | is_crop(m_arr))).astype(np.int32)
    counts += ((b_arr == 6) & (a_arr == 6) & (m_arr == 12)).astype(np.int32)
    counts += (is_crop(b_arr) & is_crop(a_arr) & (m_arr == 12)).astype(np.int32)
    counts += (is_crop(b_arr) & is_crop(a_arr) & (m_arr == 7)).astype(np.int32)
    counts += ((b_arr == 6) & (a_arr == 6) & is_crop(m_arr)).astype(np.int32)
    counts += (is_crop(b_arr) & is_crop(a_arr) & (m_arr == 6)).astype(np.int32)
    counts += ((b_arr == 1) & (a_arr == 1) & (m_arr == 6)).astype(np.int32)
    counts += ((b_arr == 6) & (a_arr == 6) & (m_arr == 1)).astype(np.int32)
    counts += ((b_arr == 1) & (a_arr == 1) & is_crop(m_arr)).astype(np.int32)
    counts += ((b_arr == 7) & (a_arr == 7) & (is_for(m_arr) | is_crop(m_arr))).astype(np.int32)
    return counts

def apply_temporal_smoothing(stack):
    """Two-pass temporal smoothing (replicates change_deforestation_afforestation)."""
    n = len(stack)
    if n < 3:
        return stack

    # Pass 1: build anomaly count
    total_count = np.zeros_like(stack[0], dtype=np.int32)
    for i in range(1, n - 1):
        total_count += anomaly_count(stack[i-1], stack[i], stack[i+1])

    # Pass 2: apply corrections to a copy
    corrected = [arr.copy() for arr in stack]
    for i in range(1, n - 1):
        b_arr = stack[i-1]
        m_arr = stack[i]
        a_arr = stack[i+1]
        fire = (total_count == 3) | (total_count == 4)
        # cond1: b==3 & m!=3 & a==3 → set m=3
        cond1 = fire & (b_arr == 3) & (m_arr != 3) & (a_arr == 3)
        corrected[i][cond1] = 3
        # cond2: b!=3 & m==3 & a!=3 → set m=b
        cond2 = fire & (b_arr != 3) & (m_arr == 3) & (a_arr != 3) & ~cond1
        corrected[i][cond2] = b_arr[cond2]

    return corrected

# ── TRANSITION CODE FUNCTIONS ─────────────────────────────────────────────────
def compute_urbanization(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = now_r == 1
    out[mask & (then_r == 1)] = 1
    out[mask & (then_r == 2)] = 2
    out[mask & (then_r == 3)] = 3
    out[mask & (then_r == 4)] = 4
    return out

def compute_degradation(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = then_r == 3
    out[mask & (now_r == 3)] = 1
    out[mask & (now_r == 1)] = 2
    out[mask & (now_r == 5)] = 3
    out[mask & (now_r == 6)] = 4
    return out

def compute_deforestation(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = then_r == 3
    out[mask & (now_r == 3)] = 1
    out[mask & (now_r == 1)] = 2
    out[mask & (now_r == 4)] = 3
    out[mask & (now_r == 5)] = 4
    out[mask & (now_r == 6)] = 5
    return out

def compute_afforestation(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = now_r == 3
    out[mask & (then_r == 3)] = 1
    out[mask & (then_r == 1)] = 2
    out[mask & (then_r == 4)] = 3
    out[mask & (then_r == 5)] = 4
    out[mask & (then_r == 6)] = 5
    return out

def compute_crop_intensity(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    out[(then_r == 6) & (now_r == 5)] = 1
    out[(then_r == 7) & (now_r == 5)] = 2
    out[(then_r == 7) & (now_r == 6)] = 3
    out[(then_r == 5) & (now_r == 6)] = 4
    out[(then_r == 5) & (now_r == 7)] = 5
    out[(then_r == 6) & (now_r == 7)] = 6
    out[(then_r == 5) & (now_r == 5)] = 7
    out[(then_r == 6) & (now_r == 6)] = 8
    out[(then_r == 7) & (now_r == 7)] = 9
    return out

# ── VECTOR STATISTICS ─────────────────────────────────────────────────────────
def compute_watershed_stats(raster_arr, transform, crs, mws_gdf, value_map):
    """
    For each watershed in mws_gdf, sum pixel areas per class code.
    value_map: {code_or_list_of_codes: attribute_name}
    Returns a GeoDataFrame with per-watershed columns.
    """
    from rasterio.features import rasterize
    import rasterio.transform as rtransform

    result_rows = []
    for _, ws in mws_gdf.iterrows():
        row = {"uid": ws.get("uid", ws.name), "geometry": ws.geometry}
        geom = ws.geometry

        # Burn a mask for this watershed
        mask = rasterize(
            [(geom, 1)],
            out_shape=raster_arr.shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )
        ws_pixels = raster_arr[mask == 1]

        for code, label in value_map.items():
            if isinstance(code, (list, tuple)):
                cnt = sum(np.sum(ws_pixels == c) for c in code)
            else:
                cnt = int(np.sum(ws_pixels == code))
            # Each pixel is 10m × 10m = 100 m² = 0.01 ha
            row[label] = cnt * 100 * 0.0001  # hectares
        result_rows.append(row)

    return gpd.GeoDataFrame(result_rows, geometry="geometry", crs=crs)

VECTOR_MAPS = {
    "Urbanization": {
        1: "bu_bu",
        2: "w_bu",
        3: "tr_bu",
        4: "b_bu",
        (2, 3, 4): "total_urb",
    },
    "Degradation": {
        1: "f_f",
        2: "f_bu",
        3: "f_ba",
        4: "f_sc",
        (2, 3, 4): "total_deg",
    },
    "Deforestation": {
        1: "fo_fo",
        2: "fo_bu",
        3: "fo_fa",
        4: "fo_ba",
        5: "fo_sc",
        (2, 3, 4, 5): "total_def",
    },
    "Afforestation": {
        1: "fo_fo",
        2: "bu_fo",
        3: "fa_fo",
        4: "ba_fo",
        5: "sc_fo",
        (2, 3, 4, 5): "total_aff",
    },
    "CropIntensity": {
        1: "do_si",
        2: "tr_si",
        3: "tr_do",
        4: "si_do",
        5: "si_tr",
        6: "do_tr",
        7: "si_si",
        8: "do_do",
        9: "tr_tr",
        (1, 2, 3, 4, 5, 6): "total_change",
    },
}

def main():
    print("=" * 60)
    print("Phase 5A: Python Change Detection (local)")
    print("=" * 60)

    log = {"rasters": {}, "vectors": {}}

    # ── Load LULC rasters ─────────────────────────────────────────────────────
    print(f"\n[1] Loading {len(YEARS)} LULC rasters")
    lulc_stack = []
    profile    = None
    for yr in YEARS:
        lulc_name = f"{d}_{b}_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
        tif_path  = os.path.join(LULC_DIR, f"{lulc_name}.tif")
        if not os.path.exists(tif_path):
            print(f"    [{yr}] MISSING: {tif_path}")
            sys.exit(1)
        with rasterio.open(tif_path) as src:
            arr = src.read(1).astype(np.int32)
            if profile is None:
                profile   = src.profile.copy()
                transform = src.transform
                crs       = src.crs
        arr[arr == -9999] = 0   # treat nodata as background (not a valid LULC class)
        lulc_stack.append(arr)
        print(f"    [{yr}] Loaded {arr.shape}, "
              f"classes={sorted(set(arr.flat) - {0})[:8]}")

    print(f"\n    Stack shape: {len(lulc_stack)} × {lulc_stack[0].shape}")
    n = len(lulc_stack)

    # ── Compute Then (mode of first 3) / Now (mode of last 3) ────────────────
    print(f"\n[2] Computing Then (first 3 years) / Now (last 3 years) periods")

    def make_then_now(remap_dict, stack):
        remapped = [apply_remap(arr, remap_dict) for arr in stack]
        then_r = pixel_mode(remapped[:3])
        now_r  = pixel_mode(remapped[3:])
        return then_r, now_r

    # ── Temporal smoothing for forest ─────────────────────────────────────────
    print(f"    Applying temporal smoothing for Deforestation/Afforestation")
    smoothed_stack = apply_temporal_smoothing(lulc_stack)

    # ── Compute 5 transition rasters ─────────────────────────────────────────
    print(f"\n[3] Computing transition rasters")
    param_rasters = {}

    then_urb, now_urb = make_then_now(REMAP_URB, lulc_stack)
    param_rasters["Urbanization"]  = compute_urbanization(then_urb, now_urb)
    print(f"    Urbanization done.  unique codes: {sorted(np.unique(param_rasters['Urbanization']).tolist())}")

    then_deg, now_deg = make_then_now(REMAP_DEG, lulc_stack)
    param_rasters["Degradation"]   = compute_degradation(then_deg, now_deg)
    print(f"    Degradation done.   unique codes: {sorted(np.unique(param_rasters['Degradation']).tolist())}")

    then_for, now_for = make_then_now(REMAP_FOR, smoothed_stack)
    param_rasters["Deforestation"] = compute_deforestation(then_for, now_for)
    print(f"    Deforestation done. unique codes: {sorted(np.unique(param_rasters['Deforestation']).tolist())}")

    param_rasters["Afforestation"] = compute_afforestation(then_for, now_for)
    print(f"    Afforestation done. unique codes: {sorted(np.unique(param_rasters['Afforestation']).tolist())}")

    then_crp, now_crp = make_then_now(REMAP_CRP, lulc_stack)
    param_rasters["CropIntensity"] = compute_crop_intensity(then_crp, now_crp)
    print(f"    CropIntensity done. unique codes: {sorted(np.unique(param_rasters['CropIntensity']).tolist())}")

    # ── Write raster outputs ──────────────────────────────────────────────────
    print(f"\n[4] Writing GeoTIFF outputs to {OUT_DIR}")
    out_profile = profile.copy()
    out_profile.update(dtype="int32", count=1, nodata=-9999, compress=None, interleave="pixel")
    for k in ("blockxsize", "blockysize", "tiled"):
        out_profile.pop(k, None)

    for param, arr in param_rasters.items():
        out_path = os.path.join(OUT_DIR, f"change_{param}.tif")
        with rasterio.open(out_path, "w", **out_profile) as dst:
            dst.write(arr.astype(np.int32), 1)
        size_kb = os.path.getsize(out_path) // 1024
        print(f"    {out_path}  ({size_kb} KB)")
        log["rasters"][param] = {
            "path": out_path,
            "unique_codes": sorted(np.unique(arr).tolist()),
            "shape": list(arr.shape),
        }

    # ── Compute vector outputs ────────────────────────────────────────────────
    mws_path = os.path.join(BASE_DIR, "kudra_verification", "lulc_downloads", f"filtered_mws_{d}_{b}_uid.geojson")
    if not os.path.exists(mws_path):
        print(f"\n[5] MWS GeoJSON not found: {mws_path}")
        print("    Skipping vector computation.")
    else:
        print(f"\n[5] Computing per-watershed statistics")
        mws_gdf = gpd.read_file(mws_path)
        if mws_gdf.crs is None:
            mws_gdf = mws_gdf.set_crs("EPSG:4326")
        mws_gdf = mws_gdf.to_crs(crs)
        print(f"    {len(mws_gdf)} watersheds loaded")

        for param, arr in param_rasters.items():
            vmap = VECTOR_MAPS[param]
            print(f"    Computing {param} vector...")
            result_gdf = compute_watershed_stats(arr, transform, crs, mws_gdf, vmap)
            out_path   = os.path.join(OUT_DIR, f"change_vector_{param}.geojson")
            result_gdf.to_file(out_path, driver="GeoJSON")
            print(f"    Wrote: {out_path}")
            log["vectors"][param] = {
                "path": out_path,
                "watershed_count": len(result_gdf),
                "columns": list(result_gdf.columns),
            }

    # ── Save log ──────────────────────────────────────────────────────────────
    log_path = os.path.join(LOG_DIR, "phase5a_python_output.json")
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\nPhase 5A complete. Log: {log_path}")

if __name__ == "__main__":
    main()
