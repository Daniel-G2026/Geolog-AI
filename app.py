# app.py
# FastAPI web interface for GeoLog AI
# Exposes the voice logging pipeline as a REST API

import os
import json
from dataclasses import asdict
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query
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
        \
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
async def check_sample_at_depth(project_id: int, borehole_id: int, depth_ft: float = Query(...)):
    try:
        result = supabase_client.table("samples") \
            .select("id, sample_no, depth_ft") \
            .eq("project_id", project_id) \
            .eq("borehole_id", borehole_id) \
            .eq("depth_ft", depth_ft) \
            .execute()
        if result.data:
            return {"exists": True, "count": len(result.data)}
        return {"exists": False}
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

        # Guard against duplicate depth before insert
        depth_ft = data.get("depth_ft")
        existing = supabase_client.table("samples") \
            .select("id") \
            .eq("project_id", project_id) \
            .eq("borehole_id", borehole_id) \
            .eq("depth_ft", depth_ft) \
            .limit(1) \
            .execute()
        if existing.data:
            raise HTTPException(status_code=400, detail=f"A sample at depth {depth_ft} ft already exists in this borehole.")

        # Recalculate SPT fields from submitted blow counts
        blow_counts = data["blow_counts"]
        pen_depths = data["pen_depths"]
        #recalculate blowcounts to ensure blow counts are always consistent in DB. In case the edited values drifterd from the recalculate endpoint
        if blow_counts:
            spt = parse_blow_counts(blow_counts, pen_depths)
            data["n_value"] = spt["n_value"]
            data["n_value_log"] = spt["n_value_log"]
            data["refusal"] = spt["refusal"]

        data["blow_counts"] = json.dumps(blow_counts)
        data["pen_depths"] = json.dumps(pen_depths)
        data["flags"] = json.dumps(data["flags"])
        data["project_id"] = project_id
        data["borehole_id"] = borehole_id

        result = supabase_client.table("samples").insert(data).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Insert failed")

        return {"saved": True, "sample_id": result.data[0]["id"]}
    except Exception as e:
        return {"saved": False, "error": str(e)}

@app.get("/")
def serve_ui():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<pre>Error: {e}</pre>", status_code=500)