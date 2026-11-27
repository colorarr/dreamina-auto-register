"""Resource inventory deliberately separate from scheduler tables."""
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InventoryMailbox(Base):
    __tablename__ = "inventory_mailboxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(254), unique=True)
    email: Mapped[str] = mapped_column(String(254))
    note: Mapped[str] = mapped_column(String(512), default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryProxy(Base):
    __tablename__ = "inventory_proxies"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    protocol: Mapped[str] = mapped_column(String(8))
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(Integer)
    has_auth: Mapped[bool] = mapped_column(Boolean)
