"""Face detection and recognition service.

Uses the insightface library (ONNX Runtime) to:
1. Detect faces in photos
2. Compute 512-dimensional face encodings
3. Cluster faces into persons using DBSCAN
4. Generate face thumbnail crops
"""

import asyncio
import logging
import pickle
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from sqlalchemy import select, func

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Photo, Face, Person

logger = logging.getLogger(__name__)

# Lazy-loaded insightface FaceAnalysis app
_face_app = None

# Face thumbnail size
FACE_THUMB_SIZE = 150

# DBSCAN clustering parameters
# Using cosine distance since insightface produces normalized embeddings
CLUSTER_DISTANCE_THRESHOLD = 0.4  # Cosine distance; lower = stricter matching
CLUSTER_MIN_SAMPLES = 2  # Minimum faces to form a person cluster


def _load_insightface():
    """Lazy-load the insightface FaceAnalysis app."""
    global _face_app
    if _face_app is not None:
        return _face_app is not False

    try:
        from insightface.app import FaceAnalysis

        app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _face_app = app
        logger.info("insightface FaceAnalysis loaded successfully (buffalo_l)")
        return True
    except ImportError as e:
        logger.error(
            "insightface not installed -- face detection will be DISABLED. "
            "Install with: pip install 'recasa[ml]'. Error: %s", e
        )
        _face_app = False
        return False
    except Exception as e:
        logger.exception("Failed to load insightface model: %s", e)
        _face_app = False
        return False


def _detect_faces(filepath: Path) -> list[dict]:
    """Detect faces in an image and compute encodings.

    Returns list of dicts with keys: bbox, encoding.
    bbox is (x, y, w, h), encoding is 512-dim numpy array.
    """
    if not _load_insightface():
        return []

    if _face_app is False:
        return []

    try:
        # Load image as BGR numpy array (insightface expects BGR from OpenCV)
        import cv2
        img = cv2.imread(str(filepath))
        if img is None:
            logger.error("Could not read image: %s", filepath)
            return []

        # Detect faces and compute embeddings in one call
        faces = _face_app.get(img)
        if not faces:
            return []

        results = []
        for face in faces:
            # face.bbox is [x1, y1, x2, y2] as float
            x1, y1, x2, y2 = face.bbox.astype(int)
            x, y, w, h = x1, y1, x2 - x1, y2 - y1

            # face.normed_embedding is a 512-dim normalized vector
            embedding = face.normed_embedding

            results.append({
                "bbox": (x, y, w, h),
                "encoding": embedding,
            })

        return results

    except Exception as e:
        logger.error("Error detecting faces in %s: %s", filepath, e)
        return []


def _generate_face_thumbnail(filepath: Path, bbox: tuple, file_hash: str, face_idx: int) -> str | None:
    """Generate a thumbnail crop of a face. Returns the relative path to the thumbnail."""
    try:
        x, y, w, h = bbox

        # Add padding around the face (30% on each side)
        pad_x = int(w * 0.3)
        pad_y = int(h * 0.3)

        with Image.open(filepath) as img:
            # Handle EXIF orientation
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Crop with padding (clamp to image bounds)
            left = max(0, x - pad_x)
            top = max(0, y - pad_y)
            right = min(img.width, x + w + pad_x)
            bottom = min(img.height, y + h + pad_y)

            face_crop = img.crop((left, top, right, bottom))
            face_crop = face_crop.convert("RGB")
            face_crop.thumbnail((FACE_THUMB_SIZE, FACE_THUMB_SIZE), Image.Resampling.LANCZOS)

            # Save to faces directory
            faces_dir = settings.data_dir / "faces" / file_hash[:2]
            faces_dir.mkdir(parents=True, exist_ok=True)

            thumb_filename = f"{file_hash}_face{face_idx}.webp"
            thumb_path = faces_dir / thumb_filename
            face_crop.save(thumb_path, "WEBP", quality=85)

            return str(thumb_path.relative_to(settings.data_dir))

    except Exception:
        logger.exception("Error generating face thumbnail for %s face %d", file_hash, face_idx)
        return None


async def detect_faces(file_hash: str) -> bool:
    """Detect faces in a photo and store them in the database."""
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        if photo.faces_detected:
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        faces = await asyncio.to_thread(_detect_faces, filepath)

        for i, face_data in enumerate(faces):
            x, y, w, h = face_data["bbox"]
            encoding = face_data["encoding"]

            # Generate face thumbnail
            thumb_path = await asyncio.to_thread(
                _generate_face_thumbnail, filepath, face_data["bbox"], file_hash, i
            )

            face = Face(
                file_hash=file_hash,
                bbox_x=x,
                bbox_y=y,
                bbox_w=w,
                bbox_h=h,
                encoding=pickle.dumps(encoding),
                face_thumbnail=thumb_path,
            )
            session.add(face)

        photo.faces_detected = True
        await session.commit()

        if faces:
            logger.debug("Detected %d faces in %s", len(faces), file_hash)
        return True


async def cluster_faces() -> int:
    """Cluster all unassigned faces into persons using DBSCAN.

    Returns the number of new person clusters created.
    """
    async with async_session() as session:
        # Get all faces with encodings that aren't yet assigned to a person
        result = await session.execute(
            select(Face).where(Face.encoding.is_not(None))
        )
        all_faces = result.scalars().all()

    if len(all_faces) < CLUSTER_MIN_SAMPLES:
        return 0

    # Deserialize encodings
    face_ids = []
    encodings = []
    for face in all_faces:
        try:
            encoding = pickle.loads(face.encoding)
            face_ids.append(face.face_id)
            encodings.append(encoding)
        except Exception:
            continue

    if len(encodings) < CLUSTER_MIN_SAMPLES:
        return 0

    # DBSCAN clustering with cosine distance (insightface produces normalized embeddings)
    try:
        from sklearn.cluster import DBSCAN

        encodings_array = np.array(encodings)
        clustering = DBSCAN(
            eps=CLUSTER_DISTANCE_THRESHOLD,
            min_samples=CLUSTER_MIN_SAMPLES,
            metric="cosine",
        ).fit(encodings_array)

        labels = clustering.labels_
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

    except ImportError:
        logger.warning("scikit-learn not installed, cannot cluster faces")
        return 0
    except Exception:
        logger.exception("Error clustering faces")
        return 0

    # Build cluster -> face_ids mapping
    cluster_map: dict[int, list[int]] = {}
    for face_id, label in zip(face_ids, labels):
        if label == -1:
            continue  # Noise point - not assigned to any cluster
        if label not in cluster_map:
            cluster_map[label] = []
        cluster_map[label].append(face_id)

    # Store clusters as persons
    new_persons = 0
    async with async_session() as session:
        for cluster_label, cluster_face_ids in cluster_map.items():
            # Count unique photos in this cluster
            face_result = await session.execute(
                select(Face).where(Face.face_id.in_(cluster_face_ids))
            )
            cluster_faces = face_result.scalars().all()
            unique_photos = set(f.file_hash for f in cluster_faces)

            # Check if these faces already belong to a person
            existing_person_ids = set(
                f.person_id for f in cluster_faces if f.person_id is not None
            )

            if existing_person_ids:
                # Use the most common existing person
                person_id = max(
                    existing_person_ids,
                    key=lambda pid: sum(1 for f in cluster_faces if f.person_id == pid)
                )
                person = await session.get(Person, person_id)
            else:
                # Create a new person
                person = Person(
                    photo_count=len(unique_photos),
                    representative_face_id=cluster_face_ids[0],
                )
                session.add(person)
                await session.flush()
                new_persons += 1

            # Assign all faces in this cluster to the person
            for face in cluster_faces:
                face.person_id = person.person_id

            # Update person photo count
            if person:
                person.photo_count = len(unique_photos)
                if not person.representative_face_id and cluster_face_ids:
                    person.representative_face_id = cluster_face_ids[0]

        await session.commit()

    logger.info("Face clustering: %d clusters, %d new persons", n_clusters, new_persons)
    return new_persons


async def process_pending_faces(batch_size: int | None = None) -> int:
    """Process all photos that haven't had face detection run yet."""
    if batch_size is None:
        batch_size = settings.batch_size

    if not _load_insightface():
        logger.info("insightface not available, skipping face detection")
        return 0

    async with async_session() as session:
        result = await session.execute(
            select(Photo.file_hash)
            .where(Photo.faces_detected == False)  # noqa: E712
            .where(Photo.thumbnail_generated == True)  # noqa: E712
            .limit(batch_size)
        )
        hashes = result.scalars().all()

    processed = 0
    for file_hash in hashes:
        if await detect_faces(file_hash):
            processed += 1

    if processed:
        logger.info("Detected faces in %d photos", processed)
    return processed
