import py7zr
import os
import traceback

archive_path = "/home/uttkarsh/core-stack-backend/data/dataset.7z"
extract_path = "/home/uttkarsh/core-stack-backend/data/admin-boundary"

print(f"Opening archive: {archive_path}")
try:
    with py7zr.SevenZipFile(archive_path, mode='r') as z:
        names = z.getnames()
        print(f"✓ Archive opened. Total files: {len(names)}")
        
        # Filter files to extract
        targets = [
            n for n in names 
            if n == "admin-boundary/input/soi_tehsil.geojson" 
            or n.startswith("admin-boundary/input/bihar/")
        ]
        print(f"Selected {len(targets)} files for extraction.")
        
        # Extract selective targets
        print(f"Extracting to: {extract_path}")
        z.extract(targets=targets, path="/home/uttkarsh/core-stack-backend/data")
        print("✓ Selective extraction complete!")
        
        # Check files after extraction
        target_dir = os.path.join(extract_path, "input")
        print(f"Checking extracted contents in: {target_dir}")
        if os.path.exists(target_dir):
            print(f"Files in target_dir: {os.listdir(target_dir)}")
            bihar_dir = os.path.join(target_dir, "bihar")
            if os.path.exists(bihar_dir):
                print(f"Files in bihar dir: {len(os.listdir(bihar_dir))}")
except Exception as e:
    print(f"✗ Error: {e}")
    traceback.print_exc()

