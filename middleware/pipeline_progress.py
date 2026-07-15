"""SQLite-backed pipeline progress tracker.

Uses the ``pipeline_status`` single-row table in ``catalogo.db`` so
progress survives page reloads and is visible across processes.

``get_progress()``  → dict with ``percentage``, ``status``, ``active``
``set_progress()``  → UPDATE the singleton row
``reset()``         → set all fields back to idle
"""

import logging

from .db import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def set_progress(
    *,
    active: bool | None = None,
    total: int | None = None,
    current: int | None = None,
    status: str | None = None,
    **_extra,
) -> None:
    """Update one or more fields of the ``pipeline_status`` singleton row.

    Accepts both ``current`` and ``processed`` as alias; ``total`` maps to
    ``total_productos``.  The ``phase`` kwarg is accepted for backward
    compatibility but ignored (not stored).
    """
    processed = _extra.get("processed", current)

    parts: list[str] = []
    params: list = []

    if active is not None:
        parts.append("activo = ?")
        params.append(1 if active else 0)
    if total is not None:
        parts.append("total_productos = ?")
        params.append(total)
    if processed is not None:
        parts.append("procesados = ?")
        params.append(processed)
    if status is not None:
        parts.append("estado = ?")
        params.append(status)

    if not parts:
        return

    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE pipeline_status SET {', '.join(parts)} WHERE id = 1",
            params,
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to update pipeline_status")
    finally:
        conn.close()


def get_progress() -> dict:
    """Read the ``pipeline_status`` row and return a JSON-friendly dict.

    Returns ``{"percentage": int, "status": str, "active": bool}``
    matching the shape consumed by the dashboard AJAX poller.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT total_productos, procesados, estado, activo "
            "FROM pipeline_status WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {"percentage": 0, "status": "", "active": False}

    total = row["total_productos"]
    procesados = row["procesados"]
    if total > 0:
        pct = round(procesados / total * 100)
        if pct > 100:
            pct = 100
    else:
        pct = 0 if row["activo"] else 100

    return {
        "percentage": pct,
        "status": row["estado"],
        "active": bool(row["activo"]),
    }


def reset() -> None:
    """Reset the ``pipeline_status`` row to idle."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE pipeline_status "
            "SET total_productos = 0, procesados = 0, estado = '', activo = 0 "
            "WHERE id = 1"
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to reset pipeline_status")
    finally:
        conn.close()
