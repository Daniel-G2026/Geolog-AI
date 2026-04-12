# Substitution Strategy — Transcript-Level Calibration

## Overview

When a tech edits a pipeline draft before confirming, the correction is stored in the
`corrections` table. Over time these corrections accumulate into a firm calibration
profile (`firm_profiles`). The question is: **where in the pipeline do we apply the
learned substitutions?**

The current implementation (flywheel v1) injects substitutions into Claude's extraction
prompt. This document proposes an alternative that is more deterministic and easier to
reason about.

---

## Current Approach — Prompt Injection (flywheel v1)

Learned substitutions are appended to the `EXTRACTION_PROMPT` sent to Claude:

```
This firm uses these specific terms: 'compact' → 'dense', 'grabble' → 'gravel'.
```

**Problems:**
- Claude may or may not consistently honour word-level hints in a system prompt
- Behaviour varies between model versions and prompt phrasings
- Hard to test — you can't assert that a specific substitution was applied
- Prompt gets longer over time as the profile grows

---

## Proposed Approach — Transcript-Level Substitution

Apply learned substitutions directly to the raw transcript string **before** it enters
the pipeline, using the same mechanism as `WHISPER_CORRECTIONS` in `whisper.py`.

### Where it fits in the pipeline

```
Audio file
    ↓
whisper.transcribe()          ← applies WHISPER_CORRECTIONS (static, hardcoded)
    ↓
raw transcript string
    ↓
apply_firm_substitutions()    ← NEW: applies learned firm substitutions here
    ↓
segment_transcript()
    ↓
extract_description_fields()  ← Claude sees already-corrected text
    ↓
combination() → SampleEntry
```

### Implementation sketch

```python
def apply_firm_substitutions(transcript: str, firm_profile: dict) -> str:
    """
    Applies firm-specific learned substitutions to the raw transcript.
    Works identically to WHISPER_CORRECTIONS in whisper.py — simple string replacement.
    Case-insensitive. Longer phrases matched before shorter ones to avoid partial matches.
    """
    substitutions = firm_profile.get("substitutions", {})
    if not substitutions:
        return transcript

    text = transcript.lower()
    for original, corrected in sorted(substitutions.items(), key=lambda x: len(x[0]), reverse=True):
        text = text.replace(original, corrected)
    return text
```

Called in `combination()` after `transcribe()` and before `segment_transcript()`:

```python
def combination(transcript, blow_counts, sample_no, depth_ft,
                sample_type="SS", firm_id=None):

    firm_profile = get_firm_profile(firm_id) if firm_id else {}
    transcript   = apply_firm_substitutions(transcript, firm_profile)  # ← inject here

    segments = segment_transcript(transcript)
    ...
```

### Why this is better

| | Prompt injection | Transcript substitution |
|---|---|---|
| Deterministic | No — Claude decides | Yes — string replace |
| Testable | Hard | Easy — unit test the function |
| Prompt length | Grows with profile | Unaffected |
| Model version sensitive | Yes | No |
| Same mechanism as WHISPER_CORRECTIONS | No | Yes — consistent pattern |

---

## What still needs fixing before implementing

1. **Positional diff is fragile** — `extract_word_substitutions()` in `calibration.py`
   compares words by index position. If the tech reorders words, every word after the
   first mismatch is flagged as a substitution. Needs a smarter diff before the
   substitution map can be trusted.

   Suggested fix: only promote substitutions where `len(orig_words) == len(corr_words)`
   (same word count), which covers the most common case of single-word corrections
   without the reordering false-positive problem.

2. **Type mismatch** — `corrections.sample_id` is defined as `uuid` in the schema but
   `samples.id` is a `bigint` auto-increment. The foreign key constraint will fail.
   Change `corrections.sample_id` to `bigint` before running the migration.

3. **No profile versioning** — if a bad substitution gets promoted into `firm_profiles`,
   there is no rollback. Consider keeping a `previous_substitutions` column or a
   `firm_profile_history` table so bad promotions can be reverted.

---

## When to implement

After the corrections table has accumulated enough real-world data to validate that
the substitution extraction is producing clean signal. Suggested threshold: 50+
confirmed corrections with `description_was_edited = true` before enabling
transcript-level substitution in production.
