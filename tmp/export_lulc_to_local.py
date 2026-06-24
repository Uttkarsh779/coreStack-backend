#!/usr/bin/env python3
"""
export_lulc_to_local.py
-----------------------
Exports real LULC GeoTIFFs from GEE to local disk for the Guindy test region.

Assets available in GEE:
  projects/arcane-mason-493503-a6/assets/apps/mws/tamil_nadu/chennai/guindy/
    - chennai_guindy_2022-07-01_2023-06-30_LULCmap_10m  [IMAGE]
    - chennai_guindy_2023-07-01_2024-06-30_LULCmap_10m  [IMAGE]
    - filtered_mws_chennai_guindy_uid                    [TABLE]
    - admin_boundary_chennai_guindy                      [TABLE]

Outputs (to data/lulc_exports/):
  lulc_guindy_2022-2023.tif
  lulc_guindy_2023-2024.tif
  mws_guindy.geojson           <- watershed polygons for zonal stats
  admin_boundary_guindy.geojson
"""
import os, sys, json
sys.path.insert(0, '/home/uttkarsh/core-stack-backend')
os.chdir('/home/uttkarsh/core-stack-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nrm_app.settings')
import django
django.setup()

from utilities.gee_utils import ee_initialize, get_gee_asset_path
import ee

ee_initialize(1)

BASE = 'projects/arcane-mason-493503-a6/assets/apps/mws/tamil_nadu/chennai/guindy'
OUT_DIR = 'data/lulc_exports'
os.makedirs(OUT_DIR, exist_ok=True)

LULC_ASSETS = [
    ('lulc_guindy_2022-2023', f'{BASE}/chennai_guindy_2022-07-01_2023-06-30_LULCmap_10m'),
    ('lulc_guindy_2023-2024', f'{BASE}/chennai_guindy_2023-07-01_2024-06-30_LULCmap_10m'),
]
MWS_ASSET = f'{BASE}/filtered_mws_chennai_guindy_uid'
ADMIN_ASSET = f'{BASE}/admin_boundary_chennai_guindy'

# ── 1. Export LULC images via GEE batch export to Google Drive ──────────────
print("=== Starting GEE → Drive exports for LULC images ===")
print("NOTE: These are async GEE tasks. Check ee.data.getTaskList() for status.")

task_ids = []
for name, asset_id in LULC_ASSETS:
    img = ee.Image(asset_id)
    ifd = img.getInfo()
    bands = [b['id'] for b in ifd.get('bands', [])]
    print(f"\n  Asset: {asset_id}")
    print(f"  Bands: {bands}")
    print(f"  CRS: {ifd.get('bands', [{}])[0].get('crs', 'unknown') if ifd.get('bands') else 'unknown'}")

    task = ee.batch.Export.image.toDrive(
        image=img,
        description=name,
        folder='core_stack_lulc_exports',
        fileNamePrefix=name,
        scale=10,
        maxPixels=1e9,
        fileFormat='GeoTIFF',
    )
    task.start()
    status = task.status()
    task_ids.append(status['id'])
    print(f"  Export task started: {status['id']} (state={status['state']})")

# ── 2. Export MWS and Admin Boundary as GeoJSON locally ─────────────────────
print("\n=== Fetching MWS watersheds (getInfo) ===")
mws_fc = ee.FeatureCollection(MWS_ASSET)
size = mws_fc.size().getInfo()
print(f"  MWS features: {size}")

if size > 0:
    mws_info = mws_fc.getInfo()
    mws_path = os.path.join(OUT_DIR, 'mws_guindy.geojson')
    with open(mws_path, 'w') as f:
        json.dump(mws_info, f)
    print(f"  Saved: {mws_path}")
else:
    print("  WARNING: no MWS features found")

print("\n=== Fetching Admin Boundary (getInfo) ===")
admin_fc = ee.FeatureCollection(ADMIN_ASSET)
admin_size = admin_fc.size().getInfo()
print(f"  Admin features: {admin_size}")

if admin_size > 0:
    admin_info = admin_fc.getInfo()
    admin_path = os.path.join(OUT_DIR, 'admin_boundary_guindy.geojson')
    with open(admin_path, 'w') as f:
        json.dump(admin_info, f)
    print(f"  Saved: {admin_path}")

# ── 3. Save task IDs for monitoring ─────────────────────────────────────────
meta = {
    'task_ids': task_ids,
    'lulc_assets': dict(LULC_ASSETS),
    'drive_folder': 'core_stack_lulc_exports',
    'note': 'Download TIFFs from Google Drive after tasks complete, place in data/lulc_exports/'
}
with open(os.path.join(OUT_DIR, 'export_meta.json'), 'w') as f:
    json.dump(meta, f, indent=2)

print(f"\n✓ Task IDs saved to {OUT_DIR}/export_meta.json")
print("\nNext steps:")
print("  1. Wait for GEE tasks to complete (check Google Drive or run check_gee_tasks.py)")
print("  2. Download the TIFFs from Google Drive folder 'core_stack_lulc_exports'")
print("  3. Place them at: data/lulc_exports/lulc_guindy_2022-2023.tif")
print("                    data/lulc_exports/lulc_guindy_2023-2024.tif")
