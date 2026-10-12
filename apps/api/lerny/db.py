from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lerny.config import settings


@lru_cache
def engine():
    url = settings().database_url
    if not url:
        raise RuntimeError("Database not configured")
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def db() -> Generator[Session, None, None]:
    with Session(engine()) as session:
        yield session
