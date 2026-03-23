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
PAIRS = []
secondary_soils = ["clay", "sand", "gravel", "silt"]
for quantifier in KNOWN_QUANTIFIERS:
    for soil in secondary_soils:
        PAIRS.append(f"{quantifier} {soil}")

def substring_check(terms, transcript):
    matches = []
    for match in terms:
        if match in transcript:
            if not any(match in already_matched for already_matched in matches):
                matches.append(match)
    return matches    

def is_relevant(transcript: str) -> bool:
    if any( term in transcript.lower() for term in ALL_SOIL_TERMS):
        return True
    else:
        return False

def extract_soil_name(transcript: str, components: list):
    transcript_lower = transcript.lower()
    matched_soil = []

    cleaned = transcript_lower

    for component in components:
        cleaned = cleaned.replace(component, "")

    matched_soil = substring_check(ALL_SOIL_TERMS,cleaned)

    pattern = r"\btill\b"
    for i,soil in enumerate(matched_soil):
        if re.search(pattern,transcript_lower):
            matched_soil[i] = f"{soil} till"
    
            
    if len(matched_soil) == 0:
        return(None,"No soil type recognized - manual input required")
    elif len(matched_soil) == 1:
        return(matched_soil[0], None)
    else:
        return (matched_soil, "Multiple soil tupes detected -Manual review required")
    
def extract_color(transcript: str):
    transcript_lower = transcript.lower()
    matched_colour = []
    matched_colour = substring_check(KNOWN_COLORS, transcript_lower)
    
    if len(matched_colour) == 0:
        return (None,"Colour not recognized - manual input required")
    elif len(matched_colour) == 1:
        return (matched_colour[0], None)
    else:
        return (matched_colour,"Multiple colours detected - Mnual review required")

def extract_moisture(transcript: str):
    transcript_lower = transcript.lower()
    matched_moisture = []
    
    matched_moisture = substring_check(KNOWN_MOISTURE,transcript_lower)
    if len(matched_moisture) == 0:
        return (None,"Moisture not found - manual input required")
    elif len(matched_moisture) == 1:
        return (matched_moisture[0], None)
    else:
        return (matched_moisture,"Multiple moistures detected - Manual review required")
    

def extract_components(transcript: str):
    transcript_lower = transcript.lower()
    components = []
    
    components = substring_check(PAIRS,transcript_lower)
            
    return (components, None) if components else ([], None)

def filter_components(components: list, soil_name: str) -> list:
    # Get individual words from the soil name
    soil_name_words = soil_name.lower().split()
    
    filtered = []
    for component in components:
        # Get the soil word from the component (last word)
        # e.g. "trace sand" → "sand", "trace to some clay" → "clay"
        component_soil_word = component.split()[-1]
        
        # Only keep component if its soil word isn't already in the primary soil name
        if component_soil_word not in soil_name_words:
            filtered.append(component)
    
    return filtered


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
    


def parse_transcript(transcript:str) -> dict:
    
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
    else:
        
        components, component_flag = extract_components(transcript)
        soil_name, soil_flag = extract_soil_name(transcript,components)

        if isinstance(soil_name, str):
            components = filter_components(components,soil_name)
            
        inclusion, inclusion_flag = extract_inclusions(transcript)
        colour, colour_flag = extract_color(transcript)
        moisture, moisture_flag = extract_moisture(transcript)
        fill, fill_flag = extract_fill(transcript)


        flags = [f for f in [soil_flag, component_flag, inclusion_flag,
                              colour_flag, moisture_flag, fill_flag] if f is not None]

        return {
            "soil_name": soil_name,
            "components": components,
            "inclusions": inclusion,
            "color": colour,
            "moisture": moisture,
            "fill": fill,
            "split_layer": isinstance(soil_name,list),
            "flags": flags
        }