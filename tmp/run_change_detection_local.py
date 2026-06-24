#!/usr/bin/env python3
"""
run_change_detection_local.py
------------------------------
Runs the CoRE Stack change detection pipeline LOCALLY using real LULC GeoTIFFs
(exported from GEE) — without any GEE dependency.

This produces the "ground truth" outputs we will verify the OCaml implementation against.

Prerequisites:
    - data/lulc_exports/lulc_guindy_2022-2023.tif  (downloaded from Google Drive)
    - data/lulc_exports/lulc_guindy_2023-2024.tif
    - data/lulc_exports/mws_guindy.geojson          (already fetched)

Math logic mirrors computing/change_detection/change_detection.py exactly:
    - remap() = ee.Image.remap()
    - mode of first N years = "then", last N years = "now"
    - pixel-wise transition class assignment
    - zonal stats = sum of pixel area per class per MWS polygon

Outputs (to data/lulc_exports/change_detection/):
    change_urbanization.tif
    change_degradation.tif
    change_deforestation.tif
    change_afforestation.tif
    change_cropintensity.tif
    change_detection_vector.geojson   (area stats per MWS polygon — mirrors vectorise_change_detection)

Author: CoRE Stack OCaml Migration — June 2026
"""
import os
# Fix PROJ db conflict
_rasterio_proj = "/home/uttkarsh/miniconda3/envs/corestackenv/lib/python3.10/site-packages/rasterio/proj_data"
os.environ.setdefault("PROJ_DATA", _rasterio_proj)
os.environ.setdefault("PROJ_LIB", _rasterio_proj)

import sys, json
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.mask import mask as rio_mask
from shapely.geometry import shape
from scipy import stats

LULC_DIR = 'data/lulc_exports'
OUT_DIR  = 'data/lulc_exports/change_detection'
os.makedirs(OUT_DIR, exist_ok=True)

LULC_FILES = [
    os.path.join(LULC_DIR, 'lulc_guindy_2022-2023.tif'),
    os.path.join(LULC_DIR, 'lulc_guindy_2023-2024.tif'),
]

# Verify inputs exist
for f in LULC_FILES:
    if not os.path.exists(f):
        print(f"ERROR: Missing input file: {f}")
        print("Please download TIFFs from Google Drive and place them at the paths above.")
        sys.exit(1)

MWS_PATH = os.path.join(LULC_DIR, 'mws_guindy.geojson')

# ── Helpers ──────────────────────────────────────────────────────────────────

FROM_CLASSES = [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]

def remap(arr: np.ndarray, to_vals: list, default: int = 0) -> np.ndarray:
    """Remap FROM_CLASSES → to_vals, same as ee.Image.remap()."""
    out = np.full_like(arr, default, dtype=np.uint8)
    for f, t in zip(FROM_CLASSES, to_vals):
        out[arr == f] = t
    return out

def pixel_mode(arrays: list) -> np.ndarray:
    """Pixel-wise mode across a list of 2D arrays, like ee.ImageCollection.mode()."""
    stack = np.stack(arrays, axis=0)
    result, _ = stats.mode(stack, axis=0, keepdims=False)
    return result.astype(np.uint8)

def save_tif(path: str, arr: np.ndarray, profile: dict):
    p = profile.copy()
    p.update(dtype=rasterio.uint8, count=1, nodata=0)
    with rasterio.open(path, 'w', **p) as dst:
        dst.write(arr, 1)
    print(f"  Saved: {os.path.basename(path)}")

# ── Load LULC rasters ────────────────────────────────────────────────────────
print("=== Loading LULC rasters ===")
arrays = []
profile = None
for path in LULC_FILES:
    with rasterio.open(path) as src:
        if profile is None:
            profile = src.profile
        data = src.read(1)
        arrays.append(data)
        print(f"  {os.path.basename(path)}: shape={data.shape}, dtype={data.dtype}, "
              f"unique={sorted(np.unique(data).tolist())[:10]}")

# With only 2 years we do:  then = arrays[0],  now = arrays[1]
# For mode of 3 years the pipeline normally uses 3 years;
# with 2 we fall back to: then = year 0 (single), now = year 1 (single)
# (mode of single image = that image)
then = arrays[0]
now  = arrays[1]
print(f"\nthen (2022-2023): unique={sorted(np.unique(then).tolist())}")
print(f"now  (2023-2024): unique={sorted(np.unique(now).tolist())}")

# ── Change Detection Functions ───────────────────────────────────────────────

def run_urbanization(then, now):
    TO = [1, 2, 2, 2, 3, 4, 3, 3, 3, 3, 4]
    t = remap(then, TO)
    n = remap(now,  TO)
    result = np.zeros_like(then, dtype=np.uint8)
    result += ((t == 1) & (n == 1)).astype(np.uint8) * 1  # bu→bu
    result += ((t == 2) & (n == 1)).astype(np.uint8) * 2  # w→bu
    result += ((t == 3) & (n == 1)).astype(np.uint8) * 3  # tr→bu
    result += ((t == 4) & (n == 1)).astype(np.uint8) * 4  # b→bu
    return result

def run_degradation(then, now):
    TO = [1, 2, 2, 2, 4, 5, 3, 3, 3, 3, 6]
    t = remap(then, TO)
    n = remap(now,  TO)
    result = np.zeros_like(then, dtype=np.uint8)
    result += ((t == 3) & (n == 3)).astype(np.uint8) * 1  # f→f (stable)
    result += ((t == 3) & (n == 1)).astype(np.uint8) * 2  # f→bu
    result += ((t == 3) & (n == 5)).astype(np.uint8) * 3  # f→ba
    result += ((t == 3) & (n == 6)).astype(np.uint8) * 4  # f→sc
    return result

def run_deforestation(then, now):
    TO = [1, 2, 2, 2, 3, 5, 4, 4, 4, 4, 6]
    t = remap(then, TO)
    n = remap(now,  TO)
    result = np.zeros_like(then, dtype=np.uint8)
    result += ((t == 3) & (n == 3)).astype(np.uint8) * 1
    result += ((t == 3) & (n == 1)).astype(np.uint8) * 2
    result += ((t == 3) & (n == 4)).astype(np.uint8) * 3
    result += ((t == 3) & (n == 5)).astype(np.uint8) * 4
    result += ((t == 3) & (n == 6)).astype(np.uint8) * 5
    return result

def run_afforestation(then, now):
    TO = [1, 2, 2, 2, 3, 5, 4, 4, 4, 4, 6]
    t = remap(then, TO)
    n = remap(now,  TO)
    result = np.zeros_like(then, dtype=np.uint8)
    result += ((t == 3) & (n == 3)).astype(np.uint8) * 1
    result += ((t == 1) & (n == 3)).astype(np.uint8) * 2
    result += ((t == 4) & (n == 3)).astype(np.uint8) * 3
    result += ((t == 5) & (n == 3)).astype(np.uint8) * 4
    result += ((t == 6) & (n == 3)).astype(np.uint8) * 5
    return result

def run_cropintensity(then, now):
    TO = [1, 2, 2, 2, 3, 4, 5, 5, 6, 7, 8]
    t = remap(then, TO)
    n = remap(now,  TO)
    result = np.zeros_like(then, dtype=np.uint8)
    result += ((t == 6) & (n == 5)).astype(np.uint8) * 1
    result += ((t == 7) & (n == 5)).astype(np.uint8) * 2
    result += ((t == 7) & (n == 6)).astype(np.uint8) * 3
    result += ((t == 5) & (n == 6)).astype(np.uint8) * 4
    result += ((t == 5) & (n == 7)).astype(np.uint8) * 5
    result += ((t == 6) & (n == 7)).astype(np.uint8) * 6
    result += ((t == 5) & (n == 5)).astype(np.uint8) * 7
    result += ((t == 6) & (n == 6)).astype(np.uint8) * 8
    result += ((t == 7) & (n == 7)).astype(np.uint8) * 9
    return result

# ── Run all change detections ─────────────────────────────────────────────────
print("\n=== Running change detection ===")
change_layers = {
    'urbanization':  run_urbanization(then, now),
    'degradation':   run_degradation(then, now),
    'deforestation': run_deforestation(then, now),
    'afforestation': run_afforestation(then, now),
    'cropintensity': run_cropintensity(then, now),
}

for name, arr in change_layers.items():
    out_path = os.path.join(OUT_DIR, f'change_{name}.tif')
    save_tif(out_path, arr, profile)
    unique = sorted(np.unique(arr).tolist())
    counts = {str(v): int(np.sum(arr == v)) for v in np.unique(arr)}
    print(f"    unique values: {unique}")
    print(f"    pixel counts: {counts}")

# ── Zonal Statistics per MWS Polygon ─────────────────────────────────────────
print("\n=== Computing zonal statistics (mirrors vectorise_change_detection) ===")

# LULC class area descriptions — same as in change_detection_vector.py
ZONAL_CLASSES = {
    'urbanization':  [
        {'value': 1, 'label': 'bu_bu'},
        {'value': 2, 'label': 'w_bu'},
        {'value': 3, 'label': 'tr_bu'},
        {'value': 4, 'label': 'b_bu'},
        {'value': [2,3,4], 'label': 'total_urb'},
    ],
    'degradation': [
        {'value': 1, 'label': 'f_f'},
        {'value': 2, 'label': 'f_bu'},
        {'value': 3, 'label': 'f_ba'},
        {'value': 4, 'label': 'f_sc'},
        {'value': [2,3,4], 'label': 'total_deg'},
    ],
    'deforestation': [
        {'value': 1, 'label': 'fo_fo'},
        {'value': 2, 'label': 'fo_bu'},
        {'value': 3, 'label': 'fo_fa'},
        {'value': 4, 'label': 'fo_ba'},
        {'value': 5, 'label': 'fo_sc'},
        {'value': [2,3,4,5], 'label': 'total_def'},
    ],
    'afforestation': [
        {'value': 1, 'label': 'fo_fo'},
        {'value': 2, 'label': 'bu_fo'},
        {'value': 3, 'label': 'fa_fo'},
        {'value': 4, 'label': 'ba_fo'},
        {'value': 5, 'label': 'sc_fo'},
        {'value': [2,3,4,5], 'label': 'total_aff'},
    ],
    'cropintensity': [
        {'value': 1, 'label': 'do_si'},
        {'value': 2, 'label': 'tr_si'},
        {'value': 3, 'label': 'tr_do'},
        {'value': 4, 'label': 'si_do'},
        {'value': 5, 'label': 'si_tr'},
        {'value': 6, 'label': 'do_tr'},
        {'value': 7, 'label': 'si_si'},
        {'value': 8, 'label': 'do_do'},
        {'value': 9, 'label': 'tr_tr'},
        {'value': [1,2,3,4,5,6], 'label': 'total_change'},
    ],
}

# Load MWS GeoJSON
with open(MWS_PATH) as f:
    mws = json.load(f)
mws_features = mws['features']
print(f"  MWS polygons: {len(mws_features)}")

# Pixel area in m² at EPSG:4326 requires reprojection — at 10m scale, each pixel = 100 m² = 0.01 ha
# For EPSG:4326 GeoTIFFs exported at 10m, rasterio gives pixel area in degrees.
# Use profile to compute pixel area in ha via the resolution and CRS.
# GEE exports at 10m so each pixel = 100 m² = 0.01 ha
PIXEL_AREA_HA = 0.01  # ha per pixel at 10m resolution

vector_output = {'type': 'FeatureCollection', 'features': []}

with rasterio.open(os.path.join(OUT_DIR, 'change_urbanization.tif')) as ref_src:
    ref_transform = ref_src.transform
    ref_crs = ref_src.crs

for feat_idx, feature in enumerate(mws_features):
    geom = feature['geometry']
    props = dict(feature.get('properties', {}))

    feat_result = {}

    for layer_name, class_defs in ZONAL_CLASSES.items():
        tif_path = os.path.join(OUT_DIR, f'change_{layer_name}.tif')
        with rasterio.open(tif_path) as src:
            try:
                masked, _ = rio_mask(src, [geom], crop=True, nodata=0, filled=True)
                pixel_arr = masked[0]
            except Exception:
                # Polygon may not overlap raster
                pixel_arr = np.array([], dtype=np.uint8)

        for cls in class_defs:
            v = cls['value']
            label = cls['label']
            if isinstance(v, list):
                mask = np.isin(pixel_arr, v)
            else:
                mask = (pixel_arr == v)
            area_ha = float(np.sum(mask)) * PIXEL_AREA_HA
            feat_result[f'{layer_name}_{label}'] = round(area_ha, 4)

    props.update(feat_result)
    vector_output['features'].append({
        'type': 'Feature',
        'geometry': geom,
        'properties': props,
    })

    if (feat_idx + 1) % 2 == 0:
        print(f"  Processed {feat_idx+1}/{len(mws_features)} polygons...")

vector_path = os.path.join(OUT_DIR, 'change_detection_vector.geojson')
with open(vector_path, 'w') as f:
    json.dump(vector_output, f)
print(f"  Saved: {vector_path}")

# ── Summary JSON (ground truth for OCaml comparison) ─────────────────────────
summary = {
    'metadata': {
        'region': 'Tamil Nadu / Chennai / Guindy',
        'lulc_years': ['2022-2023', '2023-2024'],
        'then': '2022-2023',
        'now': '2023-2024',
        'pixel_area_ha': PIXEL_AREA_HA,
        'raster_profile': {
            'crs': str(profile.get('crs', '')),
            'transform': list(profile.get('transform', [])),
            'width': profile.get('width'), 'height': profile.get('height'),
        },
    },
    'change_detection_raster': {},
}
for name, arr in change_layers.items():
    summary['change_detection_raster'][name] = {
        'unique_values': sorted([int(v) for v in np.unique(arr)]),
        'pixel_counts': {str(int(v)): int(np.sum(arr == v)) for v in np.unique(arr)},
        'total_pixels': int(arr.size),
    }

summary_path = os.path.join(OUT_DIR, 'ground_truth_summary.json')
with open(summary_path, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n✓ Ground truth summary saved to: {summary_path}")
print("\n=== All done ===")
print("These are the reference outputs for OCaml verification.")
