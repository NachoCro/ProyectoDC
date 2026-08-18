#!/usr/bin/env bash
# Instalador / ejecutor interactivo del Middleware PrestaShop.
#
# Uso:
#   ./instalar.sh            # configura (si falta) y arranca solo la Admin UI (sin daemon)
#   ./instalar.sh --solo-config   # solo pregunta y escribe el .env, sin arrancar
#
# En la primera ejecución crea el entorno virtual e instala dependencias.
# Pregunta únicamente lo que hace falta; los valores ya guardados se reutilizan.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SOLO_CONFIG=0
for arg in "$@"; do
    case "$arg" in
        --solo-config) SOLO_CONFIG=1 ;;
        *) echo "Argumento desconocido: $arg" >&2; exit 1 ;;
    esac
done

# ── banner ──────────────────────────────────────────────────────────────
echo
echo "  Middleware PrestaShop — enriquecimiento de productos"
echo "  ===================================================="
echo

# ── 1. Entorno virtual (solo la primera vez) ────────────────────────────
if [ ! -x venv/bin/python ]; then
    echo "[1/4] Primera ejecución: creando entorno virtual e instalando"
    echo "      dependencias (descarga ~3GB la primera vez, tarda unos minutos) ..."
    python3 -m venv venv
    venv/bin/pip install --upgrade pip >/dev/null
    venv/bin/pip install -r requirements.txt
else
    echo "[1/4] Entorno virtual listo."
fi

# ── 2. Cargar configuración guardada ────────────────────────────────────
ENV_PREVIO=0
if [ -f .env ]; then
    ENV_PREVIO=1
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi
API_URL="${PRESTASHOP_API_URL:-}"
API_KEY="${PRESTASHOP_API_KEY:-}"
ADMIN_PORT="${ADMIN_PORT:-5000}"
CHECK_INACTIVE="${CHECK_INACTIVE:-0}"
ENRICH_ON_START="${ENRICH_ON_START:-0}"

# ── 3. Preguntar lo necesario ────────────────────────────────────────────
echo "[2/4] Configuración de la tienda PrestaShop"
echo

if [ -n "$API_URL" ]; then
    read -rp "  URL de la API de Prestashop [$API_URL]: " input
    API_URL="${input:-$API_URL}"
else
    read -rp "  URL de la API de Prestashop (ej: http://localhost:8080/api): " API_URL
fi

if [ -n "$API_KEY" ]; then
    read -rp "  API key del webservice (dejar vacío para conservar la actual): " input
    if [ -n "$input" ]; then API_KEY="$input"; fi
else
    read -rp "  API key del webservice: " API_KEY
fi

if [ -z "$API_URL" ] || [ -z "$API_KEY" ]; then
    echo "  ERROR: URL y API key son obligatorias." >&2
    exit 1
fi

# ── probar conexión ─────────────────────────────────────────────────────
if command -v curl >/dev/null 2>&1; then
    code="$(curl -s -o /dev/null -m 15 -u "$API_KEY:" -w "%{http_code}" "$API_URL/" || true)"
    case "$code" in
        200) echo "  OK: conexión con PrestaShop exitosa." ;;
        401) echo "  AVISO: PrestaShop rechazó la API key (401). Revisala." ;;
        *)   echo "  AVISO: no se pudo verificar la conexión (HTTP ${code:-fallo})." ;;
    esac
else
    echo "  (curl no está disponible; no se probó la conexión)"
fi

read -rp "  Puerto de la Admin UI [$ADMIN_PORT]: " input
ADMIN_PORT="${input:-$ADMIN_PORT}"

if [ "$ENV_PREVIO" = "0" ]; then
    read -rp "  ¿Validar productos inactivos con stock y marcarlos para activar? (s/N): " yn
    case "$yn" in
        s|S|si|sí|SI) CHECK_INACTIVE=1 ;;
        *)            CHECK_INACTIVE=0 ;;
    esac
fi

read -rp "  ¿Ejecutar extracción + enriquecimiento al arrancar el daemon? (s/N): " yn
case "$yn" in
    s|S|si|sí|SI) ENRICH_ON_START=1 ;;
    *)            ENRICH_ON_START=0 ;;
esac

# ── guardar configuración ───────────────────────────────────────────────
cat > .env <<EOF
PRESTASHOP_API_URL=$API_URL
PRESTASHOP_API_KEY=$API_KEY
ADMIN_PORT=$ADMIN_PORT
CHECK_INACTIVE=$CHECK_INACTIVE
ENRICH_ON_START=$ENRICH_ON_START
EOF
echo "  Configuración guardada en .env"

# ── 4. Arranque ─────────────────────────────────────────────────────────
echo "[3/4] Preparando datos locales ..."
"$ROOT/venv/bin/python" -c "from middleware.db import _ensure_schema; _ensure_schema()"

# usuario administrador (solo la primera vez)
if [ "$ENV_PREVIO" = "0" ]; then
    read -rp "  ¿Crear el usuario administrador de la Admin UI ahora? (s/N): " yn
    case "$yn" in
        s|S|si|sí|SI)
            read -rp "  Usuario: " ADMIN_USER
            read -rsp "  Contraseña: " ADMIN_PASS
            echo
            "$ROOT/venv/bin/python" scripts/create_user.py \
                --usuario "$ADMIN_USER" --clave "$ADMIN_PASS" --rol admin
            ;;
        *)
            echo "  (Sin usuario: la primera vez que entres al panel lo podés crear en la pantalla de inicio)"
            ;;
    esac
fi

if [ "$ENV_PREVIO" = "0" ]; then
    read -rp "  ¿Sincronizar categorías locales con PrestaShop ahora? (s/N): " yn
    case "$yn" in
        s|S|si|sí|SI)
            echo "[4/4] Sincronizando categorías ..."
            "$ROOT/venv/bin/python" scripts/sync_categories.py
            ;;
        *)
            echo "[4/4] Categorías no sincronizadas (podés hacerlo después con:"
            echo "      venv/bin/python scripts/sync_categories.py)"
            ;;
    esac
else
    echo "[4/4] Categorías ya configuradas (re-sincronizá con:"
    echo "      venv/bin/python scripts/sync_categories.py)"
fi

if [ "$SOLO_CONFIG" = "1" ]; then
    echo
    echo "  Configuración lista. Para arrancar:  ./instalar.sh"
    exit 0
fi

# ── helpers ────────────────────────────────────────────────────────────
# ¿Algo escucha en el puerto $1?
port_in_use() {
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$1\$"
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; }
        return 1
    fi
}

# ── lanzar Admin UI (sin daemon) ───────────────────────────────────────
DAEMON_ARGS=""
if [ "$CHECK_INACTIVE" = "1" ]; then
    DAEMON_ARGS="--check-inactive"
fi
if [ "$ENRICH_ON_START" = "0" ]; then
    DAEMON_ARGS="${DAEMON_ARGS} --no-initial-pipeline"
fi

echo
echo "  Admin UI:  http://localhost:$ADMIN_PORT"
echo "  Daemon:    NO se inicia automáticamente. Para arrancarlo:"
echo "             venv/bin/python daemon.py${DAEMON_ARGS:+ }${DAEMON_ARGS}"
echo "  (Ctrl+C para detener)"
echo

ADMIN_PID=""

if port_in_use "$ADMIN_PORT"; then
    echo "  AVISO: la Admin UI ya está corriendo en el puerto $ADMIN_PORT — no se levanta otra."
else
    "$ROOT/venv/bin/python" -m waitress --listen="0.0.0.0:$ADMIN_PORT" --threads=4 admin_ui.app:app &
    ADMIN_PID=$!
fi

if [ -z "$ADMIN_PID" ]; then
    echo
    echo "  La Admin UI ya estaba corriendo. Nada para iniciar."
    echo "  Admin UI:  http://localhost:$ADMIN_PORT"
    exit 0
fi

_term() {
    echo
    echo "  Deteniendo ..."
    if [ -n "$ADMIN_PID" ]; then kill -TERM "$ADMIN_PID" 2>/dev/null || true; fi
}
trap _term INT TERM

STATUS=0
wait "$ADMIN_PID" 2>/dev/null || STATUS=$?
exit "$STATUS"
