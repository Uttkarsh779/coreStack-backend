"""
Phase 1c: Check local admin boundary data + MWS query field names.
"""
import os, sys, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nrm_app.settings")
import django; django.setup()
import ee
import geopandas as gpd
from utilities.gee_utils import ee_initialize
from utilities.constants import MWS_DATASET

def main():
    ee_initialize(1)
    print("=" * 60)
    print("Phase 1c: Boundary & MWS field inspection")
    print("=" * 60)

    # ── 1. Inspect kaimur.geojson ──────────────────────────────────────────────
    kaimur_geojson = os.path.join(BASE_DIR, "data", "admin-boundary", "input", "bihar", "kaimur.geojson")
    print(f"\n[1] Inspecting {kaimur_geojson}")
    gdf = gpd.read_file(kaimur_geojson)
    print(f"    Shape: {gdf.shape}")
    print(f"    Columns: {list(gdf.columns)}")
    print(f"    CRS: {gdf.crs}")
    # Find Kudra rows
    for col in gdf.columns:
        if col.lower() in ("block_name", "block", "subdist_name", "tehsil", "name", "block_cd"):
            vals = gdf[col].str.lower().unique() if gdf[col].dtype == object else gdf[col].unique()
            print(f"    {col}: {list(vals[:20])}")
            kudra_rows = gdf[gdf[col].str.lower().str.contains("kudra", na=False)] if gdf[col].dtype == object else gdf[gdf[col] == "Kudra"]
            if not kudra_rows.empty:
                print(f"    FOUND Kudra rows via column '{col}':")
                print(f"    {kudra_rows[list(gdf.columns[:8])].to_string()[:500]}")

    # ── 2. Check the local shapefile output ────────────────────────────────────
    shp_path = os.path.join(BASE_DIR, "data", "admin-boundary", "output", "bihar", "kaimur_kudra", "kaimur_kudra.shp")
    print(f"\n[2] Inspecting {shp_path}")
    if os.path.exists(shp_path):
        try:
            shp_gdf = gpd.read_file(shp_path)
            print(f"    Rows: {len(shp_gdf)}, Columns: {list(shp_gdf.columns)}")
            if not shp_gdf.empty:
                print(f"    CRS: {shp_gdf.crs}")
                print(f"    Bounds: {shp_gdf.total_bounds}")
                print(f"    First row:\n{shp_gdf.iloc[0]}")
        except Exception as e:
            print(f"    ERROR reading shapefile: {e}")

    # ── 3. Inspect output JSON ────────────────────────────────────────────────
    json_path = os.path.join(BASE_DIR, "data", "admin-boundary", "output", "bihar", "kaimur_kudra.json")
    print(f"\n[3] Inspecting {json_path}")
    if os.path.exists(json_path):
        with open(json_path) as f:
            content = f.read()
        print(f"    Content: {content[:500]}")

    # ── 4. MWS pan-India — check field names ─────────────────────────────────
    print(f"\n[4] MWS pan-India field names")
    try:
        sample = ee.FeatureCollection(MWS_DATASET).limit(1).first().getInfo()
        props = sample.get("properties", {})
        print(f"    Property names: {list(props.keys())}")
        print(f"    Sample values:  {props}")
    except Exception as e:
        print(f"    ERROR: {e}")

    # ── 5. Try to find Kudra / Kaimur in MWS using likely field names ─────────
    print(f"\n[5] Searching MWS for Kudra with alternate field names")
    candidate_fields = ["BLOCK", "Block", "block", "TEHSIL", "tehsil", "SUBDIST", "subdist",
                        "Subdist", "block_name", "Block_Name", "district", "DISTRICT",
                        "District", "state", "State", "STATE"]
    fc = ee.FeatureCollection(MWS_DATASET)
    for field in candidate_fields:
        try:
            count = fc.filterMetadata(field, "equals", "Kudra").size().getInfo()
            if count > 0:
                print(f"    FOUND: field='{field}', value='Kudra', count={count}")
        except:
            pass
        try:
            count = fc.filterMetadata(field, "equals", "KUDRA").size().getInfo()
            if count > 0:
                print(f"    FOUND: field='{field}', value='KUDRA', count={count}")
        except:
            pass

    # ── 6. Spatial filter MWS using Kudra admin boundary ─────────────────────
    print(f"\n[6] Spatial filter MWS using Kudra geometry from kaimur.geojson")
    try:
        gdf = gpd.read_file(kaimur_geojson)
        # Find Kudra geometry
        kudra_gdf = None
        for col in gdf.columns:
            if gdf[col].dtype == object:
                mask = gdf[col].str.lower().str.contains("kudra", na=False)
                if mask.any():
                    kudra_gdf = gdf[mask]
                    print(f"    Found Kudra via column '{col}': {len(kudra_gdf)} features")
                    break

        if kudra_gdf is not None and not kudra_gdf.empty:
            # Convert to GEE geometry
            import json as pyjson
            kudra_geom = kudra_gdf.geometry.unary_union
            kudra_geojson_dict = pyjson.loads(gpd.GeoSeries([kudra_geom]).to_json())
            geom_coords = kudra_geojson_dict["features"][0]["geometry"]
            ee_geom = ee.Geometry(geom_coords)
            mws_filtered = fc.filterBounds(ee_geom)
            count = mws_filtered.size().getInfo()
            print(f"    MWS features within Kudra boundary: {count}")
            if count > 0:
                sample = mws_filtered.first().getInfo()
                props = sample.get("properties", {})
                print(f"    Sample MWS properties: {list(props.keys())[:10]}")
                print(f"    Sample values: { {k: props[k] for k in list(props.keys())[:8]} }")
                # Save kudra geometry for later use
                kudra_bounds = kudra_geom.bounds
                print(f"    Kudra bounds: {kudra_bounds}")
    except Exception as e:
        import traceback
        print(f"    ERROR: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
