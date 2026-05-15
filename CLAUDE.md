# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Commands

- Install dev deps: `pip install -r requirements-dev.txt`
- Run server (dev): `uvicorn app:app --reload`
- Run all tests: `pytest` (config in `pytest.ini`; `testpaths = tests`)
- Run a single test file: `pytest tests/test_parser.py`
- Run a single test: `pytest tests/test_parser.py::test_name`

Production entry point is the `Procfile`: `uvicorn app:app --host 0.0.0.0 --port $PORT`

Required env vars (loaded from `.env` via `python-dotenv`):
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`.

## Core architectural principle

GeoLog AI turns a field technician's voice memo into a structured geotechnical
soil log entry. The pipeline is a one-way flow with a strict, non-negotiable split:

**Python does all geotechnical math and parsing. Claude is used only for fuzzy
field extraction and final ASTM-style description formatting.**

Never move a calculation, classification, or keyword-detection step into a Claude
call. Never hardcode a language-interpretation step that belongs in one.

Orientation — request flow:
`app.py` (FastAPI) -> `pipeline.run_from_voice` -> `whisper.transcribe` ->
`pipeline.combination` -> returns a `SampleEntry` (`models.py`).
Frontend is the single-file `index.html` served at `GET /`.
Endpoint definitions live in `app.py` — read them there, not from a doc.

## Claude's role is bounded

`pipeline.combination` is the ONLY file that calls the Anthropic API. Two calls:

- **Extraction** (`EXTRACTION_PROMPT`): natural speech -> strict JSON, fixed key
  set, closed enum of valid `soil_name`s and the 15 USCS symbols. Returns
  `null`/`[]` for missing fields — never guesses.
- **Formatting** (`ASTM_SYSTEM_PROMPT`): structured dict -> one description
  string. Uses values verbatim, omits nulls, no inference.

If extraction JSON fails to parse, the function returns a default-shaped dict
with `parse_error` set — the pipeline flags for manual review rather than crashing.

## Flags vs hard failures

The pipeline never raises for missing/invalid soil data. It short-circuits to a
`SampleEntry` with `n_value=0` and a populated `flags` list (no soil type
recognized, depth/recovery mismatch, run-on blow-count warning, etc.). The
frontend uses these flags to gate confirmation. Preserve this contract — new
failure modes should add flags, not raise exceptions.

## Critical gotchas — read before editing the pipeline or schema

- **The deterministic/probabilistic split is absolute.** SPT math, N-value
  calcs, and ASTM D2488 classification MUST be deterministic Python. See the
  core principle above — this is the rule that matters most in this codebase.

- **Every pipeline entry point MUST run `correct_transcript()` and
  `normalize_soil_names()`.** Today `combination()` does this and the
  recalculate endpoints inherit it — but any NEW entry point must call them
  explicitly. Do not rely on them being "somewhere upstream."

- **Transcript synonym substitution MUST use word-boundary regex** (`re.sub`
  with `\b` anchors). Plain `str.replace()` causes substring corruption — e.g.
  "note" matching inside "noted". This rule applies to all transcript
  substitution, including `WHISPER_CORRECTIONS` and `normalize_soil_names`.

- **Supabase IDs are int8/bigint auto-increment, NEVER UUID.** Any code or
  migration that assumes UUID is wrong.

- **Schema column types matter:** floats are `double precision`, integers are
  `bigint`. Foreign keys use `ON DELETE RESTRICT`.

## Extending the pipeline

When adding capability, update ALL the related sites — these are the blast radii:

- **New transcript section keyword:** add a synonym group to
  `parser.KEYWORD_SYNONYMS` (synonyms are matched longest-first, so
  "blow counts" matches before "blows").
- **New Whisper mishearing:** add to `whisper.WHISPER_CORRECTIONS`, or extend
  `normalize_soil_names` for regex-shaped variants. (Mind the word-boundary
  rule above.)
- **New extraction field:** extend the `EXTRACTION_PROMPT` key set, the default
  dicts in `extract_description_fields`, AND any inheritance lists in
  `parse_split_layers`.
