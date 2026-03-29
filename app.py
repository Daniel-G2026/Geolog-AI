# app.py
# FastAPI web interface for GeoLog AI
# Exposes the voice logging pipeline as a REST API

import os
import json
from dataclasses import asdict
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pipeline import run_from_voice
from pydantic import BaseModel

app = FastAPI()

# CORS middleware — allows browser requests from any origin
# Replace "*" with your deployed domain in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request body model ──
class SampleRequest(BaseModel):
    # YOUR FIELDS HERE
    pen_depths: list
    sample_no: int
    depth_ft: float
# ── Health check endpoint ──
@app.get("/health")
def health():
    # YOUR CODE HERE
    return {"status": "ok"}

# ── Main logging endpoint ──
@app.post("/log-sample")
async def log_sample(
    audio: UploadFile = File(...),
    pen_depths: str = Form(...),
    sample_no: int = Form(...),
    depth_ft: float = Form(...)
):
    # 1. Save audio to temp file
    temp_path = f"temp_{audio.filename}"
    with open(temp_path, "wb") as f:
        f.write(await audio.read())

    # 2. Parse pen_depths from JSON string to list
    pen_depths_list = json.loads(pen_depths)

    # 3. Run full pipeline
    result = run_from_voice(
        audio_file_path=temp_path,
        pen_depths=pen_depths_list,
        sample_no=sample_no,
        depth_ft=depth_ft
    )

    # 4. Clean up temp file
    os.remove(temp_path)

    # 5. Return SampleEntry as JSON
    return asdict(result)
