#!/usr/bin/env bash
# Phase 5B: Run OCaml change detection on downloaded Kudra LULC GeoTIFFs
#
# Requires the OCaml binary to be built first:
#   cd village_lulc_analytics_ocaml && dune build
#
# Usage: bash phase5b_ocaml_change_detection.sh

set -euo pipefail

REPO_ROOT="/home/uttkarsh/core-stack-backend"
OCAML_DIR="$REPO_ROOT/village_lulc_analytics_ocaml"
LULC_DIR="$REPO_ROOT/kudra_verification/lulc_downloads"
OCAML_OUT="$REPO_ROOT/kudra_verification/ocaml_output"
LOG_DIR="$REPO_ROOT/kudra_verification/logs"

mkdir -p "$OCAML_OUT"

# ── District / block helpers ──────────────────────────────────────────────────
D="kaimur"
B="kudra"
YEARS=(2018 2019 2020 2021 2022 2023)

# ── Build OCaml binary if needed ──────────────────────────────────────────────
echo "============================================================"
echo "Phase 5B: OCaml Change Detection"
echo "============================================================"
echo ""
echo "[build] Building OCaml binary..."
cd "$OCAML_DIR"
dune build 2>&1

BINARY="./_build/default/bin/main.exe"
if [ ! -f "$BINARY" ]; then
    echo "ERROR: Binary not found at $BINARY"
    exit 1
fi
echo "       Binary: $BINARY"

# ── Assemble LULC file paths (chronological) ─────────────────────────────────
LULC_ARGS=()
for YR in "${YEARS[@]}"; do
    YR1=$((YR + 1))
    TIF="${LULC_DIR}/${D}_${B}_${YR}-07-01_${YR1}-06-30_LULCmap_10m.tif"
    if [ ! -f "$TIF" ]; then
        echo "ERROR: Missing LULC raster: $TIF"
        exit 1
    fi
    LULC_ARGS+=(--lulc "$TIF")
    echo "  [${YR}] $TIF"
done

# ── MWS GeoJSON ───────────────────────────────────────────────────────────────
MWS_GEOJSON="${LULC_DIR}/filtered_mws_${D}_${B}_uid.geojson"
if [ -f "$MWS_GEOJSON" ]; then
    WS_ARG="--watersheds $MWS_GEOJSON"
    echo ""
    echo "[ws] Watersheds: $MWS_GEOJSON"
else
    WS_ARG="--no-vector"
    echo ""
    echo "[ws] MWS GeoJSON not found — running without vector output"
fi

# ── Run OCaml binary ──────────────────────────────────────────────────────────
echo ""
echo "[run] Running: $BINARY ${LULC_ARGS[*]} $WS_ARG --outdir $OCAML_OUT"
echo ""

CMD="$BINARY ${LULC_ARGS[*]} $WS_ARG --outdir $OCAML_OUT"
START_TS=$(date +%s)
eval "$CMD" 2>&1 | tee "$LOG_DIR/phase5b_ocaml_run.log"
EXIT_CODE=${PIPESTATUS[0]}
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo ""
echo "Exit code: $EXIT_CODE"
echo "Elapsed:   ${ELAPSED}s"

# ── Verify outputs ────────────────────────────────────────────────────────────
echo ""
echo "[verify] Output files:"
for PARAM in Urbanization Degradation Deforestation Afforestation CropIntensity; do
    RASTER="${OCAML_OUT}/change_${PARAM}.tif"
    VECTOR="${OCAML_OUT}/change_vector_${PARAM}.geojson"
    R_STATUS="✓"
    V_STATUS="✓"
    [ ! -f "$RASTER" ] && R_STATUS="✗ MISSING"
    [ ! -f "$VECTOR" ] && V_STATUS="✗ MISSING"
    echo "  $PARAM:"
    echo "    Raster: $R_STATUS  $RASTER"
    echo "    Vector: $V_STATUS  $VECTOR"
done

# ── Write summary JSON ────────────────────────────────────────────────────────
python3 - <<'PYEOF'
import os, json
OUT_DIR  = "/home/uttkarsh/core-stack-backend/kudra_verification/ocaml_output"
LOG_DIR  = "/home/uttkarsh/core-stack-backend/kudra_verification/logs"
import rasterio, numpy as np

params = ["Urbanization","Degradation","Deforestation","Afforestation","CropIntensity"]
log = {}
for p in params:
    raster_path = os.path.join(OUT_DIR, f"change_{p}.tif")
    vector_path = os.path.join(OUT_DIR, f"change_vector_{p}.geojson")
    r = {"raster_path": raster_path, "vector_path": vector_path}
    if os.path.exists(raster_path):
        with rasterio.open(raster_path) as src:
            arr = src.read(1)
            r["raster_exists"]  = True
            r["shape"]          = list(arr.shape)
            r["unique_codes"]   = sorted(np.unique(arr).tolist())
            r["pixel_count"]    = int(np.sum(arr != (src.nodata or -9999)))
    else:
        r["raster_exists"] = False
    if os.path.exists(vector_path):
        with open(vector_path) as f:
            fc = json.load(f)
        r["vector_exists"]   = True
        r["vector_features"] = len(fc.get("features", []))
    else:
        r["vector_exists"] = False
    log[p] = r

out = os.path.join(LOG_DIR, "phase5b_ocaml_output.json")
with open(out, "w") as f:
    json.dump(log, f, indent=2)
print(f"OCaml output log written: {out}")
for p, r in log.items():
    ok = r.get("raster_exists") and r.get("pixel_count",0) > 0
    print(f"  {p}: {'✓' if ok else '✗'}  codes={r.get('unique_codes','?')}")
PYEOF

echo ""
echo "Phase 5B complete."
