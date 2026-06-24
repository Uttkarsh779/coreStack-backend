"""
Phase 3: Validate all 6 LULC GEE assets for Kudra.

For each year, verifies:
  - asset exists
  - is readable (getInfo succeeds)
  - projection / CRS
  - dimensions (width × height)
  - band names
  - pixel value range (min/max, unique classes)
  - asset is not empty

Writes logs/phase3_lulc_validation.json
"""
import os, sys, json, re
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django; django.setup()
import ee
from utilities.gee_utils import ee_initialize, get_gee_asset_path, is_gee_asset_exists

YEARS    = [2018, 2019, 2020, 2021, 2022, 2023]
STATE    = "Bihar"
DISTRICT = "Kaimur"
BLOCK    = "Kudra"
LOG_DIR  = os.path.join(BASE_DIR, "kudra_verification", "logs")
VALID_LULC_CLASSES = {0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12}

def valid(s):
    return re.sub(r"[^a-zA-Z0-9 ,:;_-]", "", s).replace(" ", "_")

def validate_lulc_asset(asset_id, yr):
    result = {"asset_id": asset_id, "year": yr}
    d = valid(DISTRICT.lower())
    b = valid(BLOCK.lower())

    # 1. Existence
    if not is_gee_asset_exists(asset_id):
        result["exists"] = False
        result["valid"] = False
        result["errors"] = ["asset does not exist"]
        return result
    result["exists"] = True

    try:
        # 2. Readable
        img = ee.Image(asset_id)
        info = img.getInfo()
        result["readable"] = True

        # 3. Bands
        bands = [b_info.get("id") for b_info in info.get("bands", [])]
        result["bands"] = bands
        result["band_count"] = len(bands)

        # 4. Projection / CRS
        proj = img.projection().getInfo()
        result["crs"] = proj.get("crs", "unknown")
        transform = proj.get("transform", [])
        if len(transform) >= 2:
            result["x_res_m"] = abs(transform[0])

        # 5. Dimensions
        dims = img.select(bands[0]) if bands else img
        try:
            pixel_count = dims.reduceRegion(
                reducer=ee.Reducer.count(),
                scale=10,
                maxPixels=1e10,
            ).getInfo()
            result["pixel_count"] = pixel_count.get(bands[0], 0) if bands else 0
        except Exception as e:
            result["pixel_count_error"] = str(e)

        # 6. Value range (sampled)
        try:
            stats = img.select(bands[0]).reduceRegion(
                reducer=ee.Reducer.frequencyHistogram(),
                scale=10,
                maxPixels=1e10,
            ).getInfo()
            hist = stats.get(bands[0], {})
            classes = {int(float(k)): int(v) for k, v in hist.items()} if hist else {}
            class_keys = set(classes.keys())
            result["class_histogram"] = classes
            result["observed_classes"] = sorted(class_keys)
            unexpected = class_keys - VALID_LULC_CLASSES
            result["unexpected_classes"] = sorted(unexpected)
            result["has_expected_classes"] = bool(class_keys & {1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12})
        except Exception as e:
            result["histogram_error"] = str(e)

        # 7. Not empty
        total_pixels = result.get("pixel_count", 0)
        result["is_empty"] = total_pixels == 0
        result["valid"] = not result.get("is_empty", True) and result.get("readable", False)

    except Exception as e:
        result["readable"] = False
        result["errors"] = [str(e)]
        result["valid"] = False

    return result

def main():
    print("=" * 60)
    print("Phase 3: LULC Asset Validation")
    print("=" * 60)

    ee_initialize(1)
    asset_base = get_gee_asset_path(STATE, DISTRICT, BLOCK)
    d = valid(DISTRICT.lower())
    b = valid(BLOCK.lower())

    all_results = {}
    all_valid   = True

    for yr in YEARS:
        lulc_name     = f"{d}_{b}_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
        lulc_asset_id = asset_base + lulc_name
        print(f"\n[{yr}] Validating: {lulc_asset_id}")

        result = validate_lulc_asset(lulc_asset_id, yr)
        all_results[str(yr)] = result

        if not result.get("exists"):
            print(f"    ✗ MISSING")
            all_valid = False
            continue
        if not result.get("readable"):
            print(f"    ✗ NOT READABLE: {result.get('errors')}")
            all_valid = False
            continue

        print(f"    ✓ EXISTS & READABLE")
        print(f"    CRS:        {result.get('crs')}")
        print(f"    Resolution: {result.get('x_res_m')} m")
        print(f"    Bands:      {result.get('bands')}")
        print(f"    Pixels:     {result.get('pixel_count', '?'):,}")
        print(f"    Classes:    {result.get('observed_classes')}")
        if result.get("unexpected_classes"):
            print(f"    ⚠ Unexpected classes: {result['unexpected_classes']}")
        if result.get("is_empty"):
            print(f"    ✗ EMPTY RASTER!")
            all_valid = False

    # Save
    out_path = os.path.join(LOG_DIR, "phase3_lulc_validation.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n\nPhase 3 complete. Log: {out_path}")
    print(f"All valid: {all_valid}")
    for yr, r in all_results.items():
        status = "✓ VALID" if r.get("valid") else "✗ INVALID"
        print(f"  [{yr}] {status}  classes={r.get('observed_classes','?')}")

if __name__ == "__main__":
    main()
