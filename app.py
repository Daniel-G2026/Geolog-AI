# app.py
# FastAPI web interface for GeoLog AI
# Exposes the voice logging pipeline as a REST API

import os
import re
import json
import logging
from dataclasses import asdict
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pipeline import run_from_voice
from classification_engine import parse_blow_counts
from supabase import create_client
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from uuid import uuid4
from typing import Optional
supabase_client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)
class ProjectCreate(BaseModel):
    project_no: str                 # project reference number e.g. "25-1021"
    client: str                 # client name
    project_name: Optional[str] = None                # project name
    location: Optional[str] = None            # site location      
    

class BoreholeCreate(BaseModel):
    # ── Required header fields ──
    borehole_no: str            # e.g. "BH25-1"
    tech: str                   # field technician name
    drilling_method: Optional[str] = None        # e.g. "Hollow Stem Auger"
    od_augers: Optional[str] = None              # auger diameter e.g. "203mm"
    date_started: Optional[str] = None         # date drilling started
    driller: Optional[str] = None               # drilling company
    sheet_no: int = 1
    total_sheets: int = 1
    # ── Optional header fields ──                  
    weather: Optional[str] = None
    drilling_rig: Optional[str] = None
    hammer_weight: Optional[str] = None   # lbs
    hammer_drop: Optional[str] = None     # inches
    water_level_depth: Optional[float] = None   # m
    cave_in: Optional[float] = None             # m

    # ── Chunk 2: location, termination, equipment, groundwater ──
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    ground_elevation_ft: Optional[float] = None
    datum: Optional[str] = None
    depth_reference_datum: Optional[str] = None
    total_depth_ft: Optional[float] = None
    termination_reason: Optional[str] = None       # refusal / planned_depth / obstruction / other
    groundwater: Optional[dict] = None             # JSONB
    hammer_type: Optional[str] = None
    hammer_efficiency: Optional[float] = None
    sampler_id: Optional[str] = None
    borehole_diameter_in: Optional[float] = None

class LayerDepthUpdate(BaseModel):
    index: int
    depth_start: Optional[float] = None
    depth_end: Optional[float] = None

class LayerDepthPatchRequest(BaseModel):
    layers: list[LayerDepthUpdate]


# Whitelist of columns accepted from the /samples/confirmed payload.
# Anything not in this set is dropped before INSERT — defense against
# malicious or buggy clients spoofing server-controlled fields like
# `source`, `review_status`, `confidence_score`, `stratum_id`, or `id`.
# Server-controlled columns (project_id, borehole_id, source defaults,
# ingestion provenance) are populated explicitly inside the endpoint.
SAMPLES_INSERT_ALLOWLIST = frozenset({
    # Sample identification + SPT
    "sample_no", "depth_ft", "depth_m", "sample_type",
    "blow_counts", "pen_depths", "n_value", "n_value_log", "refusal",
    "recovery_inches", "recovery_mm", "cone_blow_ft",
    # Field screening
    "cgd_ppm", "pid_ppm",
    # Description
    "raw_transcript", "description", "flags", "layers", "comments", "timestamp",
    # Chunk 1 structured fields (all editable in the confirm UI)
    "soil_name", "particle_size_range", "color", "moisture",
    "plasticity", "gradation", "consistency", "density",
    "uscs_symbol", "fill",
    "inclusions", "components", "descriptor_fields",
    "depth_start_ft", "depth_end_ft",
})

# ── DB helpers ──

def check_existing(table: str, column: str, value, select: str = "id"):
    result = (
        supabase_client
        .table(table)
        .select(select)
        .eq(column, value)
        .limit(1)
        .execute()
    )
    if not result.data:
        return {"found": False, "data": None}
    return {"found": True, "data": result.data[0]}

def get_project(project_id: int):
    try:
        r = check_existing("projects", "id", project_id, "id")
        if not r["found"]:
            raise HTTPException(status_code=404, detail="Project not found")
        return r["data"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def get_borehole(project_id: int, borehole_id: int):
    try:
        result = (
            supabase_client
            .table("boreholes")
            .select("id, borehole_no")
            .eq("id", borehole_id)
            .eq("project_id", project_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Borehole not found")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app = FastAPI()


# CORS middleware — allows browser requests from any origin
# Replace "*" with your deployed domain in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health check endpoint ──
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/projects")
async def find_project(project_no: str):
    try:
        result = supabase_client.table("projects") \
            .select("id, project_no, client, project_name, location") \
            .eq("project_no", project_no) \
            .limit(1) \
            .execute()
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Project '{project_no}' not found.")
        return {"found": True, "project": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/projects/{project_id}/boreholes")
async def list_boreholes(project_id: int):
    try:
        get_project(project_id)
        result = supabase_client.table("boreholes") \
            .select("id, borehole_no, tech, date_started, drilling_method") \
            .eq("project_id", project_id) \
            .execute()
        return {"boreholes": result.data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/projects")
async def create_project(data: ProjectCreate):
    try:
        duplicate = check_existing("projects", "project_no", data.project_no)
        if duplicate["found"]:
            raise HTTPException(status_code=400, detail=f"Project number '{data.project_no}' already exists.")

        result = supabase_client.table("projects").insert(data.model_dump()).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Insert failed")

        return {"saved": True, "project_id": result.data[0]["id"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/projects/{project_id}/boreholes")
async def create_borehole(project_id: int, data: BoreholeCreate):
    try:


        duplicate = supabase_client.table("boreholes") \
            .select("id") \
            .eq("project_id", project_id) \
            .eq("borehole_no", data.borehole_no) \
            .limit(1) \
            .execute()
        if duplicate.data:
            raise HTTPException(status_code=400, detail=f"Borehole '{data.borehole_no}' already exists in this project.")

        dict_data = data.model_dump()
        dict_data["project_id"] = project_id
        print(f"DEBUG keys being inserted: {list(dict_data.keys())}")
        result = supabase_client.table("boreholes").insert(dict_data).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Insert failed")

        return {"saved": True, "project_id": project_id, "borehole_id": result.data[0]["id"]}
    except HTTPException:
        raise
    except Exception as e:
        err = str(e)
        if "23505" in err or "duplicate key" in err.lower():
            raise HTTPException(status_code=400, detail=f"Borehole '{data.borehole_no}' already exists in this project.")
        raise HTTPException(status_code=500, detail=err)

# ── Main logging endpoint ──
@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/draft")
async def log_sample(
    request: Request,
    project_id: int,
    borehole_id: int,
    audio: UploadFile = File(...),
    sample_no: int = Form(...),
    depth_ft: float = Form(...)
):
    get_borehole(project_id, borehole_id)

    temp_path = f"temp_{uuid4().hex}_{audio.filename}"
    try:
        # 1. Save audio to temp file
        with open(temp_path, "wb") as f:
            f.write(await audio.read())

        # If user cancelled before upload finished, skip the pipeline
        if await request.is_disconnected():
            return

        # 2. Run full pipeline
        result = run_from_voice(
            audio_file_path=temp_path,
            sample_no=sample_no,
            depth_ft=depth_ft
        )

        # 3. Return SampleEntry as JSON
        return asdict(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.get("/projects/{project_id}/boreholes/{borehole_id}/samples")
async def list_samples(project_id: int, borehole_id: int):
    """Return all confirmed samples for a borehole, sorted by depth.

    blow_counts / pen_depths / flags are stored as JSON strings on insert
    (see confirm_sample); parse them back into arrays here so the frontend
    receives the same shape the draft pipeline returns.
    """
    try:
        get_borehole(project_id, borehole_id)
        result = (
            supabase_client.table("samples")
            .select("*")
            .eq("project_id", project_id)
            .eq("borehole_id", borehole_id)
            .order("depth_ft")
            .execute()
        )
        samples = []
        for row in (result.data or []):
            for key in ("blow_counts", "pen_depths", "flags", "layers"):
                v = row.get(key)
                if isinstance(v, str):
                    try:
                        row[key] = json.loads(v)
                    except Exception:
                        row[key] = [] if key != "layers" else None
                elif v is None and key != "layers":
                    row[key] = []
            samples.append(row)
        return {"samples": samples}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/recalculate")
async def recalculate_sample(project_id: int, borehole_id: int, sample_data: str = Form(...)):
    try:
        from pipeline import combination
        data = json.loads(sample_data)
        blow_counts = data["blow_counts"]
        pen_depths = data["pen_depths"]
        transcript = data.get("raw_transcript", "")

        result = combination(
            transcript=transcript,
            blow_counts=blow_counts,
            sample_no=data["sample_no"],
            depth_ft=data["depth_ft"]
        )
        return asdict(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/projects/{project_id}/boreholes/{borehole_id}/samples/check")
async def check_sample_at_depth(
    project_id: int,
    borehole_id: int,
    depth_ft: float = Query(None),
    sample_no: int = Query(None),
):
    try:
        depth_exists = False
        sample_no_exists = False

        if depth_ft is not None:
            r = supabase_client.table("samples") \
                .select("id") \
                .eq("project_id", project_id) \
                .eq("borehole_id", borehole_id) \
                .eq("depth_ft", depth_ft) \
                .execute()
            depth_exists = bool(r.data)

        if sample_no is not None:
            r = supabase_client.table("samples") \
                .select("id") \
                .eq("project_id", project_id) \
                .eq("borehole_id", borehole_id) \
                .eq("sample_no", sample_no) \
                .execute()
            sample_no_exists = bool(r.data)

        return {
            "exists": depth_exists or sample_no_exists,
            "depth_exists": depth_exists,
            "sample_no_exists": sample_no_exists,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/recalculate_recovery")
async def recalculate_recovery(project_id: int, borehole_id: int, sample_data: str = Form(...)):
    try:
        data = json.loads(sample_data)
        pen_depths = data["pen_depths"]
        total_penetration = sum(pen_depths)
        new_recovery = data["recovery_inches"]

        if new_recovery <= total_penetration:
            return {"recovery_inches": new_recovery, "recovery_mm": round(new_recovery * 25.4), "flag": None}
        else:
            return {
                "recovery_inches": new_recovery,
                "recovery_mm": round(new_recovery * 25.4),
                "flag": f"Recovery exceeds total penetration ({new_recovery}\" recovery vs {total_penetration}\" penetrated) — manual review required"
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/confirmed")
async def confirm_sample(project_id: int, borehole_id: int, sample_data: str = Form(...)):
    try:
        #saftey check to see if borehole exists
        _ = get_borehole(project_id, borehole_id)
        data = json.loads(sample_data)

        # Guard against duplicate depth or sample_no before insert
        depth_ft = data.get("depth_ft")
        sample_no = data.get("sample_no")

        existing_depth = supabase_client.table("samples") \
            .select("id") \
            .eq("project_id", project_id) \
            .eq("borehole_id", borehole_id) \
            .eq("depth_ft", depth_ft) \
            .limit(1) \
            .execute()
        if existing_depth.data:
            raise HTTPException(status_code=400, detail=f"A sample at depth {depth_ft} ft already exists in this borehole.")

        existing_no = supabase_client.table("samples") \
            .select("id") \
            .eq("project_id", project_id) \
            .eq("borehole_id", borehole_id) \
            .eq("sample_no", sample_no) \
            .limit(1) \
            .execute()
        if existing_no.data:
            raise HTTPException(status_code=400, detail=f"Sample number {sample_no} already exists in this borehole.")

        # Recalculate SPT fields from submitted blow counts
        blow_counts = data["blow_counts"]
        pen_depths = data["pen_depths"]
        #recalculate blowcounts to ensure blow counts are always consistent in DB. In case the edited values drifterd from the recalculate endpoint
        if blow_counts:
            spt = parse_blow_counts(blow_counts, pen_depths)
            data["n_value"] = spt["n_value"]
            data["n_value_log"] = spt["n_value_log"]
            data["refusal"] = spt["refusal"]

        # Drop any client-supplied keys not on the allowlist so a malicious
        # or buggy client can't spoof server-controlled columns (source,
        # review_status, confidence_score, stratum_id, id, etc.).
        data = {k: v for k, v in data.items() if k in SAMPLES_INSERT_ALLOWLIST}

        # NOTE: blow_counts/pen_depths/flags are stored as `text` columns
        # (legacy schema) so they must be JSON-stringified before insert.
        # DO NOT add the Chunk 1 JSONB columns (inclusions, components,
        # lab_tests, descriptor_fields, layers) to this block — they are
        # real `jsonb` and supabase-py serializes Python dicts/lists natively.
        data["blow_counts"] = json.dumps(blow_counts)
        data["pen_depths"] = json.dumps(pen_depths)
        data["flags"] = json.dumps(data.get("flags") or [])
        data["layers"] = data.get("layers")
        data["project_id"] = project_id
        data["borehole_id"] = borehole_id

        result = supabase_client.table("samples").insert(data).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Insert failed")

        return {"saved": True, "sample_id": result.data[0]["id"]}
    except HTTPException:
        raise
    except Exception:
        # Log the real error server-side; return a generic message to clients
        # so Postgres constraint text (column names, CHECK contents, etc.)
        # doesn't leak via the API.
        logging.exception("confirm_sample failed")
        raise HTTPException(status_code=500, detail="Failed to save sample — see server logs.")

@app.patch("/projects/{project_id}/boreholes/{borehole_id}/samples/{sample_id}/layers")
async def patch_layer_depths(project_id: int, borehole_id: int, sample_id: int, data: LayerDepthPatchRequest):
    try:
        result = supabase_client.table("samples") \
            .select("layers") \
            .eq("id", sample_id) \
            .eq("project_id", project_id) \
            .eq("borehole_id", borehole_id) \
            .single() \
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Sample not found")

        current_layers = result.data.get("layers")
        if not current_layers or not isinstance(current_layers, list):
            raise HTTPException(status_code=400, detail="Sample has no split-layer data")

        for update in data.layers:
            i = update.index
            if i < 0 or i >= len(current_layers):
                raise HTTPException(status_code=400, detail=f"Layer index {i} out of range")
            lf = current_layers[i]
            if update.depth_start is not None:
                lf["depth_start"] = update.depth_start
            if update.depth_end is not None:
                lf["depth_end"] = update.depth_end
            current_layers[i] = lf

        # Rebuild top-level description
        all_prefixed = []
        for lf in current_layers:
            s = lf.get("depth_start")
            e = lf.get("depth_end")
            d = lf.get("description", "")
            if s is not None and e is not None:
                start_str = int(s) if s == int(s) else s
                end_str = int(e) if e == int(e) else e
                all_prefixed.append(f"{start_str}-{end_str} in: {d}")
            else:
                all_prefixed.append(d)
        top_description = " / ".join(all_prefixed)

        patch_result = supabase_client.table("samples") \
            .update({"layers": current_layers, "description": top_description}) \
            .eq("id", sample_id) \
            .execute()

        if not patch_result.data:
            raise HTTPException(status_code=500, detail="Patch failed")

        return {"updated": True, "description": top_description, "layers": current_layers}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/projects/{project_id}/boreholes/{borehole_id}/pdf")
def export_borehole_pdf(project_id: int, borehole_id: int):
    # Imported here to avoid the circular import (generate_pdf imports
    # supabase_client from app at module load).
    from generate_pdf import generate_boring_log

    try:
        project_row = (
            supabase_client.table("projects")
            .select("id, project_no")
            .eq("id", project_id)
            .limit(1)
            .execute()
        )
        if not project_row.data:
            raise HTTPException(status_code=404, detail="Project not found")

        borehole_row = (
            supabase_client.table("boreholes")
            .select("id, borehole_no")
            .eq("id", borehole_id)
            .eq("project_id", project_id)
            .limit(1)
            .execute()
        )
        if not borehole_row.data:
            raise HTTPException(status_code=404, detail="Borehole not found")

        try:
            pdf_bytes = generate_boring_log(project_id, borehole_id)
        except ValueError as ve:
            raise HTTPException(status_code=404, detail=str(ve))

        def _safe(part: str) -> str:
            return re.sub(r"[^A-Za-z0-9._-]+", "_", part or "").strip("_") or "log"

        project_no = _safe(str(project_row.data[0].get("project_no") or "project"))
        borehole_no = _safe(str(borehole_row.data[0].get("borehole_no") or "borehole"))
        filename = f"{project_no}_{borehole_no}_boring_log.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception:
        logging.exception("PDF export failed project_id=%s borehole_id=%s", project_id, borehole_id)
        raise HTTPException(status_code=500, detail="PDF export failed")


@app.get("/")
def serve_ui():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<pre>Error: {e}</pre>", status_code=500)