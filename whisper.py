# whisper.py
# Handles voice input transcription using OpenAI Whisper API
# Takes an audio file path, returns a corrected transcript string
# That transcript feeds directly into pipeline.py combination()

from openai import OpenAI
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# ─────────────────────────────────────────────
# WHISPER VOCABULARY PROMPT
# Primes Whisper with geotechnical terminology before transcription.
# This significantly improves accuracy on domain-specific words
# like "trace gravel" which Whisper might otherwise mishear.
# ─────────────────────────────────────────────

WHISPER_PROMPT = (
    "Geotechnical soil log description using USCS classification: "
    "silty clay, sandy silt, clayey silt, sand and gravel, sand and silt, silty sand, "
    "trace gravel, trace sand, trace clay, trace silt, "
    "some gravel, some sand, some clay, some silt, "
    "trace to some gravel, trace to some sand, trace to some clay, "
    "brown, grey, dark brown, reddish brown, black, "
    "moist, very moist, wet, dry, very moist to wet, moist to wet, "
    "stiff, very stiff, hard, firm, soft, very soft, "
    "compact, dense, very dense, loose, very loose, medium dense, "
    "till, fill, oxidation, rock fragments, organic inclusions, rootlets, "
    "silty clay till, sandy silt till, sand and silt till, silty sand till"
    "blow counts, blows, recovery, description, comments, wet spoon"
    "auger grinding"
    "gradation - poorly graded, well graded"
    "plasticity - non plastic, slightly plastic, low plasticity, high plasticity"
    "uscs/group symbol - CL, ML, SM,SP, GP, GM"
    "group name"
    "Dealing with numbers:"
    "All numbers should not be spelled and should be transcribed as numbers e.g fifty for four should be 50 for 4 etc"
    "When listing a set of number separate with commas, when a range of numbers is said e.g 0 to 10 transcribe as 0-10"
    "Single-digit blow counts spoken in sequence MUST be transcribed as comma-separated digits, never concatenated. "
    "Example: 'three seven nine nine' or 'three, seven, nine, nine' must be transcribed as '3, 7, 9, 9' — NOT as '3799'. "
    "Each blow count is a separate number even when small."
    "All inch measurements should be transcribed as 'inches' not as the symbol"
    
)


# ─────────────────────────────────────────────
# WHISPER CORRECTIONS DICTIONARY
# Maps known Whisper mishearings to correct geotechnical terms.
# Built from real field testing — add to this over time as you
# discover new mishearings during site testing.
# ─────────────────────────────────────────────

WHISPER_CORRECTIONS = {
    # "trace" mishearings
    "tree scrabble": "trace gravel",
    "trace scrabble": "trace gravel",
    "tree gravel": "trace gravel",
    "trace grabble": "trace gravel",
    "trade gravel": "trace gravel",
    "trays gravel": "trace gravel",
    "tree sand": "trace sand",
    "trace stand": "trace sand",
    "tree clay": "trace clay",
    "tree silt": "trace silt",

    # "some" mishearings
    "sum gravel": "some gravel",
    "sum sand": "some sand",
    "sum clay": "some clay",
    "sum silt": "some silt",

    # moisture mishearings
    "mo ist": "moist",
    "moiste": "moist",
    "most": "moist",

    # soil name mishearings
    "silky clay": "silty clay",
    "silly clay": "silty clay",
    "salty clay": "silty clay",
    "silty play": "silty clay",
    "sandy salt": "sandy silt",
    "sandy silk": "sandy silt",
    "clayey silk": "clayey silt",
    "clay silt": "clayey silt",
    "clay silts": "clayey silt",

    # consistency mishearings
    "very stiff": "very stiff",   # keep — just confirming
    "very stuff": "very stiff",
    "hard": "hard",
    "heart": "hard",
}

import re

# ─────────────────────────────────────────────
# SOIL NAME NORMALIZER
# Handles Whisper's creative punctuation and pluralization of compound soil names.
# Catches variants a static dictionary can't anticipate.
# ─────────────────────────────────────────────

def normalize_soil_names(text: str) -> str:
    """
    Collapses Whisper's variations on compound soil names back to canonical form.
    Examples of what this catches:
      "clay silt"       → "clayey silt"
      "clay, silt"      → "clayey silt"
      "clay silts"      → "clayey silt"
      "clayy silt"      → "clayey silt"
      "clayey silts"    → "clayey silt"
      "silt clay"       → "silty clay"
      "silty clays"     → "silty clay"
      "sandy silts"     → "sandy silt"
      "silty sands"     → "silty sand"
      "sand and silts"  → "sand and silt"
      "sand and gravels"→ "sand and gravel"
    """
    # Order matters — more specific multi-word patterns first
    text = re.sub(r'\bsand\s*and\s*silt[s]?\b',   'sand and silt',   text, flags=re.IGNORECASE)
    text = re.sub(r'\bsand\s*and\s*gravel[s]?\b', 'sand and gravel', text, flags=re.IGNORECASE)

    # "clay[y]? [,]? silt[s]?" → "clayey silt"
    text = re.sub(r'\bclay[y]?\s*[,]?\s*silt[s]?\b', 'clayey silt', text, flags=re.IGNORECASE)
    # "silt[y]? [,]? clay[s]?" → "silty clay"
    text = re.sub(r'\bsilt[y]?\s*[,]?\s*clay[s]?\b', 'silty clay', text, flags=re.IGNORECASE)

    # Pluralized simple compounds
    text = re.sub(r'\bsandy\s*silt[s]?\b',  'sandy silt',  text, flags=re.IGNORECASE)
    text = re.sub(r'\bsilty\s*sand[s]?\b',  'silty sand',  text, flags=re.IGNORECASE)

    # Pluralized singletons (careful — only when whole word)
    text = re.sub(r'\bsilts\b',   'silt',   text, flags=re.IGNORECASE)
    text = re.sub(r'\bclays\b',   'clay',   text, flags=re.IGNORECASE)
    text = re.sub(r'\bsands\b',   'sand',   text, flags=re.IGNORECASE)
    text = re.sub(r'\bgravels\b', 'gravel', text, flags=re.IGNORECASE)

    return text

def correct_transcript(transcript: str) -> str:
    """
    Applies known corrections to Whisper transcript.
    Case-insensitive replacement — converts to lowercase first,
    then applies all corrections in the dictionary.

    Add new entries to WHISPER_CORRECTIONS as you discover
    mishearings during real field testing.
    """
    corrected = transcript.lower()
    for mistake, correction in WHISPER_CORRECTIONS.items():
        corrected = corrected.replace(mistake, correction)

    normalized_transcript = normalize_soil_names(corrected)
    return normalized_transcript


def transcribe(audio_file_path: str) -> str:
    """
    Sends an audio file to OpenAI Whisper and returns a corrected transcript.

    Supported formats: mp3, mp4, wav, m4a, webm, mpeg, mpga
    Max file size: 25MB

    Input:  path to audio file as string
    Output: corrected transcript as plain string
    """
    with open(audio_file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",          # force English — faster and more accurate
            prompt=WHISPER_PROMPT   # prime Whisper with geotechnical vocabulary
        )

    return transcript.text 