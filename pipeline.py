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


def _run_enrich(dry_run: bool, override: dict | None = None) -> int:
    from middleware.enrich import run as run_enrich

    return run_enrich(dry_run=dry_run, override=override)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Middleware PrestaShop — Extracción por goteo"
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
    parser.add_argument(
        "--sub", "--tipo",
        dest="sub",
        default="",
        help="Ejecución única: tipo de producto a procesar (se matchean "
             "productos por similitud del nombre, ej. motosierras). No modifica "
             "el plan configurado.",
    )
    parser.add_argument(
        "--cantidad",
        dest="cantidad",
        type=int,
        default=0,
        help="Ejecución única: cuántos productos procesar en esta corrida.",
    )
    args = parser.parse_args()

    from middleware import plan
    override = None
    if args.sub or args.cantidad:
        override = {
            "subcategoria": args.sub.strip() or None,
            "cantidad": args.cantidad or None,
        }

    _setup_logging(args.verbose)
    logger = logging.getLogger("main")

    # Opciones avanzadas del plan: scope / modo / skip-extract / dry-run
    # se aplican cuando no hay una ejecución única explícita.
    dry_run = args.dry_run or plan.effective_dry_run()
    skip_extract = plan.effective_skip_extract()
    if override is None:
        override = {
            "scope": plan.effective_scope(),
            "modo": plan.effective_modo(),
        }

    if override:
        conn = None
        try:
            from middleware.db import get_connection
            conn = get_connection()
            objetivo = plan.describe_target(conn, override["subcategoria"], override["cantidad"])
        except Exception:
            objetivo = ", ".join(
                str(v) for v in override.values() if v
            ) or "sin objetivo"
        finally:
            if conn is not None:
                conn.close()
        logger.info("=== Ejecución única: %s ===", objetivo)

    # ---- Extraction phase --------------------------------------------------
    if skip_extract:
        logger.info("Extracción omitida (plan.skip_extract)")
    else:
        try:
            pending = run_extraction(dry_run=dry_run, override=override)
            logger.info(
                "Extracción finalizada. %d productos pendientes de enriquecimiento.",
                len(pending),
            )
        except Exception:
            logger.exception("Error durante la extracción")
            sys.exit(1)

    # ---- Enrichment phase (always runs after extraction) --------------------
    try:
        enriched = _run_enrich(dry_run=dry_run, override=override)
        logger.info("Enriquecimiento finalizado. %d productos procesados.", enriched)
    except Exception:
        logger.exception("Error durante el enriquecimiento")
        sys.exit(1)


if __name__ == "__main__":
    main()
