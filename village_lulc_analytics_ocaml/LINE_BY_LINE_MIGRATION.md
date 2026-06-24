# Change Detection — Line-by-Line Python/GEE → OCaml Comparison

Every Python line is shown with its exact OCaml counterpart and an explanation of what
that line does and why it was written the way it was.

---

## Preliminary: The Fundamental Difference in Execution Model

Before reading the line comparisons, you must understand this core difference:

**Python/GEE** — lazy, server-side, graph-based  
When you write `image.eq(1).And(image2.eq(1))` in Python, nothing is computed.
You are building a *description* (a computation graph) that Google's servers evaluate later,
across billions of pixels in parallel, only when you call `Export` or `getInfo`.

**OCaml** — eager, local, array-based  
When you write `if v1 = 1 && v2 = 1 then 1 else 0`, it runs *right now*, one pixel at a time,
sequentially in a loop over an `int array` sitting in your RAM.

Every GEE "image algebra" expression becomes an OCaml function that is called once per pixel
inside `Raster.map2`.

---

# Part 1: `change_detection.py`

---

## 1.1 `built_up(roi_boundary, l1_asset)` — Urbanization

**What this function does:**  
Answers the question: *"Which pixels became (or stayed as) Built-up land?"*  
It remaps 12 raw LULC classes into 4 urbanization categories, computes what the land was in
the first 3 years (Then) vs the last 3 years (Now), and assigns a transition code to each pixel.

---

### Line 1 — Get the projection from the first image

```python
lulc_projection = l1_asset[0].projection()
```

**What it does:**  
GEE images can be in any coordinate reference system (CRS). Before doing any arithmetic, you
pin all operations to the same projection as the source data (EPSG:32644 / UTM for Bihar-level
LULC data). Without this, GEE might silently reproject intermediate results.

**OCaml equivalent:**  
Not needed. The `Raster.metadata` struct stores `origin_x`, `origin_y`, `x_res`, `y_res` which
were read from the TIFF's GeoTIFF tags (ModelPixelScaleTag + ModelTiepointTag). Since all 6
TIFFs were exported from the same GEE asset with the same projection, they are already aligned
pixel-for-pixel. No reprojection step is needed.

```ocaml
(* In tiff_reader.ml — happens automatically when loading *)
let x_res    = if Array.length scale > 0 then scale.(0) else 10.0 in
let y_res    = if Array.length scale > 1 then scale.(1) else 10.0 in
let origin_x = if Array.length tiepoint > 3 then tiepoint.(3) else 0.0 in
let origin_y = if Array.length tiepoint > 4 then tiepoint.(4) else 0.0 in
```

---

### Lines 2–8 — Define and apply the remap function

```python
def remap_values(image):
    return image.remap(
        [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
        [1, 2, 2, 2, 3, 4, 3, 3,  3,  3,  4],
        0,
        "predicted_label",
    ).setDefaultProjection(lulc_projection)

l1_asset_remapped = [remap_values(asset) for asset in l1_asset]
```

**What it does:**  
`image.remap(from_list, to_list, default, band_name)` is a GEE operation that replaces every
pixel value in the image:
- pixels with value 1 → 1 (Built-up stays Built-up)
- pixels with value 2, 3, or 4 → 2 (all Water variants merge into one Water class)
- pixels with value 6, 8, 9, 10, 11 → 3 (Forest + all crop types = "Vegetation")
- pixels with value 7 or 12 → 4 (Barren or Scrub = "Barren")
- anything else → 0 (background/nodata)

This simplification is necessary because the transition matrix only distinguishes 4 categories
for Urbanization. The raw 12-class LULC is too fine-grained.

`setDefaultProjection` re-pins the output to the same CRS after the remap.

The list comprehension applies `remap_values` to all 6 annual images.

**OCaml equivalent:**  
An OCaml `function` (pattern match) replacing the lookup table. Then `Raster.remap` (which
is just `Raster.map`) applies it to every pixel in a single pass.

```ocaml
(* In change_detection.ml *)
let remap_urbanization = function
  | 1               -> 1   (* Built-up → Built-up *)
  | 2 | 3 | 4       -> 2   (* Water (Kharif/Rabi/Zaid) → Water *)
  | 6               -> 3   (* Forest → Vegetation *)
  | 8 | 9 | 10 | 11 -> 3   (* All crop types → Vegetation *)
  | 7               -> 4   (* Barren → Barren *)
  | 12              -> 4   (* Scrub → Barren *)
  | _               -> 0   (* Background/NoData *)

(* In raster.ml — applies the function to every pixel *)
let remap f r = map f r           (* map: Array.map f r.pixels *)

(* Called from compute_then_now: *)
let remapped = List.map (Raster.remap remap_urbanization) stack
(* This iterates all 6 rasters and applies remap_urbanization to every pixel *)
```

**Underlying principle:**  
GEE's `image.remap` is a vectorised lookup table (LUT) operation run across the entire image
on Google's infrastructure. OCaml's version is a sequential `Array.map` loop — same result,
different execution model.

---

### Lines 9–12 — Compute Then and Now

```python
then = ee.ImageCollection(l1_asset_remapped[:3]).mode().reproject(lulc_projection)
now  = ee.ImageCollection(l1_asset_remapped[3:]).mode().reproject(lulc_projection)
```

**What it does:**  
`ee.ImageCollection(images[:3])` groups the first 3 remapped images (years 2018, 2019, 2020)
into a collection. `.mode()` computes the pixel-wise statistical mode across the 3 images —
i.e. for each pixel position, it picks whichever value appears most often across the 3 years.

Examples:
- pixel = [2, 2, 3] across the 3 years → mode = 2 (appears twice)
- pixel = [3, 3, 2] → mode = 3
- pixel = [2, 3, 4] → mode = 2 (GEE picks the first value when all are different)

`reproject` ensures the output stays in the original CRS after the collection operation.

`then` represents what the land looked like during the **baseline period** (first 3 years).  
`now` represents what it looks like during the **active/recent period** (last 3 years).

**OCaml equivalent:**

```ocaml
(* In change_detection.ml *)
let compute_then_now remap_fn stack =
  let remapped = List.map (Raster.remap remap_fn) stack in  (* remap all 6 years *)
  let n = List.length remapped in
  let then_stack = Raster.slice remapped ~start:0 ~stop:3 in (* years 0,1,2 *)
  let now_stack  = Raster.slice remapped ~start:3 ~stop:n in  (* years 3,4,5 *)
  (Raster.mode_stack then_stack, Raster.mode_stack now_stack)

(* In raster.ml — mode_stack: pixel-wise mode across a list of rasters *)
let mode_stack = function
  | [r] -> r
  | first :: rest as all ->
    let n = Array.length first.pixels in
    let pixels = Array.init n (fun i ->
      mode_list (List.map (fun r -> r.pixels.(i)) all)
    ) in
    { first with pixels }

(* mode_list: frequency table approach *)
let mode_list = function
  | [x] -> x
  | first :: _ as xs ->
    let tbl = Hashtbl.create 8 in
    List.iter (fun v ->
      Hashtbl.replace tbl v (1 + (try Hashtbl.find tbl v with Not_found -> 0))
    ) xs;
    let best_v = ref first in
    let best_c = ref 1 in     (* ← should be 1, not 0, for leftmost-wins *)
    Hashtbl.iter (fun v c ->
      if c > !best_c then begin best_v := v; best_c := c end
    ) tbl;
    !best_v
```

**Underlying principle:**  
The mode across 3 years "smooths out" single-year classification errors. If a pixel was
classified as Forest in 2018 and 2019 but accidentally as Water in 2019 (sensor glitch), the
mode will correctly return Forest. It's a simple form of temporal noise reduction.

---

### Lines 13–14 — Clip to region of interest

```python
then = then.clip(roi_boundary.geometry())
now  = now.clip(roi_boundary.geometry())
```

**What it does:**  
Sets all pixels outside the watershed boundary to NoData (masked). This ensures the output
raster only has valid values within the block boundary, and reduces the exported file size.

**OCaml equivalent:**  
Not needed. The TIFF files downloaded from GEE are already clipped to the block boundary —
GEE clips during export. The downloaded raster only covers the block extent. When the OCaml
binary reads the TIFF, it reads exactly the clipped region.

```ocaml
(* No clip step — the raster is already region-specific *)
(* Pixels outside the boundary were masked to 0 (nodata) during GEE export *)
```

---

### Lines 15–18 — Compute transition masks

```python
trans_bu_bu = then.eq(1).And(now.eq(1))
trans_w_bu  = then.eq(2).And(now.eq(1)).multiply(2)
trans_tr_bu = then.eq(3).And(now.eq(1)).multiply(3)
trans_b_bu  = then.eq(4).And(now.eq(1)).multiply(4)
```

**What it does:**  
Each line produces a Boolean image (0 or 1 per pixel), then multiplies by the transition code:

- `then.eq(1).And(now.eq(1))` → 1 where pixel was Built-up AND still is Built-up, else 0
- `.multiply(2)` → makes it 0 or 2 (so it carries code 2 when true)
- `then.eq(2).And(now.eq(1)).multiply(2)` → 0 or 2 where land was Water but is now Built-up

The `.And()` is pixel-wise logical AND.  
`eq(v)` returns 1 where pixel == v, else 0.  
`.multiply(code)` scales the Boolean 0/1 to 0/code.

Because these conditions are **mutually exclusive** (a pixel can only have one then-value),
summing them in the next step gives the correct single code.

**OCaml equivalent:**

```ocaml
(* In change_detection.ml — one function replaces all four lines *)
let urbanization_pixel then_v now_v =
  if now_v <> 1 then 0        (* Not Built-up now → no urbanization transition *)
  else (match then_v with
    | 1 -> 1  (* then.eq(1).And(now.eq(1))          → code 1 *)
    | 2 -> 2  (* then.eq(2).And(now.eq(1)).multiply(2) → code 2 *)
    | 3 -> 3  (* then.eq(3).And(now.eq(1)).multiply(3) → code 3 *)
    | 4 -> 4  (* then.eq(4).And(now.eq(1)).multiply(4) → code 4 *)
    | _ -> 0)
```

**Underlying principle:**  
GEE computes all four Boolean images in parallel on the cloud. OCaml computes them for one
pixel at a time with a simple `if/match`. Because the conditions are mutually exclusive, the
`match` is correct — it handles all four cases with no addition needed.

---

### Lines 19–26 — Sum transitions into one image

```python
change_bu = (
    ee.Image.constant(0)
    .setDefaultProjection(lulc_projection)
    .clip(roi_boundary.geometry())
)
change_bu = (
    change_bu.add(trans_bu_bu)
             .add(trans_w_bu)
             .add(trans_tr_bu)
             .add(trans_b_bu)
)
return change_bu
```

**What it does:**  
Creates a zero image as the base, then adds all four transition images to it.

Since the transition conditions are mutually exclusive (a pixel matches at most one), the sum
at each pixel is exactly the code of the transition that fired (or 0 if none fired).

This is a common GEE pattern: `zero.add(cond1).add(cond2)...` instead of `if/elif` chains,
because GEE image algebra doesn't support branching — you must express everything as sums
of Boolean masks.

**OCaml equivalent:**

```ocaml
(* In change_detection.ml *)
let make_transition_raster then_r now_r pixel_fn =
  Raster.map2 pixel_fn then_r now_r   (* applies pixel_fn to every (then_v, now_v) pair *)

let urbanization stack =
  let (t, n) = compute_then_now remap_urbanization stack in
  make_transition_raster t n urbanization_pixel
  (* urbanization_pixel replaces: zero.add(trans_bu_bu).add(trans_w_bu)... *)
```

```ocaml
(* In raster.ml — map2: applies a function pixel-by-pixel *)
let map2 f a b =
  { a with
    pixels = Array.init (Array.length a.pixels)
               (fun i -> f a.pixels.(i) b.pixels.(i)) }
(* For each pixel index i, calls: urbanization_pixel then.pixels[i] now.pixels[i] *)
```

**Underlying principle:**  
In GEE: sum of Boolean images (because GEE has no per-pixel branching).  
In OCaml: direct per-pixel function (because OCaml *does* have branching — `match`).  
Both produce the same integer code at each pixel.

---

## 1.2 `change_degradation(roi_boundary, l1_asset)` — Degradation

**What this function does:**  
Answers: *"Which pixels that were Farmland/Cropland have degraded (changed to something else)?"*  
Fires only when Then = Farmland (category 3 in degradation remap).

Structure is identical to `built_up` with a different remap table and different transition codes.

---

### Remap — degradation categories

```python
image.remap(
    [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
    [1, 2, 2, 2, 4, 5,  3, 3,  3,  3,  6],
    0, "predicted_label"
)
```

**What it does:**  
Maps raw codes to 6 degradation categories:
- 1 = Built-up
- 2 = Water (all 3 seasons merged)
- 3 = **Farmland / Cropland** ← pivot class (transitions fire from here)
- 4 = Forest
- 5 = Barren
- 6 = Scrub

Note: in the urbanization remap, crops mapped to 3 (same as Forest). Here, crops map to 3 but
Forest maps to 4. The ordering is different because the parameter cares about different
transitions.

**OCaml equivalent:**

```ocaml
let remap_degradation = function
  | 1               -> 1
  | 2 | 3 | 4       -> 2
  | 8 | 9 | 10 | 11 -> 3   (* Cropland → category 3 (pivot) *)
  | 6               -> 4   (* Forest → category 4 *)
  | 7               -> 5
  | 12              -> 6
  | _               -> 0
```

---

### Transition codes — degradation

```python
trans_f_f  = then.eq(3).And(now.eq(3))
trans_f_bu = then.eq(3).And(now.eq(1)).multiply(2)
trans_f_ba = then.eq(3).And(now.eq(5)).multiply(3)
trans_f_sc = then.eq(3).And(now.eq(6)).multiply(4)
```

**What it does:**  
All transitions require `then == 3` (was Farmland). Then checks what it became:
- code 1: f_f — stable farmland (then=3, now=3)
- code 2: f_bu — farmland → built-up (then=3, now=1)
- code 3: f_ba — farmland → barren (then=3, now=5)
- code 4: f_sc — farmland → scrub (then=3, now=6)

Pixels that were not Farmland get code 0.

**OCaml equivalent:**

```ocaml
let degradation_pixel then_v now_v =
  if then_v <> 3 then 0      (* was not Farmland → no degradation *)
  else (match now_v with
    | 3 -> 1   (* f_f  *)
    | 1 -> 2   (* f_bu *)
    | 5 -> 3   (* f_ba *)
    | 6 -> 4   (* f_sc *)
    | _ -> 0)

let degradation stack =
  let (t, n) = compute_then_now remap_degradation stack in
  make_transition_raster t n degradation_pixel
```

---

## 1.3 `change_deforestation_afforestation(roi_boundary, l1_asset, lulc_projection)`

**What this function does:**  
This is the **shared preprocessing step** for both Deforestation and Afforestation.
It has two jobs:
1. Run a two-pass temporal smoothing algorithm to correct classification noise in the raw stack.
2. Return the smoothed (then, now) pair using the forest remap.

This is the most complex function in the entire pipeline.

---

### Pass 1, setup — zero accumulator image

```python
zero_image2 = (
    ee.Image.constant(0)
    .setDefaultProjection(lulc_projection)
    .clip(l1_asset[0].geometry())
)
```

**What it does:**  
Creates a blank image full of zeros, same size as the LULC images. This will accumulate
anomaly counts (how many of the 11 structural conditions fired at each pixel).

**OCaml equivalent:**

```ocaml
(* In change_detection.ml — build_anomaly_counts *)
let counts = Array.make size 0
(* A plain int array of zeros, length = width * height *)
```

---

### Pass 1, loop — 11 anomaly conditions

```python
for i in range(1, len(l1_asset) - 1):   # i = 1, 2, 3, 4  (interior years)
    before = l1_asset[i - 1]
    middle = l1_asset[i]
    after  = l1_asset[i + 1]
```

**What it does:**  
Iterates over interior years only (not the first or last). For 6 years (indices 0–5), this
is years 1, 2, 3, 4. Each iteration looks at a 3-year window: before, middle, after.

**OCaml equivalent:**

```ocaml
let arr    = Array.of_list px_arrays in   (* px_arrays: list of 6 pixel arrays *)
let nyears = Array.length arr in          (* = 6 *)
for i = 1 to nyears - 2 do               (* i = 1, 2, 3, 4 *)
  for idx = 0 to size - 1 do             (* each pixel *)
    let b = arr.(i - 1).(idx) in         (* before *)
    let m = arr.(i).(idx) in             (* middle *)
    let a = arr.(i + 1).(idx) in         (* after *)
    counts.(idx) <- counts.(idx) + anomaly_count_for_triple b m a
  done
done
```

Key difference: GEE iterates over *images* (whole-raster operations). OCaml iterates over
*pixel indices* (scalar operations). The result is identical.

---

### Pass 1, conditions 1–11

```python
cond1 = before.eq(12).And(after.eq(12)).And(
            middle.eq(6).Or(middle.eq(8)).Or(middle.eq(9)).Or(middle.eq(10)).Or(middle.eq(11)))
```

**What it does (cond1):**  
Pixel was Scrub (12) before AND Scrub (12) after AND Forest or any Crop in the middle.
This pattern = the middle year's Forest/Crop classification is noise (it was and remained Scrub).

All 11 conditions follow the same pattern: stable class B/A + anomalous middle.

| Cond | Before | Middle | After | Meaning |
|------|--------|--------|-------|---------|
| 1 | Scrub(12) | Forest/Crop | Scrub(12) | Forest/Crop sandwiched in Scrub |
| 2 | Water(2/3/4) | Forest/Crop | Water(2/3/4) | Forest/Crop sandwiched in Water |
| 3 | Forest(6) | Scrub(12) | Forest(6) | Scrub sandwiched in Forest |
| 4 | Crop | Scrub(12) | Crop | Scrub sandwiched in Crop |
| 5 | Crop | Barren(7) | Crop | Barren sandwiched in Crop |
| 6 | Forest(6) | Crop | Forest(6) | Crop sandwiched in Forest |
| 7 | Crop | Forest(6) | Crop | Forest sandwiched in Crop |
| 8 | BuiltUp(1) | Forest(6) | BuiltUp(1) | Forest sandwiched in BuiltUp |
| 9 | Forest(6) | BuiltUp(1) | Forest(6) | BuiltUp sandwiched in Forest |
| 10 | BuiltUp(1) | Crop | BuiltUp(1) | Crop sandwiched in BuiltUp |
| 11 | Barren(7) | Forest/Crop | Barren(7) | Forest/Crop sandwiched in Barren |

```python
zero_image2 = zero_image2.add(cond1).add(cond2)...add(cond11)
```

**What it does:**  
Each `cond` image is 0 or 1. Adding all 11 gives the total number of anomaly conditions that
fired at each pixel across this 3-year window. After the outer loop, the total across all
interior windows is accumulated.

**OCaml equivalent:**

```ocaml
let anomaly_count_for_triple b m a =
  let n = ref 0 in
  (* cond1: scrub–(forest|crop)–scrub *)
  if b = 12 && a = 12 && (is_forest m || is_crop m)       then incr n;
  (* cond2: water–(forest|crop)–water *)
  if is_water b && is_water a && (is_forest m || is_crop m) then incr n;
  (* cond3: forest–scrub–forest *)
  if b = 6 && a = 6 && m = 12                             then incr n;
  (* cond4: crop–scrub–crop *)
  if is_crop b && is_crop a && m = 12                      then incr n;
  (* cond5: crop–barren–crop *)
  if is_crop b && is_crop a && m = 7                       then incr n;
  (* cond6: forest–crop–forest *)
  if b = 6 && a = 6 && is_crop m                          then incr n;
  (* cond7: crop–forest–crop *)
  if is_crop b && is_crop a && m = 6                       then incr n;
  (* cond8: builtup–forest–builtup *)
  if b = 1 && a = 1 && m = 6                              then incr n;
  (* cond9: forest–builtup–forest *)
  if b = 6 && a = 6 && m = 1                              then incr n;
  (* cond10: builtup–crop–builtup *)
  if b = 1 && a = 1 && is_crop m                          then incr n;
  (* cond11: barren–(forest|crop)–barren *)
  if b = 7 && a = 7 && (is_forest m || is_crop m)         then incr n;
  !n

(* Helper predicates — replace GEE .Or() chains *)
let is_crop  v = v = 8 || v = 9 || v = 10 || v = 11
let is_water v = v = 2 || v = 3 || v = 4
let is_forest v = v = 6
```

**Underlying principle:**  
These 11 conditions identify "sandwich" patterns — a pixel that is stably class A in the year
before AND after, but misclassified as class B in between. That middle year is likely a
sensor/cloud/shadow artifact. The anomaly count tells you how severe the noise is.

A count of 3 or 4 (out of the max possible ~11 × 4 windows = 44) means the pixel shows
*consistent structural noise* — enough to warrant correction.

---

### Pass 2, setup — deep copy the raw stack

```python
l1_asset_copy = copy.deepcopy(l1_asset)
```

**What it does:**  
Creates an independent copy of the 6-year image stack. Corrections in Pass 2 are written to
this copy. The **original** stack (`l1_asset`) is kept unchanged so that conditions in Pass 2
are evaluated on the original values (not on already-corrected values, which could chain).

**OCaml equivalent:**

```ocaml
let copy = Array.map Array.copy orig
(* Array.copy creates a fresh array with the same values *)
(* Array.map Array.copy creates a fresh copy for each year's pixel array *)
(* orig remains untouched throughout Pass 2 *)
```

---

### Pass 2, loop — apply corrections

```python
for i in range(1, len(l1_asset) - 1):
    before = l1_asset[i - 1]    # ← reads from ORIGINAL
    middle = l1_asset[i]         # ← reads from ORIGINAL
    after  = l1_asset[i + 1]    # ← reads from ORIGINAL

    cond1 = (before.eq(3).And(middle.neq(3)).And(after.eq(3))
             .And(zero_image2.eq(3).Or(zero_image2.eq(4))))

    cond2 = (before.neq(3).And(middle.eq(3)).And(after.neq(3))
             .And(zero_image2.eq(3).Or(zero_image2.eq(4))))

    middle = middle.where(cond1, 3)        # ← writes to COPY
    middle = middle.where(cond2, before)   # ← writes to COPY

    l1_asset_copy[i] = middle
```

**What cond1 does:**  
`before == 3 AND middle ≠ 3 AND after == 3 AND (anomaly_count == 3 OR 4)`  
Raw class 3 = Water (Rabi season).  
The pixel was Water in the year before, NOT Water in the middle year, and Water again after.
With high anomaly count, the non-water middle year is noise → revert it to 3 (Water).

**What cond2 does:**  
`before ≠ 3 AND middle == 3 AND after ≠ 3 AND (anomaly_count == 3 OR 4)`  
The pixel was NOT Water before, IS Water in the middle year, and NOT Water after.
With high anomaly count, the middle water is noise → revert it to what it was before.

**Why only correct class 3 (Water Rabi)?**  
Water Rabi (class 3) appears in one specific season window (Rabi = winter crop harvest season,
Nov–Mar) when fields are flooded. The classifier sometimes confuses forest or cropland with
flooded fields during this window. This targeted correction only fixes that specific artefact.

**OCaml equivalent:**

```ocaml
for i = 1 to nyears - 2 do
  let size = Array.length orig.(i) in
  for idx = 0 to size - 1 do
    let cnt = anomaly_counts.(idx) in
    if cnt = 3 || cnt = 4 then begin          (* AND (zero_image2.eq(3).Or(zero_image2.eq(4))) *)
      let b = orig.(i - 1).(idx) in           (* before — from ORIGINAL *)
      let m = orig.(i).(idx) in               (* middle — from ORIGINAL *)
      let a = orig.(i + 1).(idx) in           (* after  — from ORIGINAL *)
      if b = 3 && m <> 3 && a = 3 then        (* cond1 *)
        copy.(i).(idx) <- 3                   (* middle.where(cond1, 3) *)
      else if b <> 3 && m = 3 && a <> 3 then  (* cond2 *)
        copy.(i).(idx) <- b                   (* middle.where(cond2, before) *)
    end
  done
done;
Array.to_list copy
```

---

### After Pass 2 — apply forest remap and compute Then/Now

```python
def remap_values(image):
    remapped = image.remap(
        [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
        [1, 2, 2, 2, 3, 5,  4, 4,  4,  4,  6],
        0, "predicted_label"
    ).setDefaultProjection(lulc_projection)
    return remapped

l1_asset_remapped = [remap_values(asset) for asset in l1_asset_copy]  # ← CORRECTED copy

then = ee.ImageCollection(l1_asset_remapped[:3]).mode().reproject(lulc_projection)
now  = ee.ImageCollection(l1_asset_remapped[3:]).mode().reproject(lulc_projection)

then = then.clip(roi_boundary.geometry())
now  = now.clip(roi_boundary.geometry())
return now, then
```

**What the forest remap does:**  
Maps raw codes to 6 forest categories:
- 3 = **Forest** ← pivot class for both deforestation and afforestation
- 4 = Cropland/Farmland
- 5 = Barren
- 6 = Scrub

Forest (raw=6) becomes category 3 (pivot). This is different from the urbanization/degradation
remaps — here, Forest is the key land cover being tracked.

**OCaml equivalent:**

```ocaml
(* The remap function *)
let remap_forest = function
  | 1               -> 1
  | 2 | 3 | 4       -> 2
  | 6               -> 3   (* Forest → category 3 (pivot) *)
  | 8 | 9 | 10 | 11 -> 4
  | 7               -> 5
  | 12              -> 6
  | _               -> 0

(* apply_temporal_smoothing wraps the full two-pass logic *)
let apply_temporal_smoothing stack = ...

(* compute_then_now applies remap_forest to the SMOOTHED stack *)
let deforestation stack =
  let smoothed = apply_temporal_smoothing stack in    (* two-pass correction *)
  let (t, n)   = compute_then_now remap_forest smoothed in  (* remap → mode *)
  make_transition_raster t n deforestation_pixel
```

---

## 1.4 `change_deforestation(roi_boundary, l1_asset)` — Deforestation

**What this function does:**  
*"Which pixels that were Forest have lost their forest cover?"*  
Fires only when Then == 3 (was Forest in the forest remap).

```python
def change_deforestation(roi_boundary, l1_asset):
    lulc_projection = l1_asset[0].projection()
    now, then = change_deforestation_afforestation(roi_boundary, l1_asset, lulc_projection)

    trans_fo_fo = then.eq(3).And(now.eq(3))
    trans_fo_bu = then.eq(3).And(now.eq(1)).multiply(2)
    trans_fo_fa = then.eq(3).And(now.eq(4)).multiply(3)
    trans_fo_ba = then.eq(3).And(now.eq(5)).multiply(4)
    trans_sc    = then.eq(3).And(now.eq(6)).multiply(5)

    change_def = ee.Image.constant(0)...
    change_def = change_def.add(trans_fo_fo).add(trans_fo_bu)...
    return change_def
```

**What the transitions mean:**

| Code | Name | Meaning |
|------|------|---------|
| 1 | fo_fo | Forest → Forest (stable, no change) |
| 2 | fo_bu | Forest → Built-up (human encroachment) |
| 3 | fo_fa | Forest → Farmland (agricultural expansion) |
| 4 | fo_ba | Forest → Barren (degradation, clear-cut) |
| 5 | fo_sc | Forest → Scrub (partial degradation) |

**OCaml equivalent:**

```ocaml
let deforestation_pixel then_v now_v =
  if then_v <> 3 then 0   (* was not Forest → not deforestation *)
  else (match now_v with
    | 3 -> 1   (* fo_fo: trans_fo_fo = then.eq(3).And(now.eq(3))          *)
    | 1 -> 2   (* fo_bu: trans_fo_bu = then.eq(3).And(now.eq(1)).mult(2)  *)
    | 4 -> 3   (* fo_fa: trans_fo_fa = then.eq(3).And(now.eq(4)).mult(3)  *)
    | 5 -> 4   (* fo_ba: trans_fo_ba = then.eq(3).And(now.eq(5)).mult(4)  *)
    | 6 -> 5   (* fo_sc: trans_sc    = then.eq(3).And(now.eq(6)).mult(5)  *)
    | _ -> 0)

let deforestation stack =
  let smoothed = apply_temporal_smoothing stack in
  let (t, n)   = compute_then_now remap_forest smoothed in
  make_transition_raster t n deforestation_pixel
```

---

## 1.5 `change_afforestation(roi_boundary, l1_asset)` — Afforestation

**What this function does:**  
*"Which pixels that are NOW Forest were previously something else?"*  
Mirror of deforestation — fires only when Now == 3 (currently Forest).

```python
def change_afforestation(roi_boundary, l1_asset):
    lulc_projection = l1_asset[0].projection()
    now, then = change_deforestation_afforestation(roi_boundary, l1_asset, lulc_projection)

    trans_fo_fo = then.eq(3).And(now.eq(3))           # stable forest
    trans_bu_fo = then.eq(1).And(now.eq(3)).multiply(2)  # built-up → forest
    trans_fa_fo = then.eq(4).And(now.eq(3)).multiply(3)  # farmland → forest
    trans_ba_fo = then.eq(5).And(now.eq(3)).multiply(4)  # barren → forest
    trans_sc_fo = then.eq(6).And(now.eq(3)).multiply(5)  # scrub → forest
    ...
```

**Key difference from Deforestation:**  
- Deforestation checks: `then == Forest` → what did it become?
- Afforestation checks: `now == Forest` → what was it before?

Same smoothed stack, same remap, different pixel function direction.

**OCaml equivalent:**

```ocaml
let afforestation_pixel then_v now_v =
  if now_v <> 3 then 0   (* not Forest now → not afforestation *)
  else (match then_v with
    | 3 -> 1   (* fo_fo: stable forest              *)
    | 1 -> 2   (* bu_fo: built-up → forest          *)
    | 4 -> 3   (* fa_fo: farmland  → forest         *)
    | 5 -> 4   (* ba_fo: barren    → forest         *)
    | 6 -> 5   (* sc_fo: scrub     → forest         *)
    | _ -> 0)

let afforestation stack =
  let smoothed = apply_temporal_smoothing stack in
  let (t, n)   = compute_then_now remap_forest smoothed in
  make_transition_raster t n afforestation_pixel
(* Same smoothed raster as deforestation — both use forest remap *)
```

---

## 1.6 `change_cropping_intensity(roi_boundary, l1_asset)` — Crop Intensity

**What this function does:**  
*"How has the cropping intensity changed?"* Tracks shifts between single, double, and triple
crop cycles. This is the most granular parameter — 9 distinct transition codes instead of 4–5.

```python
def change_cropping_intensity(roi_boundary, l1_asset):
    lulc_projection = l1_asset[0].projection()

    def remap_values(image):
        return image.remap(
            [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
            [1, 2, 2, 2, 3, 4,  5, 5,  6,  7,  8],
            0, "predicted_label"
        ).setDefaultProjection(lulc_projection)
```

**What this remap does:**  
- 5 = Single crop (raw 8 OR 9 — two single-crop types merged)
- 6 = Double crop (raw 10)
- 7 = Triple crop (raw 11)
- Everything else → non-crop categories (1, 2, 3, 4, 8)

**OCaml equivalent:**

```ocaml
let remap_crop = function
  | 1               -> 1
  | 2 | 3 | 4       -> 2
  | 6               -> 3
  | 7               -> 4
  | 8 | 9           -> 5   (* Single crop: raw 8 and 9 both → 5 *)
  | 10              -> 6   (* Double crop *)
  | 11              -> 7   (* Triple crop *)
  | 12              -> 8
  | _               -> 0
```

---

### Crop transition codes

```python
trans_do_si = then.eq(6).And(now.eq(5))                # double→single (intensify DOWN)
trans_tr_si = then.eq(7).And(now.eq(5)).multiply(2)    # triple→single (intensify DOWN)
trans_tr_do = then.eq(7).And(now.eq(6)).multiply(3)    # triple→double (intensify DOWN)
trans_si_do = then.eq(5).And(now.eq(6)).multiply(4)    # single→double (intensify UP)
trans_si_tr = then.eq(5).And(now.eq(7)).multiply(5)    # single→triple (intensify UP)
trans_do_tr = then.eq(6).And(now.eq(7)).multiply(6)    # double→triple (intensify UP)
si_si       = then.eq(5).And(now.eq(5)).multiply(7)    # stable single
do_do       = then.eq(6).And(now.eq(6)).multiply(8)    # stable double
tr_tr       = then.eq(7).And(now.eq(7)).multiply(9)    # stable triple
```

**What it does:**  
The 6 directional codes (1–6) capture intensification direction changes.  
The 3 stable codes (7–9) capture unchanging intensity level.  
`total_change` (in the vector output) sums codes 1–6 only (not stable).

**OCaml equivalent:**

```ocaml
let crop_intensity_pixel then_v now_v =
  match (then_v, now_v) with
  | (6, 5) -> 1   (* do_si: trans_do_si *)
  | (7, 5) -> 2   (* tr_si: trans_tr_si *)
  | (7, 6) -> 3   (* tr_do: trans_tr_do *)
  | (5, 6) -> 4   (* si_do: trans_si_do *)
  | (5, 7) -> 5   (* si_tr: trans_si_tr *)
  | (6, 7) -> 6   (* do_tr: trans_do_tr *)
  | (5, 5) -> 7   (* si_si *)
  | (6, 6) -> 8   (* do_do *)
  | (7, 7) -> 9   (* tr_tr *)
  | _       -> 0  (* not a crop-intensity transition *)
(* OCaml match on a tuple replaces 9 separate GEE Boolean image additions *)

let crop_intensity stack =
  let (t, n) = compute_then_now remap_crop stack in
  make_transition_raster t n crop_intensity_pixel
(* No temporal smoothing — raw stack used directly *)
```

---

# Part 2: `change_detection_vector.py`

---

## 2.1 `generate_vector(roi, args, state, district, block, layer_name, ...)` — Core Area Counter

**What this function does:**  
For each transition code (and "total" unions), counts the area in hectares of matching pixels
inside each watershed polygon. This is the heart of the vectorisation step.

---

### Load the transition raster

```python
raster = ee.Image(
    get_gee_asset_path(...) + f"change_{district}_{block}_{layer_name}_{start_year}_{end_year}"
)
```

**What it does:**  
Loads the previously computed change detection raster from the GEE asset path.
This is a single-band integer image where each pixel value is one of the transition codes.

**OCaml equivalent:**  
The raster is already in memory as `Raster.t` — passed directly to the vectorise functions.
No GEE asset path needed — everything is local.

---

### Loop over each attribute definition

```python
fc = roi   # start with the watershed FeatureCollection
for arg in args:
    raster = raster.select(["constant"])
```

**What it does:**  
`raster.select(["constant"])` selects the single band named "constant" (GEE's default band
name for computed images). This is a no-op cleanup — ensures you're working with the right band.

**OCaml equivalent:**  
Not needed. `Raster.t` is always single-band — there's no band selection concept.

---

### Build the pixel mask

```python
    if isinstance(arg["value"], list) and len(arg["value"]) > 1:
        # For "total_*" fields: OR multiple codes together
        ored_str = "raster.eq(ee.Number(" + str(arg["value"][0]) + "))"
        for i in range(1, len(arg["value"])):
            ored_str += ".Or(raster.eq(ee.Number(" + str(arg["value"][i]) + ")))"
        mask = eval(ored_str)
    else:
        mask = raster.eq(ee.Number(arg["value"]))
```

**What it does:**  
Builds a binary mask image: 1 where the raster pixel equals the target code(s), 0 elsewhere.

For single codes: `mask = raster.eq(2)` → 1 where code==2, else 0.  
For total fields (lists): `mask = raster.eq(2).Or(raster.eq(3)).Or(raster.eq(4))` → 1 where
code is any of 2, 3, or 4.

Note: `eval(ored_str)` is used because the GEE API doesn't support `in` or `isin` — you must
chain `.Or()` calls manually, and doing so programmatically requires string construction + eval.

**OCaml equivalent:**

```ocaml
(* compute_area_ha takes a target_codes list — handles both cases *)
let compute_area_ha raster ring target_codes =
  ...
  if List.mem v target_codes then   (* replaces raster.eq(v1).Or(raster.eq(v2))... *)
    total := !total +. pa
```

`List.mem v target_codes` handles both `[2]` (single) and `[2; 3; 4]` (total/union)
without needing eval or string construction.

---

### Compute pixel area

```python
    pixel_area = ee.Image.pixelArea()
    forest_area = pixel_area.updateMask(mask)
```

**What it does:**  
`ee.Image.pixelArea()` creates an image where each pixel's value = its area in m² at the
given projection. For EPSG:32644 (UTM, metres) at 10m resolution, this is always 100 m²
(10 × 10). But GEE computes it geometrically to handle curved-earth effects at non-UTM CRS.

`updateMask(mask)` zeroes out all pixels where mask == 0 — only "true" pixels contribute area.

**OCaml equivalent:**

```ocaml
(* In change_detection_vector.ml *)
let pixel_area_ha (meta : Raster.metadata) =
  meta.Raster.x_res *. meta.Raster.y_res *. 1e-4
(* x_res = 10.0, y_res = 10.0 → 100 m² → * 0.0001 = 0.01 ha *)
(* This is a constant for the whole raster — no per-pixel geodetic computation needed *)
(* because all pixels at 10m UTM have essentially identical area *)
```

The mask is replaced by `if List.mem v target_codes then total := !total +. pa`.

---

### Reduce regions (sum pixel area inside each watershed)

```python
    fc = forest_area.reduceRegions(
        collection=fc,
        reducer=ee.Reducer.sum(),
        scale=10,
        crs=raster.projection()
    )
```

**What it does:**  
This is GEE's spatial join + aggregation. For each polygon in `fc` (the watershed collection),
GEE:
1. Identifies all pixels whose centre falls inside the polygon.
2. Sums their area values (which are already masked to 0 for non-matching codes).
3. Stores the result as a new attribute `"sum"` on each polygon feature.

`scale=10` ensures GEE evaluates at the LULC raster's native 10m resolution (not some default).

**OCaml equivalent:**

```ocaml
(* The entire reduceRegions is replaced by: *)
let compute_area_ha (raster : Raster.t) (ring : ring) (target_codes : int list) =
  let meta = raster.Raster.meta in
  let pa   = pixel_area_ha meta in

  (* Step 1: Geographic bounding box of the watershed *)
  let (min_lon, min_lat, max_lon, max_lat) = bounding_box ring in

  (* Step 2: Convert bbox corners to pixel row/col indices *)
  let col_lo = max 0 (Float.to_int ((min_lon -. meta.origin_x) /. meta.x_res)) in
  let col_hi = min (meta.width - 1) (Float.to_int ((max_lon -. meta.origin_x) /. meta.x_res)) in
  let row_lo = max 0 (Float.to_int ((meta.origin_y -. max_lat) /. meta.y_res)) in
  let row_hi = min (meta.height - 1) (Float.to_int ((meta.origin_y -. min_lat) /. meta.y_res)) in

  (* Step 3: Scan only the bbox window, not the full raster *)
  let total = ref 0.0 in
  for row = row_lo to row_hi do
    for col = col_lo to col_hi do
      let centre = Raster.pixel_lat_lon meta row col in
      if is_point_in_polygon centre ring then begin   (* ← replaces reduceRegions *)
        let v = Raster.get raster row col in
        if List.mem v target_codes then               (* ← replaces the mask *)
          total := !total +. pa                       (* ← replaces Reducer.sum() *)
      end
    done
  done;
  !total
```

**Underlying principle — Ray-casting PIP:**

```ocaml
let is_point_in_polygon (px, py) ring =
  let n      = Array.length ring in
  let inside = ref false in
  let j      = ref (n - 1) in
  for i = 0 to n - 1 do
    let (xi, yi) = ring.(i) in
    let (xj, yj) = ring.(!j) in
    (* Does edge (j→i) cross the horizontal ray going right from (px, py)? *)
    if ((yi > py) <> (yj > py)) &&
       (px < (xj -. xi) *. (py -. yi) /. (yj -. yi) +. xi)
    then inside := not !inside;
    j := i
  done;
  !inside
```

The ray-casting algorithm shoots an imaginary ray rightward from the pixel centre. Each time
the ray crosses a polygon edge, `inside` flips. If it flips an odd number of times, the
point is inside the polygon. This is a standard O(N) algorithm where N = number of vertices.

GEE's `reduceRegions` uses a much more optimised version internally (spatial indexing, GPU),
but the result is mathematically equivalent.

---

### Convert m² to hectares and attach as attribute

```python
    def process_feature(feature):
        value = feature.get("sum")
        value = ee.Number(value).multiply(0.0001)   # m² → ha
        feature = feature.set(arg["label"], value)  # attach named attribute
        feature = remove_property(feature, "sum")   # remove intermediate "sum"
        return feature

    fc = fc.map(process_feature)
```

**What it does:**  
Converts the raw sum (in m²) to hectares by multiplying by 0.0001.
Attaches it as a named property (e.g. `"bu_bu"`, `"w_bu"`) on each feature.
Removes the temporary `"sum"` property.

**OCaml equivalent:**

```ocaml
(* pixel_area_ha already returns ha, so no post-multiplication needed *)
(* The area is attached as a typed record field, not a dynamic property *)

let vectorise_urbanization raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let bu_bu  = area [1] in   (* code 1 → bu_bu label *)
  let w_bu   = area [2] in   (* code 2 → w_bu label *)
  let tr_bu  = area [3] in
  let b_bu   = area [4] in
  { bu_bu; w_bu; tr_bu; b_bu;
    total_urb = w_bu +. tr_bu +. b_bu }
    (* total_urb = direct float sum, not a separate GEE mask operation *)
```

In GEE, `total_urb` requires a *separate iteration* through `generate_vector` with
`"value": [2, 3, 4]` because GEE can't just add the already-computed numbers — each
attribute is a separate reduce operation. In OCaml, it's just `w_bu +. tr_bu +. b_bu`
because the values are plain floats already in scope.

---

## 2.2 The Five Vector Functions — Pattern Walkthrough

All five follow the same pattern: define `args`, call `generate_vector`. The only differences
are the code→label mapping and which codes contribute to the "total" field.

### Afforestation vector

```python
def afforestation_vector(roi, state, district, block, start_year, end_year):
    args = [
        {"value": 1, "label": "fo_fo"},   # stable forest
        {"value": 2, "label": "bu_fo"},   # built-up → forest
        {"value": 3, "label": "fa_fo"},   # farmland  → forest
        {"value": 4, "label": "ba_fo"},   # barren    → forest
        {"value": 5, "label": "sc_fo"},   # scrub     → forest
        {"value": [2, 3, 4, 5], "label": "total_aff"},  # all gains (not stable)
    ]
```

**OCaml equivalent:**

```ocaml
let vectorise_afforestation raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let fo_fo_aff = area [1] in
  let bu_fo     = area [2] in
  let fa_fo     = area [3] in
  let ba_fo     = area [4] in
  let sc_fo     = area [5] in
  { fo_fo_aff; bu_fo; fa_fo; ba_fo; sc_fo;
    total_aff = bu_fo +. fa_fo +. ba_fo +. sc_fo }
    (* total_aff: codes [2,3,4,5] → direct sum since values already computed *)
```

### Crop Intensity vector

```python
def crop_intensity_vector(roi, state, district, block, start_year, end_year):
    args = [
        {"value": 1, "label": "do_si"},
        {"value": 2, "label": "tr_si"},
        {"value": 3, "label": "tr_do"},
        {"value": 4, "label": "si_do"},
        {"value": 5, "label": "si_tr"},
        {"value": 6, "label": "do_tr"},
        {"value": 7, "label": "si_si"},
        {"value": 8, "label": "do_do"},
        {"value": 9, "label": "tr_tr"},
        {"value": [1, 2, 3, 4, 5, 6], "label": "total_change"},  # directional only
    ]
```

**OCaml equivalent:**

```ocaml
let vectorise_crop_intensity raster (ws : watershed) =
  let area codes = compute_area_ha raster ws.geometry codes in
  let do_si = area [1] in
  let tr_si = area [2] in
  let tr_do = area [3] in
  let si_do = area [4] in
  let si_tr = area [5] in
  let do_tr = area [6] in
  let si_si = area [7] in
  let do_do = area [8] in
  let tr_tr = area [9] in
  { do_si; tr_si; tr_do; si_do; si_tr; do_tr; si_si; do_do; tr_tr;
    total_change = do_si +. tr_si +. tr_do +. si_do +. si_tr +. do_tr }
    (* total_change: codes 1-6 only — stable codes 7,8,9 are excluded *)
```

---

## 2.3 `vectorise_all` — Top-Level Driver

```python
# In Python this is implicit — vectorise_change_detection calls each *_vector function
# separately and they each submit a separate GEE export task
task_list = [
    afforestation_vector(...),
    deforestation_vector(...),
    degradation_vector(...),
    urbanization_vector(...),
    crop_intensity_vector(...),
]
```

**OCaml equivalent:**

```ocaml
(* In change_detection_vector.ml *)
let vectorise_all ~urb_raster ~deg_raster ~def_raster ~aff_raster ~crop_raster ~watersheds =
  List.map (fun (ws : watershed) ->
    { uid            = ws.uid;
      geometry       = ws.geometry;
      urbanization   = vectorise_urbanization  urb_raster  ws;
      degradation    = vectorise_degradation   deg_raster  ws;
      deforestation  = vectorise_deforestation def_raster  ws;
      afforestation  = vectorise_afforestation aff_raster  ws;
      crop_intensity = vectorise_crop_intensity crop_raster ws;
    }
  ) watersheds
(* For each watershed, all 5 parameters computed in one pass *)
(* In GEE: 5 separate export tasks, each reducing the full watershed collection separately *)
```

---

# Part 3: Full Execution Flow Side-by-Side

```
PYTHON / GEE                              OCAML
═════════════════════════════════════     ════════════════════════════════════════

get_change_detection() called by          ./main.exe --lulc y0.tif ... y5.tif
Celery worker                             --watersheds ws.geojson --outdir ./out

│                                         │
├─ Build l1_asset list (6 ee.Image)      ├─ Tiff_reader.read_raster_from_tiff ×6
│   GEE lazy references to cloud assets  │   Reads IFD tags, fills int array
│                                         │
├─ built_up(roi, l1_asset)               ├─ Change_detection.urbanization stack
│   ├─ remap ×6 (lazy GEE graph)        │   ├─ List.map (Raster.remap remap_urbanization)
│   ├─ ImageCollection([:3]).mode()      │   ├─ Raster.mode_stack (first 3)
│   ├─ ImageCollection([3:]).mode()      │   ├─ Raster.mode_stack (last 3)
│   └─ zero.add(mask×code)...           │   └─ Raster.map2 urbanization_pixel
│                                         │
├─ change_degradation(roi, l1_asset)     ├─ Change_detection.degradation stack
│   (same structure, different remap)    │   (same structure, remap_degradation)
│                                         │
├─ change_deforestation(roi, l1_asset)   ├─ Change_detection.deforestation stack
│   ├─ Pass1: zero_image2 +=            │   ├─ build_anomaly_counts (nested loops)
│   │   cond1..cond11 per interior year  │   │   anomaly_count_for_triple ×4 years
│   ├─ Pass2: deepcopy + where()        │   ├─ apply_corrections (Array.copy + loops)
│   ├─ remap_forest ×6                  │   ├─ List.map (Raster.remap remap_forest)
│   └─ mode + transition codes          │   └─ Raster.map2 deforestation_pixel
│                                         │
├─ change_afforestation(roi, l1_asset)   ├─ Change_detection.afforestation stack
│   (same smoothed stack, mirror pixel   │   (same smoothed stack, mirror pixel_fn)
│    function direction)                 │
│                                         │
├─ change_cropping_intensity(...)        ├─ Change_detection.crop_intensity stack
│   (no smoothing, 9-code remap)        │   (no smoothing, remap_crop, tuple match)
│                                         │
├─ export_raster_asset_to_gee ×5        ├─ Tiff_reader.write_raster_to_tiff ×5
│   Async GEE task, minutes to complete  │   Synchronous local file write, instant
│                                         │
├─ check_task_status (wait loop)         │  (no waiting — local is synchronous)
│                                         │
├─ vectorise_change_detection()          ├─ parse_watersheds_geojson
│   ├─ generate_vector ×5               │   (Ezjsonm: parse GeoJSON → watershed list)
│   │   ├─ raster.eq(code)             │
│   │   ├─ pixelArea().updateMask()    │   vectorise_all watersheds
│   │   ├─ reduceRegions(Reducer.sum)  │   ├─ vectorise_urbanization per ws
│   │   └─ * 0.0001 → ha              │   │   compute_area_ha [1],[2],[3],[4]
│   └─ export_vector_asset_to_gee ×5   │   │   bounding_box + PIP loop
│                                         │   └─ (×5 parameters, ×N watersheds)
└─ sync_to_geoserver                     │
   (infra — no OCaml equivalent)         └─ write_vector_outputs (Ezjsonm serialize)
```

---

# Part 4: Summary of Design Decisions in the Migration

| Decision | Why |
|----------|-----|
| `function` (pattern match) for remaps | Replaces GEE's array lookup table. OCaml pattern matching is compiled to jump tables — same O(1) speed. |
| `Raster.map2` for pixel operations | Replaces GEE's image algebra. Abstracts the `Array.init` loop so each parameter only writes its logic, not the loop. |
| `Hashtbl` for mode | GEE's `.mode()` is an opaque server operation. `Hashtbl` gives an exact frequency table with O(1) insert. For lists of length 3, a `Hashtbl` of size 8 is over-allocated but avoids hash collisions. |
| `best_c = ref 1` (correct) / `ref 0` (bug) | `ref 1` makes `first` (leftmost) the default winner. `ref 0` lets the first value visited by `Hashtbl.iter` win — non-deterministic. GEE always returns the first (leftmost) value on ties. |
| `Array.copy` for temporal smoothing | GEE's `deepcopy + where()` keeps the original image immutable while writing to the copy. `Array.copy` does the same: `orig` is never modified, `copy` receives all changes. |
| Bounding box + PIP instead of `reduceRegions` | `reduceRegions` on GEE uses Google's spatial database infrastructure. Locally, a bbox pre-filter + ray-casting is efficient enough for ~60 watersheds × ~10M pixels. The bbox cuts the PIP checks to only the pixels near each watershed. |
| `List.mem` for `total_*` codes | Replaces GEE's `.Or(raster.eq(v1)).Or(raster.eq(v2))...` chain. `List.mem` is O(N) on a tiny list (max 6 elements) — negligible overhead. |
| Typed records (`urb_attrs` etc.) | Replaces GEE's dynamic feature properties (string-keyed dict). OCaml's type system enforces that all required fields are present at compile time. |
