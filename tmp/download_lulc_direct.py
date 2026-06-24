#!/usr/bin/env python3
"""
download_lulc_direct.py
-----------------------
Downloads real LULC GeoTIFFs directly from GEE for the Guindy test region
using getDownloadURL, avoiding Drive/GCS export quotas.
"""
import os, sys, requests, zipfile, io
sys.path.insert(0, '/home/uttkarsh/core-stack-backend')
os.chdir('/home/uttkarsh/core-stack-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nrm_app.settings')
import django
django.setup()

from utilities.gee_utils import ee_initialize
import ee

ee_initialize(1)

BASE = 'projects/arcane-mason-493503-a6/assets/apps/mws/tamil_nadu/chennai/guindy'
OUT_DIR = 'data/lulc_exports'
os.makedirs(OUT_DIR, exist_ok=True)

LULC_ASSETS = [
    ('lulc_guindy_2022-2023', f'{BASE}/chennai_guindy_2022-07-01_2023-06-30_LULCmap_10m'),
    ('lulc_guindy_2023-2024', f'{BASE}/chennai_guindy_2023-07-01_2024-06-30_LULCmap_10m'),
]
ADMIN_ASSET = f'{BASE}/admin_boundary_chennai_guindy'

# Get admin boundary geometry for clipping
print("Fetching admin boundary for clipping...")
admin_fc = ee.FeatureCollection(ADMIN_ASSET)
region = admin_fc.geometry()

for name, asset_id in LULC_ASSETS:
    print(f"\nProcessing {name}...")
    img = ee.Image(asset_id)
    
    try:
        url = img.getDownloadURL({
            'scale': 10,
            'crs': 'EPSG:4326',
            'region': region,
            'format': 'GEO_TIFF'
        })
        print(f"  Download URL: {url}")
        
        # Download and extract the zip
        print("  Downloading...")
        r = requests.get(url)
        r.raise_for_status()
        
        # In GEE, getDownloadURL for GEO_TIFF returns the TIF directly
        out_path = os.path.join(OUT_DIR, f"{name}.tif")
        with open(out_path, 'wb') as f:
            f.write(r.content)
        print(f"  Saved to {out_path}")
        
    except Exception as e:
        print(f"  Error downloading {name}: {e}")

print("\nDone.")
