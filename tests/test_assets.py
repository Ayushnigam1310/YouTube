import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from youtube_factory.tasks.assets import build_assets

@pytest.fixture
def sample_script():
    return {
        "title": "Test Video",
        "sections": [
            {"heading": "Intro", "body": "Welcome to the video.", "b_roll": "welcome wave"},
            {"heading": "Part 1", "body": "This is the first part.", "b_roll": "nature landscape"}
        ]
    }

@pytest.fixture
def mock_storage(tmp_path):
    return tmp_path

def test_build_assets_fallback_slides(sample_script, mock_storage):
    # No Pexels key provided
    assets = build_assets(sample_script, mock_storage, pexels_api_key=None)
    
    assert len(assets) == 2
    for path in assets:
        assert path.exists()
        assert path.suffix == ".png"
        assert path.name.endswith("_slide.png")
        # Verify it's a valid image
        with Image.open(path) as img:
            assert img.format == "PNG"

@patch("youtube_factory.tasks.assets.requests.get")
def test_build_assets_pexels_success(mock_get, sample_script, mock_storage):
    # Mock search response
    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 200
    mock_search_resp.json.return_value = {
        "videos": [
            {
                "video_files": [
                    {"quality": "hd", "file_type": "video/mp4", "link": "http://fake.url/video.mp4"}
                ]
            }
        ]
    }
    
    # Mock download response
    mock_download_resp = MagicMock()
    mock_download_resp.status_code = 200
    # Ensure context manager returns self
    mock_download_resp.__enter__.return_value = mock_download_resp
    mock_download_resp.__exit__.return_value = None
    # iter_content should return an iterable (list is fine)
    mock_download_resp.iter_content.return_value = [b"fake_video_data"]
    
    # Configure side_effect to return search response then download response(s)
    # We have 2 sections, so 2 searches and 2 downloads expected = 4 calls
    mock_get.side_effect = [
        mock_search_resp, mock_download_resp,
        mock_search_resp, mock_download_resp
    ]
    
    assets = build_assets(sample_script, mock_storage, pexels_api_key="fake_key")
    
    assert len(assets) == 2
    for path in assets:
        assert path.exists()
        assert path.suffix == ".mp4"
        with open(path, "rb") as f:
            content = f.read()
            assert content == b"fake_video_data"

@patch("youtube_factory.tasks.assets.requests.get")
def test_build_assets_pexels_mixed_failure(mock_get, sample_script, mock_storage):
    # First section: Pexels fails (returns no videos)
    mock_empty_search = MagicMock()
    mock_empty_search.status_code = 200
    mock_empty_search.json.return_value = {"videos": []}
    
    # Second section: Pexels succeeds
    mock_success_search = MagicMock()
    mock_success_search.status_code = 200
    mock_success_search.json.return_value = {
        "videos": [
            {
                "video_files": [
                    {"quality": "hd", "file_type": "video/mp4", "link": "http://fake.url/video.mp4"}
                ]
            }
        ]
    }
    
    mock_download_resp = MagicMock()
    mock_download_resp.status_code = 200
    mock_download_resp.__enter__.return_value = mock_download_resp
    mock_download_resp.__exit__.return_value = None
    mock_download_resp.iter_content.return_value = [b"fake_video_data"]
    
    # Sequence: 
    # 1. Search for section 1 -> Empty
    # 2. Search for section 2 -> Found
    # 3. Download for section 2 -> Content
    mock_get.side_effect = [
        mock_empty_search, 
        mock_success_search, mock_download_resp
    ]
    
    assets = build_assets(sample_script, mock_storage, pexels_api_key="fake_key")
    
    assert len(assets) == 2
    
    # First asset should be a slide (fallback)
    assert assets[0].suffix == ".png"
    assert "01_slide" in assets[0].name
    
    # Second asset should be a video
    assert assets[1].suffix == ".mp4"
    assert "02_clip" in assets[1].name
