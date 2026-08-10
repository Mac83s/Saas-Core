import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class JsonFormatter(logging.Formatter):
    _fields = (
        "correlation_id",
        "duration_ms",
        "http_method",
        "http_path",
        "http_status",
        "security_event",
        "task_id",
        "task_name",
        "user_id",
        "organization_id",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        active_correlation_id = getattr(record, "correlation_id", None) or correlation_id.get()
        if active_correlation_id:
            payload["correlation_id"] = active_correlation_id
        for field in self._fields:
            value = getattr(record, field, None)
            if value is not None and field not in payload:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
