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
from whisper import transcribe, correct_transcript
from classification_engine import get_consistency_density, parse_blow_counts
from parser import segment_transcript, parse_blow_counts_from_string, parse_recovery, is_split_layer, looks_like_runon_blowcounts
from models import SampleEntry
import re


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


ASTM_SYSTEM_PROMPT = """You are a geotechnical soil logger formatting structured field soil data into a report-ready description using ASTM D2488 / USCS-style field logging conventions.

Your job is to produce a clear, professional soil description based on the structured data provided.

IMPORTANT:
- Use only the structured data provided. Do not invent or infer any missing properties.
- If a field is null, empty, or not provided, omit it.
- If consistency/density is provided, use it exactly as given.
- Do not alter wording unless needed for grammar, singular/plural agreement, or proper report formatting.

FORMAT RULES:
1. Start with the soil classification phrase built from soil_name.
   - Examples: "silty clay", "sandy silt", "sand and gravel"
2. If uscs_symbol is provided, place it immediately after the soil classification in parentheses.
   - e.g. "Silty clay (CL)"
3. If fill is true, prefix the description with "Fill,".
4. After the main soil classification, include remaining fields in this order:
   - additional quantified components
   - inclusions / foreign materials
   - color
   - moisture
   - consistency or density
   - plasticity (if provided)
   - gradation (if provided)
5. Use commas to separate descriptors.
6. End the description with a period.
7. Keep the tone concise and engineering-report ready.
8. Do not use bullet points.
9. Return only the final formatted description string.

SPECIAL HANDLING:
- Components should read naturally: "with trace sand", "some gravel", "trace organics"
- Inclusions should be included only if present.
- Do not repeat the primary soil name as a component.
- If split_layer is true and multiple soil names are provided, join them using " / " then continue with shared descriptors.
- Do not add extra soil names.
- Do not duplicate any soil name as a component.
- Continue with shared descriptors after the joined soil names.
- Example: "Silty clay / Sand, brown, moist, compact.
- If only one soil name is present, do not use a slash.

OUTPUT EXAMPLES:
- "Silty clay (CL), with trace sand, brown, moist, stiff."
- "Fill, sandy silt, with gravel and brick fragments, dark brown, moist."
- "Sand and gravel, wet, dense, poorly graded."

"""

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
- plasticity: one of ["non-plastic", "slightly plastic", "low plasticity", "high plasticity"] or null if not mentioned
- gradation: one of ["poorly graded", "well graded"] or null if not mentioned
- depth_start: float or null — depth range start in inches
- depth_end: float or null — depth range end in inches
- uscs_symbol: one of ["GW","GP","GM","GC","SW","SP","SM","SC","CL","ML","OL","CH","MH","OH","PT"] or null if not mentioned

Rules:
- soil_name must NOT include trace/some quantifiers
    if multiple valid soil names are detected, return soil_name as a list of strings — if only one, return it as a single string
- components are secondary soils preceded by trace/some/trace to some
- inclusions: standard geological terms (rock fragments, oxidation,concrete fragments,cobbles,boulders,rootlets) go in as-is.
  Organic matter of any kind (organic,etc) → "organic inclusions"
  Unusual foreign objects (coin, brick fragment, glass, metal debris) → include exactly as found as "foreign object" e.g "glass"
  - plasticity: map any phrasing about plasticity to one of the four enum values.
    "plasticity is low", "low plasticity", "plasticity that's low", "has a low plasticity" → "low plasticity"
    "plasticity is high", "high plasticity" → "high plasticity"
    "non plastic", "non-plastic", "not plastic" → "non-plastic"
    "slightly plastic", "little bit plastic", "barely plastic" → "slightly plastic"
 - gradation: map any phrasing about gradation to one of the two enum values.
    "poorly graded", "badly graded" → "poorly graded"
    "well graded", "well-graded" → "well graded"
    If gradation is not mentioned, return null.
- depth_start and depth_end: extract any phrasing like "0 to 14 inches", "14 inches to 20 inches", "0-14in", "from 14 to 20 inches" into numeric floats. If no depth range is stated, return null.
- uscs_symbol: map phrasings like "symbol is CL", "group name CL", "group symbol CL", "USCS CL", "(CL)", or transcription artifacts ("see L" → "CL", "see H" → "CH") to the matching symbol from the enum. Return uppercase. If no symbol is stated, return null.
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
            "fill": False,
            "plasticity": None,
            "gradation": None,
            "depth_start": None,
            "depth_end": None,
            "uscs_symbol": None,
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
            "plasticity": None,
            "gradation": None,
            "depth_start": None,
            "depth_end": None,
            "uscs_symbol": None,
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
# Parse split layers
# ─────────────────────────────────────────────
def parse_split_layers(description_segment: str) -> list:
    """
    Detects and slices layer sub-keywords from the description segment.
    Returns a list of dicts, one per layer, with extracted fields and
    shared field inheritance applied bidirectionally.
    """
    text = description_segment.lower()
    
    # Find all "layer N" occurrences and their positions
    
    matches = list(re.finditer(r'\blayer\s+(\d+)\b', text))
    
    if len(matches) < 2:
        return []  # not a split layer — caller should fall back to single path
    
    # Slice text between consecutive layer keywords
    slices = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        slices.append(text[start:end].strip())
    

    
    # Extract fields per layer
    layer_fields = []
    for s in slices:
        fields = extract_description_fields(s)
        layer_fields.append(fields)
    
    # Bidirectional shared field inheritance
    shared_fields = ["color", "moisture", "inclusions", "fill", "plasticity", "gradation"]
    
    for field in shared_fields:
        # Find the first layer that has a value for this field
        source_value = None
        for lf in layer_fields:
            val = lf.get(field)
            if val is not None and val != [] and val != "":
                source_value = val
                break
        
        # Apply to all layers missing it
        if source_value is not None:
            for lf in layer_fields:
                val = lf.get(field)
                if val is None or val == [] or val == "":
                    lf[field] = source_value
    
    return layer_fields

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
    # ─── Always-run pre-branch steps ───

    # Step 0 — normalize the transcript (dictionary corrections + soil-name regex)
    raw_transcript = transcript
    transcript = correct_transcript(transcript)

    # Step 1 — segment the transcript by keywords
    segments = segment_transcript(transcript)
    description_segment = segments.get("description", "")

    # Depth conversion
    depth_m = round(depth_ft * 0.3048, 2)

    # Step 4 — parse blow counts from transcript if not provided via tap UI
    blowcount_review_flags = []
    if not blow_counts:
        raw_blows_segment = segments.get("blows", "")
        runon_detected = looks_like_runon_blowcounts(raw_blows_segment)
        blow_counts, pen_depths = parse_blow_counts_from_string(raw_blows_segment)
        if runon_detected:
            blowcount_review_flags.append(
                "Auto-split run-on blow counts (e.g. \"3799\" → 3,7,9,9). "
                "Verify the values match what was spoken before saving."
            )
    else:
        pen_depths = [6.0] * len(blow_counts)

    # Sanity check — any individual blow count >100 with a 6\" pen is implausible
    # and likely indicates a Whisper run-on the auto-split was too cautious to fix
    # (e.g. \"375\" from \"3, 7, 5\" — auto-split skips numbers containing zeros,
    # but this catches the all-nonzero high-value case).
    if blow_counts and any(b > 100 for b in blow_counts):
        blowcount_review_flags.append(
            "Blow count exceeds 100 — verify Whisper did not run digits together."
        )

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
            ] + blowcount_review_flags,
        )

    # Step 5 — N-value
    blow_count_data = parse_blow_counts(blow_counts, pen_depths)

    # Step 7 — recovery
    recovery_inches, remainder_string, recovery_flag = parse_recovery(segments.get("recovery", ""))
    recovery_mm = round(recovery_inches * 25.4) if recovery_inches else None

    # Comments
    comments = segments.get("comments") or ""
    comments = comments.strip(" ,.")
    if not comments and remainder_string:
        comments = remainder_string.strip(" ,.")

    # Step 11 — recovery vs total penetration
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

    flags = list(recovery_vs_pen_flags) + list(blowcount_review_flags)
    soil_name_flag = ""
    split = is_split_layer(description_segment)
    layers_for_db = None

    # ─── Branch: split vs single layer ───

    if split:
        layer_fields = parse_split_layers(description_segment)

        # No soil name check — any layer missing a soil name triggers manual input
        if not layer_fields or not all(lf.get("soil_name") for lf in layer_fields):
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
                flags=["No soil type recognized — manual input required"],
            )

        layer_descriptions = []
        layers_for_db = []

        for lf in layer_fields:
            consistency = get_consistency_density(lf["soil_name"], blow_count_data["n_value"])
            lf["components"] = sort_components(lf.get("components", []))

            soil_data = {
                "soil_name": lf["soil_name"],
                "components": lf["components"],
                "inclusions": lf.get("inclusions", []),
                "color": lf.get("color"),
                "moisture": lf.get("moisture"),
                "fill": lf.get("fill", False),
                "split_layer": False,
                "consistency": consistency,
                "uscs_symbol": lf.get("uscs_symbol"),
                "plasticity": lf.get("plasticity"),
                "gradation": lf.get("gradation"),
            }

            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=ASTM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Structured soil data:{json.dumps(soil_data, indent=2)}"}],
            )
            layer_desc = message.content[0].text
            if lf.get("depth_start") is not None and lf.get("depth_end") is not None:
                ds = lf['depth_start']
                de = lf['depth_end']
                start_str = int(ds) if ds == int(ds) else ds
                end_str = int(de) if de == int(de) else de
                layer_desc_with_depth = f"{start_str}-{end_str} in: {layer_desc}"
            else:
                layer_desc_with_depth = layer_desc
            layer_descriptions.append(layer_desc_with_depth)

            layers_for_db.append({
                "soil_name": lf["soil_name"],
                "uscs_symbol": lf.get("uscs_symbol"),
                "color": lf.get("color"),
                "moisture": lf.get("moisture"),
                "consistency": consistency,
                "depth_start": lf.get("depth_start"),
                "depth_end": lf.get("depth_end"),
                "description": layer_desc,
            })

        for i, lf in enumerate(layer_fields):
            if lf.get("depth_start") is None or lf.get("depth_end") is None:
                flags.append(f"Layer {i+1} depth range not found — manual input required")

        # Check A — depth range order within each layer (start < end)
        for i, lf in enumerate(layers_for_db):
            ds = lf.get("depth_start")
            de = lf.get("depth_end")
            if ds is not None and de is not None and ds >= de:
                flags.append(f"Layer {i+1} depth range invalid: start ({ds}) ≥ end ({de}) — manual input required")

        # Check B — gap/overlap between consecutive layers
        for i in range(len(layers_for_db) - 1):
            this_end = layers_for_db[i].get("depth_end")
            next_start = layers_for_db[i + 1].get("depth_start")
            if this_end is not None and next_start is not None:
                if not isclose(this_end, next_start, abs_tol=0.1):
                    if next_start > this_end:
                        flags.append(f"Gap between layer {i+1} and layer {i+2}: layer {i+1} ends at {this_end} in, layer {i+2} starts at {next_start} in — manual review required")
                    else:
                        flags.append(f"Overlap between layer {i+1} and layer {i+2}: layer {i+1} ends at {this_end} in, layer {i+2} starts at {next_start} in — manual review required")

        # Check C — last layer depth_end vs recovery_inches
        if recovery_inches is not None and layers_for_db:
            last_end = layers_for_db[-1].get("depth_end")
            if last_end is not None and not isclose(last_end, recovery_inches, abs_tol=0.1):
                flags.append(f"Last layer ends at {last_end} in but recovery is {recovery_inches} in — partial recovery across layers, manual review required")

        description = " / ".join(layer_descriptions)

        # Per-field checks across all layers (shared inheritance already applied)
        if not any(lf.get("color") for lf in layer_fields):
            flags.append("Color not found — manual input required")
        if not any(lf.get("moisture") for lf in layer_fields):
            flags.append("Moisture not found — manual input required")
        for lf in layer_fields:
            if lf.get("parse_error"):
                flags.append(lf["parse_error"])
                break

    else:
        fields = extract_description_fields(description_segment)

        # Step 3 — early exit if no soil name found
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
                flags=["No soil type recognized — manual input required"],
            )

        # Step 6 — consistency/density from N-value
        consistency = get_consistency_density(fields["soil_name"], blow_count_data["n_value"])

        if isinstance(fields["soil_name"], list) and len(fields["soil_name"]) > 1:
            soil_name_flag = "Multiple soil names detected - Manual review required"

        # Step 8 — sort components
        fields["components"] = sort_components(fields.get("components", []))

        # Step 9 — assemble soil_data
        soil_data = {
            "soil_name": fields["soil_name"],
            "components": fields["components"],
            "inclusions": fields.get("inclusions", []),
            "color": fields.get("color"),
            "moisture": fields.get("moisture"),
            "fill": fields.get("fill", False),
            "split_layer": isinstance(fields.get("soil_name"),list),
            "consistency": consistency,
            "uscs_symbol": fields.get("uscs_symbol"),
            "plasticity": fields.get("plasticity"),
            "gradation": fields.get("gradation"),
        }

        # Step 10 — Claude formatting
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=ASTM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Structured soil data:{json.dumps(soil_data, indent=2)}"}],
        )
        description = message.content[0].text

        if not fields.get("color"):
            flags.append("Color not found — manual input required")
        if not fields.get("moisture"):
            flags.append("Moisture not found — manual input required")
        if consistency is None:
            flags.append("Soil type unrecognized — consistency requires manual input")
        if fields.get("parse_error"):
            flags.append(fields["parse_error"])

    # ─── Always-run post-branch steps ───

    if recovery_flag:
        flags.append(recovery_flag)
    if soil_name_flag:
        flags.append(soil_name_flag)

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
        comments=comments,
        layers=layers_for_db if split else None,
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