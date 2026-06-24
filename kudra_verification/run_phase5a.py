"""Phase 5A: Python Change Detection on local Int32 LULC GeoTIFFs."""
import os, sys, json
import numpy as np
import rasterio
from scipy import stats as scipy_stats
import geopandas as gpd

BASE_DIR  = "/home/uttkarsh/core-stack-backend"
YEARS     = [2018, 2019, 2020, 2021, 2022, 2023]
LULC_DIR  = os.path.join(BASE_DIR, "kudra_verification", "lulc_int32")
OUT_DIR   = os.path.join(BASE_DIR, "kudra_verification", "python_output")
LOG_DIR   = os.path.join(BASE_DIR, "kudra_verification", "logs")
MWS_PATH  = os.path.join(BASE_DIR, "kudra_verification", "lulc_downloads", "filtered_mws_kaimur_kudra_uid.geojson")
D, B      = "kaimur", "kudra"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ── Remaps (exact from change_detection.py) ───────────────────────────────────
REMAP_URB = {1:1,2:2,3:2,4:2,6:3,7:4,8:3,9:3,10:3,11:3,12:4}
REMAP_DEG = {1:1,2:2,3:2,4:2,6:4,7:5,8:3,9:3,10:3,11:3,12:6}
REMAP_FOR = {1:1,2:2,3:2,4:2,6:3,7:5,8:4,9:4,10:4,11:4,12:6}
REMAP_CRP = {1:1,2:2,3:2,4:2,6:3,7:4,8:5,9:5,10:6,11:7,12:8}

def apply_remap(arr, remap_dict):
    out = np.zeros_like(arr, dtype=np.int32)
    for src_cls, dst_cls in remap_dict.items():
        out[arr == src_cls] = dst_cls
    return out

def pixel_mode(stack):
    cube = np.stack(stack, axis=0)
    mode_result = scipy_stats.mode(cube, axis=0, keepdims=False)
    return mode_result.mode.astype(np.int32)

def anomaly_count(b_arr, m_arr, a_arr):
    is_crop  = lambda v: (v==8)|(v==9)|(v==10)|(v==11)
    is_water = lambda v: (v==2)|(v==3)|(v==4)
    is_for   = lambda v: (v==6)
    counts = np.zeros_like(b_arr, dtype=np.int32)
    counts += ((b_arr==12)&(a_arr==12)&(is_for(m_arr)|is_crop(m_arr))).astype(np.int32)
    counts += (is_water(b_arr)&is_water(a_arr)&(is_for(m_arr)|is_crop(m_arr))).astype(np.int32)
    counts += ((b_arr==6)&(a_arr==6)&(m_arr==12)).astype(np.int32)
    counts += (is_crop(b_arr)&is_crop(a_arr)&(m_arr==12)).astype(np.int32)
    counts += (is_crop(b_arr)&is_crop(a_arr)&(m_arr==7)).astype(np.int32)
    counts += ((b_arr==6)&(a_arr==6)&is_crop(m_arr)).astype(np.int32)
    counts += (is_crop(b_arr)&is_crop(a_arr)&(m_arr==6)).astype(np.int32)
    counts += ((b_arr==1)&(a_arr==1)&(m_arr==6)).astype(np.int32)
    counts += ((b_arr==6)&(a_arr==6)&(m_arr==1)).astype(np.int32)
    counts += ((b_arr==1)&(a_arr==1)&is_crop(m_arr)).astype(np.int32)
    counts += ((b_arr==7)&(a_arr==7)&(is_for(m_arr)|is_crop(m_arr))).astype(np.int32)
    return counts

def apply_temporal_smoothing(stack):
    n = len(stack)
    if n < 3:
        return stack
    total_count = np.zeros_like(stack[0], dtype=np.int32)
    for i in range(1, n-1):
        total_count += anomaly_count(stack[i-1], stack[i], stack[i+1])
    corrected = [arr.copy() for arr in stack]
    for i in range(1, n-1):
        b_arr = stack[i-1]
        m_arr = stack[i]
        a_arr = stack[i+1]
        fire  = (total_count==3)|(total_count==4)
        cond1 = fire&(b_arr==3)&(m_arr!=3)&(a_arr==3)
        corrected[i][cond1] = 3
        cond2 = fire&(b_arr!=3)&(m_arr==3)&(a_arr!=3)&~cond1
        corrected[i][cond2] = b_arr[cond2]
    return corrected

def compute_urbanization(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = now_r == 1
    out[mask&(then_r==1)]=1; out[mask&(then_r==2)]=2
    out[mask&(then_r==3)]=3; out[mask&(then_r==4)]=4
    return out

def compute_degradation(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = then_r == 3
    out[mask&(now_r==3)]=1; out[mask&(now_r==1)]=2
    out[mask&(now_r==5)]=3; out[mask&(now_r==6)]=4
    return out

def compute_deforestation(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = then_r == 3
    out[mask&(now_r==3)]=1; out[mask&(now_r==1)]=2; out[mask&(now_r==4)]=3
    out[mask&(now_r==5)]=4; out[mask&(now_r==6)]=5
    return out

def compute_afforestation(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    mask = now_r == 3
    out[mask&(then_r==3)]=1; out[mask&(then_r==1)]=2; out[mask&(then_r==4)]=3
    out[mask&(then_r==5)]=4; out[mask&(then_r==6)]=5
    return out

def compute_crop_intensity(then_r, now_r):
    out = np.zeros_like(then_r, dtype=np.int32)
    out[(then_r==6)&(now_r==5)]=1; out[(then_r==7)&(now_r==5)]=2
    out[(then_r==7)&(now_r==6)]=3; out[(then_r==5)&(now_r==6)]=4
    out[(then_r==5)&(now_r==7)]=5; out[(then_r==6)&(now_r==7)]=6
    out[(then_r==5)&(now_r==5)]=7; out[(then_r==6)&(now_r==6)]=8
    out[(then_r==7)&(now_r==7)]=9
    return out

VECTOR_MAPS = {
    "Urbanization":  {1:"bu_bu",2:"w_bu",3:"tr_bu",4:"b_bu",(2,3,4):"total_urb"},
    "Degradation":   {1:"f_f",2:"f_bu",3:"f_ba",4:"f_sc",(2,3,4):"total_deg"},
    "Deforestation": {1:"fo_fo",2:"fo_bu",3:"fo_fa",4:"fo_ba",5:"fo_sc",(2,3,4,5):"total_def"},
    "Afforestation": {1:"fo_fo",2:"bu_fo",3:"fa_fo",4:"ba_fo",5:"sc_fo",(2,3,4,5):"total_aff"},
    "CropIntensity": {1:"do_si",2:"tr_si",3:"tr_do",4:"si_do",5:"si_tr",
                      6:"do_tr",7:"si_si",8:"do_do",9:"tr_tr",(1,2,3,4,5,6):"total_change"},
}

def compute_watershed_stats(raster_arr, transform, crs, mws_gdf, value_map):
    from rasterio.features import rasterize
    result_rows = []
    for _, ws in mws_gdf.iterrows():
        row  = {"uid": ws.get("uid", ws.name), "geometry": ws.geometry}
        mask = rasterize([(ws.geometry, 1)], out_shape=raster_arr.shape,
                         transform=transform, fill=0, dtype=np.uint8)
        ws_pixels = raster_arr[mask == 1]
        for code, label in value_map.items():
            if isinstance(code, (list, tuple)):
                cnt = sum(int(np.sum(ws_pixels == c)) for c in code)
            else:
                cnt = int(np.sum(ws_pixels == code))
            row[label] = cnt * 100 * 0.0001   # px → hectares (10m×10m = 0.01 ha)
        result_rows.append(row)
    return gpd.GeoDataFrame(result_rows, geometry="geometry", crs=crs)

def make_then_now(remap_dict, stack):
    remapped = [apply_remap(arr, remap_dict) for arr in stack]
    return pixel_mode(remapped[:3]), pixel_mode(remapped[3:])

def main():
    print("=" * 60)
    print("Phase 5A: Python Change Detection (Int32 TIFFs)")
    print("=" * 60)
    log = {"rasters": {}, "vectors": {}}

    print("\n[1] Loading LULC rasters")
    lulc_stack = []
    profile = None
    for yr in YEARS:
        tif = os.path.join(LULC_DIR, "%s_%s_%d-07-01_%d-06-30_LULCmap_10m.tif" % (D, B, yr, yr+1))
        with rasterio.open(tif) as src:
            arr = src.read(1).astype(np.int32)
            if profile is None:
                profile = src.profile.copy()
                transform = src.transform
                crs = src.crs
        arr[arr == -9999] = 0   # treat nodata as background
        lulc_stack.append(arr)
        print("    [%d] shape=%s  non-zero=%d" % (yr, arr.shape, int(np.sum(arr != 0))))

    print("\n[2] Temporal smoothing")
    smoothed_stack = apply_temporal_smoothing(lulc_stack)

    print("\n[3] Computing 5 transition rasters")
    param_rasters = {}
    then_urb, now_urb = make_then_now(REMAP_URB, lulc_stack)
    param_rasters["Urbanization"]  = compute_urbanization(then_urb, now_urb)
    print("    Urbanization:  %s" % sorted(np.unique(param_rasters["Urbanization"]).tolist()))

    then_deg, now_deg = make_then_now(REMAP_DEG, lulc_stack)
    param_rasters["Degradation"]   = compute_degradation(then_deg, now_deg)
    print("    Degradation:   %s" % sorted(np.unique(param_rasters["Degradation"]).tolist()))

    then_for, now_for = make_then_now(REMAP_FOR, smoothed_stack)
    param_rasters["Deforestation"] = compute_deforestation(then_for, now_for)
    print("    Deforestation: %s" % sorted(np.unique(param_rasters["Deforestation"]).tolist()))

    param_rasters["Afforestation"] = compute_afforestation(then_for, now_for)
    print("    Afforestation: %s" % sorted(np.unique(param_rasters["Afforestation"]).tolist()))

    then_crp, now_crp = make_then_now(REMAP_CRP, lulc_stack)
    param_rasters["CropIntensity"] = compute_crop_intensity(then_crp, now_crp)
    print("    CropIntensity: %s" % sorted(np.unique(param_rasters["CropIntensity"]).tolist()))

    print("\n[4] Writing raster outputs")
    out_profile = profile.copy()
    out_profile.update(dtype="int32", count=1, nodata=-9999)
    for param, arr in param_rasters.items():
        out_path = os.path.join(OUT_DIR, "change_%s.tif" % param)
        with rasterio.open(out_path, "w", **out_profile) as dst:
            dst.write(arr.astype(np.int32), 1)
        log["rasters"][param] = {"path": out_path, "unique_codes": sorted(np.unique(arr).tolist()), "shape": list(arr.shape)}
        print("    Written: %s" % out_path)

    print("\n[5] Computing per-watershed statistics")
    mws_gdf = gpd.read_file(MWS_PATH)
    if mws_gdf.crs is None:
        mws_gdf = mws_gdf.set_crs("EPSG:4326")
    mws_gdf = mws_gdf.to_crs(crs)
    print("    %d watersheds" % len(mws_gdf))
    for param, arr in param_rasters.items():
        result_gdf = compute_watershed_stats(arr, transform, crs, mws_gdf, VECTOR_MAPS[param])
        out_path   = os.path.join(OUT_DIR, "change_vector_%s.geojson" % param)
        result_gdf.to_file(out_path, driver="GeoJSON")
        log["vectors"][param] = {"path": out_path, "watershed_count": len(result_gdf), "columns": list(result_gdf.columns)}
        print("    Written: %s" % out_path)

    log_path = os.path.join(LOG_DIR, "phase5a_python_output.json")
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    print("\nPhase 5A complete. Log: %s" % log_path)

if __name__ == "__main__":
    main()
