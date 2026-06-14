import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.shared.models import Base


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def db_session(engine):
    session = Session(engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
