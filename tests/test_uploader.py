import os
import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

from youtube_factory.tasks.uploader import upload_video, UploadError, RetriableError

@pytest.fixture
def mock_storage(tmp_path):
    return tmp_path

@pytest.fixture
def mock_paths(mock_storage):
    v = mock_storage / "test_video.mp4"
    v.write_text("fake video content") # Text is fine for size check
    t = mock_storage / "test_thumb.png"
    t.write_text("fake thumb content")
    return v, t

@patch("youtube_factory.tasks.uploader._save_pending_upload")
def test_upload_missing_credentials(mock_save, mock_paths):
    v, t = mock_paths
    mock_save.return_value = 123
    
    # Ensure no creds in env
    with patch.dict(os.environ, {}, clear=True):
        result = upload_video(v, t, "Title", "Desc", ["tag"], credentials=None)
        
    assert result["status"] == "pending_upload"
    assert result["metadata_id"] == 123
    mock_save.assert_called_once()

@patch("youtube_factory.tasks.uploader.requests.post")
@patch("youtube_factory.tasks.uploader.requests.put")
def test_upload_success(mock_put, mock_post, mock_paths):
    v, t = mock_paths
    
    # Mock Token Response
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "fake_token"}
    
    # Mock Init Upload Response
    mock_init_resp = MagicMock()
    mock_init_resp.status_code = 200
    mock_init_resp.headers = {"Location": "http://upload.url"}
    
    # Mock Thumbnail Response
    mock_thumb_resp = MagicMock()
    mock_thumb_resp.status_code = 200
    
    # Side effect for post: Token -> Init -> Thumbnail
    # Note: requests.post called for token (1), init upload (2), thumbnail (3)
    mock_post.side_effect = [mock_token_resp, mock_init_resp, mock_thumb_resp]
    
    # Mock Put (Upload Bytes) Response
    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 200
    mock_put_resp.json.return_value = {"id": "vid_123"}
    mock_put.return_value = mock_put_resp
    
    creds = {
        "YOUTUBE_CLIENT_ID": "cid", 
        "YOUTUBE_CLIENT_SECRET": "csec", 
        "YOUTUBE_REFRESH_TOKEN": "rtok"
    }
    
    result = upload_video(v, t, "Title", "Desc", ["tag"], credentials=creds)
    
    assert result["status"] == "uploaded"
    assert result["videoId"] == "vid_123"
    
    assert mock_post.call_count == 3
    assert mock_put.call_count == 1

@patch("youtube_factory.tasks.uploader.requests.post")
def test_upload_quota_error(mock_post, mock_paths):
    v, t = mock_paths
    
    # Mock Token Response (Success)
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "fake_token"}
    
    # Mock Init Upload Response (403 Quota)
    mock_init_resp = MagicMock()
    mock_init_resp.status_code = 403
    mock_init_resp.text = "Quota Exceeded"
    
    mock_post.side_effect = [mock_token_resp, mock_init_resp]
    
    creds = {
        "YOUTUBE_CLIENT_ID": "cid", 
        "YOUTUBE_CLIENT_SECRET": "csec", 
        "YOUTUBE_REFRESH_TOKEN": "rtok"
    }
    
    with pytest.raises(UploadError) as excinfo:
        upload_video(v, t, "Title", "Desc", ["tag"], credentials=creds)
        
    assert "Failed to initiate upload" in str(excinfo.value)
