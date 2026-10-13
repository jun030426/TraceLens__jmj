from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from lerny.config import settings


@lru_cache
def engine():
    url = settings().database_url
    if not url:
        raise RuntimeError("Database not configured")
    if settings().database_pool_mode == "transaction":
        return create_engine(url, poolclass=NullPool, pool_pre_ping=True,
                             connect_args={"prepare_threshold": None, "connect_timeout": 10})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         connect_args={"connect_timeout": 10})


def db() -> Generator[Session, None, None]:
    with Session(engine()) as session:
        yield session
