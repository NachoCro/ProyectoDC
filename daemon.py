#!/usr/bin/env python3
"""Daemon principal — verificación continua de productos activos.

Al iniciar ejecuta extracción + enriquecimiento, luego queda verificando
productos activos periódicamente.

Usage:
    python daemon.py [-v] [--interval SECONDS] [--dry-run] [--check-inactive]
                     [--extract-scope inactive|active|both] [--modo publicar|preparar]
                     [--skip-extract] [--no-initial-pipeline]

El intervalo por defecto es DAEMON_INTERVAL de config (300 segundos = 5 min).

Con --check-inactive el daemon además valida productos inactivos con stock
y los deja como "pendientes para activar" cuando están completos.
"""

import argparse
import logging
import os
import signal
import time

from middleware import daemon_state
from middleware.config import DAEMON_INTERVAL

logger = logging.getLogger(__name__)

_running = True


def _signal_handler(signum, frame):
    global _running
    logger.info("Received signal %d, shutting down...", signum)
    _running = False


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _run_initial_pipeline(dry_run: bool, override: dict | None,
                          skip_extract: bool = False) -> None:
    """Ejecuta extracción + enriquecimiento al iniciar el daemon."""
    from middleware.enrich import run as run_enrich
    from middleware.extract import run as run_extraction

    logger.info("=== Fase inicial: Extracción + Enriquecimiento ===")

    if skip_extract:
        logger.info("Extracción omitida (skip_extract)")
        daemon_state.log("Extracción omitida (solo enriquecer)")
    else:
        try:
            daemon_state.set_phase("extraction")
            pending = run_extraction(dry_run=dry_run, override=override)
            logger.info(
                "Extracción finalizada. %d productos pendientes de enriquecimiento.",
                len(pending),
            )
            daemon_state.log(f"Extracción: {len(pending)} productos pendientes")
        except Exception:
            logger.exception("Error durante la extracción inicial")
            daemon_state.log("ERROR en extracción inicial")
            return

    try:
        daemon_state.set_phase("enrichment")
        enriched = run_enrich(dry_run=dry_run, override=override)
        logger.info("Enriquecimiento finalizado. %d productos procesados.", enriched)
        daemon_state.log(f"Enriquecimiento: {enriched} productos procesados")
    except Exception:
        logger.exception("Error durante el enriquecimiento inicial")
        daemon_state.log("ERROR en enriquecimiento inicial")
        return


def run_daemon(
    interval: int,
    dry_run: bool,
    check_inactive: bool = False,
    no_initial_pipeline: bool = False,
    extract_scope: str | None = None,
    modo: str | None = None,
    skip_extract: bool = False,
) -> None:
    """Run the daemon loop.

    Las opciones avanzadas de la fase inicial (``extract_scope``, ``modo``,
    ``skip_extract``) ganan sobre las del plan cuando se pasan explícitamente;
    si no, el daemon aplica las opciones guardadas en el plan (agenda).  El
    ``dry_run`` de la fase inicial se activa también si el plan pide simular.
    """
    from middleware import plan
    from middleware.check_active import check_all_active, check_inactive_pending

    daemon_state.start(interval, dry_run, check_inactive)
    daemon_state.set_pid(os.getpid())

    # ---- Fase inicial: extracción + enriquecimiento -------------------------
    if not no_initial_pipeline:
        override = {
            "scope": extract_scope or plan.effective_scope(),
            "modo": modo or plan.effective_modo(),
        }
        _run_initial_pipeline(
            dry_run=dry_run or plan.effective_dry_run(),
            override=override,
            skip_extract=skip_extract or plan.effective_skip_extract(),
        )
    else:
        logger.info("Fase inicial omitida (--no-initial-pipeline)")
        daemon_state.log("Arranque sin extracción/enriquecimiento inicial")

    # ---- Loop de verificación continua --------------------------------------
    logger.info(
        "Daemon started — checking every %d seconds (dry_run=%s)",
        interval, dry_run,
    )
    daemon_state.log(
        f"Verificación continua cada {interval}s"
    )

    while _running and not daemon_state.stop_requested():
        daemon_state.set_phase("verification")

        try:
            if check_inactive:
                daemon_state.set_phase("inactive_check")
                inactive_result = check_inactive_pending(dry_run=dry_run)
                daemon_state.log(
                    f"Inactivos: {inactive_result['total']} productos, "
                    f"{inactive_result['with_stock']} con stock, "
                    f"{inactive_result['marked']} listos para activar"
                )
                logger.info(
                    "Inactive check: %d total, %d with stock, %d marked for activation, "
                    "%d auto-completed",
                    inactive_result["total"],
                    inactive_result["with_stock"],
                    inactive_result["marked"],
                    inactive_result["completed"],
                )

            result = check_all_active(dry_run=dry_run)
            daemon_state.cycle_done(result)

            logger.info(
                "Verification: %d total, %d complete, %d incomplete, "
                "%d auto-completed, %d failed",
                result["total"],
                result["complete"],
                result["incomplete"],
                result["completed"],
                result["failed"],
            )

        except Exception as exc:
            logger.error("Error during verification: %s", exc, exc_info=True)
            daemon_state.log(f"ERROR: {exc}")

        # Wait for next cycle
        if _running and not daemon_state.stop_requested():
            daemon_state.set_phase("idle")
            logger.info("Waiting %d seconds until next check...", interval)
            for _ in range(interval):
                if not _running or daemon_state.stop_requested():
                    break
                time.sleep(1)

    daemon_state.stop()
    logger.info("Daemon stopped")


def main() -> None:
    global _running

    parser = argparse.ArgumentParser(
        description="Daemon principal — verificación de productos activos"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Salida detallada (DEBUG)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DAEMON_INTERVAL,
        help=f"Seconds between checks (default: {DAEMON_INTERVAL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No escribir en BD ni PrestaShop, solo mostrar lo que se haría",
    )
    parser.add_argument(
        "--check-inactive",
        action="store_true",
        help="Validar productos inactivos con stock y marcarlos como listos para activar",
    )
    parser.add_argument(
        "--no-initial-pipeline",
        action="store_true",
        help="No ejecutar la fase inicial de extracción + enriquecimiento al arrancar",
    )
    parser.add_argument(
        "--extract-scope",
        choices=("inactive", "active", "both"),
        default=None,
        help="Qué catálogo barrer en la extracción inicial "
             "(default: plan, inactive)",
    )
    parser.add_argument(
        "--modo",
        choices=("publicar", "preparar"),
        default=None,
        help="Modo de enriquecimiento inicial: publicar (default) o preparar "
             "(guardar propuesta sin modificar PrestaShop)",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Saltar la extracción en la fase inicial (solo enriquecer)",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    # Handle graceful shutdown (SIGTERM is POSIX-only)
    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    run_daemon(
        interval=args.interval,
        dry_run=args.dry_run,
        check_inactive=args.check_inactive,
        no_initial_pipeline=args.no_initial_pipeline,
        extract_scope=args.extract_scope,
        modo=args.modo,
        skip_extract=args.skip_extract,
    )


if __name__ == "__main__":
    main()
