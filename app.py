# app.py
# FastAPI web interface for GeoLog AI
# Exposes the voice logging pipeline as a REST API

import os
import json
from dataclasses import asdict
from fastapi import FastAPI, UploadFile, File, Form
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
    project_name: str                # project name
    location: str               # site location      
    

class BoreholeCreate(BaseModel):
    # ── Required header fields ──
    borehole_no: str            # e.g. "BH25-1"
    tech: str                   # field technician name
    drilling_method: str        # e.g. "Hollow Stem Auger"
    od_augers: str              # auger diameter e.g. "203mm"
    date_started: str           # date drilling started
    driller: str                # drilling company
    sheet_no: int = 1
    total_sheets: int = 1
    # ── Optional header fields ──                  
    weather: Optional[str] = None                
    drilling_rig: str = ""
    hammer_weight: Optional[str] = None   # lbs
    hammer_drop: Optional[str] = None     # inches
    water_level_depth: Optional[float] = None   # m
    cave_in: Optional[float] = None             # m
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

@app.post("/projects")
async def create_project(data:ProjectCreate):
    try:
        # Check for duplicate project_no
        existing = supabase_client.table("projects") \
            .select("id") \
            .eq("project_no", data.project_no) \
            .limit(1) \
            .execute()
        if existing.data:
            return {"saved": False, "error": f"Project number '{data.project_no}' already exists."}

        dict_data = data.model_dump()
        result = supabase_client.table("projects").insert(dict_data).execute()
        if not result.data:
            return {"saved": False, "error": "Insert failed"}

        project_id = result.data[0]["id"]
        return {"saved": True, "project_id": project_id}
    except Exception as e:
        return {"saved": False, "error": str(e)}

@app.post("/projects/{project_id}/boreholes")
async def create_borehole(project_id:str,data:BoreholeCreate):
    try:
        project = supabase_client.table("projects") \
            .select("id, project_no") \
            .eq("id",project_id) \
            .limit(1) \
            .execute()
        if not project.data:
            return {"saved": False, "error": "Project not found"}
        project_no = project.data[0]["project_no"]

        dict_data = data.model_dump()
        dict_data["project_id"] = project_id
        dict_data["project_no"] = project_no
        result = supabase_client.table("boreholes").insert(dict_data).execute()
        if not result.data:
            return {"saved": False, "error": "Insert failed"}

        borehole_id = result.data[0]["id"]
        return {"saved":True, "project_id":project_id, "borehole_id":borehole_id}
    except Exception as e:
        return {"saved": False, "error": str(e)}

# ── Main logging endpoint ──
@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/draft")
async def log_sample(
    project_id: str,
    borehole_id: str,
    audio: UploadFile = File(...),
    sample_no: int = Form(...),
    depth_ft: float = Form(...)
):
    borehole = supabase_client.table("boreholes") \
        .select("id") \
        .eq("id",borehole_id) \
        .eq("project_id",project_id) \
        .limit(1) \
        .execute()
    
    if not borehole.data:
        return {"error":"Borehole not found"}

    temp_path = f"temp_{audio.filename}"
    try:
        # 1. Save audio to temp file
        with open(temp_path, "wb") as f:
            f.write(await audio.read())

        # 2. Run full pipeline
        result = run_from_voice(
            audio_file_path=temp_path,
            sample_no=sample_no,
            depth_ft=depth_ft
        )

        # 3. Return SampleEntry as JSON
        return asdict(result)
    except Exception as e:
        return {"error": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/recalculate")
async def recalculate_sample(project_id: str, borehole_id: str, sample_data: str = Form(...)):
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
    except Exception as e:
        return {"error": str(e)}

@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/confirmed")
async def confirm_sample(project_id:str, borehole_id:str,sample_data: str = Form(...)):
    try:
        # Look up project_no and borehole_no for denormalized storage
        borehole = supabase_client.table("boreholes") \
            .select("borehole_no, project_no") \
            .eq("id", borehole_id) \
            .eq("project_id", project_id) \
            .limit(1) \
            .execute()
        if not borehole.data:
            return {"saved": False, "error": "Borehole not found"}

        data = json.loads(sample_data)

        # Convert lists to JSON strings for storage
        # Recalculate SPT fields from submitted blow counts
        blow_counts = data["blow_counts"]
        pen_depths = data["pen_depths"]
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
        data["project_no"] = borehole.data[0]["project_no"]
        data["borehole_no"] = borehole.data[0]["borehole_no"]

        result = supabase_client.table("samples").insert(data).execute()

        if not result.data:
            return {"saved": False, "error": "Insert failed"}

        sample_id = result.data[0]["id"]
        return {"saved": True, "sample_id": sample_id}
    except Exception as e:
        return {"saved": False, "error": str(e)}

@app.get("/")
def serve_ui():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<pre>Error: {e}</pre>", status_code=500)