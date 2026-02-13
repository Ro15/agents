"""
Shared database engine, session factory, and declarative base.
Imported by models and route modules to avoid circular dependencies.

NOTE: load_dotenv() must be called BEFORE this module is imported
(done in main.py at startup).
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
