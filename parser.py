# parser.py
# Parses voice transcript into structured soil log entry
# Scope: Soil only. Rock core parsing to be added later.
import re

from classification_engine import COHESIVE_TERMS, COHESIONLESS_TERMS

ALL_SOIL_TERMS = sorted(COHESIVE_TERMS + COHESIONLESS_TERMS, key= len, reverse= True)

KNOWN_COLORS = ["dark brown", "reddish brown", "brown", "grey", "black"]
KNOWN_MOISTURE = ["very moist to wet", "moist to wet", "very moist", "moist", "dry", "wet"]
KNOWN_INCLUSIONS = ["rock fragments", {"organic inclusions":["rootlets","organics","organic"]},"oxidation"]
KNOWN_QUANTIFIERS = ["trace to some", "some", "trace"]


def is_relevant(transcript: str) -> bool:
    if any( term in transcript.lower() for term in ALL_SOIL_TERMS):
        return True
    else:
        return False

def extract_soil_name(transcript: str):
    transcript_lower = transcript.lower()
    matched_soil = []

    cleaner = ""
    components, _ = extract_components(transcript)
    if components:
        for component in components:
            cleaner += f"{component} "
        cleaner = cleaner.strip()
        cleaned = transcript_lower.replace(cleaner,"")
    else:
        cleaned = transcript_lower
    for soil_name in ALL_SOIL_TERMS:
        if  soil_name in cleaned:
            if not any(soil_name in already_matched for already_matched in matched_soil):
                if "till" in transcript.lower():
                    matched_soil.append(f"{soil_name} till")
                else:
                    matched_soil.append(soil_name)

    if len(matched_soil) == 0:
        return(None,"No soil type recognized - manual input required")
    elif len(matched_soil) == 1:
        return(matched_soil[0], None)
    else:
        return (matched_soil, "Multiple soil tupes detected -Manual review required")
    
def extract_color(transcript: str):
    transcript_lower = transcript.lower()
    matched_colour = []
    for colour in KNOWN_COLORS:
        if colour in transcript_lower:
            if not any(colour in already_matched for already_matched in matched_colour):
                matched_colour.append(colour)
    
    if len(matched_colour) == 0:
        return (None,"Colour not recognized - manual input required")
    elif len(matched_colour) == 1:
        return (matched_colour[0], None)
    else:
        return (matched_colour,"Multiple colours detected - Mnual review required")

def extract_moisture(transcript: str):
    transcript_lower = transcript.lower()
    matched_moisture = []
    for moisture in KNOWN_MOISTURE:
        if moisture in transcript_lower:
            if not any(moisture in already_matched for already_matched in matched_moisture):
                matched_moisture.append(moisture)

    if len(matched_moisture) == 0:
        return (None,"Moisture not found - manual input required")
    elif len(matched_moisture) == 1:
        return (matched_moisture[0], None)
    else:
        return (matched_moisture,"Multiple moistures detected - Manual review required")
    

def extract_components(transcript: str):
    transcript_lower = transcript.lower()
    components = []
    secondary_soils = ["clay", "sand", "gravel", "silt"]

  
    for quantifier in KNOWN_QUANTIFIERS:
        for soil in secondary_soils:
            pair = f"{quantifier} {soil}"
            if pair in transcript_lower:
                if not any(pair in already_matched for already_matched in components):
                    components.append(pair)
    
    return (components, None) if components else ([], None)


def extract_inclusions(transcript: str):
    transcript_lower = transcript.lower()
    inclusions = []

    for item in KNOWN_INCLUSIONS:
        if isinstance(item, dict):
            for standard_term, synonyms in item.items():
                for synonym in synonyms:
                    if synonym in transcript_lower:
                        if standard_term not in inclusions:
                            inclusions.append(standard_term)
                        break  # stop checking synonyms once one matches
        else:
            if item in transcript_lower:
                if item not in inclusions:
                    inclusions.append(item)
    
    return (inclusions, None) if inclusions else ([], None)
    

def extract_fill(transcript: str):
    transcript_lower = transcript.lower()
    
    pattern = r"\bfill\b"
    if re.search(pattern,transcript_lower):
        return (True, None)
    else:
        return (False, None)
    


def parse_transcript(transcript:str):
    
    if not is_relevant(transcript):
        return {
            "soil_name": None,
            "components": [],
            "inclusions": [],
            "color": None,
            "moisture": None,
            "fill": False,
            "flags": ["Transcript not recognized as a soil description — manual input required"]


        }
    else:
        
        soil_name, soil_flag = extract_soil_name(transcript)
        component, component_flag = extract_components(transcript)
        inclusion, inclusion_flag = extract_inclusions(transcript)
        colour, colour_flag = extract_color(transcript)
        moisture, moisture_flag = extract_moisture(transcript)
        fill, fill_flag = extract_fill(transcript)


        flags = [f for f in [soil_flag, component_flag, inclusion_flag,
                              colour_flag, moisture_flag, fill_flag] if f is not None]

        return {
            "soil_name": soil_name,
            "components": component,
            "inclusions": inclusion,
            "color": colour,
            "moisture": moisture,
            "fill": fill,
            "flags": flags
        }