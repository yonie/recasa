"""Configuration store model for persisting app-level settings."""

from sqlalchemy import Column, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class ConfigStore(Base):
    """Key-value store for configuration that needs to persist."""
    
    __tablename__ = "config_store"
    
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    
    def __repr__(self) -> str:
        return f"<ConfigStore(key={self.key!r}, value={self.value[:50]!r}...)>"