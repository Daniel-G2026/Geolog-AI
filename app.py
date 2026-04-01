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
supabase_client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)

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

# ── Main logging endpoint ──
@app.post("/log-sample")
async def log_sample(
    audio: UploadFile = File(...),
    sample_no: int = Form(...),
    depth_ft: float = Form(...)
):
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
@app.post("/confirm-sample")
async def confirm_sample(sample_data: str = Form(...)):
    data = json.loads(sample_data)
    
    # Convert lists to JSON strings for storage
    data["blow_counts"] = json.dumps(data["blow_counts"])
    data["pen_depths"] = json.dumps(data["pen_depths"])
    data["flags"] = json.dumps(data["flags"])
    
    
    result = supabase_client.table("log_entries").insert(data).execute()
    return {"saved": True, "id": result.data[0]["id"]}

@app.get("/")
def serve_ui():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())