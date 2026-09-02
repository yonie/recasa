"""Export and import user-generated data (favorites, person names, ignored persons).

The export format is a JSON file containing:
- favorites: list of file_hashes
- persons: list of {name, ignored, encodings} where each encoding is the raw
  little-endian float32 bytes of a 512-dim insightface faceprint vector,
  base64-encoded (the actual identity signal)

On import, favorites are restored by file_hash immediately. Person names are
stored as pending and applied whenever face clusters exist — either right away
or automatically after face detection + clustering finishes.

Format version 2 exists because version 1 base64-encoded the *pickled* numpy
array straight out of the database, and the importer called ``pickle.loads`` on
it. Unpickling a file someone uploads is arbitrary code execution, in a process
that has the entire photo library mounted. Version 2 carries plain float32 bytes
that are parsed with ``np.frombuffer``, which cannot execute anything, and
version 1 files are refused rather than read.
"""

import asyncio
import base64
import json
import logging
import pickle
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import async_session
from backend.app.models import Photo
from backend.app.models.config import ConfigStore
from backend.app.models.face import Face, Person

logger = logging.getLogger(__name__)

PENDING_IMPORT_KEY = "pending_person_import"

# Current export format. See the module docstring for why version 1 is refused.
EXPORT_VERSION = 2

# insightface buffalo_l faceprints. Fixed so a malformed or hostile file is
# rejected on sight rather than reaching numpy with an arbitrary shape.
ENCODING_DIM = 512
ENCODING_NBYTES = ENCODING_DIM * 4  # float32


def _encoding_from_db(enc_bytes: bytes) -> np.ndarray | None:
    """Decode a faceprint as stored in our own database.

    This is the one place pickle is still used, and it reads only rows this app
    wrote itself. Changing the stored format would mean a schema change and a
    full re-detect of every face, which is days of processing.
    """
    try:
        return np.asarray(pickle.loads(enc_bytes), dtype=np.float32)
    except Exception:
        return None


def _encoding_from_export(b64: str) -> np.ndarray | None:
    """Decode a faceprint out of an uploaded export file.

    Deliberately not pickle: ``np.frombuffer`` interprets bytes as numbers and
    can do nothing else, so a hostile file is at worst rejected here.
    """
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    if len(raw) != ENCODING_NBYTES:
        return None
    return np.frombuffer(raw, dtype="<f4")


async def export_user_data(session: AsyncSession) -> dict:
    """Build the export dict from the current database state."""

    # Favorites
    result = await session.execute(
        select(Photo.file_hash).where(Photo.is_favorite == True)  # noqa: E712
    )
    favorites = [row[0] for row in result]

    # Named or ignored persons with their face encodings
    result = await session.execute(
        select(Person).where(
            (Person.name.is_not(None)) | (Person.ignored == True)  # noqa: E712
        )
    )
    persons_rows = result.scalars().all()

    persons = []
    for person in persons_rows:
        # Get all face encodings for this person
        faces_result = await session.execute(
            select(Face.encoding).where(
                Face.person_id == person.person_id,
                Face.encoding.is_not(None),
            )
        )
        encodings_b64 = []
        for (enc_bytes,) in faces_result:
            enc = _encoding_from_db(enc_bytes)
            if enc is None or enc.size != ENCODING_DIM:
                continue
            # Raw float32 bytes, not the pickle we happen to store internally,
            # so importing this file never has to deserialise code.
            encodings_b64.append(
                base64.b64encode(enc.astype("<f4").tobytes()).decode("ascii")
            )

        if encodings_b64:
            persons.append({
                "name": person.name,
                "ignored": person.ignored,
                "encodings": encodings_b64,
            })

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "favorites": favorites,
        "persons": persons,
    }


def _match_persons(
    exported_persons: list[dict],
    current_faces: list[tuple[int, int, bytes]],  # (face_id, person_id, encoding)
) -> dict[int, dict]:
    """Match exported person encodings to current person_ids.

    Returns {person_id: {"name": ..., "ignored": ...}} for the best matches.
    """
    if not exported_persons or not current_faces:
        return {}

    # Build matrix of current face encodings
    current_person_ids = []
    current_encodings = []
    for face_id, person_id, enc_bytes in current_faces:
        enc = _encoding_from_db(enc_bytes)
        if enc is None or enc.size != ENCODING_DIM:
            continue
        current_encodings.append(enc)
        current_person_ids.append(person_id)

    if not current_encodings:
        return {}

    current_matrix = np.array(current_encodings, dtype=np.float32)
    # Normalize rows for cosine similarity
    norms = np.linalg.norm(current_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    current_matrix = current_matrix / norms

    assigned: dict[int, dict] = {}  # person_id -> person info
    used_person_ids: set[int] = set()

    for person_data in exported_persons:
        # Decode exported encodings
        exported_encs = []
        for b64 in person_data.get("encodings", []):
            enc = _encoding_from_export(b64)
            if enc is not None:
                exported_encs.append(enc)

        if not exported_encs:
            continue

        exported_matrix = np.array(exported_encs, dtype=np.float32)
        exp_norms = np.linalg.norm(exported_matrix, axis=1, keepdims=True)
        exp_norms[exp_norms == 0] = 1
        exported_matrix = exported_matrix / exp_norms

        # Cosine similarity: each exported encoding vs all current face encodings
        # Shape: (n_exported, n_current)
        similarities = exported_matrix @ current_matrix.T

        # For each exported encoding, find the best matching current face
        # Count how many high-confidence matches point to each person_id
        person_id_votes: dict[int, int] = {}
        for i in range(similarities.shape[0]):
            best_idx = int(np.argmax(similarities[i]))
            best_sim = float(similarities[i, best_idx])
            if best_sim >= 0.5:
                pid = current_person_ids[best_idx]
                person_id_votes[pid] = person_id_votes.get(pid, 0) + 1

        if not person_id_votes:
            continue

        # Best person_id: most votes, not already assigned
        for pid, votes in sorted(person_id_votes.items(), key=lambda x: -x[1]):
            if pid not in used_person_ids and votes >= 2:
                assigned[pid] = {
                    "name": person_data.get("name"),
                    "ignored": person_data.get("ignored", False),
                }
                used_person_ids.add(pid)
                break

    return assigned


async def _try_apply_persons(
    exported_persons: list[dict], session: AsyncSession
) -> int:
    """Try to match and apply person names/ignored flags. Returns count applied."""
    result = await session.execute(
        select(Face.face_id, Face.person_id, Face.encoding).where(
            Face.encoding.is_not(None),
            Face.person_id.is_not(None),
        )
    )
    current_faces = [(r[0], r[1], r[2]) for r in result]

    if not current_faces:
        return 0

    assignments = await asyncio.to_thread(
        _match_persons, exported_persons, current_faces
    )

    count = 0
    for person_id, info in assignments.items():
        person = await session.get(Person, person_id)
        if person:
            if info["name"] and not person.name:
                person.name = info["name"]
            if info["ignored"]:
                person.ignored = True
            count += 1

    return count


async def import_user_data(data: dict, session: AsyncSession) -> dict:
    """Import user data from an export dict. Returns a summary."""

    summary = {"favorites_restored": 0, "persons_restored": 0, "persons_pending": 0}

    # Refuse anything that is not the current format. Version 1 stored pickled
    # numpy arrays, and reading one means unpickling a file a stranger uploaded;
    # there is no safe way to accept it, so it is rejected rather than migrated.
    version = data.get("version")
    if version != EXPORT_VERSION:
        raise ValueError(
            f"Unsupported export version {version!r}; this build reads version "
            f"{EXPORT_VERSION} only. Re-export from the instance that holds the data."
        )

    # --- Favorites (immediate) ---
    fav_hashes = data.get("favorites", [])
    if fav_hashes:
        result = await session.execute(
            update(Photo)
            .where(Photo.file_hash.in_(fav_hashes))
            .values(is_favorite=True)
        )
        summary["favorites_restored"] = result.rowcount  # type: ignore[assignment]

    # --- Persons ---
    exported_persons = data.get("persons", [])
    if exported_persons:
        # Try to apply immediately (works if faces are already clustered)
        applied = await _try_apply_persons(exported_persons, session)
        summary["persons_restored"] = applied

        # Save as pending so clustering can pick up anything we couldn't match yet
        pending = await session.get(ConfigStore, PENDING_IMPORT_KEY)
        persons_json = json.dumps(exported_persons)
        if pending:
            pending.value = persons_json
        else:
            session.add(ConfigStore(key=PENDING_IMPORT_KEY, value=persons_json))

        remaining = len(exported_persons) - applied
        if remaining > 0:
            summary["persons_pending"] = remaining

    await session.commit()

    logger.info(
        "Imported user data: %d favorites, %d persons restored, %d pending",
        summary["favorites_restored"],
        summary["persons_restored"],
        summary["persons_pending"],
    )
    return summary


async def apply_pending_person_imports() -> int:
    """Apply any pending person imports. Called after face clustering completes.

    Returns the number of persons restored, or 0 if nothing pending.
    """
    async with async_session() as session:
        pending = await session.get(ConfigStore, PENDING_IMPORT_KEY)
        if not pending:
            return 0

        try:
            exported_persons = json.loads(pending.value)
        except (json.JSONDecodeError, TypeError):
            await session.delete(pending)
            await session.commit()
            return 0

        applied = await _try_apply_persons(exported_persons, session)

        # Clear pending data once applied
        if applied > 0:
            await session.delete(pending)
            await session.commit()
            logger.info("Applied %d pending person imports after clustering", applied)

        return applied
