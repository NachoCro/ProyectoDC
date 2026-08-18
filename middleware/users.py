"""Gestión de usuarios de la Admin UI (login + roles).

Roles:
- ``admin``: acceso completo (config, marcas, daemon, usuarios).
- ``operador``: aprueba/rechaza/re-sincroniza productos.
- ``lectura``: solo lectura (no puede enviar POST).

Las contraseñas se guardan hasheadas (werkzeug PBKDF2); nunca en claro.
"""

import logging

from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_connection

logger = logging.getLogger(__name__)

ROLES = ("admin", "operador", "lectura")
_WRITE_DENIED_MSG = "Tu usuario tiene permiso de solo lectura."


def _normalize(usuario: str) -> str:
    return usuario.strip().lower()


def create_user(usuario: str, clave: str, rol: str = "operador") -> tuple[bool, str]:
    """Crear un usuario. Devuelve ``(ok, error|None)``."""
    usuario = _normalize(usuario)
    if not usuario or not clave:
        return False, "El usuario y la clave no pueden estar vacíos."
    if rol not in ROLES:
        return False, f"Rol inválido: {rol} (válidos: {', '.join(ROLES)})."
    conn = get_connection()
    try:
        exists = conn.execute(
            "SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)
        ).fetchone()
        if exists:
            return False, "El usuario ya existe."
        conn.execute(
            "INSERT INTO usuarios (usuario, password_hash, rol) VALUES (?, ?, ?)",
            (usuario, generate_password_hash(clave), rol),
        )
        conn.commit()
        return True, None
    finally:
        conn.close()


def verify_user(usuario: str, clave: str) -> dict | None:
    """Verificar credenciales. Devuelve ``{'usuario', 'rol'}`` o None."""
    usuario = _normalize(usuario)
    if not usuario or not clave:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT usuario, password_hash, rol FROM usuarios WHERE usuario = ?",
            (usuario,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    if not check_password_hash(row["password_hash"], clave):
        return None
    return {"usuario": row["usuario"], "rol": row["rol"]}


def count_users() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"]
    finally:
        conn.close()


def ensure_admin_from_env() -> None:
    """Crear el admin inicial desde ADMIN_USER / ADMIN_PASS (si no hay usuarios).

    Se usa en el arranque (instalador, contenedor) para que el primer login
    sea posible sin intervención.
    """
    import os

    if count_users() > 0:
        return
    user = os.getenv("ADMIN_USER", "").strip()
    pass_ = os.getenv("ADMIN_PASS", "").strip()
    if not user or not pass_:
        return
    ok, err = create_user(user, pass_, "admin")
    if ok:
        logger.info("Admin inicial creado desde entorno: %s", user)
    else:
        logger.warning("No se pudo crear el admin inicial: %s", err)
