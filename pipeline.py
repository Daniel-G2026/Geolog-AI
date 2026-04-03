# pipeline.py
# The coordinator — takes transcript + blow counts, runs the full pipeline,
# and returns a complete SampleEntry object.
# This is the ONLY file that touches the Claude API.
# All geotechnical math is done by Python before any API call is made.

import json
import os
import anthropic
from math import isclose
from dotenv import load_dotenv
from pathlib import Path
from whisper import transcribe
from classification_engine import get_consistency_density, parse_blow_counts
from parser import segment_transcript, parse_blow_counts_from_string, parse_recovery
from models import SampleEntry


# Load .env file from the same directory as this script.
# override=True ensures .env always takes precedence over cached shell variables.
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ─────────────────────────────────────────────
# ENVISION FORMATTING PROMPT
# Claude's role is FORMATTING ONLY.
# All classification has already been done by Python.
# Claude must use every provided value exactly as given.
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a geotechnical logger for Envision Consultants Ltd.
Your job is to format the provided structured soil data into a report-ready description
that exactly matches Envision's logging style.
Do NOT determine or infer consistency or density — it is already provided to you.
Use it exactly as given.

RULES:
1. Primary soil name in ALL CAPS, followed by a colon
2. Secondary components ordered most to least: some → trace to some → trace
3. Field order: PRIMARY NAME: components, inclusions, color, moisture, consistency.
4. Color: use exactly as provided
5. Moisture: use exactly as provided
6. Consistency/density: use exactly as provided — do not change it
7. FILL prefix when fill is true: start with "FILL:" then list components,
   inclusions, color, moisture, consistency. Do NOT include the soil_name
   as a separate capitalized header. Do NOT add a colon after the soil type.
8. Transitional soils: use TO between names
9. End every description with a period
10. If split_layer is true: return each soil name from the list following the soil name format in rule 1, seperating them with a / then continue to describe the rest of the characteristicsFormat: "- [SOIL NAME/SOIL NAME]: color, moisture, consistency." if only one soil name then no need for the  /

Return only the formatted description string. No explanation, no extra text."""


# ─────────────────────────────────────────────
# CLAUDE EXTRACTION PROMPT
# Replaces the old substring parser for soil description fields.
# Claude extracts structured fields from natural speech.
# Handles messy phrasing, unusual inclusions, and speech variation
# that rigid substring matching cannot handle.
# ─────────────────────────────────────────────


EXTRACTION_PROMPT = """You are a geotechnical data extraction assistant.
Extract structured fields from a field technician's soil description.
Return ONLY a valid JSON object with these exact keys. No explanation, no markdown, no extra text.

The following are the ONLY valid primary soil names: ["silty clay", "clayey silt", "silt", "clay", "silty sand", "sandy silt", "sand and gravel", "sand"]. Any soil that matches one of these is a primary soil name, not a component.
Fields to extract:
- soil_name: primary soil classification (e.g. "silty clay till", "sandy silt")
- components: list of secondary soils with quantifiers (e.g. ["trace gravel", "some sand", "trace to some clay"])
- color: soil color (e.g. "brown", "dark brown", "reddish brown", "grey")
- moisture: moisture condition (e.g. "moist", "wet", "very moist to wet", "dry")
- inclusions: list of ALL inclusions or foreign objects found in the sample
- fill: true if "fill" appears as a soil type descriptor, false otherwise

Rules:
- soil_name must NOT include trace/some quantifiers
    if multiple valid soil names are detected, return soil_name as a list of strings — if only one, return it as a single string
- components are secondary soils preceded by trace/some/trace to some
- inclusions: standard geological terms (rock fragments, oxidation) go in as-is.
  Organic matter of any kind (roots, branches, organics, rootlets) → "organic inclusions"
  Unusual foreign objects (coin, brick fragment, glass, metal debris) → include exactly as found as "foreign object" e.g "glass"
- Use null for missing strings
- Use empty list [] for missing lists
- fill is always true or false, never null
- Return raw lowercase values only"""


# ─────────────────────────────────────────────
# DESCRIPTION FIELD EXTRACTOR
# ─────────────────────────────────────────────

def extract_description_fields(description_segment: str) -> dict:
    """
    Sends the description segment to Claude and extracts structured soil fields.
    Replaces the old substring-based parser — handles messy natural speech,
    unusual inclusions, and any variation in how the tech describes the soil.

    Input:  "silty clay till trace sand dark brown moist"
    Output: {
        "soil_name": "silty clay till",
        "components": ["trace sand"],
        "color": "dark brown",
        "moisture": "moist",
        "inclusions": [],
        "fill": false
    }

    Returns dict with null values for missing fields — never crashes.
    """
    if not description_segment:
        return {
            "soil_name": None,
            "components": [],
            "color": None,
            "moisture": None,
            "inclusions": [],
            "fill": False
        }

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": description_segment}]
    )

    try:
        raw = message.content[0].text.strip()
        # Strip markdown code fences if Claude adds them
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "soil_name": None,
            "components": [],
            "color": None,
            "moisture": None,
            "inclusions": [],
            "fill": False,
            "parse_error": "Claude extraction failed — manual input required"
        }


# ─────────────────────────────────────────────
# COMPONENT SORTER
# Orders components most → least significant before sending to Claude.
# Envision style: some → trace to some → trace
# Unknown quantifiers sort last (99) — defensive fallback.
# ─────────────────────────────────────────────

def sort_components(components: list) -> list:
    """
    Sorts component list by quantifier significance:
    some (0) → trace to some (1) → trace (2)
    """
    QUANTIFIER_ORDER = {"some": 0, "trace to some": 1, "trace": 2}

    def sort_key(component):
        for quantifier, order in QUANTIFIER_ORDER.items():
            if component.startswith(quantifier):
                return order
        return 99  # unknown quantifier — sort to end

    return sorted(components, key=sort_key)


# ─────────────────────────────────────────────
# MAIN PIPELINE FUNCTION
# ─────────────────────────────────────────────

def combination(transcript: str, blow_counts: list,
                sample_no: int, depth_ft: float, sample_type: str = "SS") -> SampleEntry:
    """
    Main pipeline function. Returns a complete SampleEntry object.

    Flow:
    1.  segment_transcript()           — split transcript by keywords
    2.  extract_description_fields()   — Claude extracts soil fields from description segment
    3.  Early exit if no soil name found
    4.  parse_blow_counts_from_string() — parse blows string if blow_counts not provided
    4b. Early exit if len(pen_depths) ≠ len(blow_counts)
    5.  parse_blow_counts()            — calculate N-value and log notation
    6.  get_consistency_density()      — classify consistency/density from N-value
    7.  parse_recovery()               — extract recovery in inches, convert to mm
    8.  sort_components()              — order components most to least
    9.  Assemble soil_data dict        — all fields ready for Claude formatting
    10. Claude formatting prompt       — produce Envision description string
    11. Recovery validation            — flag partial recovery in comments
    12. Return complete SampleEntry

    Inputs:
    - transcript:   raw voice transcript string from Whisper
    - blow_counts:  list of 1-4 ints from tap UI, or [] to parse from transcript
    - pen_depths:   list of penetration depths in inches from tap UI
    - sample_no:    sample number for this entry
    - depth_ft:     depth in feet as logged on site
    - sample_type:  "SS" = spoon sample (default), "RC" = rock core (future)
    """

    # Step 1 — segment the transcript by keywords
    segments = segment_transcript(transcript)

    # Step 2 — extract description fields via Claude
    description_segment = segments.get("description", "")
    fields = extract_description_fields(description_segment)

    # Step 3 — early exit if no soil name found
    depth_m = round(depth_ft * 0.3048, 2)
    pen_depths = []
    if not fields.get("soil_name"):
        return SampleEntry(
            depth_ft=depth_ft,
            depth_m=depth_m,
            sample_type=sample_type,
            sample_no=sample_no,
            blow_counts=blow_counts,
            pen_depths=pen_depths,
            n_value=0,
            n_value_log="",
            refusal=False,
            raw_transcript=transcript,
            flags=["No soil type recognized — manual input required"]
        )

    # Step 4 — parse blow counts from transcript if not provided via tap UI
    if not blow_counts:
        blow_counts, pen_depths = parse_blow_counts_from_string(segments.get("blows", ""))
    else:
        pen_depths = [6.0] * len(blow_counts)

    # Step 4b — each blow count interval needs one penetration depth (inches)
    if len(pen_depths) != len(blow_counts):
        return SampleEntry(
            depth_ft=depth_ft,
            depth_m=depth_m,
            sample_type=sample_type,
            sample_no=sample_no,
            blow_counts=blow_counts,
            pen_depths=pen_depths,
            n_value=0,
            n_value_log="",
            refusal=False,
            raw_transcript=transcript,
            flags=[
                "Number of pen depths must match number of blow counts "
                f"({len(pen_depths)} depths vs {len(blow_counts)} blows) — "
                "enter one penetration depth per blow interval."
            ],
        )

    # Step 5 — calculate N-value and log notation
    blow_count_data = parse_blow_counts(blow_counts, pen_depths)

    # Step 6 — classify consistency/density from N-value
    # Python does this — Claude never determines this term

    consistency = get_consistency_density(fields["soil_name"], blow_count_data["n_value"])
    if isinstance(fields["soil_name"],list) and len(fields["soil_name"]) > 1:
        soil_name_flag = "Multiple soil names detected - Manual review required"
    else:
        soil_name_flag = ""
    # Step 7 — parse recovery in inches and convert to mm
    recovery_inches, remainder_string,recovery_flag = parse_recovery(segments.get("recovery", ""))
    recovery_mm = round(recovery_inches * 25.4) if recovery_inches else None

    # Step 8 — sort components most to least significant
    fields["components"] = sort_components(fields.get("components", []))
    

    # Step 9 — assemble complete soil_data for Claude formatting
    soil_data = {
        "soil_name": fields["soil_name"],
        "components": fields["components"],
        "inclusions": fields.get("inclusions", []),
        "color": fields.get("color"),
        "moisture": fields.get("moisture"),
        "fill": fields.get("fill", False),
        "split_layer": isinstance(fields["soil_name"], list),
        "consistency": consistency,
    }

    # Step 10 — Claude formatting prompt produces the Envision description string
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(soil_data, indent=2)}]
    )
    description = message.content[0].text

    # Step 11 — recovery vs sum of pen depths (total penetration interval)
    # Recovery cannot exceed total inches driven. When it does, flag for manual review.
    # Recovery below total penetration: no comment or flag changes (voice comments unchanged).
    comments = segments.get("comments")
    comments.strip(" ,.")
    if not comments:
        comments = remainder_string.strip(" ,.")
    total_penetration = sum(pen_depths)
    recovery_vs_pen_flags = []
    if recovery_inches is not None:
        if not isclose(recovery_inches, total_penetration, rel_tol=0.0, abs_tol=0.05):
            if recovery_inches > total_penetration:
                recovery_vs_pen_flags.append(
                    "Recovery exceeds total penetration "
                    f"({recovery_inches}\" recovery vs {total_penetration}\" penetrated) — "
                    "manual review required"
                )

    # Collect all flags
    flags = list(recovery_vs_pen_flags)
    if not fields.get("color"):
        flags.append("Color not found — manual input required")
    if not fields.get("moisture"):
        flags.append("Moisture not found — manual input required")
    if consistency is None:
        flags.append("Soil type unrecognized — consistency requires manual input")
    if recovery_flag:
        flags.append(recovery_flag)
    if fields.get("parse_error"):
        flags.append(fields["parse_error"])
    if soil_name_flag:
        flags.append(soil_name_flag)
    # Step 12 — return complete SampleEntry object
    return SampleEntry(
        depth_ft=depth_ft,
        depth_m=depth_m,
        sample_type=sample_type,
        sample_no=sample_no,
        blow_counts=blow_counts,
        pen_depths=pen_depths,
        n_value=blow_count_data["n_value"],
        n_value_log=blow_count_data["n_value_log"],
        refusal=blow_count_data["refusal"],
        recovery_inches=recovery_inches,
        recovery_mm=recovery_mm,
        raw_transcript=transcript,
        description=description,
        flags=flags,
        comments=comments
    )

# ─────────────────────────────────────────────
# VOICE ENTRY POINT
# ─────────────────────────────────────────────

def run_from_voice(audio_file_path: str,
                   sample_no: int, depth_ft: float,
                   sample_type: str = "SS") -> SampleEntry:
    """
    Full pipeline starting from an audio file.
    Blow counts come from the transcript — no need to pass them separately.
    Pen depths come from tap UI input and must be passed as a parameter.

    Returns a complete SampleEntry object.
    """
    transcript = transcribe(audio_file_path)
    return combination(
        transcript=transcript,
        blow_counts=[],      # always empty — extracted from transcript
        sample_no=sample_no,
        depth_ft=depth_ft,
        sample_type=sample_type
    )