# pipeline.py
# The coordinator — takes transcript + blow counts, runs the full pipeline,
# and returns a formatted Envision-style log description.
# This is the ONLY file that touches the Claude API.
# All classification is done by Python before the API call is made.
from whisper import transcribe
from parser import parse_transcript
from classification_engine import get_consistency_density, parse_blow_counts
import json
import anthropic
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env file from the same directory as this script
# override=True ensures .env always takes precedence over any cached shell variables
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ─────────────────────────────────────────────
# ENVISION SYSTEM PROMPT
# Tells Claude its role is FORMATTING ONLY.
# All classification (consistency/density terms) has already been
# calculated by Python before this prompt is sent.
# Claude must use the provided values exactly as given.
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
10. If split_layer is true: return exactly "MANUAL REVIEW REQUIRED" on the 
    first line, then list each soil name from soil_name array as a separate 
    entry with its shared properties. Format: "- [SOIL NAME]: color, moisture, consistency."

Return only the formatted description string. No explanation, no extra text."""


# ─────────────────────────────────────────────
# COMPONENT SORTER
# Ensures components are always ordered most → least significant
# before being sent to Claude.
# Order: some (0) → trace to some (1) → trace (2)
# Unknown quantifiers sort last (99) — defensive fallback.
# ─────────────────────────────────────────────

def sort_components(components: list) -> list:
    """
    Sorts component list by quantifier significance order:
    some → trace to some → trace
    
    This ensures the formatted description always lists
    dominant components before minor ones, matching Envision's style.
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

def combination(transcript: str, blow_counts: list, pen_depths: list) -> dict:
    """
    Main pipeline function. Full flow:
    
    1. parse_transcript(transcript) → structured JSON with all soil fields
    2. Early exit if soil_name is None (irrelevant/unrecognized transcript)
    3. sort_components() — order components most to least significant
    4. parse_blow_counts(blow_counts, pen_depths) → n_value + n_value_log
    5. get_consistency_density(soil_name, n_value) → consistency/density term
    6. Add consistency and n_value_log to soil_data dict
    7. Send complete soil_data JSON to Claude API with SYSTEM_PROMPT
    8. Return {description, n_value_log, flags}
    
    Inputs:
    - transcript:   raw voice transcript string from Whisper (or typed text for now)
    - blow_counts:  list of 1–4 SPT blow count integers
    - pen_depths:   list of corresponding penetration depths in inches
    
    Returns dict:
    {
        "description": formatted Envision log string (or None if irrelevant),
        "n_value_log": string for the log e.g. "18" or "62/254mm",
        "flags":       list of any manual review messages for the UI
    }
    """

    # Step 1 — parse the transcript into structured fields
    soil_data = parse_transcript(transcript)

    # Step 2 — early exit if transcript was irrelevant or soil unrecognized
    # No point calling the API if we have nothing to format
    if soil_data["soil_name"] is None:
        return {
            "description": None,
            "n_value_log": None,
            "flags": soil_data["flags"]
        }

    # Step 3 — sort components most to least before sending to Claude
    soil_data["components"] = sort_components(soil_data["components"])

    # Step 4 — process blow counts into N-value and log notation
    blow_count_data = parse_blow_counts(blow_counts, pen_depths)

    # Step 5 — classify consistency/density from soil name + N-value
    # Python does this — Claude never determines this term
    consistency = get_consistency_density(soil_data["soil_name"], blow_count_data["n_value"])
    soil_data["consistency"] = consistency     

    # Step 6 — add log notation to the data dict so Claude can include it if needed
    soil_data["n_value_log"] = blow_count_data["n_value_log"]

    # Step 7 — send fully assembled JSON to Claude API
    # Claude's only job here is formatting — all values are already determined
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": json.dumps(soil_data, indent=2)  # indent=2 for readable input
            }
        ]
    )

    # Step 8 — return the formatted description + any flags for the UI
    return {
        "description": message.content[0].text,
        "n_value_log": blow_count_data["n_value_log"],
        "flags": soil_data["flags"]  # pass through any extraction flags to UI
    }



def run_from_voice(audio_file_path: str, blow_counts: list, pen_depths: list) -> dict:
    """
    Full pipeline starting from an audio file.
    
    1. Transcribe audio file using Whisper
    2. Pass transcript to combination()
    3. Return formatted description
    
    Input:  audio file path + blow counts + pen depths
    Output: same dict as combination()
    """
    transcript = transcribe(audio_file_path)
    print(f"Transcript: {transcript}")  # helpful for debugging during field testing
    return combination(transcript, blow_counts, pen_depths)