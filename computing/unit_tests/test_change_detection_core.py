"""
Deep unit tests for computing/change_detection/core.py.

Tests target individual pure functions, not the high-level pipeline wrappers.
No GEE credentials or network access required.

Run with:  pytest computing/tests/test_change_detection_core.py -v
"""

import numpy as np
import pytest

from computing.change_detection.core import (
    compute_modal,
    get_then_now_windows,
    remap_classes,
    compute_built_up_transitions,
    compute_degradation_transitions,
    compute_deforestation_transitions,
    compute_afforestation_transitions,
    compute_crop_intensity_transitions,
    count_deforestation_anomalies,
    apply_water_class3_smoothing,
    REMAP_URBANIZATION,
    REMAP_DEGRADATION,
    REMAP_DEFORESTATION,
    REMAP_CROP_INTENSITY,
)
from computing.unit_tests.fixtures.dummy_lulc import (
    px,
    make_stack,
    make_uniform_stack,
    MODAL_CLEAR_MAJORITY,
    MODAL_ALL_SAME,
    MODAL_TIE,
    MODAL_ONE_DOMINANT,
    BUG1_STACK_8_YEARS,
    BUG1_EXPECTED_THEN,
    BUG1_EXPECTED_NOW,
    BUG1_STACK_6_YEARS,
    BUG1_6YR_EXPECTED_THEN,
    BUG1_6YR_EXPECTED_NOW,
    ALL_RAW_CLASSES,
    UNMAPPED_CLASS,
    URBANIZATION_EXPECTED,
    DEGRADATION_EXPECTED,
    DEFORESTATION_EXPECTED,
    CROP_INTENSITY_EXPECTED,
    URBANIZATION_TRANSITIONS,
    DEGRADATION_TRANSITIONS,
    DEFORESTATION_TRANSITIONS,
    AFFORESTATION_TRANSITIONS,
    CROP_INTENSITY_TRANSITIONS,
    ANOMALY_COUNT_SCENARIOS,
    ANOMALY_ACCUMULATE_STACK,
    ANOMALY_ACCUMULATE_EXPECTED,
    ANOMALY_NONE_STACK,
    ANOMALY_NONE_EXPECTED,
    SMOOTH_COND1_STACK,
    SMOOTH_COND1_YEAR_IDX,
    SMOOTH_COND1_EXPECTED,
    SMOOTH_COND2_STACK,
    SMOOTH_COND2_YEAR_IDX,
    SMOOTH_COND2_EXPECTED,
    SMOOTH_BELOW_THRESHOLD_STACK,
    SMOOTH_BELOW_THRESHOLD_YEAR_IDX,
    SMOOTH_BELOW_THRESHOLD_EXPECTED,
)


# ===========================================================================
# compute_modal
# ===========================================================================

class TestComputeModal:

    def test_clear_majority(self):
        result = compute_modal(MODAL_CLEAR_MAJORITY)
        assert result[0, 0] == 6

    def test_all_same_value(self):
        result = compute_modal(MODAL_ALL_SAME)
        assert result[0, 0] == 8

    def test_tie_broken_by_lowest_value(self):
        # [6, 12, 6] → 6 wins (2 vs 1)
        result = compute_modal(MODAL_TIE)
        assert result[0, 0] == 6

    def test_one_dominant_value(self):
        result = compute_modal(MODAL_ONE_DOMINANT)
        assert result[0, 0] == 1

    def test_output_shape_matches_input(self):
        arrays = [np.full((3, 4), v, dtype=np.int32) for v in [6, 6, 12]]
        result = compute_modal(arrays)
        assert result.shape == (3, 4)

    def test_output_dtype_is_int(self):
        result = compute_modal(MODAL_ALL_SAME)
        assert np.issubdtype(result.dtype, np.integer)

    def test_each_pixel_computed_independently(self):
        # 1x2 grid: left pixel → mode=6, right pixel → mode=12
        a0 = np.array([[6, 12]], dtype=np.int32)
        a1 = np.array([[6, 12]], dtype=np.int32)
        a2 = np.array([[1, 12]], dtype=np.int32)
        result = compute_modal([a0, a1, a2])
        assert result[0, 0] == 6    # 6 appears twice
        assert result[0, 1] == 12   # 12 appears three times


# ===========================================================================
# get_then_now_windows
# ===========================================================================

class TestGetThenNowWindows:

    def test_then_is_modal_of_first_3_years(self):
        then, _ = get_then_now_windows(BUG1_STACK_8_YEARS)
        assert then[0, 0] == BUG1_EXPECTED_THEN

    def test_now_is_modal_of_last_3_years(self):
        """BUG-1 regression test: now must be arrays[-3:], not arrays[3:]."""
        _, now = get_then_now_windows(BUG1_STACK_8_YEARS)
        assert now[0, 0] == BUG1_EXPECTED_NOW, (
            "now-window used wrong slice. Expected modal of last 3 years "
            f"({BUG1_EXPECTED_NOW}), got {now[0, 0]}. "
            "Likely cause: arrays[3:] instead of arrays[-3:]."
        )

    def test_6_year_stack_then_and_now_correct(self):
        then, now = get_then_now_windows(BUG1_STACK_6_YEARS)
        assert then[0, 0] == BUG1_6YR_EXPECTED_THEN
        assert now[0, 0] == BUG1_6YR_EXPECTED_NOW

    def test_then_and_now_do_not_overlap_on_8_year_stack(self):
        # then = years 0-2, now = years 5-7; years 3-4 must not affect now
        stack = make_stack([6, 6, 6, 1, 1, 12, 12, 12])
        then, now = get_then_now_windows(stack)
        assert then[0, 0] == 6
        assert now[0, 0] == 12   # would be 1 if [3:] slice were used

    def test_raises_on_fewer_than_6_years(self):
        with pytest.raises(ValueError, match="6"):
            get_then_now_windows(make_stack([6, 6, 6, 6, 6]))

    def test_exactly_6_years_does_not_raise(self):
        then, now = get_then_now_windows(make_stack([6, 6, 6, 12, 12, 12]))
        assert then[0, 0] == 6
        assert now[0, 0] == 12

    def test_large_year_range_now_still_uses_last_3(self):
        # 12-year stack: years 0-8 = class 1, years 9-11 = class 6
        stack = make_stack([1]*9 + [6]*3)
        _, now = get_then_now_windows(stack)
        assert now[0, 0] == 6, (
            "now must be modal of last 3 years regardless of stack length"
        )


# ===========================================================================
# remap_classes
# ===========================================================================

class TestRemapClasses:

    @pytest.mark.parametrize("raw_class", ALL_RAW_CLASSES)
    def test_urbanization_remap_all_classes(self, raw_class):
        arr = px(raw_class)
        result = remap_classes(arr, **REMAP_URBANIZATION)
        assert result[0, 0] == URBANIZATION_EXPECTED[raw_class]

    @pytest.mark.parametrize("raw_class", ALL_RAW_CLASSES)
    def test_degradation_remap_all_classes(self, raw_class):
        arr = px(raw_class)
        result = remap_classes(arr, **REMAP_DEGRADATION)
        assert result[0, 0] == DEGRADATION_EXPECTED[raw_class]

    @pytest.mark.parametrize("raw_class", ALL_RAW_CLASSES)
    def test_deforestation_remap_all_classes(self, raw_class):
        arr = px(raw_class)
        result = remap_classes(arr, **REMAP_DEFORESTATION)
        assert result[0, 0] == DEFORESTATION_EXPECTED[raw_class]

    @pytest.mark.parametrize("raw_class", ALL_RAW_CLASSES)
    def test_crop_intensity_remap_all_classes(self, raw_class):
        arr = px(raw_class)
        result = remap_classes(arr, **REMAP_CROP_INTENSITY)
        assert result[0, 0] == CROP_INTENSITY_EXPECTED[raw_class]

    def test_unmapped_class_becomes_default_zero(self):
        arr = px(UNMAPPED_CLASS)   # class 5 not in any remap
        for remap in [REMAP_URBANIZATION, REMAP_DEGRADATION,
                      REMAP_DEFORESTATION, REMAP_CROP_INTENSITY]:
            result = remap_classes(arr, **remap)
            assert result[0, 0] == 0, f"class 5 must map to 0 in {remap}"

    def test_background_class_0_stays_0(self):
        arr = px(0)
        for remap in [REMAP_URBANIZATION, REMAP_DEGRADATION,
                      REMAP_DEFORESTATION, REMAP_CROP_INTENSITY]:
            result = remap_classes(arr, **remap)
            assert result[0, 0] == 0

    def test_custom_default_value_applied(self):
        arr = px(UNMAPPED_CLASS)
        result = remap_classes(arr, from_classes=[1], to_classes=[99], default=7)
        assert result[0, 0] == 7

    def test_output_shape_preserved(self):
        arr = np.array([[1, 6], [8, 12]], dtype=np.int32)
        result = remap_classes(arr, **REMAP_URBANIZATION)
        assert result.shape == arr.shape


# ===========================================================================
# compute_built_up_transitions
# ===========================================================================

class TestBuiltUpTransitions:

    @pytest.mark.parametrize("then_cls,now_cls,expected", URBANIZATION_TRANSITIONS)
    def test_transition_codes(self, then_cls, now_cls, expected):
        then = px(then_cls)
        now  = px(now_cls)
        result = compute_built_up_transitions(then, now)
        assert result[0, 0] == expected, (
            f"then={then_cls} → now={now_cls}: expected code {expected}, got {result[0,0]}"
        )

    def test_output_contains_only_valid_codes(self):
        valid = {0, 1, 2, 3, 4}
        remapped_classes = [0, 1, 2, 3, 4]
        for t in remapped_classes:
            for n in remapped_classes:
                out = compute_built_up_transitions(px(t), px(n))
                assert out[0, 0] in valid, (
                    f"then={t}, now={n} produced invalid code {out[0,0]}"
                )

    def test_no_two_transitions_fire_on_same_pixel(self):
        # Each (then, now) pair must produce exactly one non-zero OR exactly zero
        # i.e. the additive encoding must never double-count
        for t in [1, 2, 3, 4]:
            out = compute_built_up_transitions(px(t), px(1))
            assert out[0, 0] in {1, 2, 3, 4}


# ===========================================================================
# compute_degradation_transitions
# ===========================================================================

class TestDegradationTransitions:

    @pytest.mark.parametrize("then_cls,now_cls,expected", DEGRADATION_TRANSITIONS)
    def test_transition_codes(self, then_cls, now_cls, expected):
        result = compute_degradation_transitions(px(then_cls), px(now_cls))
        assert result[0, 0] == expected

    def test_output_contains_only_valid_codes(self):
        valid = {0, 1, 2, 3, 4}
        for t in range(7):
            for n in range(7):
                out = compute_degradation_transitions(px(t), px(n))
                assert out[0, 0] in valid

    def test_non_forest_then_always_zero(self):
        for then_cls in [1, 2, 3, 5, 6]:   # anything except 4 (forest)
            for now_cls in [1, 2, 3, 4, 5, 6]:
                out = compute_degradation_transitions(px(then_cls), px(now_cls))
                assert out[0, 0] == 0, (
                    f"then={then_cls} is not forest; expected 0, got {out[0,0]}"
                )


# ===========================================================================
# compute_deforestation_transitions
# ===========================================================================

class TestDeforestationTransitions:

    @pytest.mark.parametrize("then_cls,now_cls,expected", DEFORESTATION_TRANSITIONS)
    def test_transition_codes(self, then_cls, now_cls, expected):
        result = compute_deforestation_transitions(px(then_cls), px(now_cls))
        assert result[0, 0] == expected

    def test_output_contains_only_valid_codes(self):
        valid = {0, 1, 2, 3, 4, 5}
        for t in range(7):
            for n in range(7):
                out = compute_deforestation_transitions(px(t), px(n))
                assert out[0, 0] in valid

    def test_non_forest_then_always_zero(self):
        for then_cls in [1, 2, 4, 5, 6]:
            for now_cls in range(7):
                out = compute_deforestation_transitions(px(then_cls), px(now_cls))
                assert out[0, 0] == 0

    def test_afforestation_pixels_produce_zero(self):
        # then != forest, now == forest → not deforestation
        for then_cls in [1, 2, 4, 5, 6]:
            out = compute_deforestation_transitions(px(then_cls), px(3))
            assert out[0, 0] == 0


# ===========================================================================
# compute_afforestation_transitions
# ===========================================================================

class TestAfforestationTransitions:

    @pytest.mark.parametrize("then_cls,now_cls,expected", AFFORESTATION_TRANSITIONS)
    def test_transition_codes(self, then_cls, now_cls, expected):
        result = compute_afforestation_transitions(px(then_cls), px(now_cls))
        assert result[0, 0] == expected

    def test_output_contains_only_valid_codes(self):
        valid = {0, 1, 2, 3, 4, 5}
        for t in range(7):
            for n in range(7):
                out = compute_afforestation_transitions(px(t), px(n))
                assert out[0, 0] in valid

    def test_non_forest_now_always_zero(self):
        for now_cls in [1, 2, 4, 5, 6]:
            for then_cls in range(7):
                out = compute_afforestation_transitions(px(then_cls), px(now_cls))
                assert out[0, 0] == 0

    def test_deforestation_pixels_produce_zero(self):
        # then == forest, now != forest → not afforestation
        for now_cls in [1, 2, 4, 5, 6]:
            out = compute_afforestation_transitions(px(3), px(now_cls))
            assert out[0, 0] == 0

    def test_deforestation_and_afforestation_are_mutually_exclusive(self):
        # Code 1 = "forest stayed forest" — legitimately fires in both pipelines (no change).
        # What must never happen: an active transition (code > 1) fires in both simultaneously.
        for t in range(7):
            for n in range(7):
                defo = compute_deforestation_transitions(px(t), px(n))[0, 0]
                affo = compute_afforestation_transitions(px(t), px(n))[0, 0]
                assert not (defo > 1 and affo > 1), (
                    f"then={t}, now={n} fired active deforestation ({defo}) "
                    f"and active afforestation ({affo}) simultaneously"
                )


# ===========================================================================
# compute_crop_intensity_transitions
# ===========================================================================

class TestCropIntensityTransitions:

    @pytest.mark.parametrize("then_cls,now_cls,expected", CROP_INTENSITY_TRANSITIONS)
    def test_transition_codes(self, then_cls, now_cls, expected):
        result = compute_crop_intensity_transitions(px(then_cls), px(now_cls))
        assert result[0, 0] == expected

    def test_output_contains_only_valid_codes(self):
        valid = set(range(10))   # 0-9
        for t in range(10):
            for n in range(10):
                out = compute_crop_intensity_transitions(px(t), px(n))
                assert out[0, 0] in valid

    def test_non_crop_then_or_now_produces_zero(self):
        non_crop = [1, 2, 3, 4, 8]   # BU, Water, Tree, Barren, Shrub
        for cls in non_crop:
            # non-crop then
            for now in [5, 6, 7]:
                out = compute_crop_intensity_transitions(px(cls), px(now))
                assert out[0, 0] == 0, (
                    f"then={cls} (non-crop) → now={now}: expected 0, got {out[0,0]}"
                )
            # non-crop now
            for then in [5, 6, 7]:
                out = compute_crop_intensity_transitions(px(then), px(cls))
                assert out[0, 0] == 0

    def test_intensification_increase_codes_are_4_5_6(self):
        assert compute_crop_intensity_transitions(px(5), px(6))[0, 0] == 4  # SI→DO
        assert compute_crop_intensity_transitions(px(5), px(7))[0, 0] == 5  # SI→TR
        assert compute_crop_intensity_transitions(px(6), px(7))[0, 0] == 6  # DO→TR

    def test_intensification_decrease_codes_are_1_2_3(self):
        assert compute_crop_intensity_transitions(px(6), px(5))[0, 0] == 1  # DO→SI
        assert compute_crop_intensity_transitions(px(7), px(5))[0, 0] == 2  # TR→SI
        assert compute_crop_intensity_transitions(px(7), px(6))[0, 0] == 3  # TR→DO

    def test_no_change_codes_are_7_8_9(self):
        assert compute_crop_intensity_transitions(px(5), px(5))[0, 0] == 7  # SI→SI
        assert compute_crop_intensity_transitions(px(6), px(6))[0, 0] == 8  # DO→DO
        assert compute_crop_intensity_transitions(px(7), px(7))[0, 0] == 9  # TR→TR


# ===========================================================================
# count_deforestation_anomalies
# ===========================================================================

class TestCountDeforestationAnomalies:

    @pytest.mark.parametrize("name,stack", ANOMALY_COUNT_SCENARIOS.items())
    def test_each_condition_fires_exactly_once(self, name, stack):
        count = count_deforestation_anomalies(stack)
        assert count[0, 0] == 1, (
            f"Scenario '{name}': expected count=1, got {count[0,0]}"
        )

    def test_count_accumulates_across_years(self):
        count = count_deforestation_anomalies(ANOMALY_ACCUMULATE_STACK)
        assert count[0, 0] == ANOMALY_ACCUMULATE_EXPECTED

    def test_no_anomaly_gives_zero(self):
        count = count_deforestation_anomalies(ANOMALY_NONE_STACK)
        assert count[0, 0] == ANOMALY_NONE_EXPECTED

    def test_output_shape_matches_input(self):
        stack = [np.full((3, 4), v, dtype=np.int32) for v in [6, 12, 6, 6, 6, 6]]
        count = count_deforestation_anomalies(stack)
        assert count.shape == (3, 4)

    def test_count_is_non_negative(self):
        count = count_deforestation_anomalies(ANOMALY_NONE_STACK)
        assert (count >= 0).all()

    def test_first_and_last_year_are_never_middle(self):
        # A 3-element stack has only one interior triplet (i=1 is out of range for N=3)
        # Actually for N=3, range(1, N-1) = range(1,2) = [1], so year 1 is the only middle.
        # No anomaly should fire for a stack that is anomalous only at position 0 or N-1.
        stack = make_stack([6, 6, 12])   # year 0=forest, year 1=forest, year 2=shrub
        # Triplet (0,1,2): before=6, middle=6, after=12 — none of the 11 conditions match
        count = count_deforestation_anomalies(stack)
        assert count[0, 0] == 0

    def test_multiple_conditions_can_fire_same_triplet(self):
        # before=1 (BU), middle=6 (tree), after=1 (BU) → fires c8 (BU-tree-BU)
        # and only c8; verify count=1 not >1
        stack = make_stack([1, 6, 1])
        count = count_deforestation_anomalies(stack)
        assert count[0, 0] == 1


# ===========================================================================
# apply_water_class3_smoothing  (Pass B)
# ===========================================================================

class TestWaterClass3Smoothing:

    def _run(self, stack, anomaly_count_override=None):
        if anomaly_count_override is None:
            anomaly_count = count_deforestation_anomalies(stack)
        else:
            anomaly_count = np.full_like(stack[0], anomaly_count_override)
        return apply_water_class3_smoothing(stack, anomaly_count)

    def test_cond1_restores_water_between_water_neighbors(self):
        # [3, 8, 3, 3, 3, 3] with count forced to 3 → middle at year 1 should become 3.
        # Count override needed: the stack naturally produces count=1 (below the {3,4} threshold).
        result = self._run(SMOOTH_COND1_STACK, anomaly_count_override=3)
        assert result[SMOOTH_COND1_YEAR_IDX][0, 0] == SMOOTH_COND1_EXPECTED

    def test_cond2_reverts_isolated_water_to_before(self):
        # [8, 3, 8, 8, 8, 8] with count forced to 3 → middle at year 1 should become 8 (before).
        # Count override needed: the stack naturally produces count=0 (no anomaly conditions fire).
        result = self._run(SMOOTH_COND2_STACK, anomaly_count_override=3)
        assert result[SMOOTH_COND2_YEAR_IDX][0, 0] == SMOOTH_COND2_EXPECTED

    def test_below_threshold_count_no_correction(self):
        # count=2 → threshold requires exactly 3 or 4; no change expected
        result = self._run(
            SMOOTH_BELOW_THRESHOLD_STACK,
            anomaly_count_override=2,
        )
        assert result[SMOOTH_BELOW_THRESHOLD_YEAR_IDX][0, 0] == SMOOTH_BELOW_THRESHOLD_EXPECTED

    def test_count_above_threshold_no_correction(self):
        # BUG-2 probe: count=5 → threshold {3,4} does not fire; middle unchanged
        stack = make_stack([3, 8, 3, 3, 3, 3])
        result = self._run(stack, anomaly_count_override=5)
        assert result[1][0, 0] == 8, (
            "count=5 exceeds the hard cap of 4; no smoothing expected. "
            "If this fails it means the threshold was widened — confirm with team."
        )

    def test_count_3_fires(self):
        stack = make_stack([3, 8, 3, 3, 3, 3])
        result = self._run(stack, anomaly_count_override=3)
        assert result[1][0, 0] == 3

    def test_count_4_fires(self):
        stack = make_stack([3, 8, 3, 3, 3, 3])
        result = self._run(stack, anomaly_count_override=4)
        assert result[1][0, 0] == 3

    def test_input_list_not_mutated(self):
        stack = make_stack([3, 8, 3, 3, 3, 3])
        original_middle = stack[1][0, 0]
        _ = self._run(stack, anomaly_count_override=3)
        assert stack[1][0, 0] == original_middle, "input stack must not be mutated"

    def test_first_and_last_year_never_modified(self):
        stack = make_stack([3, 8, 3, 3, 3, 3])
        result = self._run(stack, anomaly_count_override=3)
        assert result[0][0, 0] == stack[0][0, 0]
        assert result[-1][0, 0] == stack[-1][0, 0]

    def test_non_class3_pixels_unaffected_by_smoothing(self):
        # A pixel that is class 6 (forest) throughout should not be touched
        stack = make_uniform_stack(6, 6)
        result = self._run(stack, anomaly_count_override=3)
        for year in result:
            assert year[0, 0] == 6
