#!/usr/bin/env python3
"""Daemon principal — verificación continua de productos activos.

Al iniciar ejecuta extracción + enriquecimiento, luego queda verificando
productos activos periódicamente.

Usage:
    python daemon.py [-v] [--interval SECONDS] [--dry-run] [--check-inactive]

El intervalo por defecto es DAEMON_INTERVAL de config (300 segundos = 5 min).

Con --check-inactive el daemon además valida productos inactivos con stock
y los deja como "pendientes para activar" cuando están completos.
"""

import argparse
import logging
import os
import signal
import sys
import time

from middleware.config import DAEMON_INTERVAL
from middleware import daemon_state

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


def _run_initial_pipeline(dry_run: bool) -> None:
    """Ejecuta extracción + enriquecimiento al iniciar el daemon."""
    from middleware.extract import run as run_extraction
    from middleware.enrich import run as run_enrich

    logger.info("=== Fase inicial: Extracción + Enriquecimiento ===")

    try:
        daemon_state.set_phase("extraction")
        pending = run_extraction(dry_run=dry_run)
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
        enriched = run_enrich(dry_run=dry_run)
        logger.info("Enriquecimiento finalizado. %d productos procesados.", enriched)
        daemon_state.log(f"Enriquecimiento: {enriched} productos procesados")
    except Exception:
        logger.exception("Error durante el enriquecimiento inicial")
        daemon_state.log("ERROR en enriquecimiento inicial")
        return


def run_daemon(interval: int, dry_run: bool, check_inactive: bool = False) -> None:
    """Run the daemon loop."""
    from middleware.check_active import check_all_active, check_inactive_pending

    daemon_state.start(interval, dry_run, check_inactive)
    daemon_state.set_pid(os.getpid())

    # ---- Fase inicial: extracción + enriquecimiento -------------------------
    _run_initial_pipeline(dry_run=dry_run)

    # ---- Loop de verificación continua --------------------------------------
    logger.info(
        "Daemon started — checking every %d seconds (dry_run=%s)",
        interval, dry_run,
    )
    daemon_state.log(
        f"Verificación continua cada {interval}s"
    )

    while _running:
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
        if _running:
            daemon_state.set_phase("idle")
            logger.info("Waiting %d seconds until next check...", interval)
            for _ in range(interval):
                if not _running:
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
    args = parser.parse_args()

    _setup_logging(args.verbose)

    # Handle graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    run_daemon(interval=args.interval, dry_run=args.dry_run, check_inactive=args.check_inactive)


if __name__ == "__main__":
    main()
