# parser.py
# Parses a raw voice transcript string into a structured JSON object
# ready to be sent to the Claude API via pipeline.py.
# Scope: Soil only. Rock core parsing to be added later.

import re
from classification_engine import COHESIVE_TERMS, COHESIONLESS_TERMS


# ─────────────────────────────────────────────
# SOIL TERM LOOKUP LIST
# Imported from classification_engine and combined into one sorted list.
# Sorted longest-first so more specific terms are always matched before
# shorter substrings they contain (e.g. "sandy silt" before "silt").
# ─────────────────────────────────────────────

ALL_SOIL_TERMS = sorted(COHESIVE_TERMS + COHESIONLESS_TERMS, key=len, reverse=True)


# ─────────────────────────────────────────────
# KNOWN VALUE LISTS
# All ordered longest-first to prevent partial substring matches.
# e.g. "dark brown" must come before "brown" or "dark brown" would
# match as just "brown".
# ─────────────────────────────────────────────

KNOWN_COLORS = ["dark brown", "reddish brown", "brown", "grey", "black"]

KNOWN_MOISTURE = ["very moist to wet", "moist to wet", "very moist", "moist", "dry", "wet"]

# Inclusions list is mixed — plain strings for simple terms,
# dict for organic inclusions which has multiple synonyms that all
# map to the same standard output term "organic inclusions"
KNOWN_INCLUSIONS = [
    "rock fragments",
    {"organic inclusions": ["rootlets", "organics", "organic"]},
    "oxidation"
]

# Quantifiers ordered longest-first — "trace to some" before "trace" and "some"
KNOWN_QUANTIFIERS = ["trace to some", "some", "trace"]

# Precompute all valid quantifier + soil word pairs at module load time
# so extract_components doesn't rebuild this list on every call
secondary_soils = ["clay", "sand", "gravel", "silt"]
PAIRS = []
for quantifier in KNOWN_QUANTIFIERS:
    for soil in secondary_soils:
        PAIRS.append(f"{quantifier} {soil}")

# Maps all accepted synonyms to their standard keyword
KEYWORD_SYNONYMS = [
    {"description": "description",
    "soil description": "description",
    "soil": "description",
    "desc": "description"},
    
   
    {"blows":"blows",
     "blow counts": "blows",
    "blowcounts": "blows",
    "blow count": "blows",
    "counts": "blows"},
    
    {"recovery": "recovery",
    "rec": "recovery"},
    
    {"comments": "comments",
    "comment": "comments",
    "remarks": "comments",
    "remark": "comments",
    "notes": "comments",
    "note": "comments"},
    
    {"cgd": "cgd"},
    {"pid": "pid"},
    {"cone": "cone"}
]

# ─────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────
def segment_transcript(transcript: str):

    standard_keywords = []
    text = transcript.lower().strip()
    for synonym_group in KEYWORD_SYNONYMS:
        for synonym in sorted(synonym_group.keys(),key=len,reverse=True):
            standard = synonym_group[synonym]
            if synonym in text:
                text = text.replace(synonym,standard)
                standard_keywords.append(standard)
                break

    keyword_found = []
    for keyword in standard_keywords:
        if keyword in text:
            index = text.find(keyword)
            keyword_found.append((index,keyword))
    keyword_found = sorted(keyword_found,key=lambda x:x[0])

    segment_dict = {}
    for i, (index,keyword) in enumerate(keyword_found):
        #start of content right after the keyword itself
        start = index +len(keyword)
        # end of content is the start of 
        if i+1 < len(keyword_found):
            end = keyword_found[i+1][0]
        else:
            end = len(text)
        segment_dict[keyword] = text[start:end].strip()

    return    segment_dict

def parse_blow_counts_from_string(blows_string: str) -> list:
  
    if not blows_string:
        return []
    
    raw = blows_string.replace(",", " ").split()
    
    counts = []
    for item in raw:
        try:
            counts.append(int(item))
        except ValueError:
            continue  # skip anything that isn't a number
    
    if len(counts) == 0 or len(counts) > 4:
        return []
    
    return counts

def parse_recovery(recovery_string: str) -> tuple:
    if not recovery_string:
        return (None, "Recovery not found - manual input required")
    
    num_string = ""
    for i, char in enumerate(recovery_string):
        if char.isdigit():
            num_string += char
        elif char == "." and num_string and i + 1 < len(recovery_string) and recovery_string[i + 1].isdigit():
            num_string += char
        elif char == " " and num_string:
            break
    
    if not num_string:
        return (None, "Recovery not found - manual input required")
    
    try:
        return (float(num_string), None)
    except ValueError:
        return (None, "Recovery not found - manual input required")

def substring_check(terms: list, transcript: str) -> list:
    """
    Loops through a list of terms and returns all that appear in the transcript.
    
    Includes a collision guard: if a shorter term is already a substring of
    something already matched, it won't be added again.
    
    Example: if "sandy silt" already matched, "silt" won't also be added
    because "silt" is contained within "sandy silt".
    """
    matches = []
    for term in terms:
        if term in transcript:
            # Only add if this term isn't already part of a longer match
            if not any(term in already_matched for already_matched in matches):
                matches.append(term)
    return matches


def filter_components(components: list, soil_name: str) -> list:
    """
    Logic: gets the last word of each component (the soil word),
    checks if it appears in the primary soil name. If it does, filter it out.
    """
    soil_name_words = soil_name.lower().split()
    filtered = []

    for component in components:
        # Last word in component string is always the soil word
        # e.g. "trace sand" → "sand", "trace to some clay" → "clay"
        component_soil_word = component.split()[-1]

        if component_soil_word not in soil_name_words:
            filtered.append(component)

    return filtered


# ─────────────────────────────────────────────
# EXTRACTION FUNCTIONS
# Each returns a tuple: (value, flag_message)
# flag_message is None when extraction succeeded,
# or a string when manual review is needed.
# ─────────────────────────────────────────────

def is_relevant(transcript: str) -> bool:
    """
    First gate in the pipeline. Returns True only if the transcript
    contains at least one recognized soil term.
    Returns False for completely unrelated speech — no point parsing further.
    """
    return any(term in transcript.lower() for term in ALL_SOIL_TERMS)


def extract_soil_name(transcript: str, components: list):
    """
    Returns:
    - (string, None)       → single match, clean
    - (list, flag_message) → multiple matches, triggers split_layer = True
    - (None, flag_message) → no match found
    """
    transcript_lower = transcript.lower()

    # Strip component terms from transcript before searching for soil name
    # so secondary soil words don't get mistaken for the primary soil
    cleaned = transcript_lower
    for component in components:
        cleaned = cleaned.replace(component, "")

    matched_soil = substring_check(ALL_SOIL_TERMS, cleaned)

    # Append "till" to any matched soil name if "till" appears in the transcript
    # Uses word boundary regex to avoid matching "untill" or "distilled" etc.
    till_pattern = r"\btill\b"
    for i, soil in enumerate(matched_soil):
        if re.search(till_pattern, transcript_lower):
            matched_soil[i] = f"{soil} till"

    if len(matched_soil) == 0:
        return (None, "No soil type recognized - manual input required")
    elif len(matched_soil) == 1:
        return (matched_soil[0], None)
    else:
        # Multiple soils detected — flag for manual review
        # pipeline.py will set split_layer = True and Claude handles formatting
        return (matched_soil, "Multiple soil types detected - manual review required")


def extract_color(transcript: str):
    """
    Scans for color terms using substring_check with KNOWN_COLORS.
    Returns single color string or flags multiple colors for manual review.
    """
    transcript_lower = transcript.lower()
    matched_colour = substring_check(KNOWN_COLORS, transcript_lower)

    if len(matched_colour) == 0:
        return (None, "Colour not recognized - manual input required")
    elif len(matched_colour) == 1:
        return (matched_colour[0], None)
    else:
        return (matched_colour, "Multiple colours detected - manual review required")


def extract_moisture(transcript: str):
    """
    Scans for moisture terms using substring_check with KNOWN_MOISTURE.
    
    Missing moisture is flagged but does NOT block the pipeline —
    description is still generated and flag is passed to UI for tech to see.
    """
    transcript_lower = transcript.lower()
    matched_moisture = substring_check(KNOWN_MOISTURE, transcript_lower)

    if len(matched_moisture) == 0:
        return (None, "Moisture not found - manual input required")
    elif len(matched_moisture) == 1:
        return (matched_moisture[0], None)
    else:
        return (matched_moisture, "Multiple moistures detected - manual review required")


def extract_components(transcript: str):
    """
    Finds all secondary soil components by scanning for PAIRS
    (quantifier + soil word combinations precomputed at module load).
    
    Returns a list — multiple components are valid and expected.
    Empty list with no flag is also valid (not every sample has components).
    """
    transcript_lower = transcript.lower()
    components = substring_check(PAIRS, transcript_lower)
    return (components, None) if components else ([], None)


def extract_inclusions(transcript: str):
    """
    Handles two types of inclusions:
    - Plain strings: matched directly (rock fragments, oxidation)
    - Dict entry: organic inclusions has synonyms (rootlets, organics, organic)
      that all map to the standard term "organic inclusions".
      Once one synonym matches, stops checking the rest (break).
    """
    transcript_lower = transcript.lower()
    inclusions = []

    for item in KNOWN_INCLUSIONS:
        if isinstance(item, dict):
            # Dict entry — check all synonyms, map to standard term
            for standard_term, synonyms in item.items():
                for synonym in synonyms:
                    if synonym in transcript_lower:
                        if standard_term not in inclusions:
                            inclusions.append(standard_term)
                        break  # one synonym match is enough — stop checking rest
        else:
            # Plain string — direct match
            if item in transcript_lower:
                if item not in inclusions:
                    inclusions.append(item)

    return (inclusions, None) if inclusions else ([], None)


def extract_fill(transcript: str):
    """
    Detects FILL material using regex word boundary check.
    Word boundary \\b prevents false matches from words like
    "backfill" or "fulfilled" which contain "fill" as a substring.
    """
    transcript_lower = transcript.lower()
    pattern = r"\bfill\b"

    if re.search(pattern, transcript_lower):
        return (True, None)
    else:
        return (False, None)


# ─────────────────────────────────────────────
# MAIN PARSE FUNCTION
# ─────────────────────────────────────────────

def parse_transcript(transcript: str) -> dict:


    # Gate 1 — check if transcript is relevant at all before doing any work
    if not is_relevant(transcript):
        return {
            "soil_name": None,
            "components": [],
            "inclusions": [],
            "color": None,
            "moisture": None,
            "fill": False,
            "split_layer": False,
            "flags": ["Transcript not recognized as a soil description — manual input required"]
        }

    # ── Extract all fields ──
    # Components first — needed to clean transcript before soil name extraction
    components, component_flag = extract_components(transcript)
    soil_name, soil_flag = extract_soil_name(transcript, components)

    # Filter out components whose soil word is already in the primary soil name
    # e.g. if soil is "silty clay", remove "trace to some clay" from components
    if isinstance(soil_name, str):
        components = filter_components(components, soil_name)

    inclusion, inclusion_flag = extract_inclusions(transcript)
    colour, colour_flag = extract_color(transcript)
    moisture, moisture_flag = extract_moisture(transcript)
    fill, fill_flag = extract_fill(transcript)

    # Collect all non-None flags into a single list for the UI
    flags = [f for f in [soil_flag, component_flag, inclusion_flag,
                          colour_flag, moisture_flag, fill_flag] if f is not None]

    return {
        "soil_name": soil_name,
        "components": components,
        "inclusions": inclusion,
        "color": colour,
        "moisture": moisture,
        "fill": fill,
        "split_layer": isinstance(soil_name, list),  # True only when multiple soils detected
        "flags": flags
    }
