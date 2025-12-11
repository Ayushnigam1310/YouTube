import os
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from youtube_factory.models import Base, PendingUpload

logger = logging.getLogger(__name__)

# Constants
TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"

class UploadError(Exception):
    pass

class RetriableError(UploadError):
    pass

def _get_db_session():
    """Creates a DB session. Defaults to sqlite if DATABASE_URL not set."""
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./youtube_factory.db")
    engine = create_engine(db_url)
    # Ensure tables exist (safe to call multiple times)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def _save_pending_upload(video_path: Path, thumbnail_path: Path, title: str, desc: str, tags: List[str]) -> int:
    """Persists upload metadata to DB."""
    session = _get_db_session()
    try:
        pending = PendingUpload(
            video_path=str(video_path),
            thumbnail_path=str(thumbnail_path),
            title=title,
            description=desc,
            tags=json.dumps(tags) if tags else None
        )
        session.add(pending)
        session.commit()
        session.refresh(pending)
        return pending.id
    finally:
        session.close()

def _get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchanges refresh token for access token."""
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    resp = requests.post(TOKEN_URI, data=payload)
    if resp.status_code != 200:
        raise UploadError(f"Failed to refresh token: {resp.text}")
    return resp.json()["access_token"]

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type(RetriableError),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def _upload_file_resumable(video_path: Path, metadata: Dict, access_token: str) -> str:
    """Uploads video using resumable protocol. Returns video ID."""
    file_size = video_path.stat().st_size
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Upload-Content-Length": str(file_size),
        "X-Upload-Content-Type": "video/mp4" # Assumption
    }
    
    # 1. Start Session
    params = {"uploadType": "resumable", "part": "snippet,status"}
    init_resp = requests.post(UPLOAD_URL, headers=headers, params=params, json=metadata)
    
    if init_resp.status_code >= 500:
        raise RetriableError(f"Server error initiating upload: {init_resp.status_code}")
    if init_resp.status_code != 200:
        raise UploadError(f"Failed to initiate upload: {init_resp.text}")
    
    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        raise UploadError("No upload URL returned in Location header")

    # 2. Upload Bytes
    # For simplicity, uploading in one go. For very large files, chunking is better.
    with open(video_path, "rb") as f:
        put_headers = {"Content-Type": "video/mp4"}
        put_resp = requests.put(upload_url, headers=put_headers, data=f)
    
    if put_resp.status_code >= 500:
         raise RetriableError(f"Server error uploading bytes: {put_resp.status_code}")
    if put_resp.status_code not in (200, 201):
        raise UploadError(f"Failed to upload video bytes: {put_resp.text}")
        
    return put_resp.json().get("id")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(RetriableError)
)
def _set_thumbnail(video_id: str, thumbnail_path: Path, access_token: str):
    """Sets the thumbnail for a video."""
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    params = {"videoId": video_id}
    
    with open(thumbnail_path, "rb") as f:
        # requests will handle multipart/form-data or raw bytes if files passed?
        # API expects binary content in body with correct content-type
        # Actually `videos.insert` supports media upload, `thumbnails.set` also does.
        # "The request body contains the image binary data."
        headers["Content-Type"] = "image/png" # Assuming png from previous task
        resp = requests.post(THUMBNAIL_URL, headers=headers, params=params, data=f)
        
    if resp.status_code >= 500:
        raise RetriableError(f"Server error setting thumbnail: {resp.status_code}")
    if resp.status_code != 200:
        logger.warning(f"Failed to set thumbnail: {resp.text}")
        # Don't fail the whole job if thumbnail fails, just log? 
        # Or raise? Prompt says "Upload thumbnail". I'll raise to be safe or maybe just log.
        # Let's assume strict success.
        raise UploadError(f"Failed to set thumbnail: {resp.text}")

def upload_video(
    video_path: Path, 
    thumbnail_path: Path, 
    title: str, 
    desc: str, 
    tags: List[str], 
    publish: bool = False, 
    credentials: dict = None
) -> dict:
    """
    Uploads a video to YouTube.
    
    Args:
        video_path: Path to the video file.
        thumbnail_path: Path to the thumbnail file.
        title: Video title.
        desc: Video description.
        tags: List of tags.
        publish: Whether to make the video public immediately (overridden by AUTO_PUBLISH env).
        credentials: Dict with client_id, client_secret, refresh_token.
        
    Returns:
        Dict with status and videoId or metadata_id.
    """
    # Resolve credentials
    creds = credentials or {}
    client_id = creds.get("YOUTUBE_CLIENT_ID") or os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = creds.get("YOUTUBE_CLIENT_SECRET") or os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = creds.get("YOUTUBE_REFRESH_TOKEN") or os.environ.get("YOUTUBE_REFRESH_TOKEN")
    
    if not (client_id and client_secret and refresh_token):
        logger.info("Missing YouTube credentials, saving to pending uploads.")
        meta_id = _save_pending_upload(video_path, thumbnail_path, title, desc, tags)
        return {"status": "pending_upload", "metadata_id": meta_id}
        
    # Check auto publish env
    auto_publish = os.environ.get("AUTO_PUBLISH", "False").lower() == "true"
    # If explicit publish=True passed, it might override default False, but let's respect env as "master switch" or default?
    # Prompt: "Respect AUTO_PUBLISH env var: default False."
    # Typically this means if env is set, use it. Or if env says False, never publish? 
    # Usually "Respect env" means env provides the default. 
    # If param `publish` is explicitly passed (e.g. from a CLI flag), it should probably take precedence?
    # But prompt says "default False" referring to the env var logic.
    # Let's interpret: Effective privacy status depends on `publish` arg, defaulting to `AUTO_PUBLISH` if not specified? 
    # But `publish` default in signature is `False`.
    # Let's assume if `AUTO_PUBLISH` is true, we publish. If `publish` arg is true, we publish.
    should_publish = publish or auto_publish
    privacy_status = "public" if should_publish else "private"
    
    try:
        # Get Token
        access_token = _get_access_token(client_id, client_secret, refresh_token)
        
        # Prepare Metadata
        metadata = {
            "snippet": {
                "title": title,
                "description": desc,
                "tags": tags,
                "categoryId": "22" # People & Blogs default
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False
            }
        }
        
        # Upload Video
        logger.info(f"Starting upload for {title}...")
        video_id = _upload_file_resumable(video_path, metadata, access_token)
        logger.info(f"Video uploaded: {video_id}")
        
        # Upload Thumbnail
        if thumbnail_path.exists():
            logger.info("Uploading thumbnail...")
            _set_thumbnail(video_id, thumbnail_path, access_token)
            
        return {"status": "uploaded", "videoId": video_id}
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        # Fallback to DB?
        # "If credentials missing or uploading disabled... persist".
        # It doesn't strictly say "if upload fails, persist". 
        # But it's good practice. However, adhering strictly to "If credentials missing or uploading disabled".
        # I'll re-raise exception if it's an API error, as user might want to know it failed rather than silently pending.
        raise e
