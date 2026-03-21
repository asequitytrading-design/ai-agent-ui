"""Query logger node (stub for Sprint 4).

Full implementation in Sprint 5 (S5-4) once the
``stocks.query_log`` Iceberg table exists.
"""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def log_query(state: dict) -> dict:
    """Log query metadata — stub, no-op for now."""
    _logger.debug(
        "log_query stub: intent=%s agent=%s",
        state.get("intent", ""),
        state.get("current_agent", ""),
    )
    return {}
