"""CLIP-based scene/object tagging service.

Uses OpenCLIP to compute image embeddings and match them against predefined
tag labels. This provides zero-shot classification of photos into categories
like scenes, objects, activities, weather, etc.
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, Tag, PhotoTag

logger = logging.getLogger(__name__)

# Lazy-loaded CLIP model
_model = None
_preprocess = None
_tokenizer = None
_device = None

# Predefined tag vocabulary organized by category
TAG_VOCABULARY = {
    "scene": [
        "beach", "mountain", "forest", "city", "street", "park", "garden",
        "lake", "river", "ocean", "desert", "snow", "countryside", "village",
        "skyline", "harbor", "bridge", "church", "temple", "castle",
        "restaurant", "cafe", "bar", "office", "classroom", "library",
        "stadium", "airport", "train station", "market", "mall",
        "kitchen", "bedroom", "living room", "bathroom", "backyard",
        "pool", "gym", "playground", "farm", "vineyard", "rooftop",
    ],
    "object": [
        "car", "bicycle", "motorcycle", "boat", "airplane", "train",
        "dog", "cat", "bird", "horse", "fish", "butterfly",
        "flower", "tree", "plant", "food", "cake", "pizza", "sushi",
        "book", "laptop", "phone", "camera", "guitar", "piano",
        "painting", "sculpture", "fountain", "clock tower", "monument",
        "umbrella", "hat", "sunglasses", "backpack", "tent",
    ],
    "activity": [
        "hiking", "swimming", "skiing", "surfing", "cycling", "running",
        "cooking", "reading", "dancing", "singing", "wedding", "concert",
        "festival", "party", "picnic", "camping", "fishing", "gardening",
        "painting", "photography", "graduation", "birthday",
        "sports", "yoga", "travel", "sightseeing",
    ],
    "weather": [
        "sunny", "cloudy", "rainy", "foggy", "snowy", "stormy",
    ],
    "time": [
        "sunrise", "sunset", "night", "golden hour",
    ],
    "style": [
        "portrait", "selfie", "group photo", "landscape", "macro",
        "aerial view", "panorama", "black and white", "closeup",
    ],
}

# Minimum confidence threshold to assign a tag
CONFIDENCE_THRESHOLD = 0.15

# Maximum tags per photo
MAX_TAGS_PER_PHOTO = 10


def _load_clip_model():
    """Lazy-load the CLIP model."""
    global _model, _preprocess, _tokenizer, _device

    if _model is not None:
        return True

    try:
        import torch
        import open_clip

        _device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading CLIP model on %s...", _device)

        _model, _, _preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
        _model = _model.to(_device)
        _model.eval()

        _tokenizer = open_clip.get_tokenizer("ViT-B-32")

        logger.info("CLIP model loaded successfully")
        return True

    except ImportError:
        logger.warning(
            "open-clip-torch or torch not installed. "
            "Install with: pip install 'recasa[ml]'"
        )
        return False
    except Exception:
        logger.exception("Failed to load CLIP model")
        return False


def _compute_tags(filepath: Path) -> list[tuple[str, str, float]]:
    """Compute tags for an image using CLIP zero-shot classification.

    Returns list of (tag_name, category, confidence) tuples.
    """
    if not _load_clip_model():
        return []

    try:
        import torch
        from PIL import Image

        img = Image.open(filepath).convert("RGB")
        image_input = _preprocess(img).unsqueeze(0).to(_device)

        all_results: list[tuple[str, str, float]] = []

        # Process each category separately for better discrimination
        for category, labels in TAG_VOCABULARY.items():
            prompts = [f"a photo of {label}" for label in labels]
            text_tokens = _tokenizer(prompts).to(_device)

            with torch.no_grad():
                image_features = _model.encode_image(image_input)
                text_features = _model.encode_text(text_tokens)

                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)

                similarity = (image_features @ text_features.T).squeeze(0)
                probs = similarity.softmax(dim=-1).cpu().numpy()

            for i, (label, prob) in enumerate(zip(labels, probs)):
                if prob >= CONFIDENCE_THRESHOLD:
                    all_results.append((label, category, float(prob)))

        # Sort by confidence and take top N
        all_results.sort(key=lambda x: x[2], reverse=True)
        return all_results[:MAX_TAGS_PER_PHOTO]

    except Exception:
        logger.exception("Error computing CLIP tags for %s", filepath)
        return []


async def _ensure_tag(session, name: str, category: str) -> int:
    """Get or create a tag, returning its tag_id."""
    result = await session.execute(
        select(Tag).where(Tag.name == name)
    )
    tag = result.scalar_one_or_none()
    if tag:
        return tag.tag_id

    tag = Tag(name=name, category=category)
    session.add(tag)
    await session.flush()
    return tag.tag_id


async def tag_photo(file_hash: str) -> bool:
    """Compute CLIP tags for a photo and store them."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        if photo.clip_tagged:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        tags = await asyncio.to_thread(_compute_tags, filepath)

        if tags:
            for tag_name, category, confidence in tags:
                tag_id = await _ensure_tag(session, tag_name, category)

                # Check if association already exists
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
                        confidence=confidence,
                    ))

        photo.clip_tagged = True
        await session.commit()

        logger.debug("Tagged %s with %d tags", file_hash, len(tags))
        return True


async def process_pending_tags(batch_size: int | None = None) -> int:
    """Process all photos that haven't been CLIP-tagged yet."""
    if batch_size is None:
        batch_size = settings.batch_size

    if not _load_clip_model():
        logger.info("CLIP model not available, skipping tagging")
        return 0

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash)
            .where(Photo.clip_tagged == False)  # noqa: E712
            .where(Photo.thumbnail_generated == True)  # noqa: E712
            .limit(batch_size)
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await tag_photo(file_hash):
            processed += 1

    if processed:
        logger.info("CLIP-tagged %d photos", processed)
    return processed
