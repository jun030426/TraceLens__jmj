from alembic import context
from lerny.db import engine
from lerny.models import Base

with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
