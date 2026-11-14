"""Which pipeline stages a photo still needs, decided from data that exists.

The single home of the per-stage rules (see "How to Check if Stage Output
Exists" in AGENTS.md). Three callers apply them and must agree:

- the scanner, picking the stage a (re)discovered photo enters at,
- startup resume, re-queueing photos whose processing was interrupted,
- the workers, re-checking each stage just before running it.

A stage is needed when it is enabled, applies to the photo, has no output yet
and has no recorded permanent failure (stage_failures). Scans and resume enter
a photo at its first needed stage; routing then carries it through the rest.
"""

import asyncio
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.models import Caption, Face, Photo, PhotoHash, StageFailure
from backend.app.services.thumbnail import existing_thumb_hashes, thumb_exists
from backend.app.workers.queues import QueueType

# Stages a scan or resume can enter a photo at, in pipeline order. Motion
# photos are not here: that stage has no output to check, it just runs (as a
# cheap no-op for most photos) whenever a photo passes through.
ENTRY_STAGES: tuple[QueueType, ...] = (
    QueueType.EXIF,
    QueueType.GEOCODING,
    QueueType.THUMBNAILS,
    QueueType.HASHING,
    QueueType.FACES,
    QueueType.CAPTIONING,
)


def stage_enabled(stage: QueueType) -> bool:
    """Only geocoding, faces and captioning can be switched off."""
    if stage is QueueType.GEOCODING:
        return settings.ENABLE_GEOCODING
    if stage is QueueType.FACES:
        return settings.ENABLE_FACE_DETECTION
    if stage is QueueType.CAPTIONING:
        return settings.ENABLE_CAPTIONING
    return True


def stage_applies(stage: QueueType, *, is_video: bool, has_gps: bool) -> bool:
    """Videos only get a poster thumbnail; geocoding needs coordinates."""
    if is_video:
        return stage is QueueType.THUMBNAILS
    if stage is QueueType.GEOCODING:
        return has_gps
    return True


def has_coordinates(photo: Photo) -> bool:
    """Geocoding needs both halves: a latitude alone would be queued on
    every scan and never produce a location."""
    return photo.gps_latitude is not None and photo.gps_longitude is not None


@dataclass(frozen=True, slots=True)
class PhotoFacts:
    """The photo columns the stage rules read."""

    file_hash: str
    is_video: bool
    has_exif: bool  # camera_make or date_taken is set
    has_gps: bool  # gps_latitude and gps_longitude are both set
    has_city: bool  # location_city is set

    @classmethod
    def of(cls, photo: Photo) -> "PhotoFacts":
        return cls(
            file_hash=photo.file_hash,
            is_video=bool(photo.is_video),
            has_exif=photo.camera_make is not None or photo.date_taken is not None,
            has_gps=has_coordinates(photo),
            has_city=photo.location_city is not None,
        )


# Column expressions matching PhotoFacts, for bulk loads without ORM objects.
_FACT_COLUMNS = (
    Photo.file_hash,
    Photo.is_video,
    (Photo.camera_make.is_not(None) | Photo.date_taken.is_not(None)).label("has_exif"),
    (Photo.gps_latitude.is_not(None) & Photo.gps_longitude.is_not(None)).label("has_gps"),
    Photo.location_city.is_not(None).label("has_city"),
)


@dataclass
class StageOutputs:
    """Which photos already have each stage's output, plus recorded failures.

    Loaded in bulk once (resume, full rescans) or for a single photo, so the
    rules below run without a query per photo per stage.
    """

    thumbs: set[str] = field(default_factory=set)
    hashed: set[str] = field(default_factory=set)
    faced: set[str] = field(default_factory=set)
    captioned: set[str] = field(default_factory=set)
    failures: dict[str, set[str]] = field(default_factory=dict)  # file_hash -> stages

    def has_output(self, stage: QueueType, facts: PhotoFacts) -> bool:
        fh = facts.file_hash
        if stage is QueueType.EXIF:
            return facts.has_exif
        if stage is QueueType.GEOCODING:
            return facts.has_city
        if stage is QueueType.THUMBNAILS:
            return fh in self.thumbs
        if stage is QueueType.HASHING:
            return fh in self.hashed
        if stage is QueueType.FACES:
            return fh in self.faced
        if stage is QueueType.CAPTIONING:
            return fh in self.captioned
        return False

    def failed(self, stage: QueueType, file_hash: str) -> bool:
        return stage.value in self.failures.get(file_hash, ())

    def needed_stages(self, facts: PhotoFacts) -> Iterator[QueueType]:
        """Every entry stage this photo still needs, in pipeline order."""
        for stage in ENTRY_STAGES:
            if (
                stage_enabled(stage)
                and stage_applies(stage, is_video=facts.is_video, has_gps=facts.has_gps)
                and not self.has_output(stage, facts)
                and not self.failed(stage, facts.file_hash)
            ):
                yield stage

    def first_needed_stage(self, facts: PhotoFacts) -> QueueType | None:
        """The stage this photo should enter the pipeline at, or None if done."""
        return next(self.needed_stages(facts), None)


async def load_stage_outputs(
    session: AsyncSession, file_hashes: Collection[str] | None = None
) -> StageOutputs:
    """Load stage outputs for the given photos, or for every photo when None.

    Disabled stages are not loaded: their rule never asks.
    """

    def scoped(stmt, column):
        return stmt if file_hashes is None else stmt.where(column.in_(file_hashes))

    async def hashes(stmt, column) -> set[str]:
        return set((await session.execute(scoped(stmt, column))).scalars())

    out = StageOutputs()
    if file_hashes is None:
        out.thumbs = await asyncio.to_thread(existing_thumb_hashes)
    else:
        out.thumbs = {fh for fh in file_hashes if thumb_exists(fh)}
    out.hashed = await hashes(select(PhotoHash.file_hash), PhotoHash.file_hash)
    if settings.ENABLE_FACE_DETECTION:
        out.faced = await hashes(select(Face.file_hash).distinct(), Face.file_hash)
    if settings.ENABLE_CAPTIONING:
        out.captioned = await hashes(select(Caption.file_hash), Caption.file_hash)

    rows = await session.execute(
        scoped(select(StageFailure.file_hash, StageFailure.stage), StageFailure.file_hash)
    )
    for file_hash, stage in rows:
        out.failures.setdefault(file_hash, set()).add(stage)
    return out


async def load_photo_facts(session: AsyncSession) -> list[PhotoFacts]:
    """PhotoFacts for every indexed photo and video."""
    rows = await session.execute(select(*_FACT_COLUMNS))
    return [
        PhotoFacts(fh, bool(is_video), bool(has_exif), bool(has_gps), bool(has_city))
        for fh, is_video, has_exif, has_gps, has_city in rows
    ]


async def first_needed_stage(session: AsyncSession, photo: Photo) -> QueueType | None:
    """Entry stage for one photo (the scanner's per-file path)."""
    outputs = await load_stage_outputs(session, [photo.file_hash])
    return outputs.first_needed_stage(PhotoFacts.of(photo))


async def has_output(session: AsyncSession, stage: QueueType, photo: Photo) -> bool:
    """Whether `stage` already produced its output for `photo`, checked live.

    The worker asks this right before running a stage, so it sees what the
    earlier stages just wrote. Same rules as StageOutputs.has_output.
    """
    if stage is QueueType.THUMBNAILS:
        return thumb_exists(photo.file_hash)
    if stage in (QueueType.EXIF, QueueType.GEOCODING):
        return StageOutputs().has_output(stage, PhotoFacts.of(photo))
    model = {
        QueueType.HASHING: PhotoHash,
        QueueType.FACES: Face,
        QueueType.CAPTIONING: Caption,
    }.get(stage)
    if model is None:
        return False
    return bool(await session.scalar(select(exists().where(model.file_hash == photo.file_hash))))


async def failure_recorded(session: AsyncSession, stage: QueueType, file_hash: str) -> bool:
    """Whether this photo has a recorded permanent failure for `stage`."""
    return bool(
        await session.scalar(
            select(
                exists().where(
                    StageFailure.file_hash == file_hash, StageFailure.stage == stage.value
                )
            )
        )
    )
