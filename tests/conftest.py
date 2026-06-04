import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.shared.models import Base

TEST_DB_URL = "postgresql://jawas:jawas@localhost:5432/jawas_test"


@pytest.fixture(scope="session")
def engine():
    e = create_engine(TEST_DB_URL)
    Base.metadata.create_all(e)
    yield e
    Base.metadata.drop_all(e)


@pytest.fixture
def db_session(engine):
    session = Session(engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
