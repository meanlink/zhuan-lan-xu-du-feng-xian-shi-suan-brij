from sqlalchemy import String, Integer, JSON, Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class IdentityState(Base):
    """Single row holding the monotonically increasing identity ledger version."""
    __tablename__ = 'identity_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[float] = mapped_column(Double, default=0.0)


class IdentityGroup(Base):
    """A person/identity. Groups are never deleted, even when they become empty."""
    __tablename__ = 'identity_groups'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    created_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[float] = mapped_column(Double)
    note: Mapped[str] = mapped_column(String(300), default='')


class IdentityNumber(Base):
    """A login number/account and its current identity. History lives in memberships."""
    __tablename__ = 'identity_numbers'
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    current_group_id: Mapped[int] = mapped_column(ForeignKey('identity_groups.id'), index=True)
    first_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[float] = mapped_column(Double)


class IdentityMembership(Base):
    """Append-only membership periods: [from_version, to_version)."""
    __tablename__ = 'identity_memberships'
    id: Mapped[int] = mapped_column(primary_key=True)
    number_id: Mapped[int] = mapped_column(ForeignKey('identity_numbers.id'), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('identity_groups.id'), index=True)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    operation_id: Mapped[int | None] = mapped_column(ForeignKey('identity_operations.id'), nullable=True)
    reason: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[float] = mapped_column(Double)


class IdentityOperation(Base):
    """Identity ledger entry. Version is the complete identity version produced by the operation."""
    __tablename__ = 'identity_operations'
    id: Mapped[int] = mapped_column(primary_key=True)
    operation_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    expected_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(150))
    reason: Mapped[str] = mapped_column(String(300), default='')
    numbers: Mapped[list] = mapped_column(JSON, default=list)
    affected: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), default='')
    created_at: Mapped[float] = mapped_column(Double)
