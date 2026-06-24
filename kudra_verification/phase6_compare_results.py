"""
Phase 6: Pixel-by-pixel comparison of Python vs OCaml change detection outputs.

For each of the 5 parameters:
  1. Load python_output/change_<P>.tif and ocaml_output/change_<P>.tif
  2. Count matching / mismatching pixels
  3. Compute mismatch %
  4. Write difference raster to diff_output/diff_<P>.tif
  5. Show class-level confusion summary
  6. Vector attribute comparison per watershed

Writes logs/phase6_comparison.json and diff_output/*.tif
"""
import os, sys, json
import numpy as np
import rasterio
from rasterio.enums import Resampling
import geopandas as gpd

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_DIR    = os.path.join(BASE_DIR, "kudra_verification", "python_output")
OCAML_DIR = os.path.join(BASE_DIR, "kudra_verification", "ocaml_output")
DIFF_DIR  = os.path.join(BASE_DIR, "kudra_verification", "diff_output")
LOG_DIR   = os.path.join(BASE_DIR, "kudra_verification", "logs")
os.makedirs(DIFF_DIR, exist_ok=True)

PARAMS = ["Urbanization", "Degradation", "Deforestation", "Afforestation", "CropIntensity"]

def load_raster(path):
    with rasterio.open(path) as src:
        arr     = src.read(1).astype(np.int32)
        profile = src.profile.copy()
        nodata  = src.nodata
    return arr, profile, nodata

def align_arrays(py_arr, ocaml_arr, py_profile, ocaml_profile):
    """If shapes differ, crop/pad to the intersection. Usually same shape."""
    if py_arr.shape == ocaml_arr.shape:
        return py_arr, ocaml_arr
    # Crop to min shape
    h = min(py_arr.shape[0], ocaml_arr.shape[0])
    w = min(py_arr.shape[1], ocaml_arr.shape[1])
    print(f"    Shape mismatch: py={py_arr.shape}, ocaml={ocaml_arr.shape} → cropping to ({h},{w})")
    return py_arr[:h, :w], ocaml_arr[:h, :w]

def compare_rasters(py_path, ocaml_path, diff_path, param):
    result = {"param": param, "py_path": py_path, "ocaml_path": ocaml_path}

    if not os.path.exists(py_path):
        result["error"] = f"python output missing: {py_path}"
        return result
    if not os.path.exists(ocaml_path):
        result["error"] = f"ocaml output missing: {ocaml_path}"
        return result

    py_arr,    py_prof,    py_nd    = load_raster(py_path)
    ocaml_arr, ocaml_prof, ocaml_nd = load_raster(ocaml_path)

    # Align
    py_arr, ocaml_arr = align_arrays(py_arr, ocaml_arr, py_prof, ocaml_prof)
    result["shape"] = list(py_arr.shape)

    # Build valid pixel mask (exclude nodata from both)
    nd_py    = py_nd    if py_nd    is not None else -9999
    nd_ocaml = ocaml_nd if ocaml_nd is not None else -9999
    valid    = (py_arr != nd_py) & (ocaml_arr != nd_ocaml)
    total    = int(valid.sum())
    result["total_valid_pixels"] = total

    if total == 0:
        result["error"] = "no valid pixels in valid mask"
        return result

    # Mismatch
    mismatch = valid & (py_arr != ocaml_arr)
    n_mis    = int(mismatch.sum())
    n_match  = total - n_mis
    pct_mis  = 100.0 * n_mis / total if total > 0 else 0.0

    result["matching_pixels"]   = n_match
    result["mismatching_pixels"] = n_mis
    result["mismatch_pct"]       = round(pct_mis, 4)
    result["perfect_match"]      = n_mis == 0

    print(f"    Total valid: {total:,}")
    print(f"    Matching:    {n_match:,}  ({100.0*n_match/total:.4f}%)")
    print(f"    Mismatching: {n_mis:,}  ({pct_mis:.4f}%)")

    # Per-class breakdown of mismatches
    if n_mis > 0:
        mis_py    = py_arr[mismatch]
        mis_ocaml = ocaml_arr[mismatch]
        diffs = {}
        for py_v, oc_v in zip(mis_py.tolist(), mis_ocaml.tolist()):
            key = f"py={py_v}→ocaml={oc_v}"
            diffs[key] = diffs.get(key, 0) + 1
        # Show top 10 discrepancies
        top = sorted(diffs.items(), key=lambda x: -x[1])[:10]
        result["top_discrepancies"] = {k: v for k, v in top}
        print(f"    Top discrepancies:")
        for k, v in top:
            print(f"      {k}: {v:,} pixels")

    # Class distribution comparison
    py_classes    = {int(v): int(c) for v, c in zip(*np.unique(py_arr[valid], return_counts=True))}
    ocaml_classes = {int(v): int(c) for v, c in zip(*np.unique(ocaml_arr[valid], return_counts=True))}
    result["py_class_dist"]    = py_classes
    result["ocaml_class_dist"] = ocaml_classes

    all_classes = sorted(set(py_classes) | set(ocaml_classes))
    if len(all_classes) <= 15:
        print(f"    Class distribution (py vs ocaml):")
        for cls in all_classes:
            p_cnt = py_classes.get(cls, 0)
            o_cnt = ocaml_classes.get(cls, 0)
            marker = "  " if p_cnt == o_cnt else " ✗"
            print(f"      cls={cls}: py={p_cnt:,}  ocaml={o_cnt:,}{marker}")

    # Write difference raster
    diff_arr = np.zeros_like(py_arr, dtype=np.int32)
    diff_arr[valid & (py_arr != ocaml_arr)] = 1   # 1 = mismatch
    diff_arr[~valid] = -9999
    diff_profile = py_prof.copy()
    diff_profile.update(dtype=rasterio.int32, nodata=-9999)
    with rasterio.open(diff_path, "w", **diff_profile) as dst:
        dst.write(diff_arr, 1)
    result["diff_path"] = diff_path
    print(f"    Diff raster: {diff_path}")

    return result

def compare_vectors(py_dir, ocaml_dir, param):
    py_path    = os.path.join(py_dir,    f"change_vector_{param}.geojson")
    ocaml_path = os.path.join(ocaml_dir, f"change_vector_{param}.geojson")
    result     = {"param": param}

    if not os.path.exists(py_path):
        result["error"] = f"python vector missing: {py_path}"
        return result
    if not os.path.exists(ocaml_path):
        result["error"] = f"ocaml vector missing: {ocaml_path}"
        return result

    py_gdf    = gpd.read_file(py_path)
    ocaml_gdf = gpd.read_file(ocaml_path)

    result["py_feature_count"]    = len(py_gdf)
    result["ocaml_feature_count"] = len(ocaml_gdf)

    # Align on uid
    numeric_cols = [c for c in py_gdf.columns if c not in ("uid", "geometry")]
    result["attribute_columns"] = numeric_cols

    if len(py_gdf) == 0 or len(ocaml_gdf) == 0:
        result["error"] = "empty vector"
        return result

    # Sort by uid for alignment
    try:
        py_s    = py_gdf.sort_values("uid").reset_index(drop=True)
        ocaml_s = ocaml_gdf.sort_values("uid").reset_index(drop=True)
    except Exception:
        py_s    = py_gdf.reset_index(drop=True)
        ocaml_s = ocaml_gdf.reset_index(drop=True)

    n = min(len(py_s), len(ocaml_s))
    result["compared_features"] = n

    col_results = {}
    for col in numeric_cols:
        if col not in py_s.columns or col not in ocaml_s.columns:
            continue
        py_vals    = py_s[col].fillna(0).values[:n]
        ocaml_vals = ocaml_s[col].fillna(0).values[:n]
        diff       = np.abs(py_vals - ocaml_vals)
        rel_diff   = np.where(
            np.abs(py_vals) > 1e-9, diff / np.abs(py_vals) * 100, 0.0
        )
        col_results[col] = {
            "max_abs_diff":  float(np.max(diff)),
            "mean_abs_diff": float(np.mean(diff)),
            "max_rel_diff_pct": float(np.max(rel_diff)),
            "perfect_match": bool(np.all(diff < 0.0001)),
        }
    result["column_diffs"] = col_results
    return result

def main():
    print("=" * 60)
    print("Phase 6: Python vs OCaml Comparison")
    print("=" * 60)

    log = {"raster_comparisons": {}, "vector_comparisons": {}}
    all_perfect = True

    for param in PARAMS:
        print(f"\n--- {param} ---")

        # Raster comparison
        py_path    = os.path.join(PY_DIR,    f"change_{param}.tif")
        ocaml_path = os.path.join(OCAML_DIR, f"change_{param}.tif")
        diff_path  = os.path.join(DIFF_DIR,  f"diff_{param}.tif")

        raster_result = compare_rasters(py_path, ocaml_path, diff_path, param)
        log["raster_comparisons"][param] = raster_result
        if not raster_result.get("perfect_match"):
            all_perfect = False

        # Vector comparison
        vector_result = compare_vectors(PY_DIR, OCAML_DIR, param)
        log["vector_comparisons"][param] = vector_result

    # Save log
    out_path = os.path.join(LOG_DIR, "phase6_comparison.json")
    with open(out_path, "w") as f:
        json.dump(log, f, indent=2)

    print(f"\n\nPhase 6 complete. Log: {out_path}")
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"{'Parameter':<18} {'Match%':>8}  {'Mismatch px':>12}  {'Vector OK':>10}")
    print("-" * 55)
    for param in PARAMS:
        r = log["raster_comparisons"].get(param, {})
        v = log["vector_comparisons"].get(param, {})
        mis_pct = r.get("mismatch_pct", 100.0)
        match_pct = 100.0 - mis_pct
        mis_px  = r.get("mismatching_pixels", "?")
        vec_ok  = all(
            cr.get("perfect_match", False)
            for cr in v.get("column_diffs", {}).values()
        ) if v.get("column_diffs") else "N/A"
        print(f"{param:<18} {match_pct:>7.4f}%  {str(mis_px):>12}  {str(vec_ok):>10}")

    print(f"\nOverall perfect match: {all_perfect}")

if __name__ == "__main__":
    main()
