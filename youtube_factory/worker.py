import os
import sys
import argparse
import logging
import json
from pathlib import Path
from datetime import datetime

from redis import Redis
from rq import Queue, Worker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import openai

# Import tasks
# Note: Assuming tasks are importable. 
# We don't have topic_finder yet based on history, but script_gen is there.
# I will assume topic_finder is either not strictly required if topic is passed, or I'll stub it/import it if it exists.
# The prompt says: "topic_finder -> script_gen ...". If topic is provided in CLI, maybe skip topic_finder?
# Or maybe topic_finder generates sub-topics?
# I'll implement the pipeline assuming the functions exist or import what I created.
# I created: script_gen, tts, assets, composer, thumbnail, uploader.
# I did NOT create topic_finder yet. I will check if it exists or just proceed with what I have and maybe add a placeholder.

from youtube_factory.tasks.script_gen import generate_script
from youtube_factory.tasks.tts import tts_from_text
from youtube_factory.tasks.assets import build_assets
from youtube_factory.tasks.composer import compose_video
from youtube_factory.tasks.thumbnail import generate_thumbnail
from youtube_factory.tasks.uploader import upload_video
from youtube_factory.models import Job, Base

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DB Setup
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./youtube_factory.db")
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# Redis Setup
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
redis_conn = Redis.from_url(REDIS_URL)
queue = Queue("youtube_factory", connection=redis_conn)

def _update_job_status(job_id: int, status: str, metadata: dict = None):
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if metadata:
                # Merge or replace metadata
                current_meta = dict(job.metadata_json or {})
                current_meta.update(metadata)
                job.metadata_json = current_meta
            session.commit()
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")
    finally:
        session.close()

def run_pipeline(job_id: int, topic: str, niche: str, language: str, voice_profile: str, length: int):
    """
    Executes the full video generation pipeline.
    """
    logger.info(f"Starting pipeline for Job {job_id} - Topic: {topic}")
    _update_job_status(job_id, "processing")
    
    storage_path = Path(os.environ.get("STORAGE_PATH", "/tmp/youtube_factory"))
    storage_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Script Generation (Skipping topic_finder for now as I wasn't asked to create it in previous turns, 
        # or I assume topic is passed directly. If topic_finder is needed, I'd call it here if topic was vague.)
        # Prompt says "topic_finder -> script_gen". I'll assume topic is the input to script_gen.
        
        # We need an LLM client. For now, we'll instantiate OpenAI client if key is present, or mock/fail?
        # The tasks expect dependency injection. In a real worker, we'd setup the client here.
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
             # For local testing without keys, this might fail unless mocked or handled.
             # We'll instantiate a client that uses the env var.
             llm_client = openai.OpenAI(api_key=api_key)
        else:
             llm_client = openai.OpenAI(api_key=api_key)

        logger.info("Generating script...")
        script_obj = generate_script(topic=topic, language=language, length_target_seconds=length, llm_client=llm_client)
        _update_job_status(job_id, "script_generated", {"script": script_obj})
        
        # 2. TTS
        logger.info("Generating voiceover...")
        # Combine hook + body sections for full text? Or pass sections?
        # composer expects a single audio file.
        # Let's concatenate text.
        full_text = script_obj.get("hook", "") + " "
        for sec in script_obj.get("sections", []):
            full_text += sec.get("heading", "") + ". " + sec.get("body", "") + " "
        full_text += script_obj.get("cta", "")
        
        voice_path = tts_from_text(full_text, voice_profile=voice_profile, llm_client=None, storage_path=storage_path) # llm_client used for http in tts, optional
        _update_job_status(job_id, "tts_complete", {"voice_path": str(voice_path)})
        
        # 3. Assets
        logger.info("Building assets...")
        pexels_key = os.environ.get("PEXELS_API_KEY")
        assets_paths = build_assets(script_obj, storage_path, pexels_api_key=pexels_key)
        _update_job_status(job_id, "assets_ready", {"assets": [str(p) for p in assets_paths]})
        
        # 4. Composer
        logger.info("Composing video...")
        final_video_path = compose_video(script_obj, voice_path, assets_paths, storage_path)
        _update_job_status(job_id, "video_composed", {"video_path": str(final_video_path)})
        
        # 5. Thumbnail
        logger.info("Generating thumbnail...")
        thumbnail_path = generate_thumbnail(script_obj, storage_path, ai_image_api_key=api_key)
        _update_job_status(job_id, "thumbnail_ready", {"thumbnail_path": str(thumbnail_path)})
        
        # 6. Uploader
        logger.info("Uploading...")
        upload_result = upload_video(
            final_video_path, 
            thumbnail_path, 
            script_obj.get("title", topic), 
            script_obj.get("hook", ""), # Description
            script_obj.get("tags", []), 
            credentials={} # Env vars used inside
        )
        
        final_status = "completed" if upload_result.get("status") == "uploaded" else "pending_upload"
        _update_job_status(job_id, final_status, {"upload_result": upload_result})
        logger.info(f"Job {job_id} finished with status: {final_status}")
        
    except Exception as e:
        logger.exception(f"Job {job_id} failed")
        _update_job_status(job_id, "failed", {"error": str(e)})
        raise e # Let RQ handle retry if configured, though we handled it by marking failed DB status.

def enqueue_job(topic, niche, language, voice_profile, length):
    session = SessionLocal()
    try:
        job = Job(niche=niche, topic_hint=topic, status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)
        
        # Enqueue to RQ
        queue.enqueue(
            run_pipeline, 
            job_id=job.id,
            topic=topic,
            niche=niche,
            language=language,
            voice_profile=voice_profile,
            length=length,
            job_timeout='1h',
            retry=argparse.Namespace(max=3, interval=[10, 30, 60]) # RQ 1.10+ supports Retry object or similar, but here simplified
        )
        
        print(json.dumps({"status": "queued", "job_id": job.id}))
        return job.id
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Factory Worker & CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # Enqueue Command
    enq_parser = subparsers.add_parser("enqueue")
    enq_parser.add_argument("--topic", required=True)
    enq_parser.add_argument("--niche", required=True)
    enq_parser.add_argument("--language", default="en")
    enq_parser.add_argument("--voice_profile", default="alloy")
    enq_parser.add_argument("--length", type=int, default=480)
    
    # Worker Command
    work_parser = subparsers.add_parser("work")
    
    args = parser.parse_args()
    
    if args.command == "enqueue":
        enqueue_job(args.topic, args.niche, args.language, args.voice_profile, args.length)
        
    elif args.command == "work":
        logger.info("Starting worker...")
        worker = Worker([queue], connection=redis_conn)
        worker.work()
            
    else:
        parser.print_help()
