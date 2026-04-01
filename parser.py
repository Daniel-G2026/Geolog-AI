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

def parse_blow_counts_from_string(blows_string: str) -> tuple:
    """
    Converts the blows segment string into (blow_counts, pen_depths).
    
    Detects refusal notation "50 for 3" or "50/3" and extracts pen depth.
    Normal intervals default to 6 inches penetration.
    
    Input:  "12 17 19 23"         → ([12, 17, 19, 23], [6, 6, 6, 6])
    Input:  "12 17 50 for 3 23"   → ([12, 17, 50, 23], [6, 6, 3, 6])
    Input:  "50/3"                → ([50], [3])
    Input:  ""                    → ([], [])
    """
    if not blows_string:
        return ([], [])

    # Normalize "50 for 3" and "50 for 3 inches" → "50/3"
    # Allow comma or period after the inch value (Whisper often writes "50 for 3, 23").
    normalized = re.sub(
        r'(\d+)\s+for\s+(\d+\.?\d*)(?:\s+inches?)?(?=\s*[,.]|\s|$)',
        r'\1/\2',
        blows_string,
    )

    # Remove other punctuation except / which we need
    normalized = re.sub(r'[.,?;]', ' ', normalized)

    tokens = normalized.split()
    blow_counts = []
    pen_depths = []

    for token in tokens:
        if '/' in token:
            # Refusal format — "50/3" means 50 blows for 3 inches
            parts = token.split('/')
            try:
                blow = int(parts[0])
                depth = float(parts[1])
                blow_counts.append(blow)
                pen_depths.append(depth)
            except (ValueError, IndexError):
                continue
        else:
            try:
                blow = int(token)
                blow_counts.append(blow)
                pen_depths.append(6.0)  # default full interval
            except ValueError:
                continue  # skip words like "and"

    if len(blow_counts) == 0 or len(blow_counts) > 4:
        return ([], [])

    return (blow_counts, pen_depths)

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