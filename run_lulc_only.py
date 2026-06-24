#!/usr/bin/env python3
"""Run only clip_lulc_v3 for Bihar/Jamui/Jamui after admin+MWS tasks are done."""
import os, sys, traceback

BACKEND_DIR = "/home/uttkarsh/core-stack-backend"
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")

import django
django.setup()

from utilities.gee_utils import ee_initialize
from computing.lulc.lulc_v3 import clip_lulc_v3
import ee

STATE = "bihar"
DISTRICT = "jamui"
BLOCK = "jamui"
GEE_ACCOUNT_ID = 1

print("[Init] EE init...")
sys.stdout.flush()
success = ee_initialize(GEE_ACCOUNT_ID)
if not success:
    print("ERROR: EE init failed")
    sys.exit(1)
print("  OK")
sys.stdout.flush()

# Check MWS asset status first
MWS_ASSET = "projects/arcane-mason-493503-a6/assets/apps/mws/bihar/jamui/jamui/filtered_mws_jamui_jamui_uid"
try:
    info = ee.data.getAsset(MWS_ASSET)
    print("MWS asset EXISTS:", MWS_ASSET)
    sys.stdout.flush()
except Exception as e:
    print("MWS asset NOT YET READY:", e)
    print("Check GEE task GDPFYJNU7Q2HXVGE3MYBABIF status first")
    sys.stdout.flush()

# Check LULC assets
LULC_BASE = "projects/arcane-mason-493503-a6/assets/apps/mws/bihar/jamui/jamui"
print("\nLULC asset status:")
sys.stdout.flush()
for yr in [2018, 2019, 2020, 2021, 2022, 2023]:
    asset_id = f"{LULC_BASE}/jamui_jamui_{yr}-07-01_{yr+1}-06-30_LULCmap_10m"
    try:
        ee.data.getAsset(asset_id)
        print(f"  {yr}: EXISTS")
    except:
        print(f"  {yr}: MISSING")
    sys.stdout.flush()

print("\n[Step 3/3] Clipping LULC maps 2018-2023...")
sys.stdout.flush()
try:
    r = clip_lulc_v3(
        state=STATE,
        district=DISTRICT,
        block=BLOCK,
        start_year=2018,
        end_year=2023,
        gee_account_id=GEE_ACCOUNT_ID,
    )
    print("  clip_lulc_v3 result:", r)
    sys.stdout.flush()
except BaseException as e:
    print("  clip_lulc_v3 ERROR:", type(e).__name__, e)
    traceback.print_exc()
    sys.stdout.flush()

print("\nDone.")
sys.stdout.flush()
