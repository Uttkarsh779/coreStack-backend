Implementation Plan: Pipeline Correctness Unit Tests
Context & Identified Bug
The change detection pipeline has a structural correctness issue. Given start_year = i and end_year = j:

Spec: then = modal LULC of years (i, i+1, i+2); now = modal LULC of years (j-2, j-1, j)
Bug: now = ee.ImageCollection(l1_asset_remapped[3:]).mode() — uses all years from index 3 onwards, not the last 3. Correct slice is l1_asset_remapped[-3:].
This only happens to be correct when end_year - start_year == 5 (exactly 6 assets). Any other range silently produces wrong output.

The same [:3] / [3:] pattern appears in all five change sub-functions: built_up, change_degradation, change_deforestation_afforestation, and change_cropping_intensity.

Phase 0 — Pipeline Natural Language Specifications
Write a PIPELINE_SPECS.md document (one section per pipeline) that answers: what are the inputs, what computation is performed, what are the outputs, and what invariants must hold. This document becomes the source of truth for test assertions.

Pipelines to specify:

Pipeline	File	Key spec to nail down
Change Detection (all 5)	change_detection/change_detection.py	Modal window definition, class remapping tables, transition encoding
Deforestation/Afforestation temporal smoothing	same	11-condition correction logic before modal computation
Temporal Correction	lulc/utils/temporal_correction.py	Phase 1 background fill, Phase 2 11-condition smoothing
LULC v3 clip	lulc/lulc_v3.py	Year-by-year clip, output asset naming
Cropping Frequency	lulc/cropping_frequency.py	Season counts, output class mapping
Vector pipelines	change_detection_vector.py, lulc_vector.py	Raster-to-vector rules, attribute schema
Phase 1 — Extract Pure Computation Logic
The GEE API calls make the existing functions untestable in isolation. Refactor each computation function into two layers:

Layer 1 — Pure numpy/array function (no GEE dependency, fully unit-testable):


# computing/change_detection/core.py
def compute_modal_lulc(arrays: list[np.ndarray]) -> np.ndarray:
    """Returns pixel-wise mode across a list of 2D integer arrays."""
    ...

def remap_for_urbanization(arr: np.ndarray) -> np.ndarray:
    """Applies urbanization class remap: {1→1, 2-4→2, 6,8-11→3, 7,12→4}."""
    ...

def compute_built_up_transitions(then: np.ndarray, now: np.ndarray) -> np.ndarray:
    """Returns encoded transition raster per the urbanization change matrix."""
    ...
Layer 2 — GEE adapter (thin wrapper that converts ee.Image → numpy → pure fn → ee.Image):


def built_up(roi_boundary, l1_asset):
    ...
    then_arr = ee_to_numpy(ee.ImageCollection(l1_asset_remapped[:3]).mode())
    now_arr  = ee_to_numpy(ee.ImageCollection(l1_asset_remapped[-3:]).mode())  # fix
    result_arr = compute_built_up_transitions(then_arr, now_arr)
    return numpy_to_ee(result_arr, lulc_projection)
Do this for all five change detection sub-functions, temporal correction, and cropping frequency.

Phase 2 — Dummy LULC Test Data
Create computing/tests/fixtures/dummy_lulc.py. Design small (8×8) integer arrays that exercise known transitions.

Design rules for dummy data:

Modal correctness fixture — a 3-year stack where the mode is unambiguous:


Year 0: [[6, 6], [8, 8]]
Year 1: [[6, 1], [8, 1]]  
Year 2: [[6, 6], [1, 8]]
Mode:   [[6, 6], [8, 8]]  ← expected
Change transition fixture — design then_modal and now_modal so every transition type appears at least once:

For Urbanization: include pixels that are Tree→Built-up, Water→Built-up, Barren→Built-up, and Built-up→Built-up
For Deforestation: include Forest→Built-up, Forest→Farmland, Forest→Barren, Forest→Shrub-Scrub
For Crop Intensity: include SI→DO, DO→TR, TR→SI etc.
Edge cases:

All pixels same class both periods (no change)
Full replacement (every pixel changes class)
8-year range (tests the [:3] vs [-3:] bug directly — the "now" window must be the last 3, not years 3-8)
Expected outputs are computed by hand and hardcoded as assertions.

Phase 3 — Unit Tests
Create computing/tests/test_change_detection_core.py (and one file per pipeline):


computing/tests/
├── fixtures/
│   └── dummy_lulc.py
├── test_change_detection_core.py
├── test_temporal_correction.py
├── test_cropping_frequency.py
└── test_lulc_v3_core.py
Test structure per pipeline:


# test_change_detection_core.py

class TestModalComputation:
    def test_mode_3_years_unambiguous(self): ...
    def test_mode_uses_last_3_years_for_now_window(self):
        # 8-year stack; verify now = modal of years [5,6,7], not [3,4,5,6,7]
        ...
    def test_mode_ties_handled_deterministically(self): ...

class TestUrbanizationRemap:
    def test_classes_1_to_4_remapped_correctly(self): ...
    def test_class_5_maps_to_zero(self): ...  # class 5 not in remap source

class TestBuiltUpTransitions:
    def test_water_to_builtup_encodes_as_2(self): ...
    def test_tree_to_builtup_encodes_as_3(self): ...
    def test_no_change_encodes_as_1(self): ...
    def test_output_has_no_transition_outside_valid_range(self): ...

class TestDeforestationAfforestationSmoothing:
    def test_shrub_green_shrub_corrected_to_shrub(self): ...  # cond1
    def test_water_green_water_corrected_to_water(self): ...  # cond2
    def test_all_11_conditions(self): ...

class TestCropIntensityTransitions:
    def test_double_to_single_encodes_as_1(self): ...
    def test_single_to_triple_encodes_as_5(self): ...
    def test_no_transition_outside_crop_pixels_is_zero(self): ...
Test for the specific bug (the most important test):


def test_now_window_uses_last_3_years_not_all_after_3():
    """
    With 8 years of data (i=2016, j=2023):
      then = modal(2016, 2017, 2018)
      now  = modal(2021, 2022, 2023)  ← NOT modal(2019..2023)
    This test fails with the current [3:] slice and passes after fixing to [-3:].
    """
    years_8 = [make_year(y) for y in range(8)]
    # years 3..4 contain class 1 (built-up), years 5..7 contain class 6 (forest)
    # correct now-modal = 6; buggy now-modal = 1 (mode of 5 years dominated by class 1)
    then, now = compute_then_now_windows(years_8)
    assert (now == 6).all()
Phase 4 — Execution Order & Prioritization
Step	Task	Effort
1	Write PIPELINE_SPECS.md for change detection (all 5 sub-functions)	~2h
2	Extract computing/change_detection/core.py pure functions	~3h
3	Write test_change_detection_core.py with dummy fixtures	~3h
4	Fix the [3:] → [-3:] bug once tests confirm it	~15 min
5	Write PIPELINE_SPECS.md sections for temporal correction	~1h
6	Extract & test temporal_correction pure functions	~2h
7	Write PIPELINE_SPECS.md sections for cropping frequency	~1h
8	Extract & test cropping_frequency pure functions	~2h
9	Repeat for LULC v3 clip, vector pipelines	~4h
Start with the change detection pipeline (step 1-4) because it has the confirmed bug and the most complex logic. The spec doc must be written and agreed on before tests are written, so that the tests encode the spec rather than the current (potentially buggy) behavior.

Key Constraints
Pure functions must not import ee — use numpy only. GEE adapters import both.
Test files must be runnable with pytest locally with no GEE credentials.
Dummy LULC arrays must use the real class integers (1–12) as documented in the codebase, not abstract values.
The spec document should explicitly state what happens at the boundary: when end_year - start_year < 2 (too few years to form a 3-year "then" window), the pipeline should raise a ValueError, not silently produce a modal from 1 or 2 years.