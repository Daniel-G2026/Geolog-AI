from parser import parse_transcript
from classification_engine import get_consistency_density, parse_blow_counts
import json
import anthropic
import os
from dotenv import load_dotenv
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
7. FILL prefix when fill is true: FILL: soil type, components, inclusions, color, moisture, consistency.
8. Transitional soils: use TO between names
9. End every description with a period
10. If split_layer is true: return MANUAL REVIEW REQUIRED and describe each layer separately

Return only the formatted description string. No explanation, no extra text."""
load_dotenv()

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))



def combination(transcript, blow_counts: list, pen_depths: list):
    soil_data = parse_transcript(transcript)
    if soil_data["flags"]:
        return {
        "description": None,
        "n_value_log": None,
        "flags": soil_data["flags"]
    }
    soil_data["components"] = sort_components(soil_data["components"])

    blow_count_data = parse_blow_counts(blow_counts,pen_depths)

    consistency = get_consistency_density(soil_data["soil_name"],blow_count_data["n_value"])
    soil_data["consistency"] = consistency

    soil_data["n_value_log"] = blow_count_data["n_value_log"]

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": json.dumps(soil_data)
            }
        ]
    )
    return {
        "description": message.content[0].text,
        "n_value_log": blow_count_data["n_value_log"],
        "flags": []
    }
def sort_components(components: list) -> list:
    QUANTIFIER_ORDER = {"some": 0, "trace to some": 1, "trace": 2}        
    def sort_key(component):
        for quantifier, order in QUANTIFIER_ORDER.items():
            if component.startswith(quantifier):
                return order
        return 99
    return sorted(components, key=sort_key)

