import os
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Security
from fastapi.security import APIKeyHeader
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.status import HTTP_403_FORBIDDEN

from youtube_factory.models import Job
from youtube_factory.worker import run_pipeline, queue, SessionLocal, engine

# Init FastAPI
app = FastAPI(title="YouTube Factory Monitor")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependencies
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

API_KEY_NAME = "X-API-KEY"
MONITOR_API_KEY = os.environ.get("MONITOR_API_KEY")

api_key_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def get_api_key(api_key_header: Optional[str] = Security(api_key_scheme)):
    if MONITOR_API_KEY:
        if api_key_header != MONITOR_API_KEY:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN, detail="Could not validate credentials"
            )
    return api_key_header

# Models
class JobRequest(BaseModel):
    topic: str
    niche: str
    language: str = "en"
    voice_profile: str = "alloy"
    length: int = 480

class JobSummary(BaseModel):
    id: int
    status: str
    niche: Optional[str]
    topic_hint: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# Routes

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/jobs", response_model=List[JobSummary], dependencies=[Depends(get_api_key)])
def list_jobs(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).offset(skip).limit(limit).all()
    # Manual conversion if needed or pydantic handles it. 
    # created_at is datetime, pydantic handles it to ISO string usually.
    return jobs

@app.get("/jobs/{job_id}", dependencies=[Depends(get_api_key)])
def get_job_details(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.post("/enqueue", dependencies=[Depends(get_api_key)])
def enqueue_job_endpoint(req: JobRequest, db: Session = Depends(get_db)):
    # Create Job record
    job = Job(
        niche=req.niche,
        topic_hint=req.topic,
        status="queued"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Enqueue in RQ
    # mimicking parameters from worker.py: enqueue_job
    # retry logic: passing retry params requires a version of RQ that supports it or just kwarg. 
    # In worker.py I used retry=argparse.Namespace(...). I'll stick to simple dict or kwargs if RQ supports it, 
    # or just omit complex retry for API enqueue to match 'minimal' goal, 
    # OR replicate the Namespace hack if RQ expects an object with attributes.
    # RQ's `queue.enqueue` `retry` parameter usually expects a Retry object or similar.
    # Let's try to pass it simply or omit it for safety in API if imports are tricky.
    # We will import argparse to replicate the hack if needed, or better, just rely on RQ default or simplified.
    
    queue.enqueue(
        run_pipeline,
        job_id=job.id,
        topic=req.topic,
        niche=req.niche,
        language=req.language,
        voice_profile=req.voice_profile,
        length=req.length,
        job_timeout='1h'
    )
    
    return {"status": "queued", "job_id": job.id}

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(get_api_key)])
def dashboard(db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(50).all()
    
    rows = ""
    for j in jobs:
        rows += f"""
        <tr>
            <td><a href="/jobs/{j.id}">{j.id}</a></td>
            <td>{j.status}</td>
            <td>{j.niche}</td>
            <td>{j.topic_hint}</td>
            <td>{j.created_at}</td>
        </tr>
        """
    
    html_content = f"""
    <html>
        <head>
            <title>YouTube Factory Monitor</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                tr:nth-child(even) {{ background-color: #f9f9f9; }}
                a {{ text-decoration: none; color: #007bff; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h1>Recent Jobs</h1>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Status</th>
                        <th>Niche</th>
                        <th>Topic</th>
                        <th>Created At</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </body>
    </html>
    """
    return html_content
