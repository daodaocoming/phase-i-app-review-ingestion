from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("app_name", "app_id", "page", "status", "elapsed_seconds", "error"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", log_path: str | Path = "logs/ingestion.log") -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    root.addHandler(console)

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)
