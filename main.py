#!/usr/bin/env python3
import argparse
import logging
import sys

from middleware.extract import run as run_extraction


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _run_enrich(dry_run: bool) -> int:
    from middleware.enrich import run as run_enrich

    return run_enrich(dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Middleware PrestaShop ↔ Icecat  —  Extracción por goteo"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Salida detallada (DEBUG)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No escribir en BD, solo mostrar lo que se haría",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)
    logger = logging.getLogger("main")

    # ---- Extraction phase --------------------------------------------------
    try:
        pending = run_extraction(dry_run=args.dry_run)
        logger.info(
            "Extracción finalizada. %d productos pendientes de enriquecimiento Icecat.",
            len(pending),
        )
    except Exception:
        logger.exception("Error durante la extracción")
        sys.exit(1)

    # ---- Enrichment phase (always runs after extraction) --------------------
    try:
        enriched = _run_enrich(dry_run=args.dry_run)
        logger.info("Enriquecimiento finalizado. %d productos procesados.", enriched)
    except Exception:
        logger.exception("Error durante el enriquecimiento Icecat")
        sys.exit(1)


if __name__ == "__main__":
    main()
