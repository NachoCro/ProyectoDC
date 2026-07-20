#!/usr/bin/env python3
"""Daemon principal — verificación continua de productos activos.

Al iniciar ejecuta extracción + enriquecimiento, luego queda verificando
productos activos periódicamente.

Usage:
    python daemon.py [-v] [--interval SECONDS] [--dry-run]

El intervalo por defecto es DAEMON_INTERVAL de config (300 segundos = 5 min).
"""

import argparse
import logging
import signal
import sys
import time

from middleware.config import DAEMON_INTERVAL
from middleware import pipeline_state

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
        pipeline_state.start(2)
        pipeline_state.update(1, 0, "Extrayendo productos inactivos...")

        pending = run_extraction(dry_run=dry_run)
        logger.info(
            "Extracción finalizada. %d productos pendientes de enriquecimiento.",
            len(pending),
        )
    except Exception:
        logger.exception("Error durante la extracción inicial")
        return

    try:
        pipeline_state.update(2, 0, "Enriqueciendo productos...")
        enriched = run_enrich(dry_run=dry_run)
        logger.info("Enriquecimiento finalizado. %d productos procesados.", enriched)
    except Exception:
        logger.exception("Error durante el enriquecimiento inicial")
        return

    pipeline_state.finish()


def run_daemon(interval: int, dry_run: bool) -> None:
    """Run the daemon loop."""
    from middleware.check_active import check_all_active

    # ---- Fase inicial: extracción + enriquecimiento -------------------------
    _run_initial_pipeline(dry_run=dry_run)

    # ---- Loop de verificación continua --------------------------------------
    logger.info(
        "Daemon started — checking every %d seconds (dry_run=%s)",
        interval, dry_run,
    )

    cycle = 0
    while _running:
        cycle += 1
        logger.info("=== Cycle %d ===", cycle)

        try:
            pipeline_state.start(1)
            pipeline_state.update(1, 0, "Verificando productos activos...")

            result = check_all_active(dry_run=dry_run)

            pipeline_state.add_log(
                f"Verificación completada: {result['total']} productos, "
                f"{result['complete']} completos, {result['incomplete']} incompletos, "
                f"{result['completed']} auto-completados"
            )
            pipeline_state.finish()

            logger.info(
                "Cycle %d complete: %d total, %d complete, %d incomplete, "
                "%d auto-completed, %d failed",
                cycle,
                result["total"],
                result["complete"],
                result["incomplete"],
                result["completed"],
                result["failed"],
            )

        except Exception as exc:
            logger.error("Error in cycle %d: %s", cycle, exc, exc_info=True)
            pipeline_state.finish()

        # Wait for next cycle
        if _running:
            logger.info("Waiting %d seconds until next check...", interval)
            for _ in range(interval):
                if not _running:
                    break
                time.sleep(1)

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
    args = parser.parse_args()

    _setup_logging(args.verbose)

    # Handle graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    run_daemon(interval=args.interval, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
