"""
logger.py — Persists pipeline results to SQLite and writes debug logs to file.
Separates application logging (Python logging) from data logging (SQLite).
"""

import logging
import json
import os
from datetime import datetime
from sqlalchemy.orm import Session

import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import LOG_LEVEL

# ─── Ensure logs directory exists locally ───────────────────────────────────────
if os.getenv("VERCEL") != "1":
    os.makedirs("logs", exist_ok=True)

# ─── Python Application Logger ────────────────────────────────────────────────
def get_logger(name: str = "ip_identification") -> logging.Logger:
    """
    Returns a configured Python logger that writes to both:
      - Console (stdout)
      - logs/app.log (rotating file) (or /tmp/app.log on Vercel)
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured — avoid duplicate handlers

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    log_file_path = "/tmp/app.log" if os.getenv("VERCEL") == "1" else "logs/app.log"
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# ─── Database / Data Logger ────────────────────────────────────────────────────
class PipelineLogger:
    """
    Writes structured pipeline results to SQLite via SQLAlchemy.
    Also appends a JSON record to logs/pipeline_results.jsonl for easy debugging.
    """

    JSONL_LOG_PATH = "/tmp/pipeline_results.jsonl" if os.getenv("VERCEL") == "1" else "logs/pipeline_results.jsonl"

    def __init__(self):
        self.app_logger = get_logger("pipeline")

    def log_result(self, db: Session, result: dict) -> None:
        """
        Persist a completed pipeline result to:
          1. SQLite database (via ORM model)
          2. JSONL log file (for easy tail/grep inspection)

        Args:
            db: Active SQLAlchemy Session.
            result: The full pipeline result dict.
        """
        from database.models import IPLookupLog

        try:
            company_data = result.get("company", {})
            company_json = json.dumps(company_data) if company_data else None

            log_entry = IPLookupLog(
                ip=result.get("ip", ""),
                classification=result.get("classification", ""),
                org=result.get("org", ""),
                hostname=result.get("hostname", ""),
                domain=result.get("domain", ""),
                validated=result.get("validated", False),
                validation_reason=result.get("validation_reason", ""),
                company_json=company_json,
                status=result.get("status", ""),
                error_message=result.get("error", ""),
                created_at=datetime.utcnow(),
            )

            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)

            self.app_logger.info(
                f"Logged result for IP={result.get('ip')} | "
                f"status={result.get('status')} | domain={result.get('domain')}"
            )

        except Exception as e:
            db.rollback()
            self.app_logger.error(f"Failed to write DB log: {e}")

        # Always write JSONL regardless of DB success
        self._write_jsonl(result)

    def _write_jsonl(self, result: dict) -> None:
        """Append a single JSON record to the JSONL log file."""
        try:
            record = {**result, "logged_at": datetime.utcnow().isoformat()}
            with open(self.JSONL_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            self.app_logger.warning(f"Failed to write JSONL log: {e}")
