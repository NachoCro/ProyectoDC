"""Daemon state tracker backed by SQLite (config table).

Both the daemon process and the Flask admin UI can read/write
the same state through the shared database.
"""

import json
import time

from .db import get_connection

_KEYS = [
    "daemon_running",
    "daemon_pid",
    "daemon_phase",
    "daemon_cycle",
    "daemon_interval",
    "daemon_dry_run",
    "daemon_check_inactive",
    "daemon_started_at",
    "daemon_last_check_at",
    "daemon_last_result",
    "daemon_logs",
    "daemon_stop",
    "pipeline_progress",
]

_DEFAULTS = {
    "daemon_running": "0",
    "daemon_pid": "",
    "daemon_phase": "",
    "daemon_cycle": "0",
    "daemon_interval": "300",
    "daemon_dry_run": "0",
    "daemon_check_inactive": "0",
    "daemon_started_at": "",
    "daemon_last_check_at": "",
    "daemon_last_result": "",
    "daemon_logs": "[]",
    "daemon_stop": "0",
    "pipeline_progress": "",
}


def _set(key: str, value: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def _get(key: str) -> str:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT valor FROM config WHERE clave = ?", (key,)
        ).fetchone()
        return row["valor"] if row else _DEFAULTS.get(key, "")
    finally:
        conn.close()


def _append_log(msg: str) -> None:
    """Append a log entry to the stored logs (max 100)."""
    raw = _get("daemon_logs")
    try:
        logs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logs = []
    logs.append({"t": time.time(), "msg": msg[:200]})
    if len(logs) > 100:
        logs = logs[-100:]
    _set("daemon_logs", json.dumps(logs))


# ── public API (called by daemon.py) ──────────────────────────────────

def start(interval: int, dry_run: bool, check_inactive: bool = False) -> None:
    """Mark daemon as started."""
    _set("daemon_running", "1")
    _set("daemon_phase", "startup")
    _set("daemon_cycle", "0")
    _set("daemon_interval", str(interval))
    _set("daemon_dry_run", "1" if dry_run else "0")
    _set("daemon_check_inactive", "1" if check_inactive else "0")
    _set("daemon_started_at", str(time.time()))
    _set("daemon_last_check_at", "")
    _set("daemon_last_result", "")
    _set("daemon_logs", "[]")
    _set("daemon_stop", "0")
    _append_log(
        f"Daemon iniciado — intervalo {interval}s"
        + (" — validando inactivos" if check_inactive else "")
    )


def request_stop() -> None:
    """Ask the daemon to stop gracefully (portable, SQLite-based).

    Works on any OS: the daemon polls this flag each second during its
    idle wait and exits without needing POSIX signals.
    """
    _set("daemon_stop", "1")
    _append_log("Solicitud de detención recibida")


def stop_requested() -> bool:
    """Whether a stop has been requested (polled by the daemon loop)."""
    return _get("daemon_stop") == "1"


def set_pid(pid: int) -> None:
    _set("daemon_pid", str(pid))


def set_phase(phase: str) -> None:
    _set("daemon_phase", phase)
    _append_log(f"Fase: {phase}")


def log(msg: str) -> None:
    _append_log(msg)


def set_pipeline_progress(progress: dict) -> None:
    """Persist pipeline progress (run-once / daemon pipeline) as JSON.

    Escrito por ``pipeline_state`` (mismo proceso o daemon subproceso) y
    leído por el dashboard vía ``get_state()`` — funciona entre procesos.
    """
    _set("pipeline_progress", json.dumps(progress))


def cycle_done(result: dict) -> None:
    """Mark a verification cycle as complete."""
    cycle = int(_get("daemon_cycle") or "0") + 1
    _set("daemon_cycle", str(cycle))
    _set("daemon_phase", "idle")
    _set("daemon_last_check_at", str(time.time()))
    _set("daemon_last_result", json.dumps(result))
    _append_log(
        f"Ciclo {cycle}: {result['total']} productos, "
        f"{result['complete']} completos, {result['incomplete']} incompletos, "
        f"{result['completed']} auto-completados"
    )


def stop() -> None:
    """Mark daemon as stopped."""
    _set("daemon_running", "0")
    _set("daemon_phase", "")
    _set("daemon_pid", "")
    _set("daemon_stop", "0")
    _append_log("Daemon detenido")


# ── read API (called by Flask admin UI) ───────────────────────────────

def get_state() -> dict:
    """Return a snapshot of the current daemon state."""
    running = _get("daemon_running") == "1"
    pid_raw = _get("daemon_pid")
    cycle_raw = _get("daemon_cycle")
    interval_raw = _get("daemon_interval")
    started_raw = _get("daemon_started_at")
    last_check_raw = _get("daemon_last_check_at")
    last_result_raw = _get("daemon_last_result")

    logs_raw = _get("daemon_logs")
    try:
        logs = json.loads(logs_raw)
    except (json.JSONDecodeError, TypeError):
        logs = []

    pipeline_raw = _get("pipeline_progress")
    pipeline = None
    if pipeline_raw:
        try:
            pipeline = json.loads(pipeline_raw)
        except (json.JSONDecodeError, TypeError):
            pipeline = None

    last_result = None
    if last_result_raw:
        try:
            last_result = json.loads(last_result_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "running": running,
        "phase": _get("daemon_phase"),
        "cycle": int(cycle_raw) if cycle_raw else 0,
        "interval": int(interval_raw) if interval_raw else 300,
        "dry_run": _get("daemon_dry_run") == "1",
        "check_inactive": _get("daemon_check_inactive") == "1",
        "logs": logs,
        "started_at": float(started_raw) if started_raw else None,
        "last_check_at": float(last_check_raw) if last_check_raw else None,
        "last_result": last_result,
        "pid": int(pid_raw) if pid_raw else None,
        "pipeline": pipeline,
    }
