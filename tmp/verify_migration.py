import os
import sys
import json
import numpy as np
import rasterio

PY_DIR = "data/lulc_exports/change_detection"
OC_DIR = "data/lulc_exports/ocaml_change_detection"

def verify_rasters():
    print("=== Verifying Rasters ===")
    classes = {
        "urbanization": "Urbanization",
        "degradation": "Degradation",
        "deforestation": "Deforestation",
        "afforestation": "Afforestation",
        "cropintensity": "CropIntensity"
    }
    all_match = True
    for c, oc_c in classes.items():
        py_path = os.path.join(PY_DIR, f"change_{c}.tif")
        oc_path = os.path.join(OC_DIR, f"change_{oc_c}.tif")

        
        with rasterio.open(py_path) as py_src:
            py_arr = py_src.read(1)
        with rasterio.open(oc_path) as oc_src:
            oc_arr = oc_src.read(1)
            
        if py_arr.shape != oc_arr.shape:
            print(f"❌ {c}: Shape mismatch {py_arr.shape} != {oc_arr.shape}")
            all_match = False
            continue
            
        diff = py_arr != oc_arr
        mismatches = np.sum(diff)
        if mismatches == 0:
            print(f"✅ {c}: Exact pixel-for-pixel match!")
        else:
            print(f"❌ {c}: {mismatches} mismatching pixels!")
            all_match = False
            
    return all_match

def verify_vectors():
    print("\n=== Verifying Vectors ===")
    py_path = os.path.join(PY_DIR, "change_detection_vector.geojson")
    if not os.path.exists(py_path):
        print("No Python vector file to check.")
        return True
        
    with open(py_path) as f:
        py_data = json.load(f)
    py_features = {str(f['properties']['uid']): f['properties'] for f in py_data['features']}
    
    classes = ["Urbanization", "Degradation", "Deforestation", "Afforestation", "CropIntensity"]
    all_match = True
    for c in classes:
        oc_path = os.path.join(OC_DIR, f"change_vector_{c}.geojson")
        with open(oc_path) as f:
            oc_data = json.load(f)
            
        for oc_feat in oc_data['features']:
            uid = str(oc_feat['properties']['uid'])
            oc_props = oc_feat['properties']
            py_props = py_features.get(uid, {})
            
            # Check fields
            for key in oc_props:
                if key == 'uid': continue
                # We expect floats. Allow 0.001 ha variance (10 sqm) due to float/pixel intersections
                py_val = py_props.get(key, 0.0)
                oc_val = oc_props[key]
                if abs(py_val - oc_val) > 0.001:
                    print(f"❌ {c} [UID {uid}]: '{key}' mismatch! Py={py_val:.4f}, OC={oc_val:.4f}")
                    all_match = False
    
    if all_match:
         print("✅ All vector stats match within tolerance!")
    return all_match

if __name__ == "__main__":
    r_ok = verify_rasters()
    v_ok = verify_vectors()
    if r_ok and v_ok:
        print("\n🎉 SUCCESS: OCaml migration outputs exactly match the Python baseline! 🎉")
        sys.exit(0)
    else:
        print("\n⚠️ FAILURE: Mismatches found in migration.")
        sys.exit(1)
