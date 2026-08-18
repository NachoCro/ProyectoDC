#!/usr/bin/env python3
"""Crear usuarios de la Admin UI (login).

Uso:
    python scripts/create_user.py --usuario admin --clave "clave-segura" [--rol admin]
    python scripts/create_user.py --usuario juan --clave "otra-clave" --rol operador
    python scripts/create_user.py --usuario lector --clave "clave" --rol lectura

Roles: admin (todo), operador (aprueba/procesa), lectura (solo ver).
"""

import argparse
import sys

sys.path.insert(0, ".")

from middleware.users import ROLES, create_user, verify_user  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear un usuario de la Admin UI")
    parser.add_argument("--usuario", required=True)
    parser.add_argument("--clave", required=True)
    parser.add_argument("--rol", default="operador", choices=ROLES)
    args = parser.parse_args()

    ok, err = create_user(args.usuario, args.clave, args.rol)
    if not ok:
        print(f"ERROR: {err}")
        sys.exit(1)
    print(f"[ok] Usuario '{args.usuario}' creado con rol '{args.rol}'.")
    # sanity: verificar que el login funcione
    if verify_user(args.usuario, args.clave):
        print("[ok] Verificación de credenciales exitosa.")
    else:
        print("ERROR: la verificación falló (revisá el hash).")
        sys.exit(1)


if __name__ == "__main__":
    main()
