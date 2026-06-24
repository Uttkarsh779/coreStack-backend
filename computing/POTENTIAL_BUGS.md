# Potential Bugs

Each entry has: location, description, hypothesis, and the test that will confirm or refute it.

---

## BUG-1 — Wrong "now" window in all change detection sub-pipelines

**Files:**
- `change_detection/change_detection.py` line 137 (`built_up`)
- `change_detection/change_detection.py` line 177 (`change_degradation`)
- `change_detection/change_detection.py` lines 340–341 (`change_deforestation_afforestation`)
- `change_detection/change_detection.py` lines 417–418 (`change_cropping_intensity`)

**Description:**
The "now" window is built with `l1_asset_remapped[3:]` instead of `l1_asset_remapped[-3:]`.
Per the spec, `now` must always be the modal LULC of the last 3 years `(end_year-2, end_year-1, end_year)`.
With `[3:]`, when N > 6 the now-window silently includes more than 3 years, causing the
modal computation to pull in intermediate years that should not contribute.

**Hypothesis:** Only manifests when `end_year - start_year != 5` (i.e., N != 6). For a
6-year range the two slices are identical. For 7+ years `[3:]` is wrong.

**Test to write:**
- Build a stack of 8 dummy LULC arrays (years 0–7).
- Set years 3–4 to class 1 (built-up) and years 5–7 to class 6 (forest).
- Correct `now` modal = 6. Buggy `now` modal = 1 (mode of 5-element slice dominated by class 1).
- Assert `now_window(stack) == 6` for every pixel.

---

## BUG-2 — Anomaly-count threshold hard-capped at 4 in deforestation smoothing

**File:** `change_detection/change_detection.py` lines 313–314 and 318–319

**Description:**
Pass B of the deforestation/afforestation smoothing fires only when
`zero_image.eq(3).Or(zero_image.eq(4))`, i.e., anomaly count ∈ {3, 4}.
With a year range wider than 6 years, the count can exceed 4, in which case
no correction fires at all for those pixels — potentially leaving anomalous
middle-year values uncorrected.

**Hypothesis:** For date ranges producing N > 6 assets, pixels that accumulate anomaly
count ≥ 5 are never corrected, so the smoothing silently does nothing for the most
anomalous pixels.

**Test to write:**
- Build a 9-year dummy stack where the same anomaly condition fires at every interior year
  for a target pixel (count = 7).
- Run the smoothing.
- Assert the middle year IS corrected (if threshold should be `≥ 3`) OR assert it is NOT
  corrected (if the hard cap is intentional), after confirming with the team which is expected.

---

## BUG-3 — Hardcoded `i != 2` skip in temporal correction Phase 3

**File:** `lulc/utils/temporal_correction.py` line 328

**Description:**
Inside `process_conditions`, when `i == 2` most correction conditions (cond1–cond7,
cond9–cond11) are skipped — only cond8 (BU-tree-BU with a 5-year context check) is
applied. There is no comment explaining why the third interior year is special.

**Hypothesis A (benign):** This was a deliberate choice when the pipeline always ran on
exactly 4 years (2017–2020), making `i == 2` the last interior year where neighbor
context was limited. It became incorrect once the pipeline started accepting variable-
length year ranges.

**Hypothesis B (intentional):** The third year has already been corrected by a prior pass
and re-applying would over-correct. Needs clarification from the original author.

**Test to write:**
- Build a 5-year dummy stack where the anomaly condition at `i == 2` would fire (e.g.,
  year 1=12, year 2=6, year 3=12 — shrubs-green-shrubs at position 2).
- Run `process_conditions` with count == 1 and `i == 2`.
- Assert whether `middle` is or is not corrected to 12, then record the expected behavior.

---

## BUG-4 — Purpose of Pass B in `change_deforestation_afforestation` is unclear

**File:** `change_detection/change_detection.py` lines 302–325

**Description:**
Pass A counts anomalies across 11 conditions using raw LULC classes. None of those
conditions reference raw class `3` (Water K+R) as a standalone class — it appears only
as part of the water group `{2,3,4}` in one condition (cond2 of Pass A).

Pass B then applies corrections that are entirely specific to raw class `3`:
- `cond1`: before==3, middle!=3, after==3 → set middle to 3
  ("water was on both sides but middle was something else → restore water")
- `cond2`: before!=3, middle==3, after!=3 → set middle to before
  ("water appeared only in middle → revert to what came before")

Both conditions fire only when the anomaly count from Pass A is exactly 3 or 4.

**What the code actually does:** Pass B smooths raw Water K+R (class 3) pixels based on
an anomaly count that was built from patterns across many other classes. The semantic link
between the broad anomaly count and the narrow class-3 correction is not explained anywhere
in the code.

**What is NOT known:** Whether this is intentional (water bodies in a deforestation area
need their own smoothing pass before the forest remap), misplaced code (belongs in temporal
correction, not here), or the result of an unintended copy of the wrong class number.

**No hypothesis is claimed.** The original claim in this file that this was "forest
smoothing gone wrong" had no code-level evidence and has been retracted.

**Question to resolve with the author before writing a test:**
Why does the deforestation function apply a class-3 (Water K+R) correction in Pass B?
Is this intentional, and if so what is the expected output difference when Pass B fires
vs. when it does not?

**Test to write (after clarification):**
- Build a 6-year stack with a pixel sequence `[3, 3, 8, 3, 3, 3]` (water K+R on both
  sides, cropland in the middle). This will accumulate anomaly count via Pass A cond2
  (water-green-water). Verify whether Pass B fires and what it produces.
- Build a counterpart `[6, 6, 8, 6, 6, 6]` (forest on both sides, cropland middle).
  Pass A cond6 (tree-farm-tree) fires. Verify Pass B does NOT fire (since class 6 is
  not checked in Pass B), and document whether that is the correct behaviour.

---

## BUG-5 — `built_up` applies `multiply` before `add`, risking overlap when transitions co-occur

**File:** `change_detection/change_detection.py` lines 144–157

**Description:**
Each transition value is encoded by multiplying a binary mask by its code integer, then
all masks are added together. If a pixel simultaneously satisfies two transition masks
(e.g., two conditions are both 1 for the same pixel), the codes will be summed, producing
an invalid output value.

**Hypothesis:** In theory only one transition code should fire per pixel (because `then`
and `now` each hold a single class per pixel). But if the remap table produces class 0
for an unmapped source pixel, the `eq` comparisons against classes 1–4 all return 0, so
no transition fires — this is correct. However, if `then == 0` (background), then
`then.eq(1).And(now.eq(1))` = 0, `then.eq(2).And(now.eq(1))` = 0, etc., so background
pixels output 0. This path seems safe. Needs a test to confirm no pixel can produce an
out-of-range output.

**Test to write:**
- Run each sub-pipeline on a dummy stack covering all remapped class combinations.
- Assert `output.max() <= max_valid_code` for each pipeline.
- Assert no pixel takes a value that is not in the defined valid-code set.
