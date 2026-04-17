from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from core.config import settings


DATABASE_URL = settings.DATABASE_URL

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")


# SQLite needs special connect_args, others don’t
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}


engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()