from alembic import context

from lones_vdl.db import models  # noqa: F401  (register tables on Base.metadata)
from lones_vdl.db.base import Base

config = context.config
engine = config.attributes.get("engine")
if engine is None:
    raise RuntimeError("run migrations via lones_vdl.db.migrate (engine not provided)")

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things in place
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
