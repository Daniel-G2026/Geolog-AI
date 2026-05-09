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
        "counts": "blows",
        "blow counter": "blows",
        "blowcount" : "blows"
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
            pattern = rf"\b{re.escape(synonym)}\b"
            if re.search(pattern,text):
                text = re.sub(pattern, standard, text, flags=re.IGNORECASE)
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
# Check if split layer
# ─────────────────────────────────────────────

def is_split_layer(description_segment: str) -> bool:
    matches = re.findall(r'\blayer\s+\d+\b', description_segment.lower())
    return len(matches) >= 2

# ─────────────────────────────────────────────
# Split layer depths parser
# ─────────────────────────────────────────────
def parse_depth_range(layer_slice: str) -> tuple:
    """
    Extracts depth range in inches from a layer slice.
    
    Input:  "0 to 14 inches silty clay brown moist"
    Output: (0.0, 14.0, "silty clay brown moist")
    
    Input:  "silty clay brown moist"  — no range stated
    Output: (None, None, "silty clay brown moist")
    """
    match = re.search( r'(\d+\.?\d*)\s*(?:to|-)\s*(\d+\.?\d*)\s*(?:inches|"?)', layer_slice)
    if not match:
        return (None, None, layer_slice)
    
    start = float(match.group(1))
    end = float(match.group(2))
    # Remove the depth range from the slice before passing to Claude
    remainder = layer_slice[:match.start()] + layer_slice[match.end():]
    return (start, end, remainder.strip())

# ─────────────────────────────────────────────
# BLOW COUNT PARSER
# ─────────────────────────────────────────────

def looks_like_runon_blowcounts(blows_string: str) -> bool:
    """
    Whisper-mishearing safeguard.

    Returns True when the blows segment looks like Whisper concatenated a
    sequence of small single-digit blow counts into one numeric token —
    e.g. the user said "3, 7, 9, 9" but Whisper produced "3799".

    Conservative trigger conditions (all must hold):
      • exactly one numeric token in the segment
      • that token is 3 or 4 digits long
      • no zero digits (avoids splitting legitimate values like 100, 250, 1080)
      • no '/' or 'for' refusal notation present (those are real >50 counts)
    """
    s = (blows_string or "").strip().lower()
    if not s:
        return False
    if "/" in s or " for " in s:
        return False
    cleaned = re.sub(r"[.,?;]", " ", s)
    numeric_tokens = [t for t in cleaned.split() if t.isdigit()]
    if len(numeric_tokens) != 1:
        return False
    digits = numeric_tokens[0]
    if not (3 <= len(digits) <= 4):
        return False
    if "0" in digits:
        return False
    return True


def parse_blow_counts_from_string(blows_string: str) -> tuple:
    """
    Converts the blows segment string into (blow_counts, pen_depths).

    Detects refusal notation "50 for 3" or "50/3" and extracts pen depth.
    Normal intervals default to 6 inches penetration.

    Input:  "12 17 19 23"         → ([12, 17, 19, 23], [6, 6, 6, 6])
    Input:  "12 17 50 for 3 23"   → ([12, 17, 50, 23], [6, 6, 3, 6])
    Input:  "50/3"                → ([50], [3])
    Input:  ""                    → ([], [])
    Input:  "3799"                → ([3, 7, 9, 9], [6, 6, 6, 6])  # run-on auto-split
    """
    if not blows_string:
        return ([], [])

    # Run-on safeguard — Whisper sometimes collapses "3, 7, 9, 9" into "3799".
    # Detect the pattern and split into single-digit blow counts before the
    # main parsing loop. Pipeline emits an amber review flag when this fires.
    if looks_like_runon_blowcounts(blows_string):
        digits = [int(d) for d in re.sub(r"[^\d]", "", blows_string)]
        return (digits, [6.0] * len(digits))

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
    Input:  "full"  → (None, "", "Recovery not found - manual input required")
    """
    if not recovery_string:
        return (None,"", "Recovery not found - manual input required")

    num_string = ""
    remainder = ""
    for i, char in enumerate(recovery_string):
        if char.isdigit():
            num_string += char
        elif (char == "." and num_string
              and i + 1 < len(recovery_string)
              and recovery_string[i + 1].isdigit()):
            num_string += char
        else:
            if num_string:
                remainder = recovery_string[i:]
                break
            
    remainder = remainder.replace("inches","").replace("inch","")
    remainder = remainder.strip(" ,.")

    if not num_string:
        return (None, remainder, "Recovery not found - manual input required")

    try:
        return (float(num_string),remainder, None)
    except ValueError:
        return (None, remainder,"Recovery not found - manual input required")


# ─────────────────────────────────────────────
# USCS SYMBOL PARSER
# ─────────────────────────────────────────────

VALID_USCS_SYMBOLS = {
    "gw","gp","gm","gc","sw","sp","sm","sc","cl","ml","ol","ch","mh","oh","pt"
}

def parse_uscs_symbol(text: str):
    """
    Extracts USCS group symbol from description segment.
    Returns uppercase symbol string or None.

    Input:  "silty clay symbol is cl dark brown"  → "CL"
    Input:  "sand groupname is SM"                → "SM"
    Input:  "silty clay dark brown moist"         → None
    """
    if not text:
        return None
    patterns = [
        r'group\s*name\s+is\s+([a-z]{2})',
        r'group\s*symbol\s+is\s+([a-z]{2})',
        r'symbol\s+is\s+([a-z]{2})',
        r'symbol\s+([a-z]{2})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            sym = match.group(1).lower()
            if sym in VALID_USCS_SYMBOLS:
                return sym.upper()
    return None


# ─────────────────────────────────────────────
# PLASTICITY PARSER
# ─────────────────────────────────────────────

def parse_plasticity(text: str):
    """
    Extracts plasticity descriptor from description segment.
    Returns standardised string or None.

    Input:  "plasticity is low"    → "low plasticity"
    Input:  "high plasticity"      → "high plasticity"
    Input:  "little bit plastic"   → "slightly plastic"
    Input:  "non plastic"          → "non-plastic"
    """
    if not text:
        return None
    t = text.lower()
    mappings = [
        ("little bit plastic",   "slightly plastic"),
        ("slightly plastic",     "slightly plastic"),
        ("plasticity is high",   "high plasticity"),
        ("plasticity is low",    "low plasticity"),
        ("plasticity is non",    "non-plastic"),
        ("high plasticity",      "high plasticity"),
        ("low plasticity",       "low plasticity"),
        ("non-plastic",          "non-plastic"),
        ("non plastic",          "non-plastic"),
    ]
    for phrase, result in sorted(mappings, key=lambda x: len(x[0]), reverse=True):
        if phrase in t:
            return result
    return None


# ─────────────────────────────────────────────
# GRADATION PARSER
# ─────────────────────────────────────────────

def parse_gradation(text: str):
    """
    Extracts gradation descriptor from description segment.
    Returns standardised string or None.

    Input:  "poorly graded"  → "poorly graded"
    Input:  "well graded"    → "well graded"
    """
    if not text:
        return None
    t = text.lower()
    if "poorly graded" in t:
        return "poorly graded"
    if "well graded" in t:
        return "well graded"
    return None