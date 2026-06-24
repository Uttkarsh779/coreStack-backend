#!/usr/bin/env python3
"""
run_gee_pipeline.py
-------------------
Executes the Earth Engine pipeline for Bihar / Kaimur / Kudra:
  1. Generate & Upload Sub-District Admin Boundary to GEE
  2. Extract & Upload Microwatershed (MWS) Boundaries to GEE
  3. Clip and Export 6 years of LULC Maps (2018–2023) in GEE

This script imports the Celery tasks and runs them synchronously.
"""
import os, sys

# Initialize Django environment
BACKEND_DIR = "/home/uttkarsh/core-stack-backend"
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")

import django
django.setup()

from utilities.gee_utils import ee_initialize
from computing.misc.admin_boundary import generate_tehsil_shape_file_data
from computing.mws.mws import mws_layer
from computing.lulc.lulc_v3 import clip_lulc_v3

STATE = "bihar"
DISTRICT = "kaimur"
BLOCK = "kudra"
GEE_ACCOUNT_ID = 1

def main():
    print("=" * 60)
    print("Starting Earth Engine Pipeline for Kudra Block")
    print(f"State: {STATE}, District: {DISTRICT}, Block/Tehsil: {BLOCK}")
    print("=" * 60)

    # 1. Initialize Earth Engine
    print("\nInitializing Earth Engine...")
    success = ee_initialize(GEE_ACCOUNT_ID)
    if not success:
        print("ERROR: Earth Engine initialization failed.")
        sys.exit(1)
    print("✓ Earth Engine initialized successfully.")

    # 2. Step 1: Generate & Upload Admin Boundary
    print("\n[Step 1/3] Generating sub-district Admin Boundary...")
    print("This reads kaimur.geojson and soi_tehsil.geojson, filters Kudra block, and uploads shapefile to GEE...")
    # Celery tasks automatically inject 'self' when called directly
    admin_success = generate_tehsil_shape_file_data(STATE, DISTRICT, BLOCK, GEE_ACCOUNT_ID)
    print(f"✓ Admin Boundary Step finished. Success state: {admin_success}")

    # 3. Step 2: Extract & Upload Microwatershed (MWS) Layer
    print("\n[Step 2/3] Extracting Microwatershed (MWS) boundaries...")
    print("This filters the India MWS dataset by the bounds of Kudra's admin boundary, and uploads it to GEE...")
    mws_success = mws_layer(STATE, DISTRICT, BLOCK, GEE_ACCOUNT_ID)
    print(f"✓ MWS Step finished. Success state: {mws_success}")

    # 4. Step 3: Clip and Export LULC Maps (2018–2023)
    print("\n[Step 3/3] Clipping and exporting LULC maps for 6 years (2018-2023)...")
    print("This clips the national river basin LULC dataset for each year, exports the rasters to GEE assets, and GCS...")
    lulc_success = clip_lulc_v3(
        state=STATE,
        district=DISTRICT,
        block=BLOCK,
        start_year=2018,
        end_year=2023,
        gee_account_id=GEE_ACCOUNT_ID
    )
    print(f"✓ LULC Clipping finished. Success state: {lulc_success}")

    print("\n" + "=" * 60)
    print("GEE pipeline tasks submitted and completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
