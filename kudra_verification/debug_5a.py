import os, sys, numpy as np, rasterio
from scipy import stats as scipy_stats

LULC_DIR = "/home/uttkarsh/core-stack-backend/kudra_verification/lulc_int32"
YEARS = [2018,2019,2020,2021,2022,2023]
D, B = "kaimur", "kudra"

print("Loading...", flush=True)
lulc_stack = []
for yr in YEARS:
    tif = os.path.join(LULC_DIR, "%s_%s_%d-07-01_%d-06-30_LULCmap_10m.tif" % (D,B,yr,yr+1))
    with rasterio.open(tif) as src:
        arr = src.read(1).astype(np.int32)
    arr[arr==-9999]=0
    lulc_stack.append(arr)
    print("  [%d] shape=%s" % (yr,str(arr.shape)), flush=True)

print("Mode then...", flush=True)
cube = np.stack(lulc_stack[:3],axis=0)
mode_then = scipy_stats.mode(cube, axis=0, keepdims=False).mode.astype(np.int32)
print("  done %s" % str(mode_then.shape), flush=True)
print("Mode now...", flush=True)
mode_now = scipy_stats.mode(np.stack(lulc_stack[3:],axis=0), axis=0, keepdims=False).mode.astype(np.int32)
print("  done %s  ALL OK!" % str(mode_now.shape), flush=True)
