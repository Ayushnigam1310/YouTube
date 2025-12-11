import os
import time
import logging
import uuid
from pathlib import Path
from typing import Optional, Any, Union
import re
from datetime import datetime

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Try to import optional dependencies
try:
    import boto3
except ImportError:
    boto3 = None

try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None

logger = logging.getLogger(__name__)

def _slugify(text: str) -> str:
    """Simple slugify implementation."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')

class TTSError(Exception):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, TTSError)),
    reraise=True
)
def _call_elevenlabs(text: str, voice_id: str, api_key: str, http_client: Any) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    if hasattr(http_client, "post"):
        response = http_client.post(url, json=data, headers=headers)
    else:
        # Fallback if http_client is not requests-like
        response = requests.post(url, json=data, headers=headers)
        
    if response.status_code != 200:
        raise TTSError(f"ElevenLabs API error: {response.status_code} {response.text}")
    
    return response.content

def _call_polly(text: str, voice_id: str) -> bytes:
    if boto3 is None:
        raise ImportError("boto3 is required for Amazon Polly fallback")
    
    client = boto3.client("polly")
    try:
        response = client.synthesize_speech(
            Text=text,
            OutputFormat="mp3",
            VoiceId=voice_id
        )
    except Exception as e:
        raise TTSError(f"Polly API error: {e}")
    
    if "AudioStream" in response:
        return response["AudioStream"].read()
    raise TTSError("Polly did not return audio stream")

def tts_from_text(
    text: str, 
    voice_profile: str = "alloy", 
    llm_client: Any = None, 
    storage_path: Path = Path("/tmp")
) -> Path:
    """
    Converts text to speech using ElevenLabs (default) or Amazon Polly (fallback).
    
    Args:
        text: The text to convert.
        voice_profile: Voice ID or name. Defaults to "alloy" (OpenAI name) but used as ID here.
        llm_client: Dependency injection for HTTP client (requests-like).
        storage_path: Directory to save the MP3 file.
        
    Returns:
        Path to the generated MP3 file.
    """
    eleven_key = os.environ.get("ELEVENLABS_API_KEY")
    polly_creds_present = (
        os.environ.get("AWS_ACCESS_KEY_ID") and 
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    
    if not storage_path.exists():
        storage_path.mkdir(parents=True, exist_ok=True)

    slug = _slugify(text[:30])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{timestamp}.mp3"
    output_path = storage_path / filename

    # Chunking logic for long text
    chunks = []
    if len(text) > 5000:
        # Simple split by length, ideally split by sentences
        for i in range(0, len(text), 5000):
            chunks.append(text[i:i+5000])
    else:
        chunks.append(text)

    audio_segments = []

    for i, chunk in enumerate(chunks):
        audio_data = None
        
        # 1. Try ElevenLabs
        if eleven_key:
            try:
                # Map "alloy" to a default ElevenLabs voice if needed, or use as is
                # For now we use voice_profile as the ID. 
                # If "alloy" is passed, it might fail on ElevenLabs if not mapped.
                # We'll assume the user passes a valid ID or we use a fallback ID for "alloy"
                effective_voice = "21m00Tcm4TlvDq8ikWAM" if voice_profile == "alloy" else voice_profile # Rachel default
                audio_data = _call_elevenlabs(chunk, effective_voice, eleven_key, llm_client)
            except Exception as e:
                logger.warning(f"ElevenLabs failed: {e}. Trying fallback.")
                
        # 2. Fallback to Polly
        if audio_data is None and polly_creds_present:
            try:
                # Map "alloy" to a default Polly voice
                effective_voice = "Joanna" if voice_profile == "alloy" else voice_profile
                audio_data = _call_polly(chunk, effective_voice)
            except Exception as e:
                logger.warning(f"Polly failed: {e}")

        if audio_data is None:
             raise EnvironmentError("TTS generation failed. Check credentials for ElevenLabs or AWS Polly.")

        # Save chunk to temp file to load with pydub (or append bytes directly if supported)
        chunk_path = storage_path / f"chunk_{uuid.uuid4()}.mp3"
        with open(chunk_path, "wb") as f:
            f.write(audio_data)
        
        if AudioSegment:
            segment = AudioSegment.from_mp3(str(chunk_path))
            audio_segments.append(segment)
            # cleanup chunk
            chunk_path.unlink()
        else:
            # If pydub missing, we can only support 1 chunk or simple concatenation if formats allow
            # MP3s can often be concatenated by bytes.
            audio_segments.append(audio_data) # Store bytes
            chunk_path.unlink()

    # Combine and save
    if AudioSegment and isinstance(audio_segments[0], AudioSegment):
        final_audio = audio_segments[0]
        for seg in audio_segments[1:]:
            final_audio += seg
        final_audio.export(str(output_path), format="mp3")
    else:
        # Byte concatenation fallback (works for some MP3s, risky)
        with open(output_path, "wb") as f:
            for seg in audio_segments:
                f.write(seg)
                
    return output_path
