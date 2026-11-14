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
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import func, select, update

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.models import Face, Person, Photo
from backend.app.services.image_loader import is_raw, open_image_cm

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
CLUSTER_DISTANCE_THRESHOLD = 0.3  # Cosine distance; lower = stricter matching
CLUSTER_MIN_SAMPLES = 1  # Allow single-appearance faces to form their own cluster

# Bound on ids per IN (...) list; SQLite allows at most 32766 variables.
_IN_CHUNK = 10000


class FaceModelUnavailable(Exception):
    """insightface could not be loaded, so nothing was actually examined.

    Deliberately not a PermanentStageError and not an empty result: either
    would mark photos as "checked, no faces" for good. Left unprocessed they
    are detected once the model loads (after a restart).
    """


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

    Returns list of dicts with keys: bbox, encoding, confidence.
    bbox is (x, y, w, h), encoding is 512-dim numpy array. An unreadable image
    gives [] (stored as "no faces"); a missing model raises FaceModelUnavailable.
    """
    if not _load_insightface():
        raise FaceModelUnavailable("insightface model is not available")

    try:
        # Load image - OpenCV reads most formats (JPEG/PNG/TIFF/BMP) directly
        # to BGR, which is the fastest path. HEIC/HEIF and RAW (ORF) must go
        # through the central image loader (pillow-heif / rawpy).
        import cv2

        ext = filepath.suffix.lower()
        needs_pil_path = ext in ('.heic', '.heif') or is_raw(filepath)

        if needs_pil_path:
            try:
                with open_image_cm(filepath) as pil_img:
                    pil_img = pil_img.convert('RGB')
                    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            except Exception as e:
                logger.debug("Could not read %s: %s", filepath, type(e).__name__)
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


def _crop_face(img: Image.Image, bbox: tuple, file_hash: str, face_idx: int) -> str:
    """Save a padded square-ish crop of one face; returns its path under data_dir."""
    x, y, w, h = bbox

    # Add padding around the face (30% on each side)
    pad_x = int(w * 0.3)
    pad_y = int(h * 0.3)

    # Crop with padding (clamp to image bounds)
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(img.width, x + w + pad_x)
    bottom = min(img.height, y + h + pad_y)

    face_crop = img.crop((left, top, right, bottom))
    face_crop = face_crop.convert("RGB")
    face_crop.thumbnail((FACE_THUMB_SIZE, FACE_THUMB_SIZE), Image.Resampling.LANCZOS)

    faces_dir = settings.data_dir / "faces" / file_hash[:2]
    faces_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = faces_dir / f"{file_hash}_face{face_idx}.webp"
    face_crop.save(thumb_path, "WEBP", quality=85)

    return str(thumb_path.relative_to(settings.data_dir))


def _generate_face_thumbnails(
    filepath: Path, bboxes: list[tuple], file_hash: str
) -> list[str | None]:
    """Crop every detected face from one decode of the photo.

    Returns one relative thumbnail path per bbox, None where that crop failed.
    """
    try:
        with open_image_cm(filepath) as img:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            img.load()

            paths: list[str | None] = []
            for idx, bbox in enumerate(bboxes):
                try:
                    paths.append(_crop_face(img, bbox, file_hash, idx))
                except Exception as e:
                    logger.warning(
                        "Face thumbnail failed for %s face %d: %s",
                        file_hash, idx, type(e).__name__,
                    )
                    paths.append(None)
            return paths
    except Exception as e:
        logger.warning("Face thumbnails failed for %s: %s", file_hash, type(e).__name__)
        return [None] * len(bboxes)


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
            select(Face.face_id).where(Face.file_hash == file_hash).limit(1)
        )
        if result.first() is not None:
            return True
        file_path = photo.file_path

    filepath = settings.photos_dir / file_path
    if not filepath.exists():
        return False

    faces = await asyncio.to_thread(_detect_faces, filepath)
    thumb_paths = (
        await asyncio.to_thread(
            _generate_face_thumbnails, filepath, [f["bbox"] for f in faces], file_hash
        )
        if faces
        else []
    )

    async with async_session() as session:
        if faces:
            for face_data, thumb_path in zip(faces, thumb_paths, strict=True):
                x, y, w, h = face_data["bbox"]
                session.add(Face(
                    file_hash=file_hash,
                    bbox_x=x,
                    bbox_y=y,
                    bbox_w=w,
                    bbox_h=h,
                    encoding=pickle.dumps(face_data["encoding"]),
                    face_thumbnail=thumb_path,
                    confidence=face_data.get("confidence"),
                ))
            logger.info("Detected %d face(s) in %s", len(faces), file_hash)
        else:
            # Store a marker record to indicate "processed, no faces found"
            # This prevents re-processing on restart
            session.add(Face(
                file_hash=file_hash,
                bbox_x=0,
                bbox_y=0,
                bbox_w=0,
                bbox_h=0,
                encoding=None,  # NULL encoding = no faces, just checked
            ))
            logger.debug("No faces detected in %s (marked as processed)", file_hash)

        await session.commit()
    return True


def _cluster_encodings(
    rows: list[tuple[int, int | None, bytes]],
) -> tuple[list[int], np.ndarray, dict[int, int | None]] | None:
    """Unpickle encodings and run DBSCAN. CPU-bound: runs in a worker thread.

    Returns (face_ids, labels, existing_person_map), or None when there is
    nothing to cluster or clustering failed.
    """
    face_ids: list[int] = []
    encodings = []
    existing_person_map: dict[int, int | None] = {}  # face_id -> person_id
    for face_id, person_id, blob in rows:
        try:
            # Our own rows, written by detect_faces; an unreadable one is skipped.
            encoding = pickle.loads(blob)
        except Exception:
            continue
        face_ids.append(face_id)
        encodings.append(encoding)
        existing_person_map[face_id] = person_id

    if len(encodings) < CLUSTER_MIN_SAMPLES:
        return None

    # DBSCAN clustering with cosine distance (insightface produces normalized embeddings)
    try:
        from sklearn.cluster import DBSCAN

        clustering = DBSCAN(
            eps=CLUSTER_DISTANCE_THRESHOLD,
            min_samples=CLUSTER_MIN_SAMPLES,
            metric="cosine",
        ).fit(np.array(encodings))
    except ImportError:
        logger.warning("scikit-learn not installed, cannot cluster faces")
        return None
    except Exception as e:
        logger.warning("Face clustering failed: %s", type(e).__name__)
        return None

    return face_ids, clustering.labels_, existing_person_map


async def cluster_faces() -> int:
    """Cluster all unassigned faces into persons using DBSCAN.

    Includes already-assigned faces in the clustering so that new faces
    are matched against existing persons rather than always creating new ones.

    Returns the number of new person clusters created.
    """
    async with async_session() as session:
        unassigned_count = await session.scalar(
            select(func.count(Face.face_id)).where(
                Face.encoding.is_not(None),
                Face.person_id.is_(None),
            )
        ) or 0

    if unassigned_count == 0:
        return 0

    # Load ALL faces with encodings (assigned + unassigned) so DBSCAN can
    # group new faces with existing persons. Only the three columns needed:
    # whole Face rows for 50k+ faces is a lot of objects on a Pi. face_id
    # order is the table's natural order, which the person assignment below
    # depends on (cluster order decides new person ids).
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Face.face_id, Face.person_id, Face.encoding)
                .where(Face.encoding.is_not(None))
                .order_by(Face.face_id)
            )
        ).all()

    if len(rows) < CLUSTER_MIN_SAMPLES:
        return 0

    # Unpickling and DBSCAN over every face take seconds to minutes on a Pi;
    # off the event loop so the API stays responsive meanwhile.
    clustered = await asyncio.to_thread(_cluster_encodings, rows)
    del rows
    if clustered is None:
        return 0
    face_ids, labels, existing_person_map = clustered
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

    # Build cluster -> face_ids mapping, clusters in order of their first face
    cluster_map: dict[int, list[int]] = {}
    for face_id, label in zip(face_ids, labels, strict=True):
        if label == -1:
            continue  # Noise point - not assigned to any cluster
        cluster_map.setdefault(label, []).append(face_id)

    # Store clusters as persons
    new_persons = 0
    async with async_session() as session:
        for cluster_face_ids in cluster_map.values():
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
                # All faces already assigned, nothing to do
                continue

            if existing_person_ids:
                # Use the most common existing person
                person_id = Counter(existing_person_ids).most_common(1)[0][0]
                person = await session.get(Person, person_id)
            else:
                # All faces are new: create a new person
                person = Person(
                    photo_count=0,
                    representative_face_id=unassigned_face_ids[0],
                )
                session.add(person)
                await session.flush()
                new_persons += 1

            # Assign only the unassigned faces to the person
            for i in range(0, len(unassigned_face_ids), _IN_CHUNK):
                await session.execute(
                    update(Face)
                    .where(Face.face_id.in_(unassigned_face_ids[i : i + _IN_CHUNK]))
                    .values(person_id=person.person_id)
                )

            # Update person photo count (all faces in cluster, not just new)
            person.photo_count = await session.scalar(
                select(func.count(func.distinct(Face.file_hash))).where(
                    Face.person_id == person.person_id
                )
            ) or 0
            if not person.representative_face_id:
                person.representative_face_id = unassigned_face_ids[0]

        await session.commit()

    noise_count = int(np.count_nonzero(labels == -1))
    logger.info(
        "Face clustering: %d total faces (%d unassigned), %d clusters, %d noise, %d new persons",
        len(face_ids), unassigned_count, n_clusters, noise_count, new_persons,
    )
    return new_persons
