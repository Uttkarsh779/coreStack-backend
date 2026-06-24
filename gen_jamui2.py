#!/usr/bin/env python3
import os, sys, traceback

BACKEND_DIR = "/home/uttkarsh/core-stack-backend"
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")

try:
    import django
    print("django imported")
    django.setup()
    print("django setup done")
except Exception as e:
    print("DJANGO ERROR:", e)
    traceback.print_exc()
    sys.exit(1)

try:
    from utilities.gee_utils import ee_initialize
    print("ee_initialize imported")
except Exception as e:
    print("ee_initialize IMPORT ERROR:", e)
    traceback.print_exc()

try:
    from computing.misc.admin_boundary import generate_tehsil_shape_file_data
    print("admin_boundary imported")
except Exception as e:
    print("admin_boundary IMPORT ERROR:", e)
    traceback.print_exc()

try:
    from computing.mws.mws import mws_layer
    print("mws_layer imported")
except Exception as e:
    print("mws_layer IMPORT ERROR:", e)
    traceback.print_exc()

try:
    from computing.lulc.lulc_v3 import clip_lulc_v3
    print("clip_lulc_v3 imported")
except Exception as e:
    print("clip_lulc_v3 IMPORT ERROR:", e)
    traceback.print_exc()

print("All imports done.")

STATE = "bihar"
DISTRICT = "jamui"
BLOCK = "jamui"
GEE_ACCOUNT_ID = 1

print("\n[Init] Initializing Earth Engine...")
try:
    success = ee_initialize(GEE_ACCOUNT_ID)
    if not success:
        print("ERROR: GEE init failed")
        sys.exit(1)
    print("  EE initialized OK")
except Exception as e:
    print("EE INIT ERROR:", e)
    traceback.print_exc()
    sys.exit(1)

print("\n[Step 1/3] Admin boundary...")
try:
    r = generate_tehsil_shape_file_data(STATE, DISTRICT, BLOCK, GEE_ACCOUNT_ID)
    print("  result:", r)
except Exception as e:
    print("  ERROR:", e)
    traceback.print_exc()

print("\n[Step 2/3] MWS layer...")
try:
    r = mws_layer(STATE, DISTRICT, BLOCK, GEE_ACCOUNT_ID)
    print("  result:", r)
except Exception as e:
    print("  ERROR:", e)
    traceback.print_exc()

print("\n[Step 3/3] Clipping LULC maps 2018-2023...")
try:
    r = clip_lulc_v3(
        state=STATE,
        district=DISTRICT,
        block=BLOCK,
        start_year=2018,
        end_year=2023,
        gee_account_id=GEE_ACCOUNT_ID,
    )
    print("  result:", r)
except Exception as e:
    print("  ERROR:", e)
    traceback.print_exc()

print("\nDone.")
