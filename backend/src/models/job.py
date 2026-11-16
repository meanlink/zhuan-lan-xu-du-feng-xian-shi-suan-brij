from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Job(Base):
    __tablename__ = 'jobs'
    __table_args__ = (Index('uq_jobs_operation_key', 'operation_key', unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # Client-supplied key; a retried submit replays the existing experiment
    # instead of booking a second one. NULL keys do not collide.
    operation_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Identity basis frozen when the experiment is created. The worker only
    # ever reads this snapshot, never the live ledger.
    identity_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    identity_fingerprint: Mapped[str] = mapped_column(String(64), default='')
    identity_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
