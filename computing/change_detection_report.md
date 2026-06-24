# Change Detection Pipeline — Correctness Review

**Scope:** Pipeline correctness review for `computing/change_detection/`  
**Audience:** CoRE Stack developers and research team  
**Evidence:** [`PIPELINE_SPECS.md`](PIPELINE_SPECS.md) · [`POTENTIAL_BUGS.md`](POTENTIAL_BUGS.md) · [`change_detection/core.py`](change_detection/core.py) · [`unit_tests/`](unit_tests/)

---

## Purpose

Verify that the change detection pipeline computes transitions correctly across all five sub-pipelines (Urbanization, Degradation, Deforestation, Afforestation, Crop Intensity), and identify deviations from the specification.

---

## Inputs

| Parameter | Description |
|---|---|
| `l1_asset` | Ordered list of ≥ 6 annual LULC rasters (index 0 = start year *i*, index *N−1* = end year *j*) |
| `start_year`, `end_year` | Integer year bounds |
| `roi_boundary` | Region of interest geometry |

---

## Pipeline Flow

```
l1_asset  →  Remap classes  →  mode(first 3 yrs) = then
                             →  mode(last 3 yrs)  = now
                             →  (then, now) → transition code raster
                             →  generate_vector → area per MWS polygon (ha)
```

Deforestation and Afforestation include a pre-smoothing pass (Pass A: anomaly count; Pass B: class-3 correction) before the modal computation.

Full step-by-step specification: [`PIPELINE_SPECS.md`](PIPELINE_SPECS.md)

---

## Outputs

- **Raster:** Single-band integer image, one transition code per pixel (0 = no transition).
- **Vector:** `ee.FeatureCollection` — one record per MWS polygon, with area attributes in hectares (e.g. `bu_bu`, `w_bu`, `total_urb`).

Full attribute schema: [`PIPELINE_SPECS.md §5`](PIPELINE_SPECS.md)

---

## Validation Approach

Pure-numpy equivalents of all five sub-pipelines were extracted into [`change_detection/core.py`](change_detection/core.py), decoupling algorithmic correctness from GEE infrastructure. Tests run offline with no credentials required.

**149 unit tests** across 10 test classes in [`unit_tests/test_change_detection_core.py`](unit_tests/test_change_detection_core.py) — all passing.

### Dummy Test Cases

Single-pixel (1×1) arrays using real LULC class integers. Key fixture categories:

| Fixture group | What it validates |
|---|---|
| Modal computation | Shape, dtype, tie-breaking, per-pixel independence |
| `BUG1_STACK_8_YEARS` — `[1,1,1,1,1,1,6,6]` | **now-window regression**: `[-3:]` = mode(1,6,6) = 6 ✓; buggy `[3:]` = mode(1,1,1,6,6) = 1 ✗ |
| Remap fixtures | All 11 raw classes × 4 remap tables; unmapped class 5 → 0 |
| Transition fixtures | All valid codes for each sub-pipeline; mutual exclusivity (defo/affo) |
| Anomaly count fixtures | All 11 conditions independently; accumulation across years |
| Smoothing fixtures | cond1/cond2 at threshold boundary; immutability of input |

Fixture definitions: [`unit_tests/fixtures/dummy_lulc.py`](unit_tests/fixtures/dummy_lulc.py)

### What Was Validated

- Correctness of remap tables for all five sub-pipelines
- Modal window logic and the confirmed BUG-1 regression
- All transition code assignments and their valid ranges
- All 11 anomaly conditions (Pass A) individually and in accumulation
- Pass B smoothing behaviour at the threshold boundary
- Pipeline output immutability (no input mutation)

### What Was Not Validated

- **GEE layer:** `change_detection.py` is not directly tested; `core.py` mirrors its logic but is not wired in. The production file still contains BUG-1.
- **Multi-pixel spatial correctness:** All fixtures are single-pixel (1×1). Spatial edge effects at polygon boundaries are not covered.
- **Performance / GEE quotas:** Out of scope for correctness review.
- **`change_detection_vector.py`:** No unit tests exist for the vector reduction logic.

### Current Limitations

- `core.py` and `change_detection.py` are parallel implementations, not integrated. Tests prove the algorithm; they do not run against the production GEE code.
- BUG-2, BUG-3, BUG-4 remain unresolved pending team clarification. Tests for these are blocked until expected behaviour is confirmed.

---

## Issues Identified

| ID | Status | Summary | Reference |
|---|---|---|---|
| BUG-1 | **Confirmed** | `now` window uses `[3:]` instead of `[-3:]`; silent for N=6, wrong for N>6 | Issue #1 |
| BUG-2 | Open | Pass B anomaly threshold `{3,4}` does not fire for counts > 4; may leave high-anomaly pixels uncorrected on wider date ranges | Issue #2 |
| BUG-3 | Open | `i != 2` skip in `temporal_correction.py` — intent unclear, no documentation | Issue #3 |
| BUG-4 | Open | Pass B targets raw class 3 only; semantic link to Pass A anomaly count is undocumented | — |

Detailed descriptions and reproduction steps: [`POTENTIAL_BUGS.md`](POTENTIAL_BUGS.md)

---

## Conclusion

The core algorithmic logic of the change detection pipeline is correctly specified and validated through offline unit tests. **BUG-1 is confirmed and ready to fix** — a one-line change in four locations. The remaining three issues require team input to determine whether they represent bugs or intentional design decisions before fixes or tests can be written.

**Recommended next steps:**
1. Apply BUG-1 fix to `change_detection.py` (see Issue #1).
2. Wire `core.py` into `change_detection.py` as a GEE adapter layer so future tests run against the production entry points.
3. Resolve BUG-2 / BUG-3 / BUG-4 with the original author, then close or document them.
4. Add unit tests for `change_detection_vector.py`.
