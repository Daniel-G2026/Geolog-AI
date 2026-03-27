# parser.py
# Handles transcript segmentation and field parsing for GeoLog AI.
# Scope: Soil only. Rock core parsing to be added later.
#
# What this file does:
# 1. segment_transcript()            — splits raw transcript into sections by keyword
# 2. parse_blow_counts_from_string() — converts blows segment string to list of ints
# 3. parse_recovery()                — extracts recovery value in inches from segment

import re

# ─────────────────────────────────────────────
# KEYWORD SYNONYMS
# Each dict group maps synonyms to a standard keyword.
# Sorted longest-first within each group to prevent
# shorter substrings from matching before longer phrases.
# e.g. "blow counts" must match before "blows"
# ─────────────────────────────────────────────

KEYWORD_SYNONYMS = [
    {
        "description": "description",
        "soil description": "description",
        "soil": "description",
        "desc": "description"
    },
    {
        "blows": "blows",
        "blow counts": "blows",
        "blowcounts": "blows",
        "blow count": "blows",
        "counts": "blows"
    },
    {
        "recovery": "recovery",
        "rec": "recovery"
    },
    {
        "comments": "comments",
        "comment": "comments",
        "remarks": "comments",
        "remark": "comments",
        "notes": "comments",
        "note": "comments"
    },
    {"cgd": "cgd"},
    {"pid": "pid"},
    {"cone": "cone"}
]


# ─────────────────────────────────────────────
# SEGMENT TRANSCRIPT
# ─────────────────────────────────────────────

def segment_transcript(transcript: str) -> dict:
    """
    Splits the raw Whisper transcript into sections by keyword.
    Accepts synonyms — maps them all to standard keywords first.

    The tech speaks keywords to delimit each section:
    "description silty clay till trace sand dark brown moist
     blows 12 17 19 23 recovery 12.5 comments wet spoon"

    Returns:
    {
        "description": "silty clay till trace sand dark brown moist",
        "blows":       "12 17 19 23",
        "recovery":    "12.5",
        "comments":    "wet spoon"
    }

    Returns empty dict if no keywords found.
    """
    standard_keywords = []
    text = transcript.lower().strip()

    # Step 1 — replace all synonyms with standard keywords
    # Process each synonym group, match longest synonym first to avoid
    # shorter substrings (e.g. "blow counts" before "blows")
    for synonym_group in KEYWORD_SYNONYMS:
        for synonym in sorted(synonym_group.keys(), key=len, reverse=True):
            standard = synonym_group[synonym]
            if synonym in text:
                text = text.replace(synonym, standard)
                standard_keywords.append(standard)
                break  # only replace one synonym per group

    # Step 2 — find positions of all matched standard keywords in text
    keyword_found = []
    for keyword in standard_keywords:
        if keyword in text:
            index = text.find(keyword)
            keyword_found.append((index, keyword))
    keyword_found = sorted(keyword_found, key=lambda x: x[0])

    # Step 3 — slice text between consecutive keyword positions
    segment_dict = {}
    for i, (index, keyword) in enumerate(keyword_found):
        # Content starts right after the keyword itself
        start = index + len(keyword)
        # Content ends at the start of the next keyword, or end of string
        if i + 1 < len(keyword_found):
            end = keyword_found[i + 1][0]
        else:
            end = len(text)
        segment_dict[keyword] = text[start:end].strip()

    return segment_dict


# ─────────────────────────────────────────────
# BLOW COUNT PARSER
# ─────────────────────────────────────────────

def parse_blow_counts_from_string(blows_string: str) -> list:
    """
    Converts the blows segment string into a list of integers.

    Input:  "12 17 19 23"  or  "12, 17, 19, 23."
    Output: [12, 17, 19, 23]

    Handles 1-4 numbers. Returns empty list if no valid numbers found.
    Strips punctuation before splitting — Whisper sometimes adds
    punctuation after the last number e.g. "14, 24, 16, and 14."
    Pen depths are handled separately via tap UI — not parsed here.
    """
    if not blows_string:
        return []

    # Replace punctuation with spaces before splitting
    raw = re.sub(r"[.,?;]", " ", blows_string).split()

    counts = []
    for item in raw:
        try:
            counts.append(int(item))
        except ValueError:
            continue  # skip non-numeric words e.g. "and" between numbers

    # Validate 1-4 counts — SPT drive has max 4 intervals
    if len(counts) == 0 or len(counts) > 4:
        return []

    return counts


# ─────────────────────────────────────────────
# RECOVERY PARSER
# ─────────────────────────────────────────────

def parse_recovery(recovery_string: str) -> tuple:
    """
    Extracts recovery value in inches from the recovery segment.
    Returns float to handle partial inch values like 12.5.
    Recovery is measured in inches on site at Envision.
    Conversion to mm happens in pipeline.py.

    Input:  "12.5"  → (12.5, None)
    Input:  "18"    → (18.0, None)
    Input:  ""      → (None, "Recovery not found - manual input required")
    Input:  "full"  → (None, "Recovery not found - manual input required")
    """
    if not recovery_string:
        return (None, "Recovery not found - manual input required")

    num_string = ""
    for i, char in enumerate(recovery_string):
        if char.isdigit():
            num_string += char
        elif (char == "." and num_string
              and i + 1 < len(recovery_string)
              and recovery_string[i + 1].isdigit()):
            num_string += char
        elif char == " " and num_string:
            break  # stop at first space after digits

    if not num_string:
        return (None, "Recovery not found - manual input required")

    try:
        return (float(num_string), None)
    except ValueError:
        return (None, "Recovery not found - manual input required")