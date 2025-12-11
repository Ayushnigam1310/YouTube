import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from youtube_factory.tasks.tts import tts_from_text, TTSError

@pytest.fixture
def mock_storage(tmp_path):
    return tmp_path

@pytest.fixture
def mock_http_client():
    client = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.content = b"fake_mp3_audio"
    client.post.return_value = response
    return client

def test_tts_elevenlabs_success(mock_storage, mock_http_client):
    with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "fake_key"}):
        output_path = tts_from_text(
            "Hello world",
            llm_client=mock_http_client,
            storage_path=mock_storage
        )
        
        assert output_path.exists()
        assert output_path.stat().st_size > 0
        with open(output_path, "rb") as f:
            assert f.read() == b"fake_mp3_audio"
            
        mock_http_client.post.assert_called_once()
        args, kwargs = mock_http_client.post.call_args
        assert "api.elevenlabs.io" in args[0]

def test_tts_fallback_to_polly(mock_storage, mock_http_client):
    # Simulate ElevenLabs failure or missing key
    # Here we simulate missing ElevenLabs key but present AWS creds
    with patch.dict(os.environ, {
        "AWS_ACCESS_KEY_ID": "fake",
        "AWS_SECRET_ACCESS_KEY": "fake"
    }, clear=True):
        
        # We need to mock boto3 inside the function module
        with patch("youtube_factory.tasks.tts.boto3") as mock_boto:
            mock_polly = MagicMock()
            mock_boto.client.return_value = mock_polly
            
            # Mock synthesize_speech response
            mock_stream = MagicMock()
            mock_stream.read.return_value = b"polly_audio"
            mock_polly.synthesize_speech.return_value = {"AudioStream": mock_stream}
            
            output_path = tts_from_text(
                "Hello Polly",
                llm_client=mock_http_client,
                storage_path=mock_storage
            )
            
            assert output_path.exists()
            with open(output_path, "rb") as f:
                assert f.read() == b"polly_audio"
                
            mock_http_client.post.assert_not_called()
            mock_polly.synthesize_speech.assert_called_once()

def test_tts_missing_creds(mock_storage, mock_http_client):
    # Ensure no keys
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError):
            tts_from_text(
                "Should fail",
                llm_client=mock_http_client,
                storage_path=mock_storage
            )

def test_tts_elevenlabs_retry(mock_storage, mock_http_client):
    with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "fake_key"}):
        # Fail twice then succeed
        bad_response = MagicMock()
        bad_response.status_code = 500
        bad_response.text = "Internal Server Error"
        
        good_response = MagicMock()
        good_response.status_code = 200
        good_response.content = b"audio_after_retry"
        
        mock_http_client.post.side_effect = [bad_response, bad_response, good_response] # Actually side_effect on return value logic
        # Wait, if I set return_value, it returns that. 
        # But _call_elevenlabs raises TTSError if status != 200.
        # My retry is on requests.RequestException or TTSError.
        
        # So I need to make .post return objects that trigger the check.
        mock_http_client.post.side_effect = [bad_response, bad_response, good_response]

        output_path = tts_from_text(
            "Retry me",
            llm_client=mock_http_client,
            storage_path=mock_storage
        )
        
        assert output_path.exists()
        with open(output_path, "rb") as f:
            assert f.read() == b"audio_after_retry"
            
        assert mock_http_client.post.call_count == 3
