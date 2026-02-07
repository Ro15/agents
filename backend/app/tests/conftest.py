import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import Base


@pytest.fixture(scope="session")
def engine():
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("No TEST_DATABASE_URL or DATABASE_URL set")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="function")
def db_session(engine):
    # clean tables between tests
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
