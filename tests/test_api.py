import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from youtube_factory.api.app import app, get_db
from youtube_factory.models import Base, Job

from sqlalchemy.pool import StaticPool

# Use in-memory SQLite for tests
@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine

@pytest.fixture(scope="module")
def db_session_factory(db_engine):
    return sessionmaker(bind=db_engine)

@pytest.fixture
def db_session(db_session_factory):
    session = db_session_factory()
    yield session
    session.close()

@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass # Don't close here, fixture closes it
            
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)

@pytest.fixture
def mock_queue():
    with patch("youtube_factory.api.app.queue") as mock_q:
        yield mock_q

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_enqueue_job(client, mock_queue):
    payload = {
        "topic": "API Test",
        "niche": "Tech",
        "language": "en",
        "voice_profile": "alloy",
        "length": 300
    }
    response = client.post("/enqueue", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert "job_id" in data
    
    mock_queue.enqueue.assert_called_once()

def test_list_jobs(client, db_session):
    # Create dummy job
    job = Job(niche="Test", topic_hint="List Test", status="completed")
    db_session.add(job)
    db_session.commit()
    
    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Check if our job is in list
    found = any(j["id"] == job.id for j in data)
    assert found

def test_get_job_details(client, db_session):
    job = Job(niche="Test", topic_hint="Detail Test", status="processing")
    db_session.add(job)
    db_session.commit()
    
    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job.id
    assert data["topic_hint"] == "Detail Test"

def test_auth_enforcement(client):
    # Patch environ to simulate set API key
    with patch.dict("os.environ", {"MONITOR_API_KEY": "secret"}):
        # We need to reload/re-instantiate app or logic to pick up env var if it's read at import time.
        # In `youtube_factory/api/app.py`, `MONITOR_API_KEY = os.environ.get(...)` runs at import.
        # So mocking os.environ here won't affect the already imported `MONITOR_API_KEY` global.
        # We need to patch the module-level variable.
        with patch("youtube_factory.api.app.MONITOR_API_KEY", "secret"):
            # Request without header
            response = client.get("/jobs")
            assert response.status_code == 403
            
            # Request with header
            response = client.get("/jobs", headers={"X-API-KEY": "secret"})
            assert response.status_code == 200
