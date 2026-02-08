from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class Photo(Base):
    __tablename__ = "photos"

    file_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_modified: Mapped[datetime | None] = mapped_column(DateTime)
    mime_type: Mapped[str | None] = mapped_column(String(50))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    # EXIF metadata
    date_taken: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    camera_make: Mapped[str | None] = mapped_column(String(100))
    camera_model: Mapped[str | None] = mapped_column(String(100))
    lens_model: Mapped[str | None] = mapped_column(String(100))
    focal_length: Mapped[float | None] = mapped_column(Float)
    aperture: Mapped[float | None] = mapped_column(Float)
    shutter_speed: Mapped[str | None] = mapped_column(String(20))
    iso: Mapped[int | None] = mapped_column(Integer)
    orientation: Mapped[int | None] = mapped_column(Integer)

    # GPS
    gps_latitude: Mapped[float | None] = mapped_column(Float)
    gps_longitude: Mapped[float | None] = mapped_column(Float)
    gps_altitude: Mapped[float | None] = mapped_column(Float)

    # Reverse geocoded location
    location_country: Mapped[str | None] = mapped_column(String(100))
    location_city: Mapped[str | None] = mapped_column(String(200))
    location_address: Mapped[str | None] = mapped_column(Text)

    # Live Photo / Motion Photo
    live_photo_video: Mapped[str | None] = mapped_column(Text)
    motion_photo: Mapped[bool] = mapped_column(Boolean, default=False)

    # Processing state
    thumbnail_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    exif_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    faces_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    clip_tagged: Mapped[bool] = mapped_column(Boolean, default=False)
    ollama_captioned: Mapped[bool] = mapped_column(Boolean, default=False)
    perceptual_hashed: Mapped[bool] = mapped_column(Boolean, default=False)

    # User data
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    indexed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    paths: Mapped[list["PhotoPath"]] = relationship(back_populates="photo", cascade="all, delete")
    hash_info: Mapped["PhotoHash | None"] = relationship(
        back_populates="photo", cascade="all, delete", uselist=False
    )
    faces: Mapped[list["Face"]] = relationship(  # noqa: F821
        back_populates="photo", cascade="all, delete"
    )
    tags: Mapped[list["PhotoTag"]] = relationship(  # noqa: F821
        back_populates="photo", cascade="all, delete"
    )
    caption: Mapped["Caption | None"] = relationship(  # noqa: F821
        back_populates="photo", cascade="all, delete", uselist=False
    )

    __table_args__ = (
        Index("idx_photos_location", "location_country", "location_city"),
        Index("idx_photos_size", file_size.desc()),
    )


class PhotoPath(Base):
    """Track all filesystem paths where a photo exists (handles duplicates/symlinks)."""

    __tablename__ = "photo_paths"

    file_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("photos.file_hash"), primary_key=True
    )
    file_path: Mapped[str] = mapped_column(Text, primary_key=True)

    photo: Mapped["Photo"] = relationship(back_populates="paths")


class PhotoHash(Base):
    """Perceptual hashes for duplicate detection."""

    __tablename__ = "photo_hashes"

    file_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("photos.file_hash"), primary_key=True
    )
    phash: Mapped[str | None] = mapped_column(String(16))
    ahash: Mapped[str | None] = mapped_column(String(16))
    dhash: Mapped[str | None] = mapped_column(String(16))

    photo: Mapped["Photo"] = relationship(back_populates="hash_info")
