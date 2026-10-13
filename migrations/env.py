from alembic import context
from lerny.db import engine
from lerny.models import Base

if context.is_offline_mode():
    context.configure(url="postgresql+psycopg://", target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
