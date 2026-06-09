#!/usr/bin/env python3
"""
End-to-end test for the MWS + LULC pipeline.

Runs two GEE computation tasks for a fixed test block (Tamil Nadu /
Chennai / Guindy) and verifies the results are published to GeoServer.

Usage:
    python computing/misc/lulc_pipeline_test.py

Prerequisites (must all pass first):
    python computing/misc/internal_api_initialisation_test.py --require-gee

    Admin boundary for the test block must already exist in GEE. Run once:
        python manage.py shell -c "
        from computing.misc.admin_boundary import generate_tehsil_shape_file_data
        generate_tehsil_shape_file_data.delay(
            state='tamil nadu', district='chennai', block='guindy', gee_account_id=1
        ).get()
        "

Visualise results:
    GeoServer Layer Preview: OpenLayers
    http://localhost:8080/geoserver/web/
    Workspaces: mws, LULC_level_1, LULC_level_2, LULC_level_3
"""

from __future__ import annotations

import os
import sys

# ── path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")

import django
django.setup()

from nrm_app.celery import app
app.conf.task_always_eager = True

# ── test parameters ───────────────────────────────────────────────────────────
STATE = "tamil nadu"
DISTRICT = "chennai"
BLOCK = "guindy"
GEE_ACCOUNT_ID = 1
START_YEAR = 2022
END_YEAR = 2023


def ensure_dirs():
    os.makedirs(os.path.join("data", "fc_to_shape", STATE), exist_ok=True)
    os.makedirs(os.path.join("data", "admin-boundary", "output", STATE.replace(" ", "_")), exist_ok=True)


def run_mws():
    print("\n[1/2] Running MWS layer (clips pan-India watersheds to block)...")
    from computing.mws.mws import mws_layer
    result = mws_layer.delay(
        state=STATE, district=DISTRICT, block=BLOCK, gee_account_id=GEE_ACCOUNT_ID
    )
    ok = result.get()
    if ok:
        print(f"[PASS] MWS: filtered_mws_{DISTRICT}_{BLOCK} published to GeoServer workspace 'mws'.")
    else:
        print("[FAIL] MWS: task returned False.")
    return ok


def run_lulc():
    print(f"\n[2/2] Running LULC v3 ({START_YEAR}-{END_YEAR}): submits GEE image exports, may take 5-15 min...")
    from computing.lulc.lulc_v3 import clip_lulc_v3
    result = clip_lulc_v3.delay(
        state=STATE,
        district=DISTRICT,
        block=BLOCK,
        start_year=START_YEAR,
        end_year=END_YEAR,
        gee_account_id=GEE_ACCOUNT_ID,
    )
    ok = result.get()
    if ok:
        print(f"[PASS] LULC: layers for {START_YEAR}-{END_YEAR} published to GeoServer workspaces "
              f"LULC_level_1, LULC_level_2, LULC_level_3.")
        print(f"\nVisualise in GeoServer Layer Preview (OpenLayers):")
        print(f"  http://localhost:8080/geoserver/web/")
    else:
        print("[FAIL] LULC: task returned False.")
    return ok


def main():
    print(f"LULC pipeline test: {STATE}/{DISTRICT}/{BLOCK}")
    print("=" * 60)

    ensure_dirs()

    mws_ok = run_mws()
    if not mws_ok:
        print("\nAborted: MWS must succeed before LULC can run.")
        sys.exit(1)

    lulc_ok = run_lulc()

    print("\n" + "=" * 60)
    if mws_ok and lulc_ok:
        print("LULC pipeline test passed.")
        sys.exit(0)
    else:
        print("LULC pipeline test finished with failures.")
        sys.exit(1)


if __name__ == "__main__":
    main()
