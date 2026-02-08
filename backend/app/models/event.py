from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class Event(Base):
    """Auto-detected event (cluster of photos by time + location)."""

    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(300))
    start_date: Mapped[datetime | None] = mapped_column(DateTime)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)
    location: Mapped[str | None] = mapped_column(Text)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)

    event_photos: Mapped[list["EventPhoto"]] = relationship(
        back_populates="event", cascade="all, delete"
    )


class EventPhoto(Base):
    """Association between an event and a photo."""

    __tablename__ = "event_photos"

    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.event_id"), primary_key=True
    )
    file_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("photos.file_hash"), primary_key=True
    )

    event: Mapped["Event"] = relationship(back_populates="event_photos")
