from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# Columns added after the initial snapshot. Kept explicit so an existing
# deployment upgrades in place instead of requiring a rebuild.
_ADDED_COLUMNS = {
    'jobs': {
        'identity_version': 'INTEGER NOT NULL DEFAULT 0',
        'identity_fingerprint': 'VARCHAR(64) NOT NULL DEFAULT \'\'',
        'identity_snapshot': 'JSON NULL',
        'operation_key': 'VARCHAR(160) NULL',
    },
}


def _add_missing_indexes():
    inspector = inspect(engine)
    if 'jobs' not in set(inspector.get_table_names()):
        return
    with engine.begin() as connection:
        # create_all already built the index on fresh databases; this covers
        # databases upgraded in place.
        try:
            connection.execute(text(
                'CREATE UNIQUE INDEX uq_jobs_operation_key ON jobs (operation_key)'))
        except Exception:
            pass


def _add_missing_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def _seed_identity_state():
    """The ledger starts at version 0. Existing datasets get an initial
    identity assignment so legacy jobs remain explainable."""
    from sqlalchemy.orm import Session as RawSession
    from src.models import IdentityState
    with RawSession(engine) as db:
        if db.get(IdentityState, 1) is None:
            db.add(IdentityState(id=1, version=0, updated_at=0.0))
            db.commit()


def migrate():
    Base.metadata.create_all(engine)
    _add_missing_columns()
    _add_missing_indexes()
    _seed_identity_state()


if __name__ == '__main__':
    migrate()
