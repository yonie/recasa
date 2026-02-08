from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class Caption(Base):
    """Ollama-generated natural language caption for a photo."""

    __tablename__ = "captions"

    file_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("photos.file_hash"), primary_key=True
    )
    caption: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    photo: Mapped["Photo"] = relationship(back_populates="caption")  # noqa: F821
