from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


def group_key_from_ids(person_ids) -> str:
    """Canonical identity of a together-group: its sorted person ids, joined.

    The single source of truth for what "the same group" means everywhere a
    group is named or compared: hidden_person_groups rows, the together listing
    and the export/import round-trip all build their keys through this.
    """
    return ",".join(str(pid) for pid in sorted(person_ids))


class Person(Base):
    """A recognized person (face cluster)."""

    __tablename__ = "persons"

    person_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(200))
    representative_face_id: Mapped[int | None] = mapped_column(Integer)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)

    faces: Mapped[list["Face"]] = relationship(back_populates="person")


class Face(Base):
    """A detected face within a photo."""

    __tablename__ = "faces"

    face_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("photos.file_hash"), nullable=False, index=True
    )

    # Bounding box
    bbox_x: Mapped[int | None] = mapped_column(Integer)
    bbox_y: Mapped[int | None] = mapped_column(Integer)
    bbox_w: Mapped[int | None] = mapped_column(Integer)
    bbox_h: Mapped[int | None] = mapped_column(Integer)

    # 512-dimensional face encoding from insightface
    encoding: Mapped[bytes | None] = mapped_column(LargeBinary)

    # Assigned person
    person_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("persons.person_id"), index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)

    # Thumbnail path for the face crop
    face_thumbnail: Mapped[str | None] = mapped_column(Text)

    photo: Mapped["Photo"] = relationship(back_populates="faces")  # noqa: F821
    person: Mapped["Person | None"] = relationship(back_populates="faces")


class HiddenPersonGroup(Base):
    """A Together-section tile the user hid from the people page.

    Together groups are computed on the fly from co-occurring faces, so there
    is no persistent group entity to flag. Instead we persist a canonical key
    of the group's sorted person_ids, e.g. "25,28". Keys that no longer match
    anything (person ids changed after a recluster) are simply inert.
    """

    __tablename__ = "hidden_person_groups"

    group_key: Mapped[str] = mapped_column(String(255), primary_key=True)
