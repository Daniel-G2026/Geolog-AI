# GeoLog AI

GeoLog AI turns a field technician's spoken soil-sample description into a
structured, ASTM D2488/USCS-style geotechnical log entry — SPT N-value,
consistency/density, formatted description — saved to Supabase and
exportable as a PDF boring log.

A technician drives a borehole and speaks a voice memo describing the
sample (soil type, color, moisture, blow counts, recovery, etc.). GeoLog AI
transcribes it, extracts the relevant fields, runs the SPT/USCS math
deterministically in Python, and produces a clean, ASTM-formatted
description — flagging anything ambiguous for manual review instead of
guessing.

## Architecture

**Python does all geotechnical math and parsing. Claude is used only for
fuzzy field extraction and final ASTM-style description formatting.**
Calculations and keyword detection never move into a Claude call, and
language interpretation is never hardcoded where it belongs in one.

Request flow:

```
app.py (FastAPI) -> pipeline.run_from_voice -> whisper.transcribe
                  -> pipeline.combination -> SampleEntry (models.py)
```

- **`app.py`** — FastAPI surface: endpoints for projects/boreholes/samples
  (create, list, draft-from-voice, recalculate, confirm/insert, PDF export)
  and serves the frontend at `GET /`.
- **`whisper.py`** — transcribes voice memos via OpenAI Whisper and corrects
  known mishearings (word-boundary-safe synonym substitution).
- **`parser.py`** — deterministic transcript segmentation: splits the
  transcript into sections (description, blows, recovery, comments, …) and
  parses blow-count/recovery strings.
- **`classification_engine.py`** — deterministic SPT N-value math and ASTM
  D2488/USCS classification (consistency/density lookup). No API calls.
- **`pipeline.py`** — the only file that calls the Anthropic API. Two calls:
  extraction (natural speech → strict JSON) and formatting (structured
  dict → one ASTM-style description string). Never raises on bad/missing
  data — always short-circuits to a flagged `SampleEntry`.
- **`models.py`** — plain dataclasses (`SampleEntry`, `BoreholeLog`,
  `Project`), no ORM.
- **`generate_pdf.py`** — renders the final boring log as a depth-scaled PDF,
  pulling data directly from Supabase.
- **`index.html`** — single-file frontend served by the FastAPI app.
- **`tools/`** — synthetic log/data generation and per-firm PDF styling.

## Setup

```bash
pip install -r requirements-dev.txt
```

Create a `.env` file with:

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

## Running

```bash
uvicorn app:app --reload
```

Then open `http://localhost:8000`.

Production entry point (see `Procfile`):

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

## Testing

```bash
pytest
```

Run a single file or test with `pytest tests/test_parser.py` or
`pytest tests/test_parser.py::test_name`.

## Documentation

- [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) — guidance and
  architectural rules for AI coding agents working in this repo.
- [`PROJECT_STATE.md`](PROJECT_STATE.md) — a deeper module-by-module
  walkthrough and project snapshot.
