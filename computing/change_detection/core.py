"""
Pure numpy implementations of the change detection computation logic.

No GEE dependency. Every function takes and returns numpy arrays so they
can be called from unit tests without GEE credentials.

The GEE-coupled functions in change_detection.py are the authoritative
production entry points; these functions mirror their logic exactly and
are kept in sync with any fixes made there.
"""

import copy
import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# LULC class remapping tables (raw class → sub-pipeline class)
# ---------------------------------------------------------------------------

REMAP_URBANIZATION = {
    "from_classes": [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
    "to_classes":   [1, 2, 2, 2, 3, 4, 3, 3,  3,  3,  4],
}

REMAP_DEGRADATION = {
    "from_classes": [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
    "to_classes":   [1, 2, 2, 2, 4, 5, 3, 3,  3,  3,  6],
}

# used by both deforestation and afforestation (applied after smoothing)
REMAP_DEFORESTATION = {
    "from_classes": [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
    "to_classes":   [1, 2, 2, 2, 3, 5, 4, 4,  4,  4,  6],
}

REMAP_CROP_INTENSITY = {
    "from_classes": [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12],
    "to_classes":   [1, 2, 2, 2, 3, 4, 5, 5,  6,  7,  8],
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def remap_classes(
    arr: np.ndarray,
    from_classes: list,
    to_classes: list,
    default: int = 0,
) -> np.ndarray:
    """
    Remap integer class values in `arr` according to from→to pairs.
    Any value not listed in from_classes becomes `default`.
    """
    result = np.full_like(arr, default, dtype=np.int32)
    for src, dst in zip(from_classes, to_classes):
        result[arr == src] = dst
    return result


def compute_modal(arrays: list) -> np.ndarray:
    """
    Pixel-wise statistical mode across a list of 2D integer arrays.
    All arrays must have the same shape.
    Ties are broken by the lowest value (scipy default).
    """
    stacked = np.stack(arrays, axis=0)          # (N, H, W)
    mode_result = stats.mode(stacked, axis=0, keepdims=False)
    return mode_result.mode.astype(np.int32)


def get_then_now_windows(arrays: list) -> tuple:
    """
    Split a chronological year stack into then/now modal windows.

    then = modal LULC of years (start, start+1, start+2)  → arrays[:3]
    now  = modal LULC of years (end-2, end-1, end)        → arrays[-3:]

    Requires at least 6 years. Raises ValueError otherwise.
    """
    if len(arrays) < 6:
        raise ValueError(
            f"At least 6 years required to form then/now windows; got {len(arrays)}."
        )
    then = compute_modal(arrays[:3])
    now = compute_modal(arrays[-3:])
    return then, now


# ---------------------------------------------------------------------------
# Transition encoders
# Each function receives already-remapped then/now arrays and returns an
# output array whose values are the transition codes defined in the spec.
# ---------------------------------------------------------------------------

def compute_built_up_transitions(then: np.ndarray, now: np.ndarray) -> np.ndarray:
    """
    Urbanization transition codes.
    Input classes (after REMAP_URBANIZATION): 1=BU, 2=Water, 3=Tree/Crop, 4=Barren/Scrub
    Only pixels where now==1 (built-up) produce non-zero output.

    Code  Transition
    1     built-up → built-up
    2     water → built-up
    3     tree/crop → built-up
    4     barren/scrub → built-up
    """
    out = np.zeros_like(then, dtype=np.int32)
    out = np.where((then == 1) & (now == 1), 1, out)
    out = np.where((then == 2) & (now == 1), 2, out)
    out = np.where((then == 3) & (now == 1), 3, out)
    out = np.where((then == 4) & (now == 1), 4, out)
    return out


def compute_degradation_transitions(then: np.ndarray, now: np.ndarray) -> np.ndarray:
    """
    Degradation transition codes.
    Input classes (after REMAP_DEGRADATION): 1=BU, 2=Water, 3=Crop, 4=Forest, 5=Barren, 6=Scrub
    Only pixels where then==4 (forest) produce non-zero output.

    Code  Transition
    1     forest → forest
    2     forest → built-up
    3     forest → barren
    4     forest → scrub
    """
    out = np.zeros_like(then, dtype=np.int32)
    out = np.where((then == 4) & (now == 4), 1, out)
    out = np.where((then == 4) & (now == 1), 2, out)
    out = np.where((then == 4) & (now == 5), 3, out)
    out = np.where((then == 4) & (now == 6), 4, out)
    return out


def compute_deforestation_transitions(then: np.ndarray, now: np.ndarray) -> np.ndarray:
    """
    Deforestation transition codes.
    Input classes (after REMAP_DEFORESTATION): 1=BU, 2=Water, 3=Forest, 4=Farm, 5=Barren, 6=Scrub
    Only pixels where then==3 (forest) produce non-zero output.

    Code  Transition
    1     forest → forest
    2     forest → built-up
    3     forest → farmland
    4     forest → barren
    5     forest → scrub
    """
    out = np.zeros_like(then, dtype=np.int32)
    out = np.where((then == 3) & (now == 3), 1, out)
    out = np.where((then == 3) & (now == 1), 2, out)
    out = np.where((then == 3) & (now == 4), 3, out)
    out = np.where((then == 3) & (now == 5), 4, out)
    out = np.where((then == 3) & (now == 6), 5, out)
    return out


def compute_afforestation_transitions(then: np.ndarray, now: np.ndarray) -> np.ndarray:
    """
    Afforestation transition codes.
    Input classes (after REMAP_DEFORESTATION): 1=BU, 2=Water, 3=Forest, 4=Farm, 5=Barren, 6=Scrub
    Only pixels where now==3 (forest) produce non-zero output.

    Code  Transition
    1     forest → forest
    2     built-up → forest
    3     farmland → forest
    4     barren → forest
    5     scrub → forest
    """
    out = np.zeros_like(then, dtype=np.int32)
    out = np.where((then == 3) & (now == 3), 1, out)
    out = np.where((then == 1) & (now == 3), 2, out)
    out = np.where((then == 4) & (now == 3), 3, out)
    out = np.where((then == 5) & (now == 3), 4, out)
    out = np.where((then == 6) & (now == 3), 5, out)
    return out


def compute_crop_intensity_transitions(then: np.ndarray, now: np.ndarray) -> np.ndarray:
    """
    Crop intensity transition codes.
    Input classes (after REMAP_CROP_INTENSITY):
      1=BU, 2=Water, 3=Tree, 4=Barren, 5=SI, 6=DO, 7=TR, 8=Shrub

    Code  Transition
    1     DO → SI
    2     TR → SI
    3     TR → DO
    4     SI → DO
    5     SI → TR
    6     DO → TR
    7     SI → SI
    8     DO → DO
    9     TR → TR
    """
    out = np.zeros_like(then, dtype=np.int32)
    out = np.where((then == 6) & (now == 5), 1, out)
    out = np.where((then == 7) & (now == 5), 2, out)
    out = np.where((then == 7) & (now == 6), 3, out)
    out = np.where((then == 5) & (now == 6), 4, out)
    out = np.where((then == 5) & (now == 7), 5, out)
    out = np.where((then == 6) & (now == 7), 6, out)
    out = np.where((then == 5) & (now == 5), 7, out)
    out = np.where((then == 6) & (now == 6), 8, out)
    out = np.where((then == 7) & (now == 7), 9, out)
    return out


# ---------------------------------------------------------------------------
# Deforestation / afforestation pre-processing smoothing
# ---------------------------------------------------------------------------

def count_deforestation_anomalies(arrays: list) -> np.ndarray:
    """
    Pass A: count anomaly (year, condition) firings at each pixel.

    Iterates over every interior year i (1 to N-2) and accumulates into a
    count array. The 11 conditions are the same as in temporal_correction.py.
    Returns a 2D array of non-negative integers.
    """
    count = np.zeros_like(arrays[0], dtype=np.int32)

    for i in range(1, len(arrays) - 1):
        before = arrays[i - 1]
        middle = arrays[i]
        after  = arrays[i + 1]

        c1  = (before == 12) & (after == 12) & np.isin(middle, [6, 8, 9, 10, 11])
        c2  = np.isin(before, [2, 3, 4]) & np.isin(after, [2, 3, 4]) & np.isin(middle, [6, 8, 9, 10, 11])
        c3  = (before == 6) & (after == 6) & (middle == 12)
        c4  = np.isin(before, [8, 9, 10, 11]) & np.isin(after, [8, 9, 10, 11]) & (middle == 12)
        c5  = np.isin(before, [8, 9, 10, 11]) & np.isin(after, [8, 9, 10, 11]) & (middle == 7)
        c6  = (before == 6) & (after == 6) & np.isin(middle, [8, 9, 10, 11])
        c7  = np.isin(before, [8, 9, 10, 11]) & np.isin(after, [8, 9, 10, 11]) & (middle == 6)
        c8  = (before == 1) & (after == 1) & (middle == 6)
        c9  = (before == 6) & (after == 6) & (middle == 1)
        c10 = (before == 1) & (after == 1) & np.isin(middle, [8, 9, 10, 11])
        c11 = (before == 7) & (after == 7) & np.isin(middle, [6, 8, 9, 10, 11])

        count += (c1 + c2 + c3 + c4 + c5 + c6 + c7 + c8 + c9 + c10 + c11).astype(np.int32)

    return count


def apply_water_class3_smoothing(arrays: list, anomaly_count: np.ndarray) -> list:
    """
    Pass B: correct raw Water K+R (class 3) pixels at positions where the
    anomaly count is exactly 3 or 4.

    Note: this smoothing targets raw class 3 specifically. See POTENTIAL_BUGS.md
    BUG-4 for the open question about whether class 3 here is intentional.

    Returns a new list (does not mutate the input).
    """
    result = copy.deepcopy(arrays)
    n = len(result)
    qualifies = (anomaly_count == 3) | (anomaly_count == 4)

    for i in range(1, n - 1):
        before = result[i - 1]
        middle = result[i]
        after  = result[i + 1]

        # water on both sides, non-water middle → restore to water
        cond1 = qualifies & (before == 3) & (middle != 3) & (after == 3)
        # water only in middle → revert to before
        cond2 = qualifies & (before != 3) & (middle == 3) & (after != 3)

        new_middle = np.where(cond1, 3, middle)
        new_middle = np.where(cond2, before, new_middle)
        result[i] = new_middle

    return result


# ---------------------------------------------------------------------------
# Full pipeline functions (remap + window + transitions)
# These mirror the complete logic of each GEE function end-to-end.
# ---------------------------------------------------------------------------

def pipeline_built_up(arrays: list) -> np.ndarray:
    remapped = [remap_classes(a, **REMAP_URBANIZATION) for a in arrays]
    then, now = get_then_now_windows(remapped)
    return compute_built_up_transitions(then, now)


def pipeline_degradation(arrays: list) -> np.ndarray:
    remapped = [remap_classes(a, **REMAP_DEGRADATION) for a in arrays]
    then, now = get_then_now_windows(remapped)
    return compute_degradation_transitions(then, now)


def pipeline_deforestation(arrays: list) -> np.ndarray:
    anomaly_count = count_deforestation_anomalies(arrays)
    smoothed = apply_water_class3_smoothing(arrays, anomaly_count)
    remapped = [remap_classes(a, **REMAP_DEFORESTATION) for a in smoothed]
    then, now = get_then_now_windows(remapped)
    return compute_deforestation_transitions(then, now)


def pipeline_afforestation(arrays: list) -> np.ndarray:
    anomaly_count = count_deforestation_anomalies(arrays)
    smoothed = apply_water_class3_smoothing(arrays, anomaly_count)
    remapped = [remap_classes(a, **REMAP_DEFORESTATION) for a in smoothed]
    then, now = get_then_now_windows(remapped)
    return compute_afforestation_transitions(then, now)


def pipeline_crop_intensity(arrays: list) -> np.ndarray:
    remapped = [remap_classes(a, **REMAP_CROP_INTENSITY) for a in arrays]
    then, now = get_then_now_windows(remapped)
    return compute_crop_intensity_transitions(then, now)
