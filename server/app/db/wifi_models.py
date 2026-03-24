"""
Thesis IoT Server — WiFi Configuration Model
Stores WiFi credentials securely with encrypted passwords.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.database import Base


class WifiConfig(Base):
    """Persisted WiFi configuration for the STM32 board."""
    __tablename__ = "wifi_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ssid = Column(String(32), nullable=False)
    password_encrypted = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
