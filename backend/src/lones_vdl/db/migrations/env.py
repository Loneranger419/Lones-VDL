from alembic import context

from lones_vdl.db import models  # noqa: F401  (register tables on Base.metadata)
from lones_vdl.db.base import Base

config = context.config
engine = config.attributes.get("engine")
if engine is None:
    raise RuntimeError("run migrations via lones_vdl.db.migrate (engine not provided)")

with engine.connect() as connection:
    # Batch migrations rebuild a table by copy + DROP + rename. With foreign keys on, the DROP
    # fires ON DELETE actions on referencing rows (e.g. it nulls every videos.channel_pk).
    # The pragma is ignored inside a transaction, so set it before migrating begins.
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.commit()
    try:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=True,  # SQLite cannot ALTER most things in place
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
            broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(f"migration left broken foreign keys: {broken[:5]}")
    finally:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
