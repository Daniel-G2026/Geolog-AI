# app.py
# FastAPI web interface for GeoLog AI
# Exposes the voice logging pipeline as a REST API

import os
import json
from dataclasses import asdict
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pipeline import run_from_voice
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
    project_id = str(uuid4())

    dict_data = data.model_dump()
    dict_data["id"] = project_id

    result = supabase_client.table("projects").insert(dict_data).execute()
    if not result.data:
        return {"saved": False, "error": "Insert failed"}

    return {"saved": True, "project_id": project_id}

@app.post("/projects/{project_id}/boreholes")
async def create_borehole(project_id:str,data:BoreholeCreate):
    project = supabase_client.table("projects") \
        .select("id") \
        .eq("id",project_id) \
        .limit(1) \
        .execute()
    if not project.data:
        return {"error": "Project not found"}
    borehole_id =str(uuid4())
    
    dict_data = data.model_dump()
    dict_data["id"] = borehole_id
    dict_data["project_id"] = project_id
    result = supabase_client.table("boreholes").insert(dict_data).execute()
    if not result.data:
        return {"saved": False, "error": "Insert failed"}
    
    return {"saved":True, "project_id":project_id, "borehole_id":borehole_id}

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
    
    # 1. Save audio to temp file
    temp_path = f"temp_{audio.filename}"
    with open(temp_path, "wb") as f:
        f.write(await audio.read())


    # 2. Run full pipeline
    result = run_from_voice(
        audio_file_path=temp_path,
        sample_no=sample_no,
        depth_ft=depth_ft
    )

    # 3. Clean up temp file
    os.remove(temp_path)

    # 4. Return SampleEntry as JSON
    return asdict(result)


@app.post("/projects/{project_id}/boreholes/{borehole_id}/samples/confirmed")
async def confirm_sample(project_id:str, borehole_id:str,sample_data: str = Form(...)):

    sample = supabase_client.table("boreholes") \
        .select("id") \
        .eq("borehole_id",borehole_id) \
        .eq("project_id",project_id) \
        .limit(1) \
        .execute()
    data = json.loads(sample_data)
    sample_id = str(uuid4())

    # Convert lists to JSON strings for storage
    data["blow_counts"] = json.dumps(data["blow_counts"])
    data["pen_depths"] = json.dumps(data["pen_depths"])
    data["flags"] = json.dumps(data["flags"])
    data["project_id"] = project_id
    data["borehole_id"] = borehole_id
    data["id"] = sample_id

    result = supabase_client.table("samples").insert(data).execute()

    if not result.data:
        return {"saved": False, "error": "Insert failed"}
    
    return {"saved": True, "sample_id":sample_id}

@app.get("/")
def serve_ui():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())