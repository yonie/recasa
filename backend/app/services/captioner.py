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

COMBINED_PROMPT = """Analyze this photo and provide:

1. CAPTION: One or two concise sentences describing the main subject, setting, and notable details. Be specific and descriptive.

2. TAGS: A comma-separated list of specific objects, scenes, activities, locations/landmarks, colors, mood, weather, time of day. Be specific (e.g. 'golden retriever' not 'dog', 'Eiffel Tower' not 'tower').

Format your response exactly like this:
CAPTION: [your caption here]
TAGS: [tag1, tag2, tag3, ...]"""


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

    except Exception as e:
        logger.warning("Skipping caption for %s: %s", filepath, type(e).__name__)
        return None


async def _check_ollama_available() -> bool:
    """Check if Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            return response.status_code == 200
    except Exception:
        return False


async def _generate_caption_and_tags(image_base64: str) -> tuple[str | None, list[str] | None]:
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": COMBINED_PROMPT,
                    "images": [image_base64],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 300,
                    },
                },
            )

            if response.status_code == 200:
                data = response.json()
                raw = _strip_think_blocks(data.get("response", ""))
                if raw:
                    return _parse_combined_response(raw)
            else:
                logger.warning(
                    "Ollama returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )

    except httpx.TimeoutException:
        logger.warning("Ollama request timed out")
    except Exception as e:
        logger.warning("Ollama captioning failed: %s", type(e).__name__)

    return None, None


def _parse_combined_response(raw: str) -> tuple[str | None, list[str] | None]:
    caption = None
    tags = None
    
    import re
    
    caption_match = re.search(r"CAPTION:\s*(.+?)(?=TAGS:|$)", raw, re.DOTALL | re.IGNORECASE)
    if caption_match:
        caption = caption_match.group(1).strip()
    
    tags_match = re.search(r"TAGS:\s*(.+?)$", raw, re.DOTALL | re.IGNORECASE)
    if tags_match:
        tags_raw = tags_match.group(1).strip()
        tag_list = [t.strip().lower() for t in tags_raw.split(",")]
        tag_list = [t for t in tag_list if 2 <= len(t) <= 80]
        seen = set()
        tags = []
        for t in tag_list:
            if t not in seen:
                seen.add(t)
                tags.append(t)
        tags = tags[:15]
    
    return caption, tags


async def _ensure_tag_ids(tag_names: list[str]) -> dict[str, int]:
    """Get or create tags in a dedicated session, returning a name->tag_id mapping.

    Uses a separate session to isolate tag creation from the caller's transaction,
    so that IntegrityError retries don't roll back unrelated pending changes.
    """
    from sqlalchemy.exc import IntegrityError, OperationalError
    from backend.app.models import Tag

    result_map: dict[str, int] = {}

    async with async_session() as tag_session:
        for name in tag_names:
            # Lookup first (read-only, no lock)
            result = await tag_session.execute(
                select(Tag).where(Tag.name == name)
            )
            tag = result.scalar_one_or_none()
            if tag:
                result_map[name] = tag.tag_id
                continue

            # Create with retry for concurrent inserts
            for attempt in range(3):
                try:
                    tag = Tag(name=name)
                    tag_session.add(tag)
                    await tag_session.flush()
                    result_map[name] = tag.tag_id
                    break
                except IntegrityError:
                    await tag_session.rollback()
                    result = await tag_session.execute(
                        select(Tag).where(Tag.name == name)
                    )
                    tag = result.scalar_one_or_none()
                    if tag:
                        result_map[name] = tag.tag_id
                        break
                except OperationalError:
                    await tag_session.rollback()
                    await asyncio.sleep(0.5 * (attempt + 1))
                    result = await tag_session.execute(
                        select(Tag).where(Tag.name == name)
                    )
                    tag = result.scalar_one_or_none()
                    if tag:
                        result_map[name] = tag.tag_id
                        break

        # Commit any newly created tags
        try:
            await tag_session.commit()
        except OperationalError:
            logger.warning("Failed to commit new tags, retrying...")
            await asyncio.sleep(1)
            await tag_session.commit()

    return result_map


async def caption_photo(file_hash: str) -> bool:
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        existing_caption = await session.get(Caption, file_hash)
        if existing_caption:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        image_base64 = await asyncio.to_thread(_prepare_image_base64, filepath)
        if not image_base64:
            return False

        caption_text, tag_list = await _generate_caption_and_tags(image_base64)
        
        if caption_text:
            session.add(Caption(
                file_hash=file_hash,
                caption=caption_text,
                model=settings.ollama_model,
            ))

        if tag_list:
            tag_id_map = await _ensure_tag_ids(tag_list)

            from backend.app.models import PhotoTag
            for tag_name in tag_list:
                tag_id = tag_id_map.get(tag_name)
                if tag_id is None:
                    continue
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

        await session.commit()

        if caption_text:
            logger.debug("Captioned %s: %s", file_hash, caption_text[:80])
        return True
