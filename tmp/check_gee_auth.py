#!/usr/bin/env python3
"""Check GEE accounts in the database and test authentication."""
import os, sys
sys.path.insert(0, '/home/uttkarsh/core-stack-backend')
os.chdir('/home/uttkarsh/core-stack-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nrm_app.settings')
import django
django.setup()

# List GEE accounts
print("=== GEE Accounts ===")
try:
    from gee_computing.models import GEEAccount
    accounts = GEEAccount.objects.all()
    for a in accounts:
        key_str = str(a.private_key_json or '')
        has_key = len(key_str) > 20
        print(f"  id={a.id}: {getattr(a, 'email', getattr(a, 'service_account', 'N/A'))} | has_key={has_key}")
except Exception as e:
    print(f"  Error: {e}")

# Try to initialize GEE
print("\n=== GEE Init Test (account_id=1) ===")
try:
    from utilities.gee_utils import ee_initialize
    ee_initialize(1)
    import ee
    print("  GEE initialized OK")
    # Test: list assets at root to confirm connectivity
    try:
        assets = ee.data.getAssetRoots()
        print(f"  Asset roots: {[a['id'] for a in assets[:3]]}")
    except Exception as e2:
        print(f"  Asset root query failed: {e2}")
except Exception as e:
    print(f"  GEE init failed: {e}")

# Check the admin boundary input for Assam/baksa
print("\n=== Admin Boundary Input Files ===")
import glob
for f in glob.glob('data/admin-boundary/input/**/*.geojson', recursive=True):
    size = os.path.getsize(f)
    print(f"  {f} ({size} bytes)")
for f in glob.glob('data/admin-boundary/input/*.geojson'):
    size = os.path.getsize(f)
    print(f"  {f} ({size} bytes)")
print("  SOI_TEHSIL exists:", os.path.exists('data/admin-boundary/input/soi_tehsil.geojson'))
