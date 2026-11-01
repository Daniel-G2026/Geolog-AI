# GeoLog AI — Project State

_Written 2026-10-19 as an onboarding/refresher doc after a multi-month gap. Reflects the
repo exactly as found on disk, including uncommitted changes. Regenerate or edit this
as the project evolves — it's a snapshot, not a living spec._

---

## 1. What this app does

A field technician drives a borehole, speaks a soil-sample description into a phone
(voice memo), and GeoLog AI turns that into a structured, ASTM D2488/USCS-style
geotechnical log entry — SPT N-value, consistency/density, formatted description — saved
to Supabase and exportable as a PDF boring log.

**Non-negotiable architectural rule (stated in both `CLAUDE.md` and `AGENTS.md`):**
Python does all geotechnical math, classification, and keyword detection. Claude is used
*only* for fuzzy natural-language field extraction and final prose formatting. Never move
a calculation into a Claude call; never hardcode an interpretation step that belongs in one.

Request flow: `app.py` (FastAPI) → `pipeline.run_from_voice` → `whisper.transcribe` →
`pipeline.combination` → returns a `SampleEntry` (`models.py`). Frontend is the
single-file `index.html` served at `GET /`.

---

## 2. Module-by-module walkthrough

### `parser.py` — transcript segmentation (deterministic, no API calls)
Splits the raw Whisper transcript into sections by spoken keyword ("description",
"blows", "recovery", "comments", "cgd", "pid", "cone"). Synonym groups
(`KEYWORD_SYNONYMS`) are matched longest-first so "blow counts" beats "blows". Also
has the blow-count string parser (`parse_blow_counts_from_string`, handles `"50/3"` and
`"50 for 3"` refusal notation), the recovery parser, the run-on blow-count safeguard
(Whisper sometimes collapses "3, 7, 9, 9" into "3799" — `looks_like_runon_blowcounts`
detects and splits it), and standalone regex parsers for USCS symbol / plasticity /
gradation (`parse_uscs_symbol`, `parse_plasticity`, `parse_gradation` — these are now
**dead code**, see §4).

### `classification_engine.py` — SPT math + ASTM D2488 classification (deterministic)
`parse_blow_counts()` implements the SPT convention: 4 intervals of 6", N-value =
interval 2 + interval 3, refusal detection when any interval's penetration is < 6".
`get_consistency_density()` / `consistency_density_condition()` look up the
ASTM consistency (cohesive: clay/silt) or density (cohesionless: sand/gravel) term from
the N-value, including the boundary "transitional" terms (e.g. exactly N=8 → "firm to
stiff"). Handles mixed-soil lists (e.g. "silty clay / sandy silt" → "very stiff/compact").
This is the file the whole deterministic/probabilistic split exists to protect — no
Claude calls here, ever.

### `whisper.py` — OpenAI Whisper transcription + correction
`transcribe()` calls OpenAI Whisper with a geotechnical vocabulary priming prompt.
`correct_transcript()` is supposed to apply the `WHISPER_CORRECTIONS` dictionary
(known mishearings like "silky clay" → "silty clay") then run `normalize_soil_names()`
(regex-based pluralization/punctuation cleanup for compound soil names).
**There is a real bug here — see §4, item 1.**

### `pipeline.py` — the orchestrator (the ONLY file that calls the Anthropic API)
`combination()` is the main entry point. Two Claude calls happen here:
- **Extraction** (`EXTRACTION_PROMPT`): natural speech → strict JSON (soil_name,
  components, color, moisture, inclusions, fill, plasticity, gradation, depth range,
  uscs_symbol). Returns null/[] for anything not said — never guesses.
- **Formatting** (`ASTM_SYSTEM_PROMPT`): structured dict → one ASTM-style description
  string, values used verbatim.

Also handles split-layer detection (`is_split_layer` / `parse_split_layers` — triggers
when the tech says "layer 1 ... layer 2 ..."), bidirectional field inheritance across
layers, and a battery of flag-raising validation checks (depth order, gaps/overlaps
between layers, recovery vs. penetration mismatch, run-on blow-count review, etc.).
**Never raises for bad/missing soil data — always short-circuits to a flagged
`SampleEntry` with `n_value=0`.** This flags-not-exceptions contract is explicitly
called out in `CLAUDE.md`/`AGENTS.md` as something to preserve.
**The working tree has an uncommitted change that guts the structured-field output of
this function — see §4, item 2, this is the most important thing to know before
touching this file.**

### `models.py` — data classes
`SampleEntry` (one spoon sample — SPT data, description, flags, and the Chunk-1
structured soil fields), `BoreholeLog`, `Project`. Plain dataclasses, no ORM. Note
`BoreholeLog.get_sample()` still has a `# YOUR CODE HERE` comment left in despite being
implemented — harmless but looks like a leftover exercise scaffold.

### `app.py` — FastAPI surface
REST endpoints for projects/boreholes/samples (create, list, check-duplicate,
draft-from-voice, recalculate, recalculate-recovery, confirm/insert, patch layer depths,
PDF export) plus `GET /` serving `index.html`. Notable hardening already in place:
`SAMPLES_INSERT_ALLOWLIST` whitelists exactly which client-supplied keys get inserted
into `samples` (defends against a client spoofing `source`, `review_status`,
`confidence_score`, `stratum_id`, `id`), and `confirm_sample`'s generic exception handler
intentionally returns a vague 500 instead of leaking Postgres constraint text.

### `generate_pdf.py` — production boring-log PDF renderer
Depth-scaled vertical layout (1 ft of borehole = fixed points on page), paginates
automatically, draws blow-count boxes aligned to the depth scale, renders split-layer
descriptions and flags. Fetches directly from Supabase (`_fetch_project` /
`_fetch_borehole` / `_fetch_samples`). Wired into `app.py`'s
`GET /projects/{id}/boreholes/{id}/pdf`.

### `tools/` — synthetic data + per-firm styling (forward-looking, Chunk 3 work)
- `firm_styles.py` — `FirmStyle` config (column labels, abbreviations, units) for two
  generic placeholder firms ("firma", "firmb"). Explicitly a stand-in: the docstring
  says real firms (Envision, etc.) get added "before Chunk 5 ingestion."
- `soil_corpus.py` — generates random-but-plausible synthetic samples with a documented
  ground-truth-first ordering (so PDF and JSON truth can't drift), with scenario tags
  covering the failure-mode matrix (refusal notation styles, split layers, partial/missing
  recovery, missing color, sparse/dense lab data, particle-size modifiers, ASTM
  descriptors).
- `pdf_renderer.py` — same rendering approach as `generate_pdf.py` but reads from the
  in-memory synthetic dataset instead of Supabase, and applies firm-specific abbreviations.
- `generate_synthetic_log.py` — CLI: `python -m tools.generate_synthetic_log --seed 42
  --firm firma --out fixtures/` → one synthetic PDF + ground-truth JSON pair.
- `assert_coverage.py` — CLI that unions `scenarios` tags across a fixtures directory and
  fails if any required scenario (e.g. `recovery_missing`, `split_3_layer`) is absent —
  a coverage gate for the synthetic corpus, presumably feeding a future ingestion/OCR
  accuracy harness (see `ingestion_sources`/`strata` tables in §3).

### `index.html` — the entire frontend
Single file, mobile-first "field logging cockpit" aesthetic (sunlight-readable,
glove-friendly, IBM Plex Mono + Inter). Handles project/borehole lookup and creation,
voice recording + draft logging, blow-count tap UI, recalculate, split-layer depth
editing, flag-gated confirmation, and (per uncommitted changes) a manual structured-field
editing panel — see §4, item 2.

### `tests/`
`test_parser.py` and `test_classification_engine.py` — thorough, well-commented pure-logic
unit tests (no mocking needed since these modules make no API calls). No tests exist for
`pipeline.py` (the Claude-calling orchestration logic) or `app.py` (the API layer) — see
§4 gaps.

### Root-level odds and ends
- `test_generate_sample_pdf.py` — standalone demo-PDF generator with a hardcoded 11-sample
  40 ft borehole, monkeypatches `generate_pdf._fetch_*` to avoid touching Supabase.
  **Currently broken** — see §4, item 5.
- `docs/substitution_strategy.md` — a design proposal, not implemented code. This is the
  source of the "corrections"/"firm_profiles" concepts — see §3.

---

## 3. Database schema

**No local SQL migration files exist in this repo** (no `migrations/` or `supabase/`
directory — AGENTS.md/CLAUDE.md's instruction to "add the column via a Supabase
migration" is managed directly against the hosted Supabase project, not via checked-in
SQL). I pulled the live schema directly from the connected Supabase project
(`geolog-ai`, project ref `jgophesedpwljliwigdn`, region us-east-1, Postgres 17).
Two migrations are recorded in Supabase's own migration history:
`chunk1_samples_structured_fields` and `chunk2_boreholes_strata_ingestion_sources`.

### Tables that actually exist

**`projects`** — `id` (bigint identity), `project_no` (unique), `client`,
`project_name`, `location`, `created_at`.

**`boreholes`** — `id`, `project_id` (FK → projects), `borehole_no`, `tech`,
`drilling_method`, `od_augers`, `weather`, `date_started`, `sheet_no`, `total_sheets`,
`driller`, `drilling_rig`, `hammer_weight`, `hammer_drop`, `water_level_depth`,
`cave_in`, plus **Chunk 2** additions: `latitude`, `longitude`, `ground_elevation_ft`,
`datum`, `depth_reference_datum`, `total_depth_ft`, `termination_reason` (CHECK:
refusal/planned_depth/obstruction/other), `groundwater` (jsonb), `hammer_type`,
`hammer_efficiency`, `sampler_id`, `borehole_diameter_in`.

**`samples`** — the big one. `id`, `created_at`, `project_id` + `borehole_id` (FKs),
core SPT/sample fields (`sample_no`, `depth_ft`, `depth_m`, `n_value`, `n_value_log`,
`refusal`, `recovery_inches`, `recovery_mm`, `blow_counts`/`pen_depths`/`flags` — these
three are **legacy `text` columns holding JSON strings**, not jsonb, hence the
`json.dumps()` calls in `app.py`'s `confirm_sample`), `description`, `raw_transcript`,
`comments`, `cgd_ppm`/`pid_ppm`, `cone_blow_ft`, `sample_type`, `layers` (jsonb, for
split-layer samples), and the **Chunk 1 structured fields**: `soil_name`,
`particle_size_range`, `color`, `moisture`, `plasticity`, `gradation`, `consistency`,
`density`, `uscs_symbol`, `fill`, `inclusions`/`components`/`descriptor_fields` (jsonb),
`depth_start_ft`/`depth_end_ft`. Plus some columns that are **schema-ahead-of-pipeline**
(present in the DB, not yet populated by any code path): `n60` (double precision — no
corresponding field in `models.SampleEntry`), `source` (CHECK: voice/ingested/manual,
default `'voice'`), `review_status` (CHECK: unreviewed/auto_accepted/human_verified,
default `'unreviewed'`), `confidence_score`, `pen_depth_source` (CHECK: five ingestion
provenance values), `stratum_id` (FK → `strata`), `ingestion_source_id` (FK →
`ingestion_sources`), `source_page`, `source_row`, `raw_extracted_text`,
`ocr_confidence`, `lab_tests` (jsonb — used by the synthetic generator, not by the live
pipeline).

**`strata`** — `id`, `borehole_id` (FK), `depth_start_ft`/`depth_end_ft`, `soil_name`,
`uscs_symbol`, `description`, `derivation` (CHECK: extracted/inferred/voice_logged),
`descriptor_fields` (jsonb), `ingestion_source_id` (FK), `source_page`, `source_row`,
`created_at`. **Not referenced anywhere in current Python code** — this plus
`samples.stratum_id` is schema laid down for a future "ingest someone else's PDF boring
log and extract strata" feature, ahead of the code that would populate it.

**`ingestion_sources`** — `id`, `project_id` (FK), `filename`, `file_hash`,
`file_size_bytes`, `uploaded_at`, `ingestion_status` (CHECK: pending/processing/
processed/failed/partial), `firm_config_id`, `error_log`. Same story — schema exists,
no ingestion code consumes it yet. `firm_config_id` is presumably meant to key into
something like `tools/firm_styles.py`'s `FIRM_STYLES` dict, but that dict is in-code,
not DB-backed.

### ⚠️ Critical: Row Level Security is disabled on all 5 tables

Supabase's own advisor flags this as **critical**: `projects`, `boreholes`, `samples`,
`ingestion_sources`, and `strata` all have RLS **disabled**, meaning anyone holding the
anon/publishable key (which ships in `index.html`'s requests, or anywhere the frontend
runs) can read or write every row in the database with no restriction. This has not been
addressed. I have **not** applied any fix — enabling RLS without policies would lock out
the app entirely, so this needs a deliberate policy design (likely "anyone can do
anything for now" while single-tenant, or real auth if this becomes multi-firm). The
remediation SQL Supabase suggests, for when you're ready:

```sql
ALTER TABLE "public"."samples" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."projects" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."boreholes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."ingestion_sources" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."strata" ENABLE ROW LEVEL SECURITY;
```
Running this alone (with no policies) will make the app stop working — add policies in
the same migration.

### The "corrections table" and "firm profiles" you asked about

**Neither exists as a database table.** They're a design proposal only, written up in
`docs/substitution_strategy.md` ("Substitution Strategy — Transcript-Level
Calibration"). The idea: when a tech edits a pipeline draft before confirming, store the
correction in a (currently hypothetical) `corrections` table; accumulate those into a
per-firm `firm_profiles` calibration profile; apply learned substitutions to the raw
transcript before it hits `segment_transcript()`, the same mechanism as
`WHISPER_CORRECTIONS`. The doc itself lists three unresolved problems blocking
implementation (see §4, item 7) — including a noted **type mismatch**: the sketch assumes
`corrections.sample_id` would be `uuid`, which the doc itself flags as wrong since
`samples.id` is `bigint` (consistent with this repo's hard rule that all Supabase IDs are
int8, never UUID). There's no `calibration.py` file in the repo — the functions sketched
in the doc (`apply_firm_substitutions`, `get_firm_profile`) don't exist yet anywhere.
`tools/firm_styles.py`'s `FIRM_STYLES` dict is a related but separate concept — PDF
column/abbreviation styling for the synthetic-log generator, not a learned-correction
profile, and it's a hardcoded Python dict, not a DB table.

---

## 4. Running locally, and what I found broken or half-finished

### Setup
```bash
pip install -r requirements-dev.txt
uvicorn app:app --reload
```
Tests: `pytest` (config in `pytest.ini`, `testpaths = tests`).
Production entry point: `Procfile` → `uvicorn app:app --host 0.0.0.0 --port $PORT`.
Required env vars (`.env`, loaded via `python-dotenv`): `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` — I confirmed all four are populated in
your local `.env` (didn't print values). `SUPABASE_KEY` is only 46 characters, which
reads as one of Supabase's newer short-form `sb_publishable_...`/`sb_secret_...` keys
rather than a legacy long JWT — worth double-checking it's the key you intend, given the
RLS situation above.

### Things I found broken or half-finished, roughly in order of how much they'll bite you

**1. `correct_transcript()` in `whisper.py` has a real bug — committed, not just a
work-in-progress edit.** The `return` statement is indented one level too deep, inside
the `for mistake, correction in WHISPER_CORRECTIONS.items():` loop body:

```python
def correct_transcript(transcript: str) -> str:
    corrected = transcript.lower()
    for mistake, correction in WHISPER_CORRECTIONS.items():
        corrected = re.sub(r'\b' + re.escape(mistake) + r'\b', correction, corrected)
        return normalize_soil_names(corrected)   # ← inside the loop
```
This means only the **first** entry in `WHISPER_CORRECTIONS` (`"tree scrabble"` →
`"trace gravel"`) is ever checked before the function returns. Every other mishearing
correction in that dictionary (silky clay, sum gravel, mo ist, clay silk, etc. — about
20 entries) is dead code right now. Fix is a one-line dedent of the `return`.

**2. Uncommitted working-tree changes currently break the Chunk 1 structured-field
pipeline end-to-end.** `git status` shows uncommitted edits to `app.py`, `index.html`,
`pipeline.py`, `tools/pdf_renderer.py` (plus untracked `AGENTS.md`, `.codex/`). The
`pipeline.py` diff removes the entire block in `combination()` that was populating
`soil_name`, `particle_size_range`, `color`, `moisture`, `plasticity`, `gradation`,
`consistency`, `density`, `uscs_symbol`, `fill`, `inclusions`, `components`,
`descriptor_fields`, `depth_start_ft`, `depth_end_ft` onto the returned `SampleEntry` —
every one of them, not just the particle-size/descriptor-field additions the
`EXTRACTION_PROMPT` diff suggests was the actual intent. Meanwhile the uncommitted
`index.html`/`app.py` changes build out a whole manual-edit UI + insert allowlist
expecting those same fields to be editable and persisted. Net effect **right now**: a
voice-logged sample will persist `NULL` for every Chunk 1 structured column unless the
tech manually opens the new "Soil Classification (advanced)" panel and fills it in by
hand — the automatic extraction→persistence path that commit `0c4c3bf` just added is
silently disconnected. This looks like a mid-refactor state (possibly intentionally
moving from "Claude auto-fills these" to "manual entry only" for `particle_size_range`/
`descriptor_fields` specifically, but the diff took the whole block with it). Given
`CLAUDE.md`'s own instruction — *"do NOT remove the structured fields when editing
combination()"* — this is almost certainly not the intended end state. Worth deciding
deliberately before committing: restore the `top_*` assignment block (minus
`particle_size_range`/`descriptor_fields` if those are being deprecated from
auto-extraction on purpose), or finish the pivot to manual-only entry consistently.

**3. RLS disabled on all 5 tables** — see §3. Not new, but worth re-surfacing since it's
easy to forget about between sessions.

**4. Schema ahead of code in a few places** (not bugs, just things to know aren't wired
up yet): `samples.n60`, `source`, `review_status`, `confidence_score`,
`pen_depth_source`, `stratum_id`, `ingestion_source_id`, `source_page`, `source_row`,
`raw_extracted_text`, `ocr_confidence`; the entire `strata` and `ingestion_sources`
tables. These all look like groundwork for a future "ingest a PDF/scanned boring log
from another firm" pipeline, consistent with `tools/soil_corpus.py`'s scenario-coverage
framing and `tools/firm_styles.py`'s "before Chunk 5 ingestion" comment.

**5. `test_generate_sample_pdf.py` is stale and will crash if run.** It calls
`generate_pdf.generate_boring_log(project_id=..., borehole_id=..., output_path=out)`,
but the current signature in `generate_pdf.py` is
`generate_boring_log(project_id: int, borehole_id: int) -> bytes` — no `output_path`
parameter, and it returns PDF bytes rather than writing a file. This script predates the
refactor that made `generate_pdf.py` return bytes (so `app.py` could wrap it in a FastAPI
`Response`), and nobody updated the demo script to match.

**6. Untracked files sitting in the repo**: `.codex/` (a `code-reviewer` agent config,
mirrors `.claude/agents/`) and `AGENTS.md` (Codex's equivalent of `CLAUDE.md`, currently
*slightly* stale — it still describes `get_consistency_density`'s "from
classification_engine import COHESIVE_TERMS, COHESIONLESS_TERMS" split-into-consistency/
density logic that the uncommitted `pipeline.py` diff also strips out). Not broken, just
flagging so you don't mistake them for accidental scratch files — they look intentional
(parallel Codex tooling) but are currently untracked.

**7. No tests for `pipeline.py` or `app.py`.** `tests/` only covers the pure functions in
`parser.py` and `classification_engine.py` — reasonable, since those need no mocking, but
it means the Claude-calling orchestration logic (the split/single-layer branches, flag
generation, the now-broken structured-field assembly from item 2) has zero automated
coverage. `requirements-dev.txt` already includes `pytest-mock`, so the scaffolding for
mocking the Anthropic/OpenAI/Supabase clients is available, just unused.

---

## 5. Open TODOs / design questions (pulled from code comments, docs, and commit history)

From `docs/substitution_strategy.md` (the corrections/firm-profile design — not yet
implemented, see §3), three explicitly unresolved blockers before it could be built:
1. **Positional diff is fragile** — `extract_word_substitutions()` (referenced in the doc,
   doesn't exist in the repo yet) would compare words by index position; any reordering
   by the tech cascades into false-positive substitutions. Doc suggests only promoting
   substitutions where original/corrected word counts match, as a first cut.
2. **Type mismatch** — the sketch assumes `corrections.sample_id` is `uuid`; must be
   `bigint` to match `samples.id` (consistent with this repo's absolute "never UUID" rule).
3. **No profile versioning / rollback** — a bad learned substitution promoted into
   `firm_profiles` has no undo path. Doc suggests a `previous_substitutions` column or a
   `firm_profile_history` table.
   Suggested gate before enabling in production: 50+ confirmed corrections with
   `description_was_edited = true`, to validate the extraction signal is clean first.

From `tools/` docstrings — the synthetic-log / firm-style work is explicitly staged:
- `firm_styles.py`: only 2 generic placeholder firms exist; real firms (Envision, etc.)
  are planned "before Chunk 5 ingestion."
- `generate_synthetic_log.py`: "Stratigraphic + hybrid + real firm styles deferred to
  Chunk 3b / 5" — i.e. today's synthetic generator only does sample-driven logs.
- The `strata`/`ingestion_sources` tables plus `assert_coverage.py`'s scenario-coverage
  gate strongly suggest the next big arc is: ingest a PDF boring log from another firm,
  OCR/extract strata, and validate against the synthetic ground-truth corpus — but no
  ingestion code exists yet.

From code:
- `parser.py`'s `parse_uscs_symbol` / `parse_plasticity` / `parse_gradation` are fully
  implemented and tested but appear to be **dead code** — `pipeline.py` gets these same
  fields from the Claude `EXTRACTION_PROMPT` instead. Worth deciding whether to delete
  them or keep as a deterministic fallback/cross-check.
- `models.py`'s `BoreholeLog.get_sample()` has a leftover `# YOUR CODE HERE` comment
  even though the method is implemented — cosmetic, but looks like it was never cleaned
  up after an early scaffolding pass.
- See §4 items 1 and 2 for the two concrete bugs that should probably be the first things
  fixed when you pick this back up.
