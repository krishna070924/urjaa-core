"""Alembic environment.

The schema baseline is defined by Alembic as of URJ-004 (revision 0); new schema
changes belong in Alembic revisions. (Runtime cutover — routing docker-compose /
app startup through ``alembic upgrade head`` and retiring the ``create_all`` hooks —
is a tracked follow-up.) The connection URL is taken from the ``DATABASE_URL``
environment variable (same source as ``urjaa_core.core.database``); the ``sqlalchemy.url``
key in ``alembic.ini`` is intentionally left blank.

``target_metadata`` is wired to the ORM ``Base.metadata`` so future migrations can
use ``--autogenerate``. Importing the models is optional and guarded: plain
``upgrade``/``downgrade``/``stamp`` must work even if the app package cannot be
imported (e.g. missing optional deps), so a failed import simply disables
autogenerate rather than breaking migrations.
"""

import logging
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context

# Make the "urjaa_core" package importable regardless of the current working
# directory (alembic is normally invoked from backend/core_pkg/, but be
# defensive). parents[1] of this file is backend/core_pkg/, which is the
# directory containing the urjaa_core package.
CORE_PKG_DIR = Path(__file__).resolve().parents[1]
if str(CORE_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_PKG_DIR))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL (environment) is the single source of truth for the connection.
DB_URL = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if not DB_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Alembic reads the connection URL from the "
        "DATABASE_URL environment variable (see backend/alembic/env.py)."
    )

# Wire ORM metadata for future --autogenerate. Optional: never let this break a
# plain upgrade/downgrade/stamp.
target_metadata = None
try:
    os.environ.setdefault("DATABASE_URL", DB_URL)
    import urjaa_core.models  # noqa: F401,E402  (import for side effect: register tables)
    from urjaa_core.models.base import Base  # noqa: E402

    target_metadata = Base.metadata
except Exception as exc:  # autogenerate is a convenience; upgrade/downgrade/stamp don't need it
    # Make the disabled state visible: otherwise a later `alembic revision
    # --autogenerate` would silently emit an EMPTY migration.
    logging.getLogger("alembic.env").warning(
        "Could not import app models; --autogenerate is DISABLED for this run (%s: %s)",
        type(exc).__name__,
        exc,
    )
    target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI needed)."""
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    connectable = create_engine(DB_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
