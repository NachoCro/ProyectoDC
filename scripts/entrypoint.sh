#!/bin/sh
# Entrypoint del contenedor por cliente: Admin UI (waitress) + daemon.
#
# Variables de entorno (desde clients/<slug>/.env):
#   PRESTASHOP_API_URL / PRESTASHOP_API_KEY   — obligatorias
#   DAEMON_ARGS                               — args extra del daemon (ej: "--check-inactive")
set -e

if [ -z "$PRESTASHOP_API_URL" ] || [ -z "$PRESTASHOP_API_KEY" ]; then
    echo "[entrypoint] ERROR: faltan PRESTASHOP_API_URL / PRESTASHOP_API_KEY" >&2
    exit 1
fi

# Admin inicial desde entorno (opcional): ADMIN_USER / ADMIN_PASS
if [ -n "${ADMIN_USER:-}" ] && [ -n "${ADMIN_PASS:-}" ]; then
    echo "[entrypoint] Creando usuario administrador desde entorno..."
    python -c "from middleware.users import ensure_admin_from_env; ensure_admin_from_env()"
fi

echo "[entrypoint] Admin UI en 0.0.0.0:5000 (waitress)..."
python -m waitress --listen=0.0.0.0:5000 --threads=4 admin_ui.app:app &
ADMIN_PID=$!

echo "[entrypoint] Daemon (args: ${DAEMON_ARGS:-ninguno})..."
# sin comillas: DAEMON_ARGS se corta por palabras (--check-inactive, --interval N)
python daemon.py $DAEMON_ARGS &
DAEMON_PID=$!

_term() {
    echo "[entrypoint] Señal recibida, apagando..."
    kill -TERM "$DAEMON_PID" 2>/dev/null || true
    kill -TERM "$ADMIN_PID" 2>/dev/null || true
}
trap _term INT TERM

# El daemon marca el ciclo de vida del contenedor
wait "$DAEMON_PID"
STATUS=$?
kill -TERM "$ADMIN_PID" 2>/dev/null || true
exit "$STATUS"
