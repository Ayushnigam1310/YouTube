import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from moviepy import AudioFileClip, AudioClip
from PIL import Image
import numpy as np

from youtube_factory.tasks.composer import compose_video

@pytest.fixture
def mock_storage(tmp_path):
    return tmp_path

@pytest.fixture
def dummy_assets(mock_storage):
    # Create 2 image assets
    assets = []
    for i in range(2):
        p = mock_storage / f"asset_{i}.png"
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        img.save(p)
        assets.append(p)
    return assets

@pytest.fixture
def dummy_voice(mock_storage):
    # Create a short silent audio file using moviepy
    # AudioClip takes a make_frame(t) -> numpy array
    def make_frame(t):
        return np.array([0, 0]) # Stereo silence
        
    clip = AudioClip(make_frame, duration=2.0, fps=44100)
    p = mock_storage / "voice.mp3"
    clip.write_audiofile(str(p), logger=None)
    return p

@pytest.fixture
def sample_script():
    return {
        "title": "Test Video",
        "sections": [
            {"heading": "Part 1", "body": "Short text."},
            {"heading": "Part 2", "body": "Another short text."}
        ]
    }

def test_compose_video_success(sample_script, dummy_voice, dummy_assets, mock_storage):
    output_dir = mock_storage / "output"
    output_dir.mkdir()
    
    final_path = compose_video(
        script_obj=sample_script,
        voice_file=dummy_voice,
        assets=dummy_assets,
        output_path=output_dir,
        fps=1 # Low FPS for speed
    )
    
    assert final_path.exists()
    assert final_path.suffix == ".mp4"
    assert final_path.stat().st_size > 0
    
    # Check SRT
    srt_path = final_path.with_suffix(".srt")
    assert srt_path.exists()
    content = srt_path.read_text()
    assert "Short text." in content
    assert "Another short text." in content
    assert "00:00:00,000" in content

def test_compose_video_missing_voice(sample_script, dummy_assets, mock_storage):
    with pytest.raises(FileNotFoundError):
        compose_video(
            script_obj=sample_script,
            voice_file=mock_storage / "non_existent.mp3",
            assets=dummy_assets,
            output_path=mock_storage
        )
