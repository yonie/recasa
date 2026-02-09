"""Ollama vision model captioning service.

Uses Ollama with a vision-capable model (e.g., LLaVA) to generate
natural language descriptions of photos. Runs as a background task
since it's the slowest step in the pipeline.
"""

import asyncio
import base64
import logging
from pathlib import Path

import httpx

from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, Caption, Tag, PhotoTag

logger = logging.getLogger(__name__)

# Max dimension to resize images before sending to Ollama (saves bandwidth)
MAX_IMAGE_DIMENSION = 1024

CAPTION_PROMPT = (
    "Describe this photo in one or two concise sentences. "
    "Focus on the main subject, setting, and any notable details. "
    "Be specific and descriptive."
)

TAG_PROMPT = (
    "List tags for this photo as a comma-separated list. "
    "Include: specific objects, scenes, activities, locations/landmarks, "
    "colors, mood, weather, time of day, and any other relevant descriptors. "
    "Be specific (e.g. 'golden retriever' not just 'dog', 'Eiffel Tower' not just 'tower'). "
    "Return ONLY the comma-separated tags, nothing else. Example: sunset, beach, ocean, golden hour, waves, silhouette"
)


def _strip_think_blocks(text: str) -> str:
    """Strip <think>...</think> blocks from qwen3-vl responses."""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _prepare_image_base64(filepath: Path) -> str | None:
    """Load and resize an image, returning base64-encoded JPEG."""
    try:
        from PIL import Image

        with Image.open(filepath) as img:
            # Handle EXIF orientation
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Convert to RGB
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Resize if too large
            if max(img.width, img.height) > MAX_IMAGE_DIMENSION:
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

            # Encode as JPEG
            from io import BytesIO
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

    except Exception:
        logger.exception("Error preparing image for captioning: %s", filepath)
        return None


async def _check_ollama_available() -> bool:
    """Check if Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            return response.status_code == 200
    except Exception:
        return False


async def _generate_caption(image_base64: str) -> str | None:
    """Send an image to Ollama and get a caption."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": CAPTION_PROMPT,
                    "images": [image_base64],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 150,
                    },
                },
            )

            if response.status_code == 200:
                data = response.json()
                caption = _strip_think_blocks(data.get("response", ""))
                if caption:
                    return caption
            else:
                logger.warning(
                    "Ollama returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )

    except httpx.TimeoutException:
        logger.warning("Ollama request timed out")
    except Exception:
        logger.exception("Error generating caption via Ollama")

    return None


async def _generate_tags(image_base64: str) -> list[str] | None:
    """Send an image to Ollama and get tags."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": TAG_PROMPT,
                    "images": [image_base64],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 200,
                    },
                },
            )

            if response.status_code == 200:
                data = response.json()
                raw = _strip_think_blocks(data.get("response", ""))
                if raw:
                    # Parse comma-separated tags, normalize
                    tags = [t.strip().lower() for t in raw.split(",")]
                    # Remove empty, too-short, or too-long tags
                    tags = [t for t in tags if 2 <= len(t) <= 80]
                    # Deduplicate preserving order
                    seen = set()
                    unique = []
                    for t in tags:
                        if t not in seen:
                            seen.add(t)
                            unique.append(t)
                    return unique[:15]  # Cap at 15 tags
            else:
                logger.warning(
                    "Ollama tags returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )

    except httpx.TimeoutException:
        logger.warning("Ollama tag request timed out")
    except Exception:
        logger.exception("Error generating tags via Ollama")

    return None


async def _ensure_tag(session, name: str) -> int:
    """Get or create a tag, returning its tag_id."""
    from backend.app.models import Tag
    result = await session.execute(
        select(Tag).where(Tag.name == name)
    )
    tag = result.scalar_one_or_none()
    if tag:
        return tag.tag_id

    tag = Tag(name=name)
    session.add(tag)
    await session.flush()
    return tag.tag_id


async def caption_photo(file_hash: str) -> bool:
    """Generate an AI caption for a photo using Ollama."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        if photo.ollama_captioned:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        # Prepare image
        image_base64 = await asyncio.to_thread(_prepare_image_base64, filepath)
        if not image_base64:
            return False

        # Generate caption
        caption_text = await _generate_caption(image_base64)
        if not caption_text:
            # Mark as attempted but failed (don't retry endlessly)
            photo.ollama_captioned = True
            await session.commit()
            return True

        # Store caption
        existing_caption = await session.get(Caption, file_hash)
        if existing_caption:
            existing_caption.caption = caption_text
            existing_caption.model = settings.ollama_model
        else:
            session.add(Caption(
                file_hash=file_hash,
                caption=caption_text,
                model=settings.ollama_model,
            ))

        # Generate and store tags
        tag_list = await _generate_tags(image_base64)
        if tag_list:
            from backend.app.models import PhotoTag
            for tag_name in tag_list:
                tag_id = await _ensure_tag(session, tag_name)
                # Check if association exists
                existing = await session.execute(
                    select(PhotoTag).where(
                        PhotoTag.file_hash == file_hash,
                        PhotoTag.tag_id == tag_id,
                    )
                )
                if not existing.scalar_one_or_none():
                    session.add(PhotoTag(
                        file_hash=file_hash,
                        tag_id=tag_id,
                    ))
            logger.debug("Tagged %s with %d tags: %s", file_hash, len(tag_list), ", ".join(tag_list[:5]))

        photo.ollama_captioned = True
        await session.commit()

        logger.debug("Captioned %s: %s", file_hash, caption_text[:80])
        return True


async def process_pending_captions(batch_size: int | None = None) -> int:
    """Process all photos that haven't been captioned yet."""
    if batch_size is None:
        batch_size = settings.batch_size

    # Check if Ollama is available first
    if not await _check_ollama_available():
        logger.info("Ollama not available at %s, skipping captioning", settings.ollama_url)
        return 0

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash)
            .where(Photo.ollama_captioned == False)  # noqa: E712
            .where(Photo.thumbnail_generated == True)  # noqa: E712
            .limit(batch_size)
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await caption_photo(file_hash):
            processed += 1

    if processed:
        logger.info("Generated captions for %d photos", processed)
    return processed
