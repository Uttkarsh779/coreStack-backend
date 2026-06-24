#!/usr/bin/env python3
"""
download_admin_boundary.py
--------------------------
Downloads the India administrative boundary dataset (~8GB) from
Google Drive using gdown, extracts it using py7zr (pure Python,
no system 7z needed), and places the files in:
  data/admin-boundary/input/  <-- as expected by the GEE pipeline

Google Drive file ID (from install.sh): 1VqIhB6HrKFDkDnlk1vedcEHhh5fk4f1d
"""
import os, sys, shutil
import gdown
import py7zr

BACKEND_DIR  = "/home/uttkarsh/core-stack-backend"
DATA_DIR     = os.path.join(BACKEND_DIR, "data")
ARCHIVE_PATH = os.path.join(DATA_DIR, "dataset.7z")
EXTRACT_ROOT = os.path.join(DATA_DIR, ".admin-boundary-extract")
TARGET_DIR   = os.path.join(DATA_DIR, "admin-boundary")
FILEID       = "1VqIhB6HrKFDkDnlk1vedcEHhh5fk4f1d"

# ── 1. Check if already extracted ────────────────────────────────
kaimur_geojson = os.path.join(TARGET_DIR, "input", "bihar", "kaimur.geojson")
if os.path.exists(kaimur_geojson):
    print(f"✓ Admin boundary for Kaimur already exists at {kaimur_geojson}")
    print("  Skipping download. Delete the file to force re-download.")
    sys.exit(0)

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(EXTRACT_ROOT, exist_ok=True)

# ── 2. Download via gdown ─────────────────────────────────────────
if not os.path.exists(ARCHIVE_PATH):
    print("=" * 60)
    print("Downloading ~8GB admin boundary dataset from Google Drive...")
    print("This will take several minutes — please wait.")
    print("=" * 60)
    gdown.download(id=FILEID, output=ARCHIVE_PATH, quiet=False)
    print(f"\n✓ Download complete: {ARCHIVE_PATH}")
else:
    print(f"Archive already downloaded at {ARCHIVE_PATH}. Skipping download.")

# ── 3. Extract using py7zr ────────────────────────────────────────
print(f"\nExtracting archive to {EXTRACT_ROOT}...")
print("This may take a few minutes for a large archive...")
with py7zr.SevenZipFile(ARCHIVE_PATH, mode='r') as z:
    z.extractall(path=EXTRACT_ROOT)
print("✓ Extraction complete.")

# ── 4. Find soi_tehsil.geojson inside extracted content ──────────
print("\nLocating soi_tehsil.geojson inside extracted archive...")
soi_tehsil = None
for root, dirs, files in os.walk(EXTRACT_ROOT):
    for f in files:
        if f == "soi_tehsil.geojson":
            soi_tehsil = os.path.join(root, f)
            break
    if soi_tehsil:
        break

if not soi_tehsil:
    print("ERROR: soi_tehsil.geojson not found in extracted archive!")
    print(f"Please check the contents of: {EXTRACT_ROOT}")
    sys.exit(1)

extracted_input_dir = os.path.dirname(soi_tehsil)
print(f"✓ Found soi_tehsil.geojson at: {soi_tehsil}")
print(f"  Input directory: {extracted_input_dir}")

# ── 5. Move extracted files to target location ────────────────────
target_input = os.path.join(TARGET_DIR, "input")
os.makedirs(TARGET_DIR, exist_ok=True)
if os.path.exists(target_input):
    print(f"Removing old input dir: {target_input}")
    shutil.rmtree(target_input)
shutil.copytree(extracted_input_dir, target_input)
print(f"✓ Admin boundary data placed at: {target_input}")

# ── 6. Verify Kaimur exists in the extracted data ─────────────────
if os.path.exists(kaimur_geojson):
    print(f"✓ Kaimur boundary confirmed: {kaimur_geojson}")
else:
    bihar_dir = os.path.join(target_input, "bihar")
    if os.path.exists(bihar_dir):
        files = os.listdir(bihar_dir)
        print(f"Bihar dir contents: {files}")
    else:
        # Try listing top-level to debug naming conventions
        top = os.listdir(target_input)
        print(f"Top-level input dirs: {top[:20]}")
    print("Note: kaimur.geojson not at expected path — check naming in Bihar dir above.")

# ── 7. Clean up archive and extract tmp dir ───────────────────────
shutil.rmtree(EXTRACT_ROOT, ignore_errors=True)
if os.path.exists(ARCHIVE_PATH):
    os.remove(ARCHIVE_PATH)
    print("✓ Cleaned up archive and temp files.")

print("\n" + "=" * 60)
print("Admin boundary download and extraction COMPLETE.")
print("=" * 60)
