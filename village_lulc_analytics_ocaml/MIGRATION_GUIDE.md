# Change Detection — Python (GEE) → OCaml Local Migration Guide

This document covers every function in `change_detection.py` and `change_detection_vector.py`,
how each was ported to OCaml, which library was used, and what the computation does — so you
can trace the full pipeline from raw LULC rasters to per-watershed GeoJSON outputs.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Raw LULC Class Codes](#2-raw-lulc-class-codes)
3. [change_detection.py — All Functions](#3-change_detectionpy--all-functions)
4. [change_detection_vector.py — All Functions](#4-change_detection_vectorpy--all-functions)
5. [OCaml Module Map](#5-ocaml-module-map)
6. [Library Reference](#6-library-reference)
7. [Step-by-Step Pipeline Walkthrough](#7-step-by-step-pipeline-walkthrough)
8. [Key Differences Between GEE and Local OCaml](#8-key-differences-between-gee-and-local-ocaml)

---

## 1. Architecture Overview

```
PYTHON (GEE — cloud)                     OCAML (local — your machine)
─────────────────────────────────────    ────────────────────────────────────────
GEE ImageCollection (ee.Image)      →    Raster.t  (flat int array + metadata)
ee.ImageCollection.mode()           →    Raster.mode_stack / mode_list
image.remap(from, to)               →    Raster.remap (apply OCaml function)
image.eq().And().multiply()         →    Raster.map2 (pixel-wise int function)
ee.Image.pixelArea().updateMask()   →    pixel_area_ha * count of matching pixels
reduceRegions(ee.Reducer.sum())     →    bounding box + ray-cast PIP loop
export to GEE asset / GCS           →    write_raster_to_tiff / write_geojson
```

**GEE runs on Google's servers; your OCaml binary runs everything locally on downloaded GeoTIFFs.**
There is no internet call during computation — everything is pure in-memory array math.

---

## 2. Raw LULC Class Codes

These are the raw pixel values coming out of the LULC GeoTIFF files. Every remap and every
transition check is defined over these codes.

| Code | Meaning               |
|------|-----------------------|
| 0    | Background / NoData   |
| 1    | Built-up              |
| 2    | Water (Kharif season) |
| 3    | Water (Rabi season)   |
| 4    | Water (Zaid season)   |
| 6    | Forest                |
| 7    | Barren land           |
| 8    | Single crop (type A)  |
| 9    | Single crop (type B)  |
| 10   | Double crop           |
| 11   | Triple crop           |
| 12   | Scrub                 |

> Note: there is no class 5. Classes 8+9 are both "Single crop" variants remapped to the same
> simplified code in most parameters.

---

## 3. change_detection.py — All Functions

### 3.1 `get_change_detection` (Celery task — orchestrator)

**Python role:** The top-level Celery task. It:
1. Builds a list of 6 `ee.Image` objects (one per year, 2018–2023).
2. Calls each of the 5 parameter functions to get 5 GEE transition images.
3. Exports each image to a GEE asset.
4. Waits for tasks, saves layer info to DB, makes assets public, syncs to GCS/GeoServer.

**OCaml equivalent:** `bin/main.ml` — the `main` entry point.  
It does the same steps but locally: reads 6 TIFF files from disk, calls the 5 OCaml functions,
writes 5 output TIFFs, then runs vectorisation.

**Library used in OCaml:** Standard `Arg` module for CLI, `Unix` for directory creation.

---

### 3.2 `built_up(roi_boundary, l1_asset)` → Urbanization

**What it does:**

```
Step 1 — Remap each year's raw codes:
  [1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,3,4,3,3,3,3,4]

  Simplified:
    1 = Built-up
    2 = Water (all seasons merged)
    3 = Vegetation / Crop / Forest
    4 = Barren / Scrub

Step 2 — Compute Then / Now:
  Then = mode(year[0], year[1], year[2])   ← baseline 3-year period
  Now  = mode(year[3], year[4], year[5])   ← active 3-year period

Step 3 — Assign transition code per pixel:
  now == 1 (Built-up now)?
    then == 1 → code 1  (bu_bu:  was Built-up, still Built-up)
    then == 2 → code 2  (w_bu:   was Water, now Built-up)
    then == 3 → code 3  (tr_bu:  was Veg/Crop, now Built-up)
    then == 4 → code 4  (b_bu:   was Barren, now Built-up)
  otherwise → code 0  (not urbanization)
```

**GEE implementation:** builds `trans_bu_bu`, `trans_w_bu`, `trans_tr_bu`, `trans_b_bu`
as Boolean images, multiplies each by its code, sums them into a zero image.

**OCaml equivalents:**

| Step | Python | OCaml | File |
|------|--------|-------|------|
| Remap | `image.remap([1..12], [1,2,2,2,3,4,3,3,3,3,4])` | `remap_urbanization` (pattern match) | `change_detection.ml` |
| Then/Now | `ee.ImageCollection([:3]).mode()` | `compute_then_now remap_urbanization stack` | `change_detection.ml` |
| Pixel code | `then.eq(1).And(now.eq(1))` etc. | `urbanization_pixel then_v now_v` | `change_detection.ml` |
| Apply to all pixels | GEE image algebra | `Raster.map2 urbanization_pixel then_r now_r` | `raster.ml` |
| Top-level call | `built_up(roi, l1_asset)` | `Change_detection.urbanization lulc_stack` | `change_detection.ml` |

---

### 3.3 `change_degradation(roi_boundary, l1_asset)` → Degradation

**What it does:**

```
Step 1 — Remap:
  [1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,4,5,3,3,3,3,6]

  Simplified:
    1 = Built-up
    2 = Water
    3 = Farmland / Cropland   ← pivot class for transitions
    4 = Forest
    5 = Barren
    6 = Scrub

Step 2 — Compute Then / Now (same formula as urbanization)

Step 3 — Assign code (fires only when Then == 3, i.e. was Farmland):
  now == 3 → code 1  (f_f:  stable farmland)
  now == 1 → code 2  (f_bu: farmland → built-up)
  now == 5 → code 3  (f_ba: farmland → barren)
  now == 6 → code 4  (f_sc: farmland → scrub)
  otherwise → code 0
```

> "f_" prefix means **Farmland**, not Forest.

**OCaml equivalents:**

| Step | Python | OCaml |
|------|--------|-------|
| Remap | `image.remap([...], [1,2,2,2,4,5,3,3,3,3,6])` | `remap_degradation` |
| Pixel code | `then.eq(3).And(now.eq(3))` etc. | `degradation_pixel then_v now_v` |
| Top-level | `change_degradation(roi, l1_asset)` | `Change_detection.degradation lulc_stack` |

---

### 3.4 `change_deforestation_afforestation(roi_boundary, l1_asset, lulc_projection)` — Temporal Smoothing

This is the shared helper that **both** deforestation and afforestation call. It runs a
two-pass noise correction on the raw LULC stack before remapping. This was the hardest
function to migrate because GEE does it lazily (deferred graph evaluation); OCaml does it
eagerly (imperative loops over arrays).

#### Pass 1 — Build per-pixel anomaly count (`zero_image2`)

For each interior year `i` (years 2, 3, 4 out of 6), look at the triplet
`(before=year[i-1], middle=year[i], after=year[i+1])` and count how many of 11
structural conditions fire:

| # | Condition | Meaning |
|---|-----------|---------|
| 1 | before=12 AND after=12 AND middle∈{6,8,9,10,11} | Scrub–Forest/Crop–Scrub |
| 2 | before∈{2,3,4} AND after∈{2,3,4} AND middle∈{6,8,9,10,11} | Water–Forest/Crop–Water |
| 3 | before=6 AND after=6 AND middle=12 | Forest–Scrub–Forest |
| 4 | before∈crop AND after∈crop AND middle=12 | Crop–Scrub–Crop |
| 5 | before∈crop AND after∈crop AND middle=7 | Crop–Barren–Crop |
| 6 | before=6 AND after=6 AND middle∈crop | Forest–Crop–Forest |
| 7 | before∈crop AND after∈crop AND middle=6 | Crop–Forest–Crop |
| 8 | before=1 AND after=1 AND middle=6 | Built-up–Forest–Built-up |
| 9 | before=6 AND after=6 AND middle=1 | Forest–Built-up–Forest |
| 10 | before=1 AND after=1 AND middle∈crop | Built-up–Crop–Built-up |
| 11 | before=7 AND after=7 AND middle∈{6,8,9,10,11} | Barren–Forest/Crop–Barren |

The total count for a pixel accumulates across all interior years. Pixels with count 3 or 4
are considered "anomalous" (the land cover flip was a sensor/classification artifact).

#### Pass 2 — Apply corrections to a deep copy (`l1_asset_copy`)

Only pixels where `anomaly_count ∈ {3, 4}`:

- **cond1:** `before==3 AND middle≠3 AND after==3` → replace middle with 3
  *(water sandwiches a non-water — the non-water is noise; revert to water)*
- **cond2:** `before≠3 AND middle==3 AND after≠3` → replace middle with before
  *(water appears for one year between non-water — the water is noise; revert to before)*

After corrections, the forest remap is applied to the corrected stack.

**GEE implementation:** uses `ee.Image.where()` which lazily patches pixels.  
**OCaml implementation:** uses explicit `Array.copy` + two nested for-loops.

**OCaml equivalents:**

| Concept | Python | OCaml | File |
|---------|--------|-------|------|
| Helper predicates | `middle.eq(6).Or(middle.eq(8))...` | `is_crop`, `is_water`, `is_forest` | `change_detection.ml` |
| 11 conditions per triple | `cond1..cond11` image expressions | `anomaly_count_for_triple b m a` | `change_detection.ml` |
| Pass 1 accumulation | `zero_image2.add(cond1)...` loop | `build_anomaly_counts px_arrays size` | `change_detection.ml` |
| Pass 2 corrections | `middle.where(cond1, 3)` | `apply_corrections orig counts` | `change_detection.ml` |
| Full smoothing call | `change_deforestation_afforestation()` | `apply_temporal_smoothing stack` | `change_detection.ml` |

---

### 3.5 `change_deforestation(roi_boundary, l1_asset)` → Deforestation

**What it does:**
1. Calls `change_deforestation_afforestation` to get the temporally smoothed `(now, then)`.
2. Both use the **forest remap**: `[1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,3,5,4,4,4,4,6]`
   - 3 = Forest (pivot class)
   - 4 = Cropland, 5 = Barren, 6 = Scrub
3. Fires only when **Then == 3** (was Forest):

```
then=3, now=3 → code 1  (fo_fo: stable forest)
then=3, now=1 → code 2  (fo_bu: forest → built-up)
then=3, now=4 → code 3  (fo_fa: forest → farmland/crop)
then=3, now=5 → code 4  (fo_ba: forest → barren)
then=3, now=6 → code 5  (fo_sc: forest → scrub)
```

**OCaml equivalent:** `deforestation_pixel then_v now_v` + `Change_detection.deforestation lulc_stack`

---

### 3.6 `change_afforestation(roi_boundary, l1_asset)` → Afforestation

**What it does:** Same smoothed stack as deforestation, same forest remap.  
But fires only when **Now == 3** (Forest is the current state):

```
then=3, now=3 → code 1  (fo_fo: stable forest)
then=1, now=3 → code 2  (bu_fo: built-up → forest)
then=4, now=3 → code 3  (fa_fo: farmland → forest)
then=5, now=3 → code 4  (ba_fo: barren → forest)
then=6, now=3 → code 5  (sc_fo: scrub → forest)
```

**OCaml equivalent:** `afforestation_pixel then_v now_v` + `Change_detection.afforestation lulc_stack`

> Deforestation and Afforestation share the same smoothed raster pair in OCaml — each call to
> `apply_temporal_smoothing` is independent but both use `remap_forest`.

---

### 3.7 `change_cropping_intensity(roi_boundary, l1_asset)` → CropIntensity

**What it does:**

```
Step 1 — Remap:
  [1,2,3,4,6,7,8,9,10,11,12] → [1,2,2,2,3,4,5,5,6,7,8]

  Simplified:
    5 = Single crop (8 or 9)
    6 = Double crop (10)
    7 = Triple crop (11)
    Others = non-crop (don't appear in any transition code)

Step 2 — Then/Now via mode (no temporal smoothing)

Step 3 — Assign transition code (9 combinations + 0 for non-crop):
  (6,5) → 1  do_si: double→single
  (7,5) → 2  tr_si: triple→single
  (7,6) → 3  tr_do: triple→double
  (5,6) → 4  si_do: single→double
  (5,7) → 5  si_tr: single→triple
  (6,7) → 6  do_tr: double→triple
  (5,5) → 7  si_si: stable single
  (6,6) → 8  do_do: stable double
  (7,7) → 9  tr_tr: stable triple
```

**OCaml equivalent:** `crop_intensity_pixel then_v now_v` (OCaml `match` over the tuple) + `Change_detection.crop_intensity lulc_stack`

---

### 3.8 `sync_to_gcs_geoserver(...)` — Infra / No OCaml Equivalent

Syncs GEE assets to Google Cloud Storage and GeoServer. This is pure infrastructure — it has
no computational logic and no OCaml equivalent. The OCaml binary writes output files to a
local directory instead.

---

## 4. change_detection_vector.py — All Functions

### 4.1 `vectorise_change_detection` (Celery task — orchestrator)

**Python role:** Top-level orchestrator. Calls all 5 vector functions, exports them as GEE
FeatureCollections, waits for tasks, saves to DB, syncs to GeoServer.

**OCaml equivalent:** the `if not !no_vector then ...` block in `bin/main.ml`. It parses
watersheds from a local GeoJSON file, calls `Change_detection_vector.vectorise_all`, then
calls `write_vector_outputs` to save 5 GeoJSON files locally.

---

### 4.2 `generate_vector(roi, args, state, district, block, layer_name, ...)` — Core Area Counter

This is the **most important function** in the vector file — all five parameter vector
functions call it with different `args`.

**What it does:**
1. Load the transition-code raster from a GEE asset.
2. For each `{value, label}` entry in `args`:
   - Build a binary mask: pixels where code == value (or code ∈ list of values for totals).
   - Multiply mask by `ee.Image.pixelArea()` to get per-pixel area in m².
   - Use `reduceRegions(ee.Reducer.sum(), scale=10)` to sum pixel areas inside each MWS polygon.
   - Multiply sum by 0.0001 to convert m² → hectares.
   - Attach result as a named attribute on each watershed feature.
3. Export the enriched FeatureCollection as a GEE vector asset.

**OCaml equivalent:** `compute_area_ha` in `change_detection_vector.ml`

```
Python (GEE server-side):              OCaml (local):
─────────────────────────────────────  ────────────────────────────────────
raster.eq(value)                  →    pixel value == target_code check
ee.Image.pixelArea()              →    pixel_area_ha = x_res * y_res * 1e-4
reduceRegions(Reducer.sum())      →    bounding_box + is_point_in_polygon + loop
* 0.0001 (m² → ha)               →    included in pixel_area_ha formula
fc.set(label, value)              →    record field in urb_attrs / deg_attrs / etc.
```

**Library used in OCaml:** No external library — pure stdlib math.  
The polygon intersection (`reduceRegions`) is replaced by a custom **ray-casting PIP algorithm**
implemented in `change_detection_vector.ml`.

---

### 4.3 `urbanization_vector` / `afforestation_vector` / `deforestation_vector` / `degradation_vector` / `crop_intensity_vector`

These five functions all follow the same pattern:

```python
def urbanization_vector(roi, state, district, block, start_year, end_year):
    args = [
        {"value": 1, "label": "bu_bu"},
        {"value": 2, "label": "w_bu"},
        ...
        {"value": [2, 3, 4], "label": "total_urb"},  # sum of multiple codes
    ]
    return generate_vector(roi, args, state, district, block, "Urbanization", ...)
```

They define **which transition codes map to which attribute name** and delegate to
`generate_vector`.

**OCaml equivalents:**

| Python function | OCaml function | File |
|----------------|----------------|------|
| `urbanization_vector` | `vectorise_urbanization` | `change_detection_vector.ml` |
| `degradation_vector` | `vectorise_degradation` | `change_detection_vector.ml` |
| `deforestation_vector` | `vectorise_deforestation` | `change_detection_vector.ml` |
| `afforestation_vector` | `vectorise_afforestation` | `change_detection_vector.ml` |
| `crop_intensity_vector` | `vectorise_crop_intensity` | `change_detection_vector.ml` |

Each OCaml function calls `compute_area_ha raster ws.geometry [code]` for each individual
code, then builds the record with `total_*` as a direct float sum (no separate GEE mask needed).

---

### 4.4 `sync_change_to_geoserver(...)` — Infra / No OCaml Equivalent

Pushes the final FeatureCollection to GeoServer. No OCaml equivalent — output is written to
a local GeoJSON file instead.

---

## 5. OCaml Module Map

```
village_lulc_analytics_ocaml/
├── lib/
│   ├── raster.ml                  ← Data type + pixel primitives
│   │     type metadata            ← spatial extent (width, height, origin, resolution)
│   │     type t                   ← the raster: metadata + int array
│   │     create / of_array2d      ← constructors
│   │     get                      ← pixel access by (row, col)
│   │     map / map2               ← pixel-wise transforms
│   │     remap                    ← alias for map (GEE image.remap)
│   │     mode3                    ← mode of exactly 3 values (fast path)
│   │     mode_list                ← mode of arbitrary list (frequency table)
│   │     mode_stack               ← pixel-wise mode across N rasters
│   │     slice                    ← sub-list [start..stop)
│   │     pixel_lat_lon            ← pixel centre in WGS-84
│   │
│   ├── tiff_reader.ml             ← GeoTIFF I/O
│   │     read_raster_from_tiff    ← load a Uint8/16/32 TIFF → Raster.t
│   │     write_raster_to_tiff     ← save a Raster.t → Uint8 TIFF
│   │
│   ├── change_detection.ml        ← Transition raster generation
│   │     remap_urbanization       ← raw code → simplified category
│   │     remap_degradation        ←   "
│   │     remap_forest             ←   " (shared by deforestation + afforestation)
│   │     remap_crop               ←   "
│   │     compute_then_now         ← remap → split at year 3 → mode each half
│   │     urbanization_pixel       ← (then_v, now_v) → int code
│   │     degradation_pixel        ←   "
│   │     deforestation_pixel      ←   "
│   │     afforestation_pixel      ←   "
│   │     crop_intensity_pixel     ←   "
│   │     anomaly_count_for_triple ← 11-condition counter (temporal smoothing pass 1)
│   │     build_anomaly_counts     ← pass 1 over full pixel stack
│   │     apply_corrections        ← pass 2: water-class noise correction
│   │     apply_temporal_smoothing ← two-pass wrapper (deforestation/afforestation only)
│   │     urbanization             ← top-level: stack → transition raster
│   │     degradation              ←   "
│   │     deforestation            ←   " (with smoothing)
│   │     afforestation            ←   " (with smoothing)
│   │     crop_intensity           ←   "
│   │
│   ├── change_detection_vector.ml ← Vectorisation (per-watershed area stats)
│   │     coord / ring / watershed ← geometry types
│   │     urb_attrs / deg_attrs /  ← typed output records (one per parameter)
│   │       def_attrs / aff_attrs /
│   │       crop_attrs
│   │     watershed_stats          ← all five parameters for one watershed
│   │     pixel_area_ha            ← x_res * y_res * 1e-4
│   │     bounding_box             ← min/max lon/lat of a ring
│   │     is_point_in_polygon      ← ray-casting PIP test
│   │     compute_area_ha          ← main area counter (replaces reduceRegions)
│   │     vectorise_urbanization   ← one watershed → urb_attrs
│   │     vectorise_degradation    ←   "
│   │     vectorise_deforestation  ←   "
│   │     vectorise_afforestation  ←   "
│   │     vectorise_crop_intensity ←   "
│   │     vectorise_all            ← all watersheds → watershed_stats list
│   │
│   └── village_lulc_analytics_lib.ml   ← Re-exports all lib modules
│
└── bin/
    ├── main.ml                    ← CLI entry point
    │     parse_watersheds_geojson ← GeoJSON file → watershed list
    │     write_vector_outputs     ← watershed_stats list → 5 GeoJSON files
    │     main ()                  ← wires everything together
    └── gee_cli.ml                 ← (unused stub for future GEE HTTP API)
```

---

## 6. Library Reference

### Libraries linked at build time (from `lib/dune` and `bin/dune`)

| Library | Package | Used in | Purpose |
|---------|---------|---------|---------|
| `tiff` | `ocaml-tiff` (geocaml opam switch) | `tiff_reader.ml` | Read/write GeoTIFF IFDs and pixel data |
| `tiff.unix` | `ocaml-tiff` | `tiff_reader.ml` | `Tiff_unix.with_open_in/out` — file handles for TIFF |
| `geojson` | opam `geojson` | (type definitions) | GeoJSON type declarations |
| `ezjsonm` | opam `ezjsonm` | `main.ml` | JSON parse (`Ezjsonm.from_string`) + serialize (`Ezjsonm.to_string`) for reading watershed GeoJSON and writing output GeoJSON |
| `unix` | OCaml stdlib | `main.ml` | `Unix.mkdir` to create output directory |

### OCaml stdlib modules (no install needed)

| Module | Used in | Purpose |
|--------|---------|---------|
| `Arg` | `main.ml` | CLI flag parsing (`--lulc`, `--watersheds`, `--outdir`, `--no-raster`, `--no-vector`) |
| `Bigarray` / `Genarray` | `tiff_reader.ml` | Raw multi-dimensional pixel buffer returned by `ocaml-tiff` |
| `Hashtbl` | `raster.ml` | Frequency table for `mode_list` |
| `Array`, `List` | everywhere | Pixel arrays, raster stacks |
| `Printf`, `Filename` | `main.ml`, `change_detection.ml` | Output formatting, path construction |
| `Float` | `change_detection_vector.ml` | `Float.min/max/infinity/neg_infinity` for bounding box |

### What was NOT needed (no network, no DB)

The OCaml binary has zero runtime dependency on:
- `earthengine-api` (no GEE calls)
- Django / PostgreSQL / Celery (no DB)
- `cohttp` / `lwt` (no HTTP, despite being in opam)
- GDAL / PROJ (coordinates stored as plain floats from GeoTIFF tiepoints)

---

## 7. Step-by-Step Pipeline Walkthrough

Here is exactly what happens when you run the binary:

```
./main.exe \
  --lulc yr2018.tif yr2019.tif yr2020.tif yr2021.tif yr2022.tif yr2023.tif \
  --watersheds filtered_mws.geojson \
  --outdir ./output
```

### Step 1 — Load 6 LULC rasters (`Tiff_reader.read_raster_from_tiff`)

For each TIFF file:
- `Tiff_unix.with_open_in` opens a file descriptor.
- `Tiff.Ifd.read_header` reads the TIFF magic bytes and offset to the IFD.
- `Tiff.Ifd.v` parses the Image File Directory — this gives width, height, compression type,
  bits-per-sample, strip offsets.
- `Tiff.Ifd.pixel_scale` reads GeoTIFF tag 33550 (ModelPixelScaleTag) → x_res, y_res.
- `Tiff.Ifd.tiepoint` reads GeoTIFF tag 33922 (ModelTiepointTag) → origin_x, origin_y.
- `Tiff.from_file Tiff.Uint8` + `Tiff.data` reads all strip data into a `Bigarray.Genarray`.
- A plain OCaml `int array` is filled by iterating `r * width + c`.
- Returns `Raster.t { meta = { width; height; x_res; y_res; origin_x; origin_y }; pixels }`.

**Result:** a list of 6 `Raster.t` values, each holding ~10 M integers (for a Kudra-size region).

### Step 2 — Run change detection (5 parameters)

**For Urbanization, Degradation, CropIntensity** (no temporal smoothing):

```
remap each of 6 rasters pixel-by-pixel  →  6 remapped Raster.t
take first 3 → mode_stack (pixel-wise)  →  then_raster
take last 3  → mode_stack (pixel-wise)  →  now_raster
apply pixel_fn to every (then, now) pair →  transition_raster
```

`mode_stack` iterates every pixel index `i` and calls `mode_list` on the list
`[r0.pixels[i]; r1.pixels[i]; r2.pixels[i]]`. `mode_list` builds a `Hashtbl`
frequency table and returns the value with the highest count (leftmost-wins on tie).

**For Deforestation and Afforestation** (with temporal smoothing):

```
Pass 1: build anomaly_counts array (size = width*height, all zeros)
  for each interior year i in [1..4]:
    for each pixel idx:
      b = raw_stack[i-1].pixels[idx]
      m = raw_stack[i  ].pixels[idx]
      a = raw_stack[i+1].pixels[idx]
      anomaly_counts[idx] += anomaly_count_for_triple(b, m, a)  ← 0..11

Pass 2: deep-copy raw pixel arrays, then correct
  for each interior year i:
    for each pixel idx where anomaly_counts[idx] ∈ {3, 4}:
      if before==3 AND middle≠3 AND after==3:  copy[i][idx] = 3
      if before≠3  AND middle==3 AND after≠3:  copy[i][idx] = before

Then proceed as normal: remap corrected stack → mode → then/now → transition_pixel
```

### Step 3 — Write transition TIFFs (`Tiff_reader.write_raster_to_tiff`)

- Creates a `Bigarray.Genarray` of `int8_unsigned` with shape `[height; width]`.
- Fills it from `Raster.get raster r c` for each (r, c).
- `Tiff.make arr` wraps it in an in-memory TIFF structure.
- `Tiff_unix.with_open_out` + `Tiff.to_file` writes it to disk.

Output: 5 uncompressed Uint8 TIFFs, one per parameter.  
**Note:** these TIFFs do not carry georeferencing tags (no tiepoint/scale written back).

### Step 4 — Parse watershed GeoJSON (`parse_watersheds_geojson` in `main.ml`)

- `Ezjsonm.from_string` parses the GeoJSON text into a tree of `Ezjsonm.value` nodes.
- `Ezjsonm.find json ["features"]` navigates to the features array.
- For each feature:
  - `Ezjsonm.find feat ["properties"; "uid"]` extracts the watershed UID.
  - `Ezjsonm.find feat ["geometry"; "type"]` checks for Polygon or MultiPolygon.
  - `Ezjsonm.find feat ["geometry"; "coordinates"]` extracts the outer ring as `(lon, lat)` pairs.
- Returns a `watershed list`: `{ uid; geometry: coord array }`.

### Step 5 — Compute per-watershed area stats (`vectorise_all`)

For each watershed and each of the 5 transition rasters:

```
compute_area_ha raster ring [target_code]:

1. bounding_box ring        → (min_lon, min_lat, max_lon, max_lat)
2. Convert bbox to pixel coords:
     col_lo = (min_lon - origin_x) / x_res
     row_lo = (origin_y - max_lat) / y_res
     (clamped to 0..width-1 and 0..height-1)
3. For each pixel (row, col) in the bbox window:
     centre = pixel_lat_lon meta row col
              = (origin_x + (col + 0.5) * x_res,
                 origin_y - (row + 0.5) * y_res)
     if is_point_in_polygon centre ring:
       if Raster.get raster row col == target_code:
         total += x_res * y_res * 1e-4   (area in hectares)
```

`is_point_in_polygon` uses the **ray-casting algorithm**:
- Cast a horizontal ray from the point to the right (→).
- Count how many polygon edges it crosses.
- If odd → inside; if even → outside.

Each `vectorise_*` function calls `compute_area_ha` once per transition code,
then constructs a typed record (`urb_attrs`, `deg_attrs`, etc.) where `total_*`
fields are just the direct float sum of the individual codes.

### Step 6 — Write GeoJSON outputs (`write_vector_outputs` in `main.ml`)

- For each of the 5 parameters, iterates `watershed_stats list`.
- For each watershed, calls the appropriate `*_props` function to get a
  `(string * Ezjsonm.value) list` (attribute name → float).
- Constructs a GeoJSON Feature object with `Ezjsonm` dict/list constructors.
- Wraps all features in a FeatureCollection.
- `Ezjsonm.to_string fc` serialises to JSON text.
- Writes to `<outdir>/change_vector_<Param>.geojson`.

---

## 8. Key Differences Between GEE and Local OCaml

| Aspect | GEE (Python) | Local OCaml |
|--------|-------------|-------------|
| **Execution** | Google's servers | Your machine |
| **Pixel representation** | `ee.Image` (lazy graph) | `int array` (eager, in RAM) |
| **Remap** | `image.remap(from, to)` | OCaml `match` function |
| **Mode** | `ee.ImageCollection.mode()` | `mode_stack` → `mode_list` with Hashtbl |
| **Pixel operations** | `image.eq(v).And(image2.eq(v2))` | `Raster.map2 pixel_fn` |
| **Polygon intersection** | `reduceRegions(Reducer.sum())` | Bounding box + ray-cast PIP loop |
| **Pixel area** | `ee.Image.pixelArea()` | `x_res * y_res * 1e-4` |
| **GeoJSON I/O** | GEE FeatureCollection API | `ezjsonm` |
| **TIFF I/O** | GEE asset pipeline | `ocaml-tiff` (`geocaml` switch) |
| **Coordinate system** | GEE handles projection | Tiepoint/scale read from TIFF header |
| **Mode tie-breaking (bug)** | Leftmost value (deterministic) | Hash bucket order (non-deterministic) → fix: `best_c = ref 1` |
| **Output** | GEE assets + GeoServer | Local TIFF + GeoJSON files |
| **Clipping to ROI** | `image.clip(roi.geometry())` | Not needed — raster is already clipped |
