from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class DuplicateGroup(Base):
    """A group of visually similar/duplicate photos."""

    __tablename__ = "duplicate_groups"

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["DuplicateMember"]] = relationship(
        back_populates="group", cascade="all, delete"
    )


class DuplicateMember(Base):
    """A photo that belongs to a duplicate group."""

    __tablename__ = "duplicate_members"

    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("duplicate_groups.group_id"), primary_key=True
    )
    file_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("photos.file_hash"), primary_key=True
    )

    group: Mapped["DuplicateGroup"] = relationship(back_populates="members")
