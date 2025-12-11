import math
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import textwrap

# MoviePy 2.x imports
from moviepy import VideoFileClip, ImageClip, AudioFileClip, TextClip, concatenate_videoclips, CompositeVideoClip, CompositeAudioClip
from moviepy.video.fx import Resize, CrossFadeIn

logger = logging.getLogger(__name__)

def _estimate_section_timings(script_obj: Dict, total_audio_duration: float) -> List[float]:
    """
    Estimates the duration of each section based on word count relative to total word count.
    """
    sections = script_obj.get("sections", [])
    if not sections:
        return []
    
    # Calculate word counts
    # A crude approximation: split by space.
    section_word_counts = []
    for sec in sections:
        text = sec.get("body", "") + " " + sec.get("heading", "")
        count = len(text.split())
        if count == 0: count = 1 # Avoid zero division or zero duration issues
        section_word_counts.append(count)
        
    total_words = sum(section_word_counts)
    if total_words == 0:
        return [total_audio_duration / len(sections)] * len(sections)
    
    timings = []
    current_time = 0.0
    for count in section_word_counts:
        duration = (count / total_words) * total_audio_duration
        timings.append(duration)
        
    return timings

def _format_srt_time(seconds: float) -> str:
    """Formats seconds into SRT time format HH:MM:SS,mmm"""
    millis = int((seconds - int(seconds)) * 1000)
    seconds = int(seconds)
    minutes = seconds // 60
    hours = minutes // 60
    minutes %= 60
    seconds %= 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

def _generate_srt(script_obj: Dict, timings: List[float], output_path: Path):
    """Generates an SRT file alongside the video."""
    sections = script_obj.get("sections", [])
    srt_path = output_path.with_suffix(".srt")
    
    with open(srt_path, "w", encoding="utf-8") as f:
        current_time = 0.0
        for i, (section, duration) in enumerate(zip(sections, timings)):
            start_str = _format_srt_time(current_time)
            end_time = current_time + duration
            end_str = _format_srt_time(end_time)
            
            # Text to display: Heading + Body snippet? Or just body?
            # For subtitles, usually we want the spoken text.
            # Since we don't have exact speech-to-text alignment, we'll put the section body.
            # We might want to wrap it.
            text = section.get("body", "")
            # Simple wrapping for SRT
            wrapped_text = "\n".join(textwrap.wrap(text, width=40))
            
            f.write(f"{i+1}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{wrapped_text}\n\n")
            
            current_time = end_time
            
    return srt_path

def compose_video(
    script_obj: dict, 
    voice_file: Path, 
    assets: List[Path], 
    output_path: Path, 
    fps: int = 24
) -> Path:
    """
    Composes the final video from script, voiceover, and assets.
    
    Args:
        script_obj: Script dictionary with sections.
        voice_file: Path to the TTS audio file.
        assets: List of paths to image/video assets (corresponding to sections).
        output_path: Directory or full path to save the output video.
        fps: Frames per second.
        
    Returns:
        Path to the generated MP4 file.
    """
    if not voice_file.exists():
        raise FileNotFoundError(f"Voice file not found: {voice_file}")
    
    # Prepare output filename
    if output_path.is_dir():
        job_id = voice_file.stem
        final_output = output_path / f"final_{{job_id}}.mp4"
    else:
        final_output = output_path
        # Ensure parent dir exists
        final_output.parent.mkdir(parents=True, exist_ok=True)

    # Load Audio
    try:
        audio_clip = AudioFileClip(str(voice_file))
        total_duration = audio_clip.duration
    except Exception as e:
        logger.error(f"Failed to load audio: {e}")
        raise e
        
    # Calculate timings
    timings = _estimate_section_timings(script_obj, total_duration)
    
    if len(assets) != len(timings):
        logger.warning(f"Mismatch between assets count ({len(assets)}) and sections ({len(timings)}). Truncating or reusing.")
        # logic to handle mismatch if needed, for now assume aligned or slice
        pass

    clips = []
    for i, (asset_path, duration) in enumerate(zip(assets, timings)):
        if not asset_path.exists():
            logger.warning(f"Asset missing: {asset_path}, skipping/using placeholder?")
            # Ideally create a black clip or skip
            continue
            
        is_video = asset_path.suffix.lower() in ['.mp4', '.mov', '.avi', '.mkv']
        
        if is_video:
            clip = VideoFileClip(str(asset_path))
            # Loop if too short
            if clip.duration < duration:
                # Loop
                n_loops = math.ceil(duration / clip.duration)
                clip = clip.looped(n_loops)
                clip = clip.with_duration(duration)
            else:
                # Cut
                clip = clip.with_duration(duration)
        else:
            # Image
            clip = ImageClip(str(asset_path))
            clip = clip.with_duration(duration)
            
        # Standardize resolution (1920x1080)
        # Using .resized instead of .resize in v2? The import was: from moviepy.video.fx import Resize
        # Actually in v2 it's typically clip.resized(...) or clip.with_effects([Resize(...)])
        # Let's check typical usage.
        # Assuming v2 API: clip.resized(new_size=(1920, 1080)) or similar.
        # Safest is to use the Resize fx if imported, or the method if available.
        # moviepy 2.x method is usually `clip.resized(...)`
        try:
            # Try method first
            clip = clip.resized(new_size=(1920, 1080)) 
        except AttributeError:
             # Fallback/Older API check (though we installed 2.x)
             pass

        # Add transition (Crossfade in) except for the first one maybe
        if i > 0:
             clip = clip.with_effects([CrossFadeIn(duration=0.5)])
        
        clips.append(clip)
        
    if not clips:
        raise ValueError("No clips could be created.")
        
    final_video = concatenate_videoclips(clips, method="compose")
    final_video = final_video.with_audio(audio_clip)
    
    # Write file
    logger.info(f"Writing video to {final_output}")
    final_video.write_videofile(
        str(final_output), 
        fps=fps, 
        codec="libx264", 
        audio_codec="aac",
        logger=None # Silent output
    )
    
    # Generate SRT
    _generate_srt(script_obj, timings, final_output)
    
    return final_output
