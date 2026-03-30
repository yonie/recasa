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

# Face detection confidence threshold - filter low-confidence detections
FACE_DET_THRESHOLD = 0.6

# Minimum face bounding box size (pixels on shorter edge)
FACE_MIN_SIZE = 40

# Maximum roll angle (degrees) — faces tilted beyond this are filtered
FACE_MAX_ROLL = 45.0

# DBSCAN clustering parameters
# Using cosine distance since insightface produces normalized embeddings
CLUSTER_DISTANCE_THRESHOLD = 0.5  # Cosine distance; lower = stricter matching
CLUSTER_MIN_SAMPLES = 1  # Allow single-appearance faces to form their own cluster


def _compute_roll_from_kps(kps: np.ndarray) -> float | None:
    """Compute face roll angle (degrees) from 5-point keypoints.

    kps layout: [right_eye, left_eye, nose, right_mouth, left_mouth].
    Returns absolute roll in degrees (0 = upright), or None if kps unavailable.
    """
    if kps is None or len(kps) < 2:
        return None
    right_eye, left_eye = kps[0], kps[1]
    dx = float(left_eye[0] - right_eye[0])
    dy = float(left_eye[1] - right_eye[1])
    return abs(np.degrees(np.arctan2(dy, dx)))


def _load_insightface():
    """Lazy-load the insightface FaceAnalysis app."""
    global _face_app
    if _face_app is not None:
        return _face_app is not False

    try:
        from insightface.app import FaceAnalysis

        models_dir = str(settings.data_dir / "models")
        app = FaceAnalysis(
            name="buffalo_l",
            root=models_dir,
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
        # Load image - handle HEIC/HEIF files specially
        import cv2
        
        # Check if HEIC/HEIF - OpenCV doesn't support these
        ext = filepath.suffix.lower()
        if ext in ('.heic', '.heif'):
            try:
                from pillow_heif import register_heif_opener
                from PIL import Image
                register_heif_opener()
                
                with Image.open(filepath) as pil_img:
                    pil_img = pil_img.convert('RGB')
                    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            except ImportError:
                logger.debug("pillow-heif not installed, skipping HEIC: %s", filepath)
                return []
            except Exception as e:
                logger.debug("Could not read HEIC %s: %s", filepath, type(e).__name__)
                return []
        else:
            img = cv2.imread(str(filepath))
            
        if img is None:
            logger.error("Could not read image: %s", filepath)
            return []

        # Detect faces and compute embeddings in one call
        faces = _face_app.get(img)
        if not faces:
            return []

        results = []
        filtered_low_conf = 0
        filtered_small = 0
        filtered_roll = 0
        for face in faces:
            det_score = float(face.det_score) if hasattr(face, 'det_score') else 1.0
            if det_score < FACE_DET_THRESHOLD:
                filtered_low_conf += 1
                continue

            x1, y1, x2, y2 = face.bbox.astype(int)
            x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)

            if min(w, h) < FACE_MIN_SIZE:
                filtered_small += 1
                continue

            roll = _compute_roll_from_kps(getattr(face, 'kps', None))
            if roll is not None and roll > FACE_MAX_ROLL:
                filtered_roll += 1
                continue

            embedding = face.normed_embedding

            results.append({
                "bbox": (x, y, w, h),
                "encoding": embedding,
                "confidence": det_score,
            })

        filtered_total = filtered_low_conf + filtered_small + filtered_roll
        if filtered_total > 0:
            logger.debug(
                "Filtered face detections: %d low-confidence, %d too-small, %d excessive-roll",
                filtered_low_conf, filtered_small, filtered_roll,
            )

        return results

    except Exception as e:
        logger.warning("Skipping face detection for %s: %s", filepath, type(e).__name__)
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

    except Exception as e:
        logger.warning("Face thumbnail failed for %s face %d: %s", file_hash, face_idx, type(e).__name__)
        return None


async def detect_faces(file_hash: str) -> bool:
    """Detect faces in a photo and store them in the database.
    
    Even when no faces are found, we store a marker record to prevent
    re-processing on restart. The marker has encoding=NULL to indicate
    "checked but no faces".
    """
    async with async_session() as session:
        photo = await session.get(Photo, file_hash)
        if not photo:
            return False

        # Check if faces already processed (including marker record for no faces)
        result = await session.execute(
            select(Face).where(Face.file_hash == file_hash).limit(1)
        )
        if result.scalar_one_or_none():
            return True

        filepath = settings.photos_dir / photo.file_path
        if not filepath.exists():
            return False

        faces = await asyncio.to_thread(_detect_faces, filepath)

        if faces:
            for i, face_data in enumerate(faces):
                x, y, w, h = face_data["bbox"]
                encoding = face_data["encoding"]
                confidence = face_data.get("confidence")

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
                    confidence=confidence,
                )
                session.add(face)

            logger.info("Detected %d face(s) in %s", len(faces), file_hash)
        else:
            # Store a marker record to indicate "processed, no faces found"
            # This prevents re-processing on restart
            marker = Face(
                file_hash=file_hash,
                bbox_x=0,
                bbox_y=0,
                bbox_w=0,
                bbox_h=0,
                encoding=None,  # NULL encoding = no faces, just checked
            )
            session.add(marker)
            logger.debug("No faces detected in %s (marked as processed)", file_hash)

        await session.commit()
        return True


async def cluster_faces() -> int:
    """Cluster all unassigned faces into persons using DBSCAN.

    Includes already-assigned faces in the clustering so that new faces
    are matched against existing persons rather than always creating new ones.

    Returns the number of new person clusters created.
    """
    async with async_session() as session:
        # Check if there are any unassigned faces to process
        unassigned_result = await session.execute(
            select(func.count(Face.face_id)).where(
                Face.encoding.is_not(None),
                Face.person_id.is_(None),
            )
        )
        unassigned_count = unassigned_result.scalar() or 0

    if unassigned_count == 0:
        return 0

    async with async_session() as session:
        # Load ALL faces with encodings (assigned + unassigned) so DBSCAN
        # can group new faces with existing persons
        result = await session.execute(
            select(Face).where(Face.encoding.is_not(None))
        )
        all_faces = result.scalars().all()

    if len(all_faces) < CLUSTER_MIN_SAMPLES:
        return 0

    # Deserialize encodings, tracking which faces are already assigned
    face_ids = []
    encodings = []
    existing_person_map: dict[int, int | None] = {}  # face_id -> person_id
    for face in all_faces:
        try:
            encoding = pickle.loads(face.encoding)
            face_ids.append(face.face_id)
            encodings.append(encoding)
            existing_person_map[face.face_id] = face.person_id
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
    except Exception as e:
        logger.warning("Face clustering failed: %s", type(e).__name__)
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
            # Check if any faces in this cluster already belong to a person
            existing_person_ids = [
                existing_person_map[fid]
                for fid in cluster_face_ids
                if existing_person_map.get(fid) is not None
            ]

            # Find unassigned face IDs in this cluster
            unassigned_face_ids = [
                fid for fid in cluster_face_ids
                if existing_person_map.get(fid) is None
            ]

            if not unassigned_face_ids:
                # All faces already assigned — nothing to do
                continue

            if existing_person_ids:
                # Use the most common existing person
                from collections import Counter
                person_id = Counter(existing_person_ids).most_common(1)[0][0]
                person = await session.get(Person, person_id)
            else:
                # All faces are new — create a new person
                person = Person(
                    photo_count=0,
                    representative_face_id=unassigned_face_ids[0],
                )
                session.add(person)
                await session.flush()
                new_persons += 1

            # Assign only the unassigned faces to the person
            face_result = await session.execute(
                select(Face).where(Face.face_id.in_(unassigned_face_ids))
            )
            for face in face_result.scalars().all():
                face.person_id = person.person_id

            # Update person photo count (all faces in cluster, not just new)
            all_face_result = await session.execute(
                select(Face).where(Face.person_id == person.person_id)
            )
            all_person_faces = all_face_result.scalars().all()
            unique_photos = set(f.file_hash for f in all_person_faces)
            person.photo_count = len(unique_photos)
            if not person.representative_face_id:
                person.representative_face_id = unassigned_face_ids[0]

        await session.commit()

    noise_count = sum(1 for l in labels if l == -1)
    logger.info(
        "Face clustering: %d total faces (%d unassigned), %d clusters, %d noise, %d new persons",
        len(encodings), unassigned_count, n_clusters, noise_count, new_persons,
    )
    return new_persons
