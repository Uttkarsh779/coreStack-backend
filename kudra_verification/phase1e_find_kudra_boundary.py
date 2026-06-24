"""
Phase 1e: Find Kudra block boundary via:
  1. Grouping kaimur.geojson by TID (block code) and computing centroids
  2. Checking data/admin-boundary/input for other files
  3. Verifying which TID group geographically matches Kudra (~83.5°E, 25.0°N)
"""
import os, sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django; django.setup()
import geopandas as gpd
import json

kaimur_path = os.path.join(BASE_DIR, "data", "admin-boundary", "input", "bihar", "kaimur.geojson")
admin_input  = os.path.join(BASE_DIR, "data", "admin-boundary", "input")
admin_output = os.path.join(BASE_DIR, "data", "admin-boundary", "output")

print("=" * 60)
print("Phase 1e: Find Kudra block boundary")
print("=" * 60)

# ── 1. List ALL files in admin-boundary/input ─────────────────────────────────
print(f"\n[1] Files in {admin_input}:")
for root, dirs, files in os.walk(admin_input):
    for f in files:
        fp = os.path.join(root, f)
        size = os.path.getsize(fp)
        print(f"    {fp.replace(BASE_DIR,'.')}  ({size:,} bytes)")

# ── 2. Group kaimur.geojson by TID and show centroids ────────────────────────
print(f"\n[2] kaimur.geojson — per-TID geographic centroids and bounds")
gdf = gpd.read_file(kaimur_path)
# Compute dissolved geometry per TID
grouped = gdf.dissolve(by="TID", as_index=False)
print(f"    {'TID':<8} {'SUB_DIST':<10} {'Centroid lon':<16} {'Centroid lat':<16} {'Villages'}")
for _, row in grouped.iterrows():
    centroid = row.geometry.centroid
    tid = row["TID"]
    sub = row.get("SUB_DIST", "?")
    # Count villages with this TID
    cnt = len(gdf[gdf["TID"] == tid])
    print(f"    {tid:<8} {str(sub):<10} {centroid.x:<16.4f} {centroid.y:<16.4f} {cnt}")

# ── 3. Find TID closest to Kudra town (~83.5°E, 25.0°N) ──────────────────────
# Kudra town approximate coordinates from public records
KUDRA_LON = 83.49
KUDRA_LAT = 25.03
print(f"\n[3] TID group closest to Kudra town ({KUDRA_LON}°E, {KUDRA_LAT}°N):")
import math
best_tid, best_dist = None, float("inf")
for _, row in grouped.iterrows():
    centroid = row.geometry.centroid
    dist = math.sqrt((centroid.x - KUDRA_LON)**2 + (centroid.y - KUDRA_LAT)**2)
    if dist < best_dist:
        best_dist = dist
        best_tid = row["TID"]
print(f"    Best TID: {best_tid}  (distance ~{best_dist:.4f}°)")

# ── 4. Extract that TID group, dissolve, save as Kudra boundary ───────────────
kudra_villages = gdf[gdf["TID"] == best_tid].copy()
print(f"\n[4] Extracting TID={best_tid} as Kudra boundary")
print(f"    {len(kudra_villages)} villages")
print(f"    Village names sample: {kudra_villages['NAME'].head(5).tolist()}")
kudra_boundary = kudra_villages.dissolve()
bounds = kudra_boundary.total_bounds
print(f"    Bounds: {bounds}")
print(f"    Area (sq deg): {kudra_boundary.geometry.area.sum():.6f}")

out_path = os.path.join(BASE_DIR, "kudra_verification", "kudra_boundary.geojson")
kudra_boundary.to_file(out_path, driver="GeoJSON")
print(f"    Saved: {out_path}")

# Also save the village-level features (with properties for MWS upload)
out_village = os.path.join(BASE_DIR, "kudra_verification", "kudra_villages.geojson")
kudra_villages[["geometry","NAME","TID","SUB_DIST","pc11_village_id","pc11_subdistrict_id"]].to_file(out_village, driver="GeoJSON")
print(f"    Villages saved: {out_village}")

# ── 5. Show pc11_subdistrict_id for Kudra TID ─────────────────────────────────
sub_ids = kudra_villages["pc11_subdistrict_id"].dropna().unique()
print(f"\n[5] pc11_subdistrict_id values for TID={best_tid}: {sorted(sub_ids)}")

# ── 6. Check any NAME column that has 'kudra' across ALL state data ───────────
print(f"\n[6] Searching for 'kudra' in NAME column of kaimur.geojson")
kudra_named = gdf[gdf["NAME"].str.lower().str.contains("kudra", na=False)]
print(f"    Rows with 'kudra' in NAME: {len(kudra_named)}")
if not kudra_named.empty:
    print(kudra_named[["NAME","TID","SUB_DIST","pc11_village_id","pc11_subdistrict_id"]].to_string())
