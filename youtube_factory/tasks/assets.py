import os
import logging
import uuid
import textwrap
import requests
from pathlib import Path
from typing import List, Dict, Optional, Any

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

def _get_job_id(script_obj: Dict) -> str:
    """Generate or retrieve a job ID from the script object."""
    # If the script object had an ID field we would use it, otherwise generate one.
    # Using title slug + short UUID to ensure uniqueness.
    title = script_obj.get("title", "untitled")
    slug = "".join(c if c.isalnum() else "_" for c in title)[:20]
    return f"{slug}_{uuid.uuid4().hex[:8]}"

def _download_file(url: str, dest_path: Path):
    """Download a file from a URL to a destination path."""
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

def _search_pexels_video(query: str, api_key: str) -> Optional[str]:
    """Search Pexels for a video and return the download URL of the first match."""
    headers = {"Authorization": api_key}
    url = "https://api.pexels.com/videos/search"
    params = {
        "query": query,
        "per_page": 1,
        "orientation": "landscape", # YouTube standard
        "size": "medium" # reasonable size for preview/MVP
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("videos"):
            # Get the first video file (prefer 720p or similar if possible, here picking the first file)
            # Pexels returns a list of video_files. We want a compatible format like mp4.
            video_files = data["videos"][0].get("video_files", [])
            # Sort by quality/size? For MVP just take the first one or one with 'hd' quality
            for vf in video_files:
                if vf.get("quality") == "hd" and vf.get("file_type") == "video/mp4":
                    return vf.get("link")
            # Fallback to any mp4
            for vf in video_files:
                 if vf.get("file_type") == "video/mp4":
                    return vf.get("link")
            return None
        return None
    except Exception as e:
        logger.warning(f"Pexels API failed for query '{query}': {e}")
        return None

def _create_slide_image(text: str, heading: str, dest_path: Path):
    """Create a simple slide image using Pillow."""
    width, height = 1280, 720
    bg_color = (20, 20, 20)
    text_color = (255, 255, 255)
    
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # Try to load a font, fallback to default
    try:
        # Provide a path to a font if known, or use load_default
        # For better looking slides, a TTF would be needed, but for MVP:
        font_heading = ImageFont.load_default()
        font_body = ImageFont.load_default()
        # Scale logic would be needed for default font which is tiny
        # Pillow's default font is bitmap and doesn't scale well.
        # Ideally we'd look for system fonts.
    except IOError:
        font_heading = ImageFont.load_default()
        font_body = ImageFont.load_default()

    # Layout
    margin = 100
    
    # Draw Heading
    # Since default font is small, this is a placeholder visual.
    # In a real app we'd bundle a .ttf file.
    draw.text((margin, margin), heading.upper(), font=font_heading, fill=(255, 215, 0))
    
    # Wrap and Draw Body
    wrapper = textwrap.TextWrapper(width=60) # Approximated char width
    lines = wrapper.wrap(text)
    
    y_text = margin + 50
    for line in lines:
        draw.text((margin, y_text), line, font=font_body, fill=text_color)
        y_text += 15 # Line height for default font

    img.save(dest_path)

def build_assets(script_obj: dict, storage_path: Path, pexels_api_key: str = None) -> List[Path]:
    """
    Builds or downloads visual assets for the script.
    
    Args:
        script_obj: The script dictionary.
        storage_path: Base path to store assets.
        pexels_api_key: API key for Pexels. If None, falls back to generated slides.
        
    Returns:
        List of Paths to the generated assets.
    """
    job_id = _get_job_id(script_obj)
    asset_dir = storage_path / "assets" / job_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    
    assets = []
    
    sections = script_obj.get("sections", [])
    if not sections:
        logger.warning("No sections found in script object.")
        return []

    for i, section in enumerate(sections):
        index_prefix = f"{i+1:02d}"
        heading = section.get("heading", "")
        body = section.get("body", "")
        b_roll_query = section.get("b_roll", heading) # Use heading if b_roll empty
        
        # Determine strategy
        asset_path = None
        
        if pexels_api_key:
            logger.info(f"Searching Pexels for: {b_roll_query}")
            video_url = _search_pexels_video(b_roll_query, pexels_api_key)
            if video_url:
                filename = f"{index_prefix}_clip.mp4"
                target_path = asset_dir / filename
                try:
                    _download_file(video_url, target_path)
                    asset_path = target_path
                except Exception as e:
                    logger.error(f"Failed to download video: {e}")
                    # Fallback to slide if download fails
        
        # Fallback Strategy: Generate Slide
        if not asset_path:
            filename = f"{index_prefix}_slide.png"
            target_path = asset_dir / filename
            logger.info(f"Generating slide for section {i+1}")
            _create_slide_image(body, heading, target_path)
            asset_path = target_path
            
        assets.append(asset_path)
        
    return assets
