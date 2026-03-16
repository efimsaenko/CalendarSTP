# logger.py
"""
JSON one-line logger for this project.

Usage:
    from logger import get_logger
    logger = get_logger("DailyTG")

Each log line is a single JSON object with fields:
 - timestamp (YYYY-MM-DD HH:MM:SS,mmm)
 - level
 - module
 - message
 - optional: request_id, user_id, username, active_pipelines, traceback

This logger is safe to import from other scripts.
"""
import logging
import json
import os
import traceback
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

class JsonFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]

    def format(self, record):
        obj = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        # extras
        for fld in ("request_id", "user_id", "username", "active_pipelines"):
            val = getattr(record, fld, None)
            if val is not None:
                obj[fld] = val
        if record.exc_info:
            tb = "".join(traceback.format_exception(*record.exc_info))
            obj["traceback"] = tb.replace("\n", " ")
        return json.dumps(obj, ensure_ascii=False)

def get_logger(name: str = "app", when: str = "midnight", backup_count: int = 14):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    # If handlers already present, return same logger (avoid duplicated handlers)
    if logger.handlers:
        return logger

    log_file = os.path.join(LOG_DIR, f"{name}_{datetime.now().strftime('%Y-%m-%d')}.log")
    fh = TimedRotatingFileHandler(log_file, when=when, interval=1, backupCount=backup_count, encoding="utf-8")
    fh.setFormatter(JsonFormatter())

    ch = logging.StreamHandler()
    ch.setFormatter(JsonFormatter())

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False
    return logger