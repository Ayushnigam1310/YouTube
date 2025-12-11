import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from PIL import Image
import os

from youtube_factory.tasks.thumbnail import generate_thumbnail

@pytest.fixture
def mock_storage(tmp_path):
    return tmp_path

@pytest.fixture
def sample_script():
    return {
        "title": "Amazing YouTube Video",
        "hook": "You won't believe what happens next in this tutorial."
    }

def test_generate_thumbnail_pillow_fallback(sample_script, mock_storage):
    # No API key provided
    output_path = generate_thumbnail(sample_script, mock_storage, ai_image_api_key=None)
    
    assert output_path.exists()
    assert output_path.suffix == ".png"
    
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)
        # Check format
        assert img.format == "PNG"

@patch("youtube_factory.tasks.thumbnail.openai")
@patch("youtube_factory.tasks.thumbnail.requests.get")
def test_generate_thumbnail_ai_success(mock_get, mock_openai, sample_script, mock_storage):
    # Mock OpenAI client and response
    mock_client = MagicMock()
    mock_openai.OpenAI.return_value = mock_client
    
    mock_response = MagicMock()
    mock_image_obj = MagicMock()
    mock_image_obj.url = "http://fake.url/image.png"
    mock_response.data = [mock_image_obj]
    
    mock_client.images.generate.return_value = mock_response
    
    # Mock image download
    mock_download_resp = MagicMock()
    mock_download_resp.status_code = 200
    mock_download_resp.__enter__.return_value = mock_download_resp
    mock_download_resp.__exit__.return_value = None
    mock_download_resp.iter_content.return_value = [b"fake_ai_image_bytes"]
    mock_get.return_value = mock_download_resp
    
    output_path = generate_thumbnail(sample_script, mock_storage, ai_image_api_key="sk-fake-key")
    
    assert output_path.exists()
    with open(output_path, "rb") as f:
        assert f.read() == b"fake_ai_image_bytes"
        
    mock_client.images.generate.assert_called_once()

@patch("youtube_factory.tasks.thumbnail.openai")
def test_generate_thumbnail_ai_failure_fallback(mock_openai, sample_script, mock_storage):
    # Mock OpenAI to raise an exception
    mock_client = MagicMock()
    mock_openai.OpenAI.return_value = mock_client
    mock_client.images.generate.side_effect = Exception("API Error")
    
    output_path = generate_thumbnail(sample_script, mock_storage, ai_image_api_key="sk-fake-key")
    
    # Should fall back to Pillow
    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (1280, 720) # Pillow size
