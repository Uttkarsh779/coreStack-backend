"""
Dummy LULC arrays for unit tests.

All arrays use real LULC class integers {0,1,2,3,4,6,7,8,9,10,11,12}.
Shape is always (1, 1) unless the test explicitly needs spatial variation,
so expected outputs can be hand-verified by reading the array values directly.

Factory functions return plain numpy arrays; nothing here touches GEE.
"""

import numpy as np


def px(value: int) -> np.ndarray:
    """Single pixel array — the simplest possible test unit."""
    return np.array([[value]], dtype=np.int32)


def make_stack(values: list) -> list:
    """
    Turn a list of scalar class values into a list of (1,1) arrays.
    Represents one pixel observed across N years.
    e.g. make_stack([6, 6, 12, 6, 6, 6]) → 6-year stack, pixel=shrub in year 2.
    """
    return [px(v) for v in values]


def make_uniform_stack(value: int, n_years: int) -> list:
    """Stack where the pixel holds the same class for all N years."""
    return [px(value)] * n_years


# ---------------------------------------------------------------------------
# Modal computation fixtures
# ---------------------------------------------------------------------------

# Unambiguous majority: two 6s vs one 12 → mode = 6
MODAL_CLEAR_MAJORITY = make_stack([6, 6, 12])          # expected mode: 6

# All same
MODAL_ALL_SAME = make_stack([8, 8, 8])                 # expected mode: 8

# Tie broken by lowest value (scipy behaviour): [6, 12] tie → 6
MODAL_TIE = make_stack([6, 12, 6])                     # expected mode: 6 (2 vs 1)

# Three distinct values — the one appearing twice wins
MODAL_ONE_DOMINANT = make_stack([1, 6, 1])             # expected mode: 1


# ---------------------------------------------------------------------------
# BUG-1: now-window slice fixtures
# ---------------------------------------------------------------------------

# 8-year stack.
# Years 0-4: class 1 (built-up). Years 5-7: class 6 (forest).
# Correct  now = modal(years 5,6,7) = 6
# Buggy    now = modal(years 3,4,5,6,7) = 1  (3 ones vs 2 sixes)
BUG1_STACK_8_YEARS = make_stack([1, 1, 1, 1, 1, 1, 6, 6])
BUG1_EXPECTED_THEN = 1   # modal of years 0,1,2 → 1
BUG1_EXPECTED_NOW  = 6   # modal of years 5,6,7 → 6

# 6-year stack — identical result from [:3] and [-3:] (boundary case that hides the bug)
BUG1_STACK_6_YEARS = make_stack([1, 1, 1, 1, 6, 6])
BUG1_6YR_EXPECTED_THEN = 1
BUG1_6YR_EXPECTED_NOW  = 6


# ---------------------------------------------------------------------------
# Remap fixtures — one pixel per source class
# ---------------------------------------------------------------------------

ALL_RAW_CLASSES = [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]
UNMAPPED_CLASS  = 5   # class 5 does not appear in any remap source list → 0

URBANIZATION_EXPECTED = {1: 1, 2: 2, 3: 2, 4: 2, 6: 3, 7: 4,
                         8: 3, 9: 3, 10: 3, 11: 3, 12: 4, 5: 0}

DEGRADATION_EXPECTED  = {1: 1, 2: 2, 3: 2, 4: 2, 6: 4, 7: 5,
                         8: 3, 9: 3, 10: 3, 11: 3, 12: 6, 5: 0}

DEFORESTATION_EXPECTED = {1: 1, 2: 2, 3: 2, 4: 2, 6: 3, 7: 5,
                          8: 4, 9: 4, 10: 4, 11: 4, 12: 6, 5: 0}

CROP_INTENSITY_EXPECTED = {1: 1, 2: 2, 3: 2, 4: 2, 6: 3, 7: 4,
                           8: 5, 9: 5, 10: 6, 11: 7, 12: 8, 5: 0}


# ---------------------------------------------------------------------------
# Urbanization transition fixtures (inputs are already-remapped classes)
# Remapped: 1=BU, 2=Water, 3=Tree/Crop, 4=Barren/Scrub
# ---------------------------------------------------------------------------

URBANIZATION_TRANSITIONS = [
    # (then_class, now_class, expected_output_code)
    (1, 1, 1),   # BU → BU
    (2, 1, 2),   # Water → BU
    (3, 1, 3),   # Tree/Crop → BU
    (4, 1, 4),   # Barren/Scrub → BU
    (1, 2, 0),   # BU → Water  (not urbanization, no code)
    (3, 2, 0),   # Tree → Water (no code)
    (0, 0, 0),   # Background → Background
    (0, 1, 0),   # Background → BU (unmapped source → no code)
]


# ---------------------------------------------------------------------------
# Degradation transition fixtures (remapped: 1=BU, 2=Water, 3=Crop, 4=Forest,
#                                            5=Barren, 6=Scrub)
# ---------------------------------------------------------------------------

DEGRADATION_TRANSITIONS = [
    (4, 4, 1),   # forest → forest
    (4, 1, 2),   # forest → BU
    (4, 5, 3),   # forest → barren
    (4, 6, 4),   # forest → scrub
    (3, 1, 0),   # cropland → BU  (not degradation)
    (4, 2, 0),   # forest → water (no code defined)
    (0, 0, 0),
]


# ---------------------------------------------------------------------------
# Deforestation transition fixtures (remapped: 1=BU, 2=Water, 3=Forest,
#                                              4=Farm, 5=Barren, 6=Scrub)
# ---------------------------------------------------------------------------

DEFORESTATION_TRANSITIONS = [
    (3, 3, 1),   # forest → forest
    (3, 1, 2),   # forest → BU
    (3, 4, 3),   # forest → farmland
    (3, 5, 4),   # forest → barren
    (3, 6, 5),   # forest → scrub
    (1, 3, 0),   # BU → forest (afforestation, not deforestation)
    (4, 3, 0),   # farm → forest (afforestation)
    (0, 0, 0),
]


# ---------------------------------------------------------------------------
# Afforestation transition fixtures (same remapping as deforestation)
# ---------------------------------------------------------------------------

AFFORESTATION_TRANSITIONS = [
    (3, 3, 1),   # forest → forest
    (1, 3, 2),   # BU → forest
    (4, 3, 3),   # farmland → forest
    (5, 3, 4),   # barren → forest
    (6, 3, 5),   # scrub → forest
    (3, 1, 0),   # forest → BU (deforestation, not afforestation)
    (3, 4, 0),   # forest → farm
    (0, 0, 0),
]


# ---------------------------------------------------------------------------
# Crop intensity transition fixtures
# (remapped: 1=BU, 2=Water, 3=Tree, 4=Barren, 5=SI, 6=DO, 7=TR, 8=Shrub)
# ---------------------------------------------------------------------------

CROP_INTENSITY_TRANSITIONS = [
    (6, 5, 1),   # DO → SI
    (7, 5, 2),   # TR → SI
    (7, 6, 3),   # TR → DO
    (5, 6, 4),   # SI → DO
    (5, 7, 5),   # SI → TR
    (6, 7, 6),   # DO → TR
    (5, 5, 7),   # SI → SI
    (6, 6, 8),   # DO → DO
    (7, 7, 9),   # TR → TR
    (1, 1, 0),   # BU → BU  (not a crop pixel)
    (3, 5, 0),   # Tree → SI (tree is not a crop class in this remap)
    (0, 0, 0),
]


# ---------------------------------------------------------------------------
# Anomaly count fixtures — one scenario per condition
# Each entry is a 3-year stack (before, middle, after) that triggers exactly
# one condition. The expected count at the single pixel is 1.
# ---------------------------------------------------------------------------

ANOMALY_COUNT_SCENARIOS = {
    "c1_shrubs_green_shrubs":     make_stack([12, 6, 12]),
    "c1_shrubs_crop_shrubs":      make_stack([12, 8, 12]),
    "c2_water_green_water":       make_stack([2, 6, 3]),
    "c2_water_crop_water":        make_stack([4, 10, 2]),
    "c3_tree_shrub_tree":         make_stack([6, 12, 6]),
    "c4_crop_shrub_crop":         make_stack([8, 12, 10]),
    "c5_crop_barren_crop":        make_stack([9, 7, 11]),
    "c6_tree_farm_tree":          make_stack([6, 8, 6]),
    "c7_farm_tree_farm":          make_stack([10, 6, 11]),
    "c8_BU_tree_BU":              make_stack([1, 6, 1]),
    "c9_tree_BU_tree":            make_stack([6, 1, 6]),
    "c10_BU_farm_BU":             make_stack([1, 8, 1]),
    "c11_barren_green_barren":    make_stack([7, 6, 7]),
}

# A 5-year stack where 2 conditions fire across different interior triplets.
# i=1: before=6, middle=12, after=6  → c3 (tree-shrub-tree) fires  → count += 1
# i=2: before=12, middle=6, after=8  → no condition matches
# i=3: before=6,  middle=8, after=6  → c6 (tree-farm-tree) fires   → count += 1
# total count = 2
ANOMALY_ACCUMULATE_STACK   = make_stack([6, 12, 6, 8, 6])
ANOMALY_ACCUMULATE_EXPECTED = 2

# Stack that generates NO anomalies (straight forest)
ANOMALY_NONE_STACK    = make_stack([6, 6, 6, 6, 6, 6])
ANOMALY_NONE_EXPECTED = 0


# ---------------------------------------------------------------------------
# Water class 3 smoothing fixtures (Pass B)
# ---------------------------------------------------------------------------

# cond1: water on both sides, non-water middle, count=3 → restore middle to 3
SMOOTH_COND1_STACK    = make_stack([3, 8, 3, 3, 3, 3])   # triplet(0,1,2) fires c2 x3
SMOOTH_COND1_YEAR_IDX = 1          # middle year to inspect after smoothing
SMOOTH_COND1_EXPECTED = 3          # middle restored to water

# cond2: water only in middle, not on sides, count=3 → revert middle to before
SMOOTH_COND2_STACK    = make_stack([8, 3, 8, 8, 8, 8])
SMOOTH_COND2_YEAR_IDX = 1
SMOOTH_COND2_EXPECTED = 8          # middle reverted to before (8)

# count=2 → no correction fires (threshold is exactly 3 or 4)
SMOOTH_BELOW_THRESHOLD_STACK    = make_stack([3, 8, 3, 8, 8, 8])
SMOOTH_BELOW_THRESHOLD_YEAR_IDX = 1
SMOOTH_BELOW_THRESHOLD_EXPECTED = 8   # no change; middle stays 8
