import pytest
from youtube_factory import __version__
from youtube_factory.api import app
from youtube_factory.models import Job

def test_version():
    assert __version__ is not None

def test_app_import():
    assert app is not None

def test_model_import():
    job = Job(id=1, status="pending")
    assert job.id == 1
    assert job.status == "pending"
