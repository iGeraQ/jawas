from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.shared.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()
