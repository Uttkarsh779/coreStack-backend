"""Phase 1d: Check SUB_DIST values in kaimur.geojson + SOI tehsil for Kudra."""
import os, sys, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django; django.setup()
import geopandas as gpd
from utilities.constants import ADMIN_BOUNDARY_INPUT_DIR, SOI_TEHSIL

kaimur_path = os.path.join(BASE_DIR, ADMIN_BOUNDARY_INPUT_DIR, "bihar", "kaimur.geojson")
soi_path    = os.path.join(BASE_DIR, SOI_TEHSIL)

print("=" * 60)
print("Phase 1d: SUB_DIST / SOI check for Kudra")
print("=" * 60)

# ── kaimur.geojson SUB_DIST unique values ─────────────────────────────────────
print(f"\n[1] kaimur.geojson  →  SUB_DIST values")
gdf = gpd.read_file(kaimur_path)
for col in ["SUB_DIST", "sub_dist", "SUBDIST", "subdistrict", "block", "BLOCK", "TID", "SID"]:
    if col in gdf.columns:
        vals = sorted(gdf[col].dropna().unique().tolist())
        print(f"    {col}: {vals[:30]}")

# check pc11_subdistrict_id mapping
if "pc11_subdistrict_id" in gdf.columns and "TEHSIL" in gdf.columns:
    mapping = gdf[["pc11_subdistrict_id","TEHSIL"]].drop_duplicates().sort_values("TEHSIL")
    print(f"\n    pc11_subdistrict_id → TEHSIL:\n{mapping.to_string()}")

# check if any column contains 'kudra'
print(f"\n[2] Searching ALL columns in kaimur.geojson for 'kudra'")
for col in gdf.columns:
    if gdf[col].dtype == object:
        mask = gdf[col].str.lower().str.contains("kudra", na=False)
        if mask.any():
            print(f"    Column '{col}': {gdf.loc[mask, col].unique()}")

# ── SOI file ──────────────────────────────────────────────────────────────────
print(f"\n[3] SOI tehsil file: {soi_path}")
if os.path.exists(soi_path):
    soi = gpd.read_file(soi_path)
    print(f"    Shape: {soi.shape}, Columns: {list(soi.columns)}")
    bihar_soi = soi[soi["STATE"].str.lower().str.strip() == "bihar"] if "STATE" in soi.columns else soi
    print(f"    Bihar rows: {len(bihar_soi)}")
    if "District" in soi.columns:
        kaimur_soi = bihar_soi[bihar_soi["District"].str.lower().str.strip().str.contains("kaimur", na=False)]
        print(f"    Kaimur rows in SOI: {len(kaimur_soi)}")
        if not kaimur_soi.empty:
            print(f"    TEHSIL values:\n    {sorted(kaimur_soi['TEHSIL'].str.lower().unique().tolist())}")
            kudra_soi = kaimur_soi[kaimur_soi["TEHSIL"].str.lower().str.strip() == "kudra"]
            print(f"    'kudra' rows: {len(kudra_soi)}")
            if not kudra_soi.empty:
                print(f"    Bounds: {kudra_soi.total_bounds}")
                kudra_soi.to_file("/home/uttkarsh/core-stack-backend/kudra_verification/kudra_soi_boundary.geojson", driver="GeoJSON")
                print("    Saved to kudra_soi_boundary.geojson")
else:
    print(f"    NOT FOUND: {soi_path}")

# ── Look at MWS generation pipeline ───────────────────────────────────────────
print(f"\n[4] Looking for MWS generation pipeline")
for root, dirs, files in os.walk(os.path.join(BASE_DIR, "computing")):
    for f in files:
        if "mws" in f.lower() or "watershed" in f.lower():
            print(f"    {os.path.join(root, f)}")
