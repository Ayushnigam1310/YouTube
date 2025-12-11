import os
import logging
import uuid
import textwrap
import requests
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# Try to import openai, handle if missing
try:
    import openai
except ImportError:
    openai = None

logger = logging.getLogger(__name__)

def _get_job_id(script_obj: Dict) -> str:
    title = script_obj.get("title", "untitled")
    slug = "".join(c if c.isalnum() else "_" for c in title)[:20]
    return f"{slug}_{uuid.uuid4().hex[:8]}"

def _download_image(url: str, dest_path: Path):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

def _generate_with_dalle(prompt: str, api_key: str, dest_path: Path):
    if openai is None:
        raise ImportError("openai module required for DALL-E generation")
    
    client = openai.OpenAI(api_key=api_key)
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        url = response.data[0].url
        _download_image(url, dest_path)
    except Exception as e:
        logger.error(f"DALL-E generation failed: {e}")
        raise e

def _get_font(size: int) -> ImageFont.FreeTypeFont:
    # Try common macOS font since we detected it, fallback to default (which won't scale well but prevents crash)
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" # Linux common
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int, start_size: int = 100) -> Tuple[ImageFont.ImageFont, list]:
    """
    Finds a font size and wrapped lines that fit within max_width and max_height.
    """
    size = start_size
    min_size = 20
    
    while size >= min_size:
        font = _get_font(size)
        # Wrap text based on approximate char width? 
        # Pillow doesn't have native multiline wrap based on pixels easily without iteration.
        # We'll try to wrap based on an estimated average char width.
        # Heuristic: Average char width ~ 0.5 * size (very rough)
        # max_chars_per_line ~ max_width / (0.5 * size)
        avg_char_width = size * 0.5
        chars_per_line = max(1, int(max_width / avg_char_width))
        
        wrapper = textwrap.TextWrapper(width=chars_per_line)
        lines = wrapper.wrap(text)
        
        # Calculate actual size
        # ImageDraw.textbbox or textsize (deprecated)
        # We'll use multiline_textbbox if available (Pillow 8+)
        try:
            left, top, right, bottom = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font)
            w = right - left
            h = bottom - top
        except AttributeError:
            # Fallback for older Pillow
            w, h = draw.multiline_textsize("\n".join(lines), font=font)
            
        if w <= max_width and h <= max_height:
            return font, lines
        
        size -= 5
        
    return _get_font(min_size), textwrap.wrap(text, width=20) # Fallback

def _generate_with_pillow(title: str, hook: str, dest_path: Path):
    width, height = 1280, 720
    # High contrast background: Bright Yellow or Red or Deep Blue?
    # Let's go with Deep Blue background, White text, Yellow accent.
    bg_color = (10, 25, 47) 
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # 1. Large Headline (Title or part of it)
    # Extract first 3-5 words or use title
    headline = " ".join(title.split()[:5])
    
    # Define area for headline
    margin = 60
    max_w = width - 2 * margin
    max_h = height * 0.6
    
    font_headline, lines_headline = _fit_text(draw, headline.upper(), max_w, max_h, start_size=150)
    
    # Draw Headline
    text_headline = "\n".join(lines_headline)
    # Center vertically in top portion?
    # Get bbox
    left, top, right, bottom = draw.multiline_textbbox((0, 0), text_headline, font=font_headline)
    h_text = bottom - top
    y_headline = margin + (max_h - h_text) / 2
    
    draw.multiline_text((margin, y_headline), text_headline, font=font_headline, fill=(255, 255, 255), align="left")
    
    # 2. Subtitle (Hook)
    subtitle = hook[:60] + "..." if len(hook) > 60 else hook
    max_h_sub = height * 0.2
    y_sub = margin + max_h + 20
    
    font_sub, lines_sub = _fit_text(draw, subtitle, max_w, max_h_sub, start_size=60)
    draw.multiline_text((margin, y_sub), "\n".join(lines_sub), font=font_sub, fill=(200, 200, 200), align="left")
    
    # 3. Brand Corner Badge
    # A circle or rect in bottom right
    badge_size = 150
    badge_rect = [width - badge_size - margin, height - badge_size - margin, width - margin, height - margin]
    draw.ellipse(badge_rect, fill=(255, 0, 0)) # Red badge
    
    # "NEW" text in badge
    badge_text = "NEW"
    font_badge = _get_font(40)
    lb, tb, rb, bb = draw.textbbox((0,0), badge_text, font=font_badge)
    bw, bh = rb - lb, bb - tb
    bx = badge_rect[0] + (badge_size - bw) / 2
    by = badge_rect[1] + (badge_size - bh) / 2
    draw.text((bx, by - 5), badge_text, font=font_badge, fill=(255, 255, 255))

    img.save(dest_path)

def generate_thumbnail(script_obj: Dict, storage_path: Path, ai_image_api_key: str = None) -> Path:
    """
    Generates a thumbnail for the video.
    
    Args:
        script_obj: Script dictionary containing title and hook.
        storage_path: Directory to save the thumbnail.
        ai_image_api_key: Optional API key for AI generation.
        
    Returns:
        Path to the generated thumbnail file.
    """
    if not storage_path.exists():
        storage_path.mkdir(parents=True, exist_ok=True)
        
    job_id = _get_job_id(script_obj)
    filename = f"thumbnail_{job_id}.png"
    output_path = storage_path / filename
    
    title = script_obj.get("title", "Video Title")
    hook = script_obj.get("hook", "Watch this video!")
    
    generated_by_ai = False
    if ai_image_api_key:
        try:
            logger.info("Generating thumbnail with AI...")
            # Create a prompt
            prompt = f"YouTube thumbnail for video titled '{title}'. Concept: {hook}. High contrast, catchy, 4k resolution."
            _generate_with_dalle(prompt, ai_image_api_key, output_path)
            generated_by_ai = True
        except Exception as e:
            logger.warning(f"AI generation failed, falling back to Pillow: {e}")
            generated_by_ai = False
            
    if not generated_by_ai:
        logger.info("Generating thumbnail with Pillow...")
        _generate_with_pillow(title, hook, output_path)
        
    return output_path
