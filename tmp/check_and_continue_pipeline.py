#!/usr/bin/env python3
"""
check_and_continue_pipeline.py
--------------------------------
Checks if admin boundary GEE asset is ready, then runs MWS + LULC steps.
This is needed because the admin boundary upload is async and must complete
before MWS can use it.
"""
import os, sys
sys.path.insert(0, '/home/uttkarsh/core-stack-backend')
os.chdir('/home/uttkarsh/core-stack-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nrm_app.settings')
import django
django.setup()

import ee, time
from utilities.gee_utils import ee_initialize, is_gee_asset_exists, check_task_status
from computing.mws.mws import mws_layer
from computing.lulc.lulc_v3 import clip_lulc_v3

STATE = "bihar"
DISTRICT = "kaimur"
BLOCK = "kudra"
GEE_ACCOUNT_ID = 1

ADMIN_BOUNDARY_ASSET = "projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/admin_boundary_kaimur_kudra"
MWS_ASSET = "projects/arcane-mason-493503-a6/assets/apps/mws/bihar/kaimur/kudra/filtered_mws_kaimur_kudra_uid"

print("=" * 60)
print("Continuing GEE Pipeline: MWS + LULC steps for Kudra")
print("=" * 60)

ee_initialize(GEE_ACCOUNT_ID)
print("✓ Earth Engine initialized.")

# --- Wait for Admin Boundary Asset to be ready ---
print(f"\nChecking if admin boundary asset exists in GEE...")
MAX_WAIT_MINS = 10
for attempt in range(MAX_WAIT_MINS * 2):
    if is_gee_asset_exists(ADMIN_BOUNDARY_ASSET):
        print(f"✓ Admin boundary asset is ready: {ADMIN_BOUNDARY_ASSET}")
        break
    else:
        print(f"  Waiting for asset... (attempt {attempt+1}/{MAX_WAIT_MINS*2})")
        time.sleep(30)
else:
    print(f"✗ Admin boundary asset still not ready after {MAX_WAIT_MINS} minutes!")
    print("  The GEE upload task may have failed. Check GEE console.")
    sys.exit(1)

# --- Step 2: MWS ---
print("\n[Step 2/3] Running MWS layer extraction...")
mws_success = mws_layer(STATE, DISTRICT, BLOCK, GEE_ACCOUNT_ID)
print(f"✓ MWS step finished. Success: {mws_success}")
print(f"  MWS asset: {MWS_ASSET}")

# Verify MWS asset
if not is_gee_asset_exists(MWS_ASSET):
    print("✗ MWS asset not found in GEE after step. Aborting LULC step.")
    sys.exit(1)

# --- Step 3: LULC Clipping ---
print("\n[Step 3/3] Clipping LULC maps for 6 years (2018-2023)...")
lulc_success = clip_lulc_v3(
    state=STATE,
    district=DISTRICT,
    block=BLOCK,
    start_year=2018,
    end_year=2023,
    gee_account_id=GEE_ACCOUNT_ID
)
print(f"✓ LULC clipping finished. Success: {lulc_success}")

print("\n" + "=" * 60)
print("Pipeline complete! Check GEE console for task statuses.")
print("=" * 60)
