"""Export and import user-generated data (favorites, person names, ignored
persons, hidden together-tiles).

The export format is a JSON file containing:
- favorites: list of file_hashes
- persons: list of {name, ignored, encodings} where each encoding is the raw
  little-endian float32 bytes of a 512-dim insightface faceprint vector,
  base64-encoded (the actual identity signal)
- hidden_groups (optional): list of {members: [{encodings: [...]}, ...]} for
  the Together tiles hid on the people page. A tile has no stable identity of
  its own — person ids do not survive a rebuild — so it travels as its
  members' faceprints and is re-keyed on import to whatever ids exist then.

On import, favorites are restored by file_hash immediately. Person names are
stored as pending and applied whenever face clusters exist — either right away
or automatically after face detection + clustering finishes. Hidden groups
resolve the same way, and whatever cannot be matched yet waits as pending too.

hidden_groups is an additive field of version 2: exports from before it
existed simply lack the key, and older builds ignore it when present.

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
from backend.app.models.face import Face, Person, HiddenPersonGroup, group_key_from_ids

logger = logging.getLogger(__name__)

PENDING_IMPORT_KEY = "pending_person_import"
PENDING_HIDDEN_GROUPS_KEY = "pending_hidden_group_import"

# Together-tile members travel as a sample of their faceprints rather than
# every face they have: a handful of the most representative vectors is plenty
# for the >=2-votes match, and avoids duplicating the multi-MB encoding sets
# named people already carry in the persons section.
HIDDEN_MEMBER_SAMPLES = 8

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


async def _load_person_encodings(session: AsyncSession, person_id: int) -> list[np.ndarray]:
    """All decodable faceprints of one person, straight from the DB."""
    result = await session.execute(
        select(Face.encoding).where(
            Face.person_id == person_id,
            Face.encoding.is_not(None),
        )
    )
    encodings = []
    for (enc_bytes,) in result:
        enc = _encoding_from_db(enc_bytes)
        if enc is None or enc.size != ENCODING_DIM:
            continue
        encodings.append(enc)
    return encodings


def _sample_encodings(encodings: list[np.ndarray], limit: int) -> list[str]:
    """The `limit` faceprints closest to the person's centroid, as base64.

    Central vectors are the most representative ones, so they vote true more
    often on import than an arbitrary slice would.
    """
    if not encodings:
        return []
    if len(encodings) <= limit:
        picked = encodings
    else:
        matrix = np.array(encodings, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        matrix = matrix / norms
        centroid = matrix.mean(axis=0)
        norm = float(np.linalg.norm(centroid)) or 1.0
        sims = matrix @ (centroid / norm)
        picked = [encodings[i] for i in np.argsort(sims)[-limit:]]
    return [
        base64.b64encode(enc.astype("<f4").tobytes()).decode("ascii")
        for enc in picked
    ]


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

    # Hidden Together tiles. Person ids do not survive an export/import
    # round-trip, so a tile travels as its members' faceprints; on import the
    # members are matched back to whatever person ids exist by then.
    hidden_result = await session.execute(select(HiddenPersonGroup.group_key))
    hidden_groups = []
    member_cache: dict[int, list[np.ndarray]] = {}
    for (group_key,) in hidden_result:
        try:
            member_ids = [int(x) for x in group_key.split(",") if x]
        except ValueError:
            continue
        members = []
        for pid in member_ids:
            if pid not in member_cache:
                member_cache[pid] = await _load_person_encodings(session, pid)
            sample = _sample_encodings(member_cache[pid], HIDDEN_MEMBER_SAMPLES)
            if sample:
                members.append({"encodings": sample})
        if len(members) >= 2:
            hidden_groups.append({"members": members})

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "favorites": favorites,
        "persons": persons,
        "hidden_groups": hidden_groups,
    }


def _current_face_matrix(
    current_faces: list[tuple[int, int, bytes]],  # (face_id, person_id, encoding)
) -> tuple[np.ndarray | None, list[int]]:
    """Stack current face encodings into one normalized matrix for matching."""
    current_person_ids: list[int] = []
    current_encodings = []
    for _face_id, person_id, enc_bytes in current_faces:
        enc = _encoding_from_db(enc_bytes)
        if enc is None or enc.size != ENCODING_DIM:
            continue
        current_encodings.append(enc)
        current_person_ids.append(person_id)

    if not current_encodings:
        return None, []

    current_matrix = np.array(current_encodings, dtype=np.float32)
    # Normalize rows for cosine similarity
    norms = np.linalg.norm(current_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return current_matrix / norms, current_person_ids


def _vote_person_ids(
    exported_encs: list[np.ndarray],
    current_matrix: np.ndarray,
    current_person_ids: list[int],
    min_sim: float = 0.5,
) -> dict[int, int]:
    """How many exported encodings best-match each current person.

    Cosine similarity of each exported encoding against every current face;
    an encoding votes for the person of its single best match when that match
    clears min_sim.
    """
    exported_matrix = np.array(exported_encs, dtype=np.float32)
    exp_norms = np.linalg.norm(exported_matrix, axis=1, keepdims=True)
    exp_norms[exp_norms == 0] = 1
    exported_matrix = exported_matrix / exp_norms

    # Shape: (n_exported, n_current)
    similarities = exported_matrix @ current_matrix.T

    person_id_votes: dict[int, int] = {}
    for i in range(similarities.shape[0]):
        best_idx = int(np.argmax(similarities[i]))
        best_sim = float(similarities[i, best_idx])
        if best_sim >= min_sim:
            pid = current_person_ids[best_idx]
            person_id_votes[pid] = person_id_votes.get(pid, 0) + 1
    return person_id_votes


def _match_persons(
    exported_persons: list[dict],
    current_faces: list[tuple[int, int, bytes]],  # (face_id, person_id, encoding)
) -> dict[int, dict]:
    """Match exported person encodings to current person_ids.

    Returns {person_id: {"name": ..., "ignored": ...}} for the best matches.
    """
    if not exported_persons or not current_faces:
        return {}

    current_matrix, current_person_ids = _current_face_matrix(current_faces)
    if current_matrix is None:
        return {}

    assigned: dict[int, dict] = {}  # person_id -> person info
    used_person_ids: set[int] = set()

    for person_data in exported_persons:
        # Decode exported encodings
        exported_encs = [
            enc
            for enc in (_encoding_from_export(b64) for b64 in person_data.get("encodings", []))
            if enc is not None
        ]
        if not exported_encs:
            continue

        person_id_votes = _vote_person_ids(exported_encs, current_matrix, current_person_ids)
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


def _best_person_for_encodings(
    b64_list: list,
    current_matrix: np.ndarray,
    current_person_ids: list[int],
) -> int | None:
    """Resolve one exported identity (a set of faceprints) to a current person.

    Needs two agreeing votes, except when the identity carries a single
    sample — then one clear match at the same similarity bar is accepted,
    so tiny (often junk) people still resolve instead of being dropped.
    """
    encs = [
        enc for enc in (_encoding_from_export(b64) for b64 in b64_list)
        if enc is not None
    ]
    if not encs:
        return None
    votes = _vote_person_ids(encs, current_matrix, current_person_ids)
    if not votes:
        return None
    pid, votes_won = max(votes.items(), key=lambda kv: kv[1])
    if votes_won >= 2 or (votes_won == 1 and len(encs) == 1):
        return pid
    return None


def _match_hidden_groups(
    exported_hidden: list,
    current_faces: list[tuple[int, int, bytes]],  # (face_id, person_id, encoding)
) -> tuple[list[str], list]:
    """Resolve hidden-group members to current person_ids.

    Returns (restored_keys, unresolved). A group restores when every member
    matches a current person and at least two distinct people remain — if two
    members merged into one cluster, there is no two-person tile left to hide.
    """
    current_matrix, current_person_ids = _current_face_matrix(current_faces)
    if current_matrix is None:
        return [], exported_hidden

    restored: list[str] = []
    unresolved: list = []
    for group in exported_hidden:
        members = group.get("members", []) if isinstance(group, dict) else []
        resolved: set[int] = set()
        complete = len(members) >= 2
        for member in members:
            if not isinstance(member, dict):
                complete = False
                break
            pid = _best_person_for_encodings(
                member.get("encodings", []), current_matrix, current_person_ids
            )
            if pid is None:
                complete = False
                break
            resolved.add(pid)
        if complete and len(resolved) >= 2:
            restored.append(group_key_from_ids(resolved))
        else:
            unresolved.append(group)
    return restored, unresolved


async def _load_current_faces(session: AsyncSession) -> list[tuple[int, int, bytes]]:
    """(face_id, person_id, encoding) for every face that carries a faceprint."""
    result = await session.execute(
        select(Face.face_id, Face.person_id, Face.encoding).where(
            Face.encoding.is_not(None),
            Face.person_id.is_not(None),
        )
    )
    return [(r[0], r[1], r[2]) for r in result]


async def _try_apply_persons(
    exported_persons: list[dict],
    session: AsyncSession,
    current_faces: list[tuple[int, int, bytes]] | None = None,
) -> int:
    """Try to match and apply person names/ignored flags. Returns count applied."""
    if current_faces is None:
        current_faces = await _load_current_faces(session)
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


async def _try_apply_hidden_groups(
    exported_hidden: list,
    session: AsyncSession,
    current_faces: list[tuple[int, int, bytes]] | None = None,
) -> tuple[int, list]:
    """Match hidden-tile members to current persons and store the tiles.

    Returns (applied count, unresolved groups) — the unresolved ones are meant
    for the pending row that the post-clustering pass picks up.
    """
    if current_faces is None:
        current_faces = await _load_current_faces(session)
    if not current_faces:
        return 0, exported_hidden

    restored, unresolved = await asyncio.to_thread(
        _match_hidden_groups, exported_hidden, current_faces
    )
    for group_key in restored:
        if await session.get(HiddenPersonGroup, group_key) is None:
            session.add(HiddenPersonGroup(group_key=group_key))
    return len(restored), unresolved


async def import_user_data(data: dict, session: AsyncSession) -> dict:
    """Import user data from an export dict. Returns a summary."""

    summary = {
        "favorites_restored": 0,
        "persons_restored": 0,
        "persons_pending": 0,
        "hidden_groups_restored": 0,
        "hidden_groups_pending": 0,
    }

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

    # --- Hidden together tiles ---
    exported_hidden = data.get("hidden_groups", [])
    if not isinstance(exported_hidden, list):
        exported_hidden = []

    # One scan of all current faceprints serves both matchers below.
    current_faces = (
        await _load_current_faces(session)
        if (exported_persons or exported_hidden)
        else None
    )

    if exported_persons:
        # Try to apply immediately (works if faces are already clustered)
        applied = await _try_apply_persons(exported_persons, session, current_faces)
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

    if exported_hidden:
        applied_groups, unresolved = await _try_apply_hidden_groups(
            exported_hidden, session, current_faces
        )
        summary["hidden_groups_restored"] = applied_groups
        if unresolved:
            pending = await session.get(ConfigStore, PENDING_HIDDEN_GROUPS_KEY)
            groups_json = json.dumps(unresolved)
            if pending:
                pending.value = groups_json
            else:
                session.add(
                    ConfigStore(key=PENDING_HIDDEN_GROUPS_KEY, value=groups_json)
                )
            summary["hidden_groups_pending"] = len(unresolved)
        else:
            # Everything resolved right away; drop any stale pending list.
            stale = await session.get(ConfigStore, PENDING_HIDDEN_GROUPS_KEY)
            if stale:
                await session.delete(stale)

    await session.commit()

    logger.info(
        "Imported user data: %d favorites, %d persons restored (%d pending), "
        "%d hidden tiles restored (%d pending)",
        summary["favorites_restored"],
        summary["persons_restored"],
        summary["persons_pending"],
        summary["hidden_groups_restored"],
        summary["hidden_groups_pending"],
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


async def apply_pending_hidden_group_imports() -> int:
    """Apply pending hidden-together-tile imports after clustering completes.

    Unlike the person pending row, this one is rewritten with whatever is
    still unresolved, so a partial match keeps waiting instead of being
    dropped the moment anything else matches.
    """
    async with async_session() as session:
        pending = await session.get(ConfigStore, PENDING_HIDDEN_GROUPS_KEY)
        if not pending:
            return 0

        try:
            exported_hidden = json.loads(pending.value)
        except (json.JSONDecodeError, TypeError):
            await session.delete(pending)
            await session.commit()
            return 0

        current_faces = await _load_current_faces(session)
        if current_faces:
            restored, unresolved = await asyncio.to_thread(
                _match_hidden_groups, exported_hidden, current_faces
            )
        else:
            restored, unresolved = [], exported_hidden

        for group_key in restored:
            if await session.get(HiddenPersonGroup, group_key) is None:
                session.add(HiddenPersonGroup(group_key=group_key))

        if unresolved:
            pending.value = json.dumps(unresolved)
        else:
            await session.delete(pending)
        await session.commit()

        if restored:
            logger.info(
                "Applied %d pending hidden-group imports after clustering",
                len(restored),
            )
        return len(restored)
