"""Carousel image generator — creates Instagram-style carousel slides."""

import io
import zipfile
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from app.services.storage import upload_file, get_public_url

# Carousel slide dimensions (Instagram 1080x1350)
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350

# Color presets
THEMES = {
    "dark": {"bg": "#1a1a2e", "text": "#eaeaea", "accent": "#e94560"},
    "light": {"bg": "#f5f5f5", "text": "#2d2d2d", "accent": "#3b82f6"},
    "gradient_blue": {"bg": "#0f0c29", "text": "#ffffff", "accent": "#24c6dc"},
    "warm": {"bg": "#2d1b69", "text": "#f8f8f8", "accent": "#ff6b6b"},
    "green": {"bg": "#1b4332", "text": "#f0fff0", "accent": "#95d5b2"},
}


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _wrap_text(text: str, max_chars_per_line: int = 28) -> list[str]:
    """Word-wrap text to fit slide width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars_per_line:
            current = f"{current} {word}".strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_slide(
    title: str,
    body: str,
    slide_number: int = 0,
    total_slides: int = 1,
    theme: str = "dark",
    author: str = "",
) -> Image.Image:
    """Generate a single carousel slide image."""
    colors = THEMES.get(theme, THEMES["dark"])
    bg = _hex_to_rgb(colors["bg"])
    text_color = _hex_to_rgb(colors["text"])
    accent = _hex_to_rgb(colors["accent"])

    img = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    # Use default font (Pillow built-in, works everywhere)
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        body_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # Accent bar at top
    draw.rectangle([(0, 0), (SLIDE_WIDTH, 8)], fill=accent)

    # Slide number indicator
    if total_slides > 1:
        indicator = f"{slide_number}/{total_slides}"
        draw.text((SLIDE_WIDTH - 100, 30), indicator, fill=accent, font=small_font)

    # Title
    y = 120
    title_lines = _wrap_text(title, 24)
    for line in title_lines:
        draw.text((80, y), line, fill=accent, font=title_font)
        y += 65

    # Divider line
    y += 20
    draw.line([(80, y), (SLIDE_WIDTH - 80, y)], fill=accent, width=2)
    y += 40

    # Body text
    body_lines = _wrap_text(body, 32)
    for line in body_lines:
        draw.text((80, y), line, fill=text_color, font=body_font)
        y += 50

    # Author at bottom
    if author:
        draw.text((80, SLIDE_HEIGHT - 80), f"@{author}", fill=accent, font=small_font)

    # Bottom accent bar
    draw.rectangle([(0, SLIDE_HEIGHT - 8), (SLIDE_WIDTH, SLIDE_HEIGHT)], fill=accent)

    return img


def generate_carousel(
    slides_data: list[dict],
    theme: str = "dark",
    author: str = "",
) -> str:
    """Generate a full carousel and upload as ZIP.

    Args:
        slides_data: List of dicts with 'title' and 'body' keys.
        theme: Color theme name (dark, light, gradient_blue, warm, green).
        author: Instagram handle to display.

    Returns:
        Public URL of the uploaded ZIP file.
    """
    total = len(slides_data)
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, slide_data in enumerate(slides_data, 1):
            img = generate_slide(
                title=slide_data.get("title", ""),
                body=slide_data.get("body", ""),
                slide_number=i,
                total_slides=total,
                theme=theme,
                author=author,
            )
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="PNG", quality=95)
            zf.writestr(f"slide_{i:02d}.png", img_buffer.getvalue())

    zip_data = zip_buffer.getvalue()
    key = upload_file(zip_data, f"carousel_{uuid4().hex[:8]}.zip", "application/zip")
    return get_public_url(key)
