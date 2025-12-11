import pytest
from unittest.mock import MagicMock, patch
import os
from pathlib import Path
from youtube_factory.worker import run_pipeline
from youtube_factory.models import Job, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine

@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def mock_storage(tmp_path):
    # Patch the storage path to a temp dir
    with patch("youtube_factory.worker.Path") as mock_path_cls:
        # We need to handle Path usage. The worker uses Path(env var).
        # Easier to patch os.environ
        with patch.dict(os.environ, {"STORAGE_PATH": str(tmp_path)}):
            yield tmp_path

def test_local_smoke_pipeline(db_session, mock_storage):
    # This test runs the pipeline function directly to ensure end-to-end logic works.
    # We mock external APIs.
    
    with patch("youtube_factory.worker.SessionLocal") as mock_session_maker:
        # Proxy session
        real_session = db_session
        session_proxy = MagicMock(wraps=real_session)
        session_proxy.close = MagicMock()
        session_proxy.__enter__.return_value = session_proxy
        session_proxy.__exit__.return_value = None
        mock_session_maker.return_value = session_proxy
        
        with patch("youtube_factory.worker.generate_script") as mock_gen, \
             patch("youtube_factory.worker.tts_from_text") as mock_tts, \
             patch("youtube_factory.worker.build_assets") as mock_assets, \
             patch("youtube_factory.worker.compose_video") as mock_compose, \
             patch("youtube_factory.worker.generate_thumbnail") as mock_thumb, \
             patch("youtube_factory.worker.upload_video") as mock_upload, \
             patch("youtube_factory.worker.openai"): # Handle import

            # Setup successful returns
            mock_gen.return_value = {
                "title": "Smoke Test", "hook": "Hook", "sections": [], "cta": "", "tags": []
            }
            # Mock paths relative to storage
            mock_tts.return_value = Path(mock_storage) / "voice.mp3"
            mock_assets.return_value = [Path(mock_storage) / "asset.png"]
            mock_compose.return_value = Path(mock_storage) / "final.mp4"
            mock_thumb.return_value = Path(mock_storage) / "thumb.png"
            mock_upload.return_value = {"status": "uploaded", "videoId": "smoke_vid"}
            
            # Create Job
            job = Job(niche="Smoke", topic_hint="Smoke Run", status="queued")
            db_session.add(job)
            db_session.commit()
            db_session.refresh(job)
            
            # Run
            run_pipeline(job.id, "Smoke Run", "Smoke", "en", "alloy", 60)
            
            # Verify
            db_session.refresh(job)
            assert job.status == "completed"
            assert job.metadata_json["upload_result"]["videoId"] == "smoke_vid"