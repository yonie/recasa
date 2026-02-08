from sqlalchemy import ForeignKey, Integer, LargeBinary, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class Person(Base):
    """A recognized person (face cluster)."""

    __tablename__ = "persons"

    person_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(200))
    representative_face_id: Mapped[int | None] = mapped_column(Integer)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)

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

    # 128-dimensional face encoding from dlib
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
