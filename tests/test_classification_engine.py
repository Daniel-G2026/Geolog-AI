# tests/test_classification_engine.py
# Tests for classification_engine.py — SPT math and soil classification.
# Pure deterministic logic, no API calls, no mocking.
#
# Expected values are marked with `# TODO(you): fill in expected value`.
# Verify each one against your ASTM D2488 tables before filling — these
# are the exact boundary rules that determine consistency/density in the log.
#
# Run from project root:
#     pytest tests/test_classification_engine.py -v

import pytest

from classification_engine import (
    get_consistency_density,
    consistency_density_condition,
    parse_blow_counts,
)


# ─────────────────────────────────────────────
# consistency_density_condition
#
# This is the core lookup — two tables, one boundary-value-per-integer.
# Every bracket and boundary gets tested here so get_consistency_density
# tests above can stay focused on dispatch behavior (single vs list).
# ─────────────────────────────────────────────

class TestConsistencyDensityConditionCohesionless:
    """
    Cohesionless (sand/gravel) relative density table (ASTM D2488):
        N < 4    → very loose
        N = 4    → very loose to loose
        4 < N < 10 → loose
        N = 10   → loose to medium dense
        10 < N < 30 → compact
        N = 30   → compact to dense
        30 < N < 50 → dense
        N = 50   → dense to very dense
        N > 50   → very dense
    """

    @pytest.mark.parametrize(
        "n_value, expected",
        [
            # Lower bracket
            (0,   "very loose"),
            (3,   "very loose"),
            # Boundary @ 4
            (4,   "very loose to loose"),
            # Loose bracket
            (5,   "loose"),
            (9,   "loose"),
            # Boundary @ 10
            (10,  "loose to medium dense"),
            # Compact bracket
            (11,  "compact"),
            (29,  "compact"),
            # Boundary @ 30
            (30,  "compact to dense"),
            # Dense bracket
            (31,  "dense"),
            (49,  "dense"),
            # Boundary @ 50
            (50,  "dense to very dense"),
            # Upper bracket
            (51,  "very dense"),
            (100, "very dense"),
        ],
    )
    def test_sand_brackets(self, n_value, expected):
        assert consistency_density_condition("sand", n_value) == expected

    def test_gravel_also_classifies_cohesionless(self):
        # "gravel" is in COHESIONLESS_TERMS — any N-value uses the density table.
        result = consistency_density_condition("gravel", 20)
        expected = "compact"
        assert result == expected

    def test_silty_sand_classifies_cohesionless(self):
        # "silty sand" — substring matcher must hit COHESIONLESS before COHESIVE.
        result = consistency_density_condition("silty sand", 20)
        expected = "compact"
        assert result == expected

    def test_sandy_silt_classifies_cohesionless(self):
        # "sandy silt" — cohesionless check runs first and wins.
        result = consistency_density_condition("sandy silt", 20)
        expected = "compact"
        assert result == expected


class TestConsistencyDensityConditionCohesive:
    """
    Cohesive (clay/silt) consistency table (ASTM D2488):
        N < 2    → very soft
        N = 2    → very soft to soft
        2 < N < 4 → soft
        N = 4    → soft to firm
        4 < N < 8 → firm
        N = 8    → firm to stiff
        8 < N < 15 → stiff
        N = 15   → stiff to very stiff
        15 < N < 30 → very stiff
        N = 30   → very stiff to hard
        N > 30   → hard
    """

    @pytest.mark.parametrize(
        "n_value, expected",
        [
            # Lower bracket
            (0,   "very soft"),
            (1,   "very soft"),
            # Boundary @ 2
            (2,   "very soft to soft"),
            # Soft bracket
            (3,   "soft"),
            # Boundary @ 4
            (4,   "soft to firm"),
            # Firm bracket
            (5,   "firm"),
            (7,   "firm"),
            # Boundary @ 8
            (8,   "firm to stiff"),
            # Stiff bracket
            (9,   "stiff"),
            (14,  "stiff"),
            # Boundary @ 15
            (15,  "stiff to very stiff"),
            # Very stiff bracket
            (16,  "very stiff"),
            (29,  "very stiff"),
            # Boundary @ 30
            (30,  "very stiff to hard"),
            # Hard bracket
            (31,  "hard"),
            (100, "hard"),
        ],
    )
    def test_clay_brackets(self, n_value, expected):
        assert consistency_density_condition("clay", n_value) == expected

    def test_silt_classifies_cohesive(self):
        result = consistency_density_condition("silt", 10)
        expected = "stiff"
        assert result == expected

    def test_silty_clay_classifies_cohesive(self):
        result = consistency_density_condition("silty clay", 10)
        expected = "stiff"
        assert result == expected

    def test_clayey_silt_classifies_cohesive(self):
        result = consistency_density_condition("clayey silt", 10)
        expected = "stiff"
        assert result == expected


class TestConsistencyDensityConditionEdgeCases:
    """
    Till stripping, unrecognized soils, and the substring-match quirks.
    """

    def test_till_suffix_stripped_cohesive(self):
        # "silty clay till" classifies the same as "silty clay"
        result = consistency_density_condition("silty clay till", 10)
        expected = "stiff"
        assert result == expected

    def test_till_suffix_stripped_cohesionless(self):
        result = consistency_density_condition("sandy silt till", 20)
        expected = "compact"
        assert result == expected

    def test_unrecognized_soil_returns_none(self):
        # "peat" isn't in either term list — must return None to trigger flag.
        assert consistency_density_condition("peat", 10) is None

    def test_empty_soil_name_returns_none(self):
        assert consistency_density_condition("", 10) is None


# ─────────────────────────────────────────────
# get_consistency_density
#
# Dispatch wrapper — handles single strings vs lists, and the mixed
# cohesive/cohesionless combining rule.
# ─────────────────────────────────────────────

class TestGetConsistencyDensitySingle:
    """Single string soil name — normal path."""

    def test_single_cohesive(self):
        result = get_consistency_density("silty clay", 10)
        expected = "stiff"
        assert result == expected

    def test_single_cohesionless(self):
        result = get_consistency_density("sand", 20)
        expected = "compact"
        assert result == expected

    def test_single_with_mixed_case_input(self):
        # Input has mixed capitalization — function must lowercase before lookup.
        result = get_consistency_density("Silty Clay", 10)
        expected = "stiff"
        assert result == expected

    def test_single_unrecognized_returns_none(self):
        assert get_consistency_density("peat", 10) is None


class TestGetConsistencyDensityList:
    """
    List soil names — two sub-cases:
      1. All same type → uses soil[0] for classification
      2. Mixed cohesive + cohesionless → "term1/term2" joined in input order
    """

    def test_list_all_cohesive_uses_first(self):
        # Both cohesive — function uses the first entry for classification.
        result = get_consistency_density(["silty clay", "clay"], 10)
        expected = "stiff"
        assert result == expected

    def test_list_all_cohesionless_uses_first(self):
        result = get_consistency_density(["sand", "gravel"], 20)
        expected = "compact"
        assert result == expected

    def test_list_mixed_cohesive_then_cohesionless(self):
        # Input order: cohesive first, then cohesionless.
        # Output joins with "/" in input order.
        result = get_consistency_density(["silty clay", "sandy silt"], 20)
        expected = "very stiff/compact"
        assert result == expected

    def test_list_mixed_cohesionless_then_cohesive(self):
        # Input order flipped — output order flips too.
        result = get_consistency_density(["sandy silt", "silty clay"], 20)
        expected = "compact/very stiff"
        assert result == expected

    def test_list_with_till_variant_detects_mixed(self):
        # After the till-stripping fix in the list branch, "silty clay till"
        # is recognized as the cohesive member of a mixed list and combined
        # with the cohesionless term just like the plain "silty clay" case.
        result = get_consistency_density(["silty clay till", "sandy silt"], 20)
        expected = "very stiff/compact"
        assert result == expected

    def test_list_all_cohesive_with_till_variant(self):
        # Both entries cohesive after till stripping — falls into
        # all-same-type branch, classifies using soil[0] (till stripped).
        result = get_consistency_density(["silty clay till", "clay"], 10)
        expected = "stiff"
        assert result == expected

    def test_list_with_mixed_case_entries(self):
        # List entries are lowercased inside the function.
        result = get_consistency_density(["Silty Clay", "Sandy Silt"], 20)
        expected = "very stiff/compact"
        assert result == expected


# ─────────────────────────────────────────────
# parse_blow_counts
#
# SPT convention:
#   - 4 intervals of 6 inches = 24 inches total drive
#   - N-value = interval 2 + interval 3 (indices 1 and 2)
#   - Any pen_depth < 6.0 inches = refusal at that interval
# ─────────────────────────────────────────────

class TestParseBlowCountsFullDrive:
    """4 intervals, all full-penetration (pen_depths all 6.0)."""

    def test_normal_full_drive(self):
        result = parse_blow_counts([12, 17, 19, 23], [6.0, 6.0, 6.0, 6.0])
        # n_value = 17 + 19 = 36
        expected = {
            "n_value": 36,
            "n_value_log": "36",
            "refusal": False,
        }
        assert result == expected

    def test_zero_blow_counts_still_full_drive(self):
        # All zero blow counts but full pen_depths — still "normal" in the
        # code's sense because no refusal interval triggers.
        result = parse_blow_counts([0, 0, 0, 0], [6.0, 6.0, 6.0, 6.0])
        expected = {
            "n_value": 0,
            "n_value_log": "0",
            "refusal": False,
        }
        assert result == expected


class TestParseBlowCountsRefusalMidDrive:
    """4 blow_counts received but one interval has pen_depth < 6.0."""

    def test_refusal_on_interval_3(self):
        # Interval 3 hit 50 blows after only 3 inches.
        # n_value = blows[1] + blows[2] = 17 + 50 = 67
        # combined_pen_mm = round((6 + 3) * 25.4) = round(228.6) = 229
        result = parse_blow_counts([12, 17, 50, 5], [6.0, 6.0, 3.0, 6.0])
        expected = {
            "n_value": 67,
            "n_value_log": "67/229mm",
            "refusal": True,
        }
        assert result == expected

    def test_refusal_on_interval_4(self):
        # Interval 4 refused — but n_value still = blows[1] + blows[2].
        # combined_pen_mm still uses pen_depths[1] + pen_depths[2] = 6 + 6.
        # round(12 * 25.4) = round(304.8) = 305
        result = parse_blow_counts([12, 17, 19, 50], [6.0, 6.0, 6.0, 3.0])
        expected = {
            "n_value": 36,
            "n_value_log": "36/305mm",
            "refusal": True,
        }
        assert result == expected


class TestParseBlowCountsShortDrive:
    """Fewer than 4 blow counts — refusal on that interval."""

    def test_refusal_on_interval_1(self):
        # Hit 50 before interval 1 finished (3 inches).
        # round(3 * 25.4) = round(76.2) = 76
        result = parse_blow_counts([50], [3.0])
        expected = {
            "n_value": 50,
            "n_value_log": "50/76mm",
            "refusal": True,
        }
        assert result == expected

    def test_refusal_on_interval_2(self):
        # Completed interval 1, refused at interval 2 (2 inches).
        # round(2 * 25.4) = round(50.8) = 51
        result = parse_blow_counts([12, 50], [6.0, 2.0])
        expected = {
            "n_value": 50,
            "n_value_log": "50/51mm",
            "refusal": True,
        }
        assert result == expected

    def test_refusal_on_interval_3(self):
        # Completed 1 and 2, refused at 3 (4 inches).
        # n_value = blows[1] + blows[2] = 17 + 50 = 67
        # combined_pen_mm = round((6 + 4) * 25.4) = round(254.0) = 254
        result = parse_blow_counts([12, 17, 50], [6.0, 6.0, 4.0])
        expected = {
            "n_value": 67,
            "n_value_log": "67/254mm",
            "refusal": True,
        }
        assert result == expected


class TestParseBlowCountsDefensive:
    """Defensive fallthrough — pipeline rejects these before calling, but the
    function must return a stable shape if ever reached."""

    def test_empty_inputs(self):
        result = parse_blow_counts([], [])
        expected = {
            "n_value": 0,
            "n_value_log": "",
            "refusal": False,
        }
        assert result == expected

    def test_more_than_four_blow_counts(self):
        # Five intervals shouldn't happen per SS spec — falls through.
        result = parse_blow_counts(
            [12, 17, 19, 23, 25],
            [6.0, 6.0, 6.0, 6.0, 6.0],
        )
        expected = {
            "n_value": 0,
            "n_value_log": "",
            "refusal": False,
        }
        assert result == expected
