#!/usr/bin/env python3
"""Aprovisionar un cliente nuevo para el despliegue por contenedor.

Crea ``clients/<slug>/.env`` (credenciales PrestaShop + tuning), genera el
``catalogo.db`` con el esquema local, y opcionalmente sincroniza categorías
contra el PrestaShop del cliente.

Uso:
    python scripts/new_client.py --slug tienda1 --host-port 5001 \
        --api-url http://host.docker.internal:8080/api \
        --api-key 1234567890abcdef \
        [--interval 300] [--batch-size 10] [--api-sleep 2] \
        [--check-inactive] [--sync-categories] [--test-connection]

Luego:
    docker compose --env-file clients/tienda1/.env \
        -f docker-compose.client.yml up -d
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "clients"

_TUNING_DEFAULTS = {
    "BATCH_SIZE": "10",
    "API_SLEEP": "2",
    "DAEMON_INTERVAL": "300",
    "PS_COMPAT_81": "1",
    "PS_MPN_FIELD": "mpn",
    "PS_CREATE_FEATURES": "0",
}


def slugify(name: str) -> str:
    s = name.strip().lower()
    for ch, repl in (
        ("ñ", "n"),
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        (" ", "-"),
        ("_", "-"),
    ):
        s = s.replace(ch, repl)
    s = re.sub(r"[^a-z0-9-]", "", s)
    return re.sub(r"-+", "-", s).strip("-")


def build_client_env(args: argparse.Namespace) -> dict[str, str]:
    env = {
        "CLIENT": args.slug,
        "HOST_PORT": str(args.host_port),
        "PRESTASHOP_API_URL": args.api_url,
        "PRESTASHOP_API_KEY": args.api_key,
        # ruta DENTRO del contenedor (montada desde clients/<slug>/)
        "DB_PATH": "/data/catalogo.db",
    }
    for key, default in _TUNING_DEFAULTS.items():
        env[key] = getattr(args, key.lower(), None) or default
    if args.check_inactive:
        env["DAEMON_ARGS"] = "--check-inactive"
    return env


def host_env_for(client_dir: Path, args: argparse.Namespace) -> dict[str, str]:
    """Enviroment para correr el pipeline en el host (venv) contra este cliente."""
    env = dict(os.environ)
    env["DB_PATH"] = str(client_dir / "catalogo.db")
    env["PRESTASHOP_API_URL"] = args.api_url
    env["PRESTASHOP_API_KEY"] = args.api_key
    return env


def test_connection(args: argparse.Namespace) -> None:
    import requests

    url = f"{args.api_url.rstrip('/')}/"
    print(f"  Probando conexión con PrestaShop en {url} ...")
    resp = requests.get(url, auth=(args.api_key, ""), timeout=15)
    if resp.status_code in (200, 401):
        # PrestaShop responde 401 cuando la key es inválida
        if resp.status_code == 401:
            print("  ERROR: API key rechazada (401) — revisá la key del webservice.")
            sys.exit(1)
        print(f"  OK — API accesible ({resp.status_code})")
    else:
        print(f"  ERROR: respuesta inesperada {resp.status_code} {resp.text[:120]}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aprovisionar un cliente nuevo (carpeta + .env + catalogo.db).")
    parser.add_argument("--slug", required=True, help="Identificador del cliente (ej: tienda1)")
    parser.add_argument("--host-port", type=int, required=True, help="Puerto host de la Admin UI")
    parser.add_argument("--api-url", required=True, help="URL de la API de PrestaShop del cliente")
    parser.add_argument("--api-key", required=True, help="API key del webservice del cliente")
    parser.add_argument(
        "--interval", type=int, help="Daemon interval (default {}s)".format(_TUNING_DEFAULTS["DAEMON_INTERVAL"])
    )
    parser.add_argument(
        "--batch-size", type=int, help="Batch por corrida (default {})".format(_TUNING_DEFAULTS["BATCH_SIZE"])
    )
    parser.add_argument(
        "--api-sleep",
        type=int,
        help="Sleep entre llamadas externas (default {}s)".format(_TUNING_DEFAULTS["API_SLEEP"]),
    )
    parser.add_argument(
        "--check-inactive", action="store_true", help="El daemon valida inactivos con stock y los marca para activar"
    )
    parser.add_argument("--admin-user", help="Usuario administrador de la Admin UI (opcional)")
    parser.add_argument("--admin-pass", help="Contraseña del usuario administrador (opcional)")
    parser.add_argument(
        "--sync-categories", action="store_true", help="Crear categorías en PrestaShop desde las subcategorías locales"
    )
    parser.add_argument(
        "--test-connection", action="store_true", help="Verificar que la API key funcione antes de aprovisionar"
    )
    args = parser.parse_args()

    args.slug = slugify(args.slug)
    if not args.slug:
        parser.error("--slug quedó vacío tras normalizar")

    if args.test_connection:
        test_connection(args)

    client_dir = CLIENTS_DIR / args.slug
    client_dir.mkdir(parents=True, exist_ok=True)

    env = build_client_env(args)
    env_file = client_dir / ".env"
    env_file.write_text(
        "\n".join(f"{k}={v}" for k, v in sorted(env.items())) + "\n",
        encoding="utf-8",
    )
    print(f"[ok] .env escrito: {env_file}")

    host_env = host_env_for(client_dir, args)

    print(f"[..] Inicializando catalogo.db ({client_dir / 'catalogo.db'}) ...")
    subprocess.run(
        [sys.executable, "-c", "from middleware.db import _ensure_schema; _ensure_schema()"],
        cwd=ROOT,
        env=host_env,
        check=True,
    )
    print("[ok] catalogo.db listo (esquema + seed)")

    if args.admin_user and args.admin_pass:
        print(f"[..] Creando usuario administrador '{args.admin_user}' ...")
        subprocess.run(
            [sys.executable, "scripts/create_user.py",
             "--usuario", args.admin_user, "--clave", args.admin_pass, "--rol", "admin"],
            cwd=ROOT, env=host_env, check=True,
        )
        print("[ok] Usuario administrador creado")
    elif args.admin_user or args.admin_pass:
        print("[aviso] Faltó --admin-user o --admin-pass; no se creó usuario. "
              "Podés crearlo después en la pantalla de login del panel.")

    if args.sync_categories:
        print("[..] Sincronizando categorías con PrestaShop del cliente ...")
        subprocess.run(
            [sys.executable, "scripts/sync_categories.py"],
            cwd=ROOT,
            env=host_env,
            check=True,
        )
        print("[ok] Categorías sincronizadas")

    print()
    print("Cliente listo. Para levantar el contenedor:")
    print()
    print(f"  docker compose --env-file clients/{args.slug}/.env \\")
    print("      -f docker-compose.client.yml up -d")
    print()
    print(f"  Admin UI: http://localhost:{args.host_port}")


if __name__ == "__main__":
    main()
