# tests/test_parser.py
# Tests for parser.py — pure, deterministic parsing functions.
# No Claude API calls in this module, so no mocking needed.
#
# Expected values are marked with `# TODO(you): fill in expected value`
# so you can verify each one against the actual parser behavior instead
# of trusting an inferred guess.
#
# Run from project root:
#     pytest tests/test_parser.py -v

import pytest

from parser import (
    segment_transcript,
    parse_blow_counts_from_string,
    parse_recovery,
    parse_uscs_symbol,
    parse_plasticity,
    parse_gradation,
    looks_like_runon_blowcounts,
)


# ─────────────────────────────────────────────
# segment_transcript
# ─────────────────────────────────────────────

class TestSegmentTranscript:
    """
    Covers:
      - all five standard keywords get detected
      - synonym groups map to the canonical keyword
      - longest-first matching ("blow counts" wins over "blows")
      - keywords out of natural order still segment correctly
      - empty / no-keyword input returns empty dict
      - content between keywords is trimmed
    """

    def test_all_standard_keywords_present(self):
        transcript = (
            "description silty clay till trace sand dark brown moist "
            "blows 12 17 19 23 recovery 12.5 comments wet spoon"
        )
        result = segment_transcript(transcript)
        expected = {
            "description": "silty clay till trace sand dark brown moist",
            "blows": "12 17 19 23",
            "recovery": "12.5",
            "comments": "wet spoon",
        }
        assert result == expected

    def test_synonym_blow_counts_maps_to_blows(self):
        # "blow counts" is a synonym for "blows" — must map to the canonical key.
        transcript = "description silty clay blow counts 12 17 19 23"
        result = segment_transcript(transcript)
        expected = {
            "description": "silty clay",
            "blows": "12 17 19 23",
        }
        assert result == expected

    def test_longest_synonym_wins_over_shorter(self):
        # Input contains "blow counts" — the longer synonym must match before
        # the shorter "blows" substring sneaks in.
        transcript = "blow counts 12 17 19 23"
        result = segment_transcript(transcript)
        expected = {
            "blows": "12 17 19 23",
        }
        assert result == expected

    def test_soil_synonym_maps_to_description(self):
        transcript = "soil silty clay moist blows 10 12 14 16"
        result = segment_transcript(transcript)
        expected = {
            "description": "silty clay moist",
            "blows": "10 12 14 16",
        }
        assert result == expected

    def test_comments_synonym_remarks(self):
        transcript = "description silty clay remarks wet spoon"
        result = segment_transcript(transcript)
        expected = {
            "description": "silty clay",
            "comments": "wet spoon",
        }
        assert result == expected

    def test_keywords_out_of_order(self):
        # The tech spoke comments before recovery — segmentation should
        # still slice correctly based on keyword positions.
        transcript = (
            "description silty clay blows 12 17 19 23 "
            "comments wet spoon recovery 12.5"
        )
        result = segment_transcript(transcript)
        expected = {
            "description": "silty clay",
            "blows": "12 17 19 23",
            "comments": "wet spoon",
            "recovery": "12.5",
        }
        assert result == expected

    def test_no_keywords_returns_empty_dict(self):
        transcript = "this transcript has no recognized keywords in it"
        result = segment_transcript(transcript)
        assert result == {}

    def test_empty_string(self):
        result = segment_transcript("")
        assert result == {}

    def test_content_is_stripped(self):
        # Leading/trailing whitespace between keyword boundary and content
        # should be stripped.
        transcript = "description   silty clay   blows   12 17 19 23  "
        result = segment_transcript(transcript)
        expected = {
            "description": "silty clay",
            "blows": "12 17 19 23",
        }
        assert result == expected


# ─────────────────────────────────────────────
# parse_blow_counts_from_string
# ─────────────────────────────────────────────

class TestParseBlowCountsFromString:
    """
    Covers:
      - normal 4-interval sequence
      - refusal "50 for 3"
      - refusal "50/3" slash notation
      - mixed normal + refusal in one string
      - empty string
      - >4 tokens rejects
      - 0 tokens rejects
      - garbage tokens skipped
      - "50 for 3 inches" with the word
      - comma / period after inch value (Whisper quirk)
    """

    def test_normal_four_intervals(self):
        result = parse_blow_counts_from_string("12 17 19 23")
        expected = ([12, 17, 19, 23], [6.0, 6.0, 6.0, 6.0])
        assert result == expected

    def test_refusal_for_notation(self):
        result = parse_blow_counts_from_string("12 17 50 for 3 23")
        expected = ([12, 17, 50, 23], [6.0, 6.0, 3.0, 6.0])
        assert result == expected

    def test_refusal_for_inches_word(self):
        # "50 for 3 inches" should normalize the same as "50 for 3"
        result = parse_blow_counts_from_string("12 17 50 for 3 inches 23")
        expected = ([12, 17, 50, 23], [6.0, 6.0, 3.0, 6.0])
        assert result == expected

    def test_refusal_slash_notation_alone(self):
        result = parse_blow_counts_from_string("50/3")
        expected = ([50], [3.0])
        assert result == expected

    def test_refusal_with_trailing_comma(self):
        # Whisper often writes "50 for 3, 23" — comma after inch value.
        result = parse_blow_counts_from_string("12 17 50 for 3, 23")
        expected = ([12, 17, 50, 23], [6.0, 6.0, 3.0, 6.0])
        assert result == expected

    def test_empty_string(self):
        result = parse_blow_counts_from_string("")
        assert result == ([], [])

    def test_zero_valid_tokens_returns_empty(self):
        # All tokens are garbage — no ints parsed.
        result = parse_blow_counts_from_string("and then also")
        assert result == ([], [])

    def test_more_than_four_tokens_rejected(self):
        # >4 blow counts is invalid — SS sample is 4 intervals max.
        result = parse_blow_counts_from_string("12 17 19 23 25")
        assert result == ([], [])

    def test_garbage_tokens_skipped(self):
        # Non-numeric tokens ("and") should be silently skipped.
        result = parse_blow_counts_from_string("12 and 17 and 19 and 23")
        expected = ([12, 17, 19, 23], [6.0, 6.0, 6.0, 6.0])
        assert result == expected

    def test_refusal_slash_malformed_skipped(self):
        # "50/" has no denominator — ValueError path, token skipped.
        # The malformed token is skipped, leaving 3 valid ints with default pen_depths.
        result = parse_blow_counts_from_string("12 17 50/ 23")
        expected = ([12, 17, 23], [6.0, 6.0, 6.0])
        assert result == expected


# ─────────────────────────────────────────────
# Run-on safeguard — Whisper concatenation defense
# ─────────────────────────────────────────────

class TestRunOnBlowCountsSafeguard:
    """
    Whisper occasionally collapses single-digit blow counts spoken in close
    succession into one numeric token (e.g. "3, 7, 9, 9" → "3799"). The parser
    detects and auto-splits this conservatively, and the pipeline emits an
    amber review flag.
    """

    # ── detector positives ──
    def test_detect_runon_four_digit_no_zeros(self):
        assert looks_like_runon_blowcounts("3799") is True

    def test_detect_runon_three_digit_no_zeros(self):
        assert looks_like_runon_blowcounts("379") is True

    def test_detect_runon_with_punctuation(self):
        assert looks_like_runon_blowcounts("3799.") is True
        assert looks_like_runon_blowcounts("3799,") is True

    # ── detector negatives ──
    def test_detect_skip_when_zero_present(self):
        # 250 is a legitimate (if extreme) single value — has zero, don't split.
        assert looks_like_runon_blowcounts("250") is False

    def test_detect_skip_when_two_digit(self):
        assert looks_like_runon_blowcounts("47") is False

    def test_detect_skip_when_five_digit(self):
        assert looks_like_runon_blowcounts("12345") is False

    def test_detect_skip_when_multiple_tokens(self):
        # Already separated — not a run-on.
        assert looks_like_runon_blowcounts("12 17 19 23") is False

    def test_detect_skip_when_slash_present(self):
        # Refusal notation — real >50 count, not a run-on.
        assert looks_like_runon_blowcounts("50/3") is False

    def test_detect_skip_when_for_present(self):
        assert looks_like_runon_blowcounts("50 for 3") is False

    def test_detect_skip_empty(self):
        assert looks_like_runon_blowcounts("") is False
        assert looks_like_runon_blowcounts("   ") is False

    # ── auto-split end-to-end ──
    def test_autosplit_four_digit_runon(self):
        # The reported field bug: "3, 7, 9, 9" got transcribed as "3799".
        result = parse_blow_counts_from_string("3799")
        expected = ([3, 7, 9, 9], [6.0, 6.0, 6.0, 6.0])
        assert result == expected

    def test_autosplit_three_digit_runon(self):
        result = parse_blow_counts_from_string("379")
        expected = ([3, 7, 9], [6.0, 6.0, 6.0])
        assert result == expected

    def test_autosplit_does_not_fire_on_normal_input(self):
        # Sanity — normal multi-token input bypasses the run-on path.
        result = parse_blow_counts_from_string("12 17 19 23")
        expected = ([12, 17, 19, 23], [6.0, 6.0, 6.0, 6.0])
        assert result == expected

    def test_autosplit_does_not_fire_when_zero_present(self):
        # 250 has a zero — left alone as a single (extreme but legal) value.
        result = parse_blow_counts_from_string("250")
        expected = ([250], [6.0])
        assert result == expected


# ─────────────────────────────────────────────
# parse_recovery
# ─────────────────────────────────────────────

class TestParseRecovery:
    """
    Note: parse_recovery returns a 3-tuple (inches, remainder, flag).

    Covers:
      - plain integer
      - decimal value
      - integer followed by "inches"
      - empty string → flag
      - non-numeric string → flag, empty num
      - decimal where second digit missing (edge in the isdigit loop)
      - trailing comment text becomes remainder
    """

    def test_plain_integer(self):
        result = parse_recovery("18")
        expected = (18.0, "", None)
        assert result == expected

    def test_decimal_value(self):
        result = parse_recovery("12.5")
        expected = (12.5, "", None)
        assert result == expected

    def test_integer_with_inches_word(self):
        result = parse_recovery("18 inches")
        # "inches" is stripped from remainder; remaining whitespace stripped.
        expected = (18.0, "", None)
        assert result == expected

    def test_decimal_with_inches_word(self):
        result = parse_recovery("12.5 inches")
        expected = (12.5, "", None)
        assert result == expected

    def test_empty_string_returns_flag(self):
        result = parse_recovery("")
        # From the code: (None, "", "Recovery not found - manual input required")
        expected = (None, "", "Recovery not found - manual input required")
        assert result == expected

    def test_non_numeric_string_returns_flag(self):
        result = parse_recovery("full")
        # No digits found — num_string stays empty, remainder stays "".
        expected = (None, "", "Recovery not found - manual input required")
        assert result == expected

    def test_number_followed_by_comment_text(self):
        # "12 wet spoon" — 12 is recovery, rest is remainder.
        result = parse_recovery("12 wet spoon")
        expected = (12.0, "wet spoon", None)
        assert result == expected


# ─────────────────────────────────────────────
# parse_uscs_symbol
# ─────────────────────────────────────────────

class TestParseUscsSymbol:
    """
    Covers each of the 4 regex patterns, invalid symbols, empty input,
    case normalization.
    """

    def test_group_name_is_pattern(self):
        result = parse_uscs_symbol("sand groupname is sm")
        expected = "SM"
        assert result == expected

    def test_group_symbol_is_pattern(self):
        result = parse_uscs_symbol("silty clay group symbol is cl dark brown")
        expected = "CL"
        assert result == expected

    def test_symbol_is_pattern(self):
        result = parse_uscs_symbol("silty clay symbol is cl dark brown")
        expected = "CL"
        assert result == expected

    def test_symbol_bare_pattern(self):
        result = parse_uscs_symbol("silty clay symbol ml moist")
        expected = "ML"
        assert result == expected

    def test_invalid_symbol_returns_none(self):
        # "zz" is not in VALID_USCS_SYMBOLS — must return None.
        result = parse_uscs_symbol("silty clay symbol is zz")
        assert result is None

    def test_no_symbol_phrase_returns_none(self):
        result = parse_uscs_symbol("silty clay dark brown moist")
        assert result is None

    def test_empty_string_returns_none(self):
        assert parse_uscs_symbol("") is None

    def test_uppercase_input(self):
        # The regex lowercases text first — uppercase input should still work.
        result = parse_uscs_symbol("SILTY CLAY SYMBOL IS CL")
        expected = "CL"
        assert result == expected


# ─────────────────────────────────────────────
# parse_plasticity
# ─────────────────────────────────────────────

class TestParsePlasticity:
    """
    Covers each mapping and the longest-match precedence
    ("little bit plastic" must win over any shorter substring).
    """

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("plasticity is low",    "low plasticity"),
            ("low plasticity",       "low plasticity"),
            ("plasticity is high",   "high plasticity"),
            ("high plasticity",      "high plasticity"),
            ("non plastic",          "non-plastic"),
            ("non-plastic",          "non-plastic"),
            ("plasticity is non",    "non-plastic"),
            ("slightly plastic",     "slightly plastic"),
            ("little bit plastic",   "slightly plastic"),
        ],
    )
    def test_mappings(self, text, expected):
        assert parse_plasticity(text) == expected

    def test_no_plasticity_mention(self):
        assert parse_plasticity("silty clay dark brown moist") is None

    def test_empty_string(self):
        assert parse_plasticity("") is None

    def test_embedded_in_longer_sentence(self):
        # Phrase inside a larger description should still match.
        result = parse_plasticity("silty clay dark brown moist low plasticity stiff")
        expected = "low plasticity"
        assert result == expected


# ─────────────────────────────────────────────
# parse_gradation
# ─────────────────────────────────────────────

class TestParseGradation:
    """
    Covers both enum values, absence, and empty input.
    """

    def test_poorly_graded(self):
        result = parse_gradation("sand and gravel poorly graded wet")
        expected = "poorly graded"
        assert result == expected

    def test_well_graded(self):
        result = parse_gradation("sand and gravel well graded wet")
        expected = "well graded"
        assert result == expected

    def test_neither_mentioned(self):
        assert parse_gradation("silty clay dark brown moist") is None

    def test_empty_string(self):
        assert parse_gradation("") is None
