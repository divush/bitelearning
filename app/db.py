from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db():
    from app import models  # noqa: F401  (ensure models are registered on Base)
    from app.models import Base

    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()
