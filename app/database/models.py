"""
models.py — SQLAlchemy ORM models for IP identification logs.
Uses SQLite for simple, file-based persistence (MVP-appropriate).
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import sys
import os

# Allow importing config from parent package
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import DATABASE_URL

# ─── SQLAlchemy Setup ────────────────────────────────────────────────────────
Base = declarative_base()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ─── ORM Model ───────────────────────────────────────────────────────────────
class IPLookupLog(Base):
    """
    Stores one row per IP identification request.
    Captures the full pipeline result for debugging and analysis.
    """
    __tablename__ = "ip_lookup_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Input
    ip = Column(String(45), nullable=False, index=True)

    # Classification
    classification = Column(String(50), nullable=True)   # corporate/isp/hosting/vpn/unknown
    org = Column(String(255), nullable=True)              # Organization from IPinfo

    # Reverse DNS
    hostname = Column(String(255), nullable=True)

    # Domain extraction
    domain = Column(String(255), nullable=True)

    # Validation
    validated = Column(Boolean, default=False)
    validation_reason = Column(String(255), nullable=True)

    # Enrichment result (stored as JSON string)
    company_json = Column(Text, nullable=True)

    # Final pipeline status
    status = Column(String(50), nullable=True)  # identified/rejected/invalid_domain/error

    # Meta
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Create all tables if they don't exist. Called at app startup."""
    # Ensure the logs directory exists locally
    is_vercel = bool(os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV") or os.getenv("VERCEL_URL") or os.getenv("AWS_EXECUTION_ENV"))
    if not is_vercel:
        os.makedirs("logs", exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
