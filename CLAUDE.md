# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install dev deps: `pip install -r requirements-dev.txt`
- Run server (dev): `uvicorn app:app --reload` (prod entry is the `Procfile`: `uvicorn app:app --host 0.0.0.0 --port $PORT`)
- Run all tests: `pytest` (config in `pytest.ini`; `testpaths = tests`)
- Run a single test file: `pytest tests/test_parser.py`
- Run a single test: `pytest tests/test_parser.py::test_name`

Required env vars (loaded from `.env` via `python-dotenv` in `pipeline.py` / `whisper.py`):
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`.

## Architecture

GeoLog AI turns a field technician's voice memo into a structured geotechnical soil log entry. The pipeline is a one-way flow with strict separation: Python does all geotechnical math and parsing; Claude is used only for fuzzy field extraction and final ASTM-style description formatting.

### Request flow

`app.py` (FastAPI) → `pipeline.run_from_voice` → `whisper.transcribe` → `pipeline.combination` → returns a `SampleEntry` (see `models.py`). The frontend is the single-file `index.html` served at `GET /`.

Key endpoints (all under `/projects/{project_id}/boreholes/{borehole_id}`):
- `POST .../samples/draft` — audio upload → full pipeline → unsaved `SampleEntry` JSON
- `POST .../samples/recalculate` — rerun `combination()` with edited blow_counts/pen_depths
- `POST .../samples/recalculate_recovery` — pure-Python recovery vs penetration check
- `POST .../samples/confirmed` — persist; recomputes SPT once more from submitted blow counts so the DB stays consistent if the user edited values
- `PATCH .../samples/{sample_id}/layers` — edit split-layer depth ranges post-confirm; rebuilds the top-level description without re-invoking Claude

Persistence is Supabase (`projects`, `boreholes`, `samples`). `blow_counts`, `pen_depths`, `flags`, `layers` are stored as JSON strings on `samples` and parsed back to arrays in `list_samples`.

### Pipeline contract (`pipeline.combination`)

This is the only file that calls the Anthropic API. The flow:

1. `whisper.correct_transcript` — dictionary fixes (`WHISPER_CORRECTIONS`) + regex `normalize_soil_names` collapse Whisper variants of compound soil names ("clay silt" → "clayey silt", plurals stripped).
2. `parser.segment_transcript` — splits transcript by spoken keywords (`description`, `blows`, `recovery`, `comments`, `cgd`, `pid`, `cone`) using `KEYWORD_SYNONYMS`. Synonyms within a group are tried longest-first so "blow counts" matches before "blows".
3. Blow-count parsing — `parse_blow_counts_from_string` handles refusal notation (`50/3`, `50 for 3 inches`) and `looks_like_runon_blowcounts` auto-splits Whisper run-ons like `"3799"` → `[3,7,9,9]` (3–4 digits, no zeros, no `/` or `for`). When the run-on splitter fires, an amber review flag is appended.
4. SPT math — `classification_engine.parse_blow_counts` (N-value, log notation, refusal) and `get_consistency_density` (lookup against cohesive vs cohesionless tables; lists handle mixed soils with `/` separator).
5. Split-layer branch — `parser.is_split_layer` triggers when ≥2 `layer N` markers appear in the description segment. `pipeline.parse_split_layers` slices the segment by layer keyword, calls Claude per-slice via `extract_description_fields`, then bidirectionally inherits shared fields (`color`, `moisture`, `inclusions`, `fill`, `plasticity`, `gradation`) across layers. Three depth-validation checks emit flags: per-layer start<end, gap/overlap between consecutive layers, last layer end vs `recovery_inches`.
6. Single-layer branch — one `extract_description_fields` call.
7. ASTM formatting — Claude (`claude-sonnet-4-6`) is given the structured `soil_data` dict + `ASTM_SYSTEM_PROMPT` and returns the final report-ready description string. For split layers, each layer is formatted separately and joined with ` / `, with depth prefixes like `0-14 in: ...`.

### Claude's role is bounded

- **Extraction** (`EXTRACTION_PROMPT`): natural speech → strict JSON with a fixed key set including a closed enum of valid `soil_name`s and the 15 USCS symbols. Returns `null`/`[]` for missing fields, never guesses.
- **Formatting** (`ASTM_SYSTEM_PROMPT`): structured dict → one description string. Must use values verbatim and omit nulls; no inference.

If Claude's extraction JSON fails to parse, the function returns a default-shaped dict with `parse_error` set so the pipeline can flag manual review rather than crash.

### Flags vs hard failures

The pipeline never raises for missing/invalid soil data. Instead it short-circuits to a `SampleEntry` with `n_value=0` and a `flags` list (`"No soil type recognized — manual input required"`, depth/recovery mismatches, run-on warnings, etc.). The frontend uses these flags to gate confirmation. See `docs/substitution_strategy.md` for the planned flywheel calibration approach (transcript-level substitutions over prompt injection).

### Adding parsers/keywords

- New transcript section keyword: add a synonym group to `parser.KEYWORD_SYNONYMS`.
- New Whisper mishearing: add to `whisper.WHISPER_CORRECTIONS` (case-insensitive replace) or extend `normalize_soil_names` for regex-shaped variants.
- New extraction field: extend `EXTRACTION_PROMPT` keys, the default dicts in `extract_description_fields`, and any inheritance lists in `parse_split_layers`.
