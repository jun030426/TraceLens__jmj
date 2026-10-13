import pytest
from lerny.db import db, engine
from lerny.main import create_app
from lerny.models import Base, User
from lerny.security import hasher
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def app_db():
    test_engine = create_engine(engine().url.set(database="lerny_test"))
    assert test_engine.url.database == "lerny_test"
    assert test_engine.url.host in {"127.0.0.1", "localhost", "::1"}, "Tests must never reset a cloud database"
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    app = create_app()

    def override():
        yield session

    app.dependency_overrides[db] = override
    for name, role in [
        ("teacher1", "teacher"),
        ("teacher2", "teacher"),
        ("student1", "student"),
        ("student2", "student"),
        ("operator1", "operator"),
    ]:
        session.add(
            User(
                login_id=name,
                display_name=name,
                role=role,
                password_hash=hasher.hash("Test-only-password-123"),
            )
        )
    session.commit()
    yield app, session
    session.close()
    transaction.rollback()
    connection.close()
    test_engine.dispose()
