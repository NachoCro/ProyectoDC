"""In-memory pipeline state tracker for real-time dashboard updates.

También espeja los logs del pipeline y todo el output INFO+ del logger a
``daemon_state`` (SQLite) para que la consola del dashboard los muestre —
funciona incluso entre procesos (daemon subproceso → admin UI).
"""

import logging
import re
import threading
import time
from collections import deque
from typing import Any

_lock = threading.Lock()

#: Ruido HTTP del cliente PrestaShop (cada GET/PUT se loguea a INFO) — no
#: debe espejarse al panel del dashboard.
_PS_REQUEST_RE = re.compile(r"^PS (GET|POST|PUT|PATCH|DELETE|HEAD) ")

#: Guarda si la persistencia a daemon_state ya se habilitó (evita reintentos).
_persist_enabled: bool | None = None

_state: dict[str, Any] = {
    "running": False,
    "current": 0,
    "total": 0,
    "pid": None,
    "product_name": "",
    "phase": "",
    "logs": deque(maxlen=50),
    "started_at": None,
    "finished_at": None,
}


def _persist_progress() -> None:
    """Espejar el progreso del pipeline a ``daemon_state`` (SQLite) para que
    la barra de progreso del dashboard funcione incluso cuando el pipeline
    corre en otro proceso (daemon subproceso → admin UI)."""
    try:
        from . import daemon_state
        daemon_state.set_pipeline_progress({
            "running": _state["running"],
            "phase": _state["phase"],
            "current": _state["current"],
            "total": _state["total"],
            "pid": _state["pid"],
            "product_name": _state["product_name"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
        })
    except Exception:
        pass


def _persist_to_daemon_logs(msg: str) -> None:
    """Espejar el log en ``daemon_state`` (SQLite) para que la consola del
    dashboard lo muestre — funciona entre procesos (daemon subproceso → admin)."""
    global _persist_enabled
    if _persist_enabled is False:
        return
    if _persist_enabled is None:
        try:
            from . import daemon_state  # lazy para evitar ciclos de import
            daemon_state  # noqa: B018 — solo verifica que importe
            _persist_enabled = True
        except Exception:
            _persist_enabled = False
            return
    try:
        from . import daemon_state
        daemon_state.log(msg)
    except Exception:
        pass


class _DashboardLogHandler(logging.Handler):
    """Handler que espeja cada registro INFO+ del logger a la consola del
    dashboard (via ``daemon_state`` / SQLite)."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "werkzeug":
            return
        if record.levelno < logging.WARNING:
            msg = record.getMessage()
            if _PS_REQUEST_RE.match(msg):
                return
        try:
            msg = self.format(record)
        except Exception:
            return
        _persist_to_daemon_logs(msg)


_DASHBOARD_HANDLER_INSTALLED = False


def install_dashboard_log_handler() -> None:
    """Instalar (una sola vez por proceso) el espejo del logger al dashboard."""
    global _DASHBOARD_HANDLER_INSTALLED
    if _DASHBOARD_HANDLER_INSTALLED:
        return
    _DASHBOARD_HANDLER_INSTALLED = True
    try:
        handler = _DashboardLogHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logging.getLogger().addHandler(handler)
    except Exception:
        _DASHBOARD_HANDLER_INSTALLED = False


install_dashboard_log_handler()


def start(total: int, phase: str = "Enriqueciendo productos") -> None:
    """Mark pipeline as started."""
    msg = f"Iniciando pipeline — {total} productos"
    with _lock:
        _state["running"] = True
        _state["current"] = 0
        _state["total"] = total
        _state["pid"] = None
        _state["product_name"] = ""
        _state["phase"] = phase
        _state["logs"].clear()
        _state["started_at"] = time.time()
        _state["finished_at"] = None
        _state["logs"].append({"t": time.time(), "msg": msg})
    _persist_progress()
    _persist_to_daemon_logs(msg)


def set_phase(phase: str) -> None:
    """Actualizar la fase en curso (extracción / enriquecimiento / ...)."""
    with _lock:
        _state["phase"] = phase
    _persist_progress()


def update(current: int, pid=None, product_name: str = "") -> None:
    """Update current product being processed."""
    msg = f"[{current}/{_state['total']}] id={pid} {product_name[:60]}" if pid else ""
    with _lock:
        _state["current"] = current
        _state["pid"] = pid
        _state["product_name"] = product_name[:80]
        if pid:
            _state["logs"].append({"t": time.time(), "msg": msg})
    _persist_progress()
    if msg:
        _persist_to_daemon_logs(msg)


def add_log(msg: str) -> None:
    """Append a log line to the terminal output."""
    with _lock:
        _state["logs"].append({"t": time.time(), "msg": msg[:200]})
    _persist_to_daemon_logs(msg)


def finish() -> None:
    """Mark pipeline as finished."""
    n = _state["current"]
    msg = f"Pipeline completado — {n} productos procesados"
    with _lock:
        _state["running"] = False
        _state["finished_at"] = time.time()
        _state["logs"].append({"t": time.time(), "msg": msg})
    _persist_progress()
    _persist_to_daemon_logs(msg)


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
            "phase": _state["phase"],
            "logs": logs,
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
        }
