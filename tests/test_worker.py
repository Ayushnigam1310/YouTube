import pytest
from unittest.mock import MagicMock, patch
import json
from youtube_factory.worker import run_pipeline, enqueue_job, Job
from youtube_factory.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use in-memory SQLite for tests
@pytest.fixture(scope="module")
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
def mock_tasks(db_session):
    # Create a proxy for the session that ignores close()
    real_session = db_session
    session_proxy = MagicMock(wraps=real_session)
    session_proxy.close = MagicMock() # Do nothing
    # Ensure context manager also works if used (though code uses try/finally)
    session_proxy.__enter__.return_value = session_proxy
    session_proxy.__exit__.return_value = None
    
    with patch("youtube_factory.worker.generate_script") as mock_gen, \
         patch("youtube_factory.worker.tts_from_text") as mock_tts, \
         patch("youtube_factory.worker.build_assets") as mock_assets, \
         patch("youtube_factory.worker.compose_video") as mock_compose, \
         patch("youtube_factory.worker.generate_thumbnail") as mock_thumb, \
         patch("youtube_factory.worker.upload_video") as mock_upload, \
         patch("youtube_factory.worker.redis_conn") as mock_redis, \
         patch("youtube_factory.worker.queue") as mock_queue, \
         patch("youtube_factory.worker.SessionLocal") as mock_session_maker, \
         patch("youtube_factory.worker.openai"): # Mock openai module import/usage
        
        # Setup mocks
        mock_gen.return_value = {
            "title": "Test Video", "hook": "Hook", "sections": [], "cta": "", "tags": []
        }
        mock_tts.return_value = "path/to/voice.mp3"
        mock_assets.return_value = ["path/to/asset.png"]
        mock_compose.return_value = "path/to/final.mp4"
        mock_thumb.return_value = "path/to/thumb.png"
        mock_upload.return_value = {"status": "uploaded", "videoId": "123"}
        
        # Mock SessionLocal to return our proxy
        mock_session_maker.return_value = session_proxy
        
        yield {
            "gen": mock_gen, "tts": mock_tts, "assets": mock_assets, 
            "compose": mock_compose, "thumb": mock_thumb, "upload": mock_upload,
            "session_maker": mock_session_maker, "queue": mock_queue,
            "session_proxy": session_proxy
        }

def test_enqueue_job(mock_tasks, db_session):
    # Configure SessionLocal to return our test db_session
    # Since enqueue_job creates a new session instance, we mock the class/callable
    # mock_tasks["session_maker"].return_value = db_session # Handled in fixture
    
    job_id = enqueue_job("Test Topic", "Test Niche", "en", "alloy", 60)
    
    assert job_id is not None
    # Verify Job in DB
    job = db_session.query(Job).filter_by(id=job_id).first()
    assert job is not None
    assert job.status == "queued"
    assert job.topic_hint == "Test Topic"
    
    # Verify Enqueue called
    mock_tasks["queue"].enqueue.assert_called_once()

def test_run_pipeline_success(mock_tasks, db_session):
    # mock_tasks["session_maker"].return_value = db_session # Handled in fixture
    
    # Create a job first
    job = Job(niche="Test", topic_hint="Run Test", status="queued")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    
    # Run pipeline
    run_pipeline(job.id, "Run Test", "Test", "en", "alloy", 60)
    
    # Verify tasks called
    mock_tasks["gen"].assert_called_once()
    mock_tasks["tts"].assert_called_once()
    mock_tasks["assets"].assert_called_once()
    mock_tasks["compose"].assert_called_once()
    mock_tasks["thumb"].assert_called_once()
    mock_tasks["upload"].assert_called_once()
    
    # Verify DB update
    db_session.refresh(job)
    assert job.status == "completed"
    assert job.metadata_json["upload_result"]["videoId"] == "123"

def test_run_pipeline_failure(mock_tasks, db_session):
    # mock_tasks["session_maker"].return_value = db_session # Handled in fixture
    
    job = Job(niche="Test", topic_hint="Fail Test", status="queued")
    db_session.add(job)
    db_session.commit()
    
    # Make a task fail
    mock_tasks["gen"].side_effect = Exception("Generation Failed")
    
    with pytest.raises(Exception):
        run_pipeline(job.id, "Fail Test", "Test", "en", "alloy", 60)
        
    db_session.refresh(job)
    assert job.status == "failed"
    assert "Generation Failed" in job.metadata_json["error"]
