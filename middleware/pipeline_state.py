"""In-memory pipeline state tracker for real-time dashboard updates."""

import threading
import time
from collections import deque
from typing import Any

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "current": 0,
    "total": 0,
    "pid": None,
    "product_name": "",
    "logs": deque(maxlen=50),
    "started_at": None,
    "finished_at": None,
}


def start(total: int) -> None:
    """Mark pipeline as started."""
    with _lock:
        _state["running"] = True
        _state["current"] = 0
        _state["total"] = total
        _state["pid"] = None
        _state["product_name"] = ""
        _state["logs"].clear()
        _state["started_at"] = time.time()
        _state["finished_at"] = None
        _state["logs"].append({"t": time.time(), "msg": f"Iniciando pipeline — {total} productos"})


def update(current: int, pid=None, product_name: str = "") -> None:
    """Update current product being processed."""
    with _lock:
        _state["current"] = current
        _state["pid"] = pid
        _state["product_name"] = product_name[:80]
        if pid:
            msg = f"[{current}/{_state['total']}] id={pid} {product_name[:60]}"
            _state["logs"].append({"t": time.time(), "msg": msg})


def add_log(msg: str) -> None:
    """Append a log line to the terminal output."""
    with _lock:
        _state["logs"].append({"t": time.time(), "msg": msg[:200]})


def finish() -> None:
    """Mark pipeline as finished."""
    with _lock:
        _state["running"] = False
        _state["finished_at"] = time.time()
        n = _state["current"]
        _state["logs"].append({"t": time.time(), "msg": f"Pipeline completado — {n} productos procesados"})


def get_state() -> dict:
    """Return a snapshot of the current state."""
    with _lock:
        logs = list(_state["logs"])
        return {
            "running": _state["running"],
            "current": _state["current"],
            "total": _state["total"],
            "pid": _state["pid"],
            "product_name": _state["product_name"],
            "logs": logs,
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
        }
