import logging

from . import pipeline_state, plan
from .config import BATCH_SIZE
from .db import (
    ensure_subcategoria,
    get_connection,
    get_subcategoria_by_ps_category,
    insert_product,
    sync_producto_from_prestashop,
)
from .prestashop import PrestashopClient

logger = logging.getLogger(__name__)


def _load_known() -> tuple[set[int], set[str]]:
    """Load every local ``id_prestashop`` + EAN into memory.

    Used to short-circuit already-known products *during* the walk so they
    don't consume the ``target_count`` quota — the old code counted them as
    candidates and skipped them later at insert time, so repeated runs would
    walk the same known products and process fewer new ones than requested.
    """
    conn = get_connection()
    try:
        ids: set[int] = set()
        eans: set[str] = set()
        for r in conn.execute("SELECT id_prestashop, ean FROM productos"):
            ids.add(int(r["id_prestashop"]))
            if r["ean"]:
                eans.add(r["ean"])
        return ids, eans
    finally:
        conn.close()


def run(dry_run: bool = False, override: dict | None = None) -> list[dict]:
    """Extraer productos inactivos de PrestaShop a la BD local.

    ``override`` (opcional) es un dict ``{'subcategoria': str, 'cantidad': int}``
    para una ejecución única: se usa ESE objetivo en vez del plan configurado,
    sin modificarlo.

    La extracción reporta su propio progreso (fase "extracción", barra
    indeterminada) al dashboard vía ``pipeline_state``.
    """
    pipeline_state.start(0, phase="Extrayendo productos de PrestaShop")
    try:
        return _run_inner(dry_run=dry_run, override=override)
    finally:
        pipeline_state.finish()


def _run_inner(dry_run: bool, override: dict | None) -> list[dict]:
    """Extraction pipeline (RF-01, RF-02, RF-04, RF-05, RF-10).

    Steps
    -----
    1. Fetch manufacturer name map from PrestaShop.
    2. Walk inactive products in pages, checking stock (RF-01 / RF-02).
    3. Cross-reference EAN / id_prestashop against local DB — short-circuit if
       already known (RF-04, RF-05).
    4. Insert new products into ``productos`` with
       ``estado_actualizacion = 'desactualizado'`` for later enrichment processing.
    5. Respect batch-size limit and API throttle (RF-10).
    """
    client = PrestashopClient()

    # -- 0. Plan de trabajo (objetivo por tipo de producto + cantidad) -------
    #    La ejecución única (override) gana sobre el plan sin modificarlo.
    #    La SELECCIÓN de productos del plan se hace por similitud del nombre
    #    con el tipo de producto objetivo (ver plan.matches_name).
    target_sub = (
        (override or {}).get("subcategoria")
        or plan.effective_subcategoria()
    )
    target_count = (
        (override or {}).get("cantidad")
        or plan.effective_cantidad(BATCH_SIZE)
    )

    target_name = target_sub if target_sub else None
    conn_lookup = get_connection()
    try:
        objetivo = (
            plan.describe_target(conn_lookup, target_sub, target_count)
            if override
            else plan.describe_plan(conn_lookup)
        )
        logger.info(
            "Plan de trabajo: %s (objetivo %d por ciclo)",
            objetivo, target_count,
        )
    finally:
        conn_lookup.close()

    # -- 1. Manufacturer map (for brand name) --------------------------------
    manufacturers = client.get_manufacturers()
    logger.info("Loaded %d manufacturers", len(manufacturers))

    # -- 2. Walk products until we have enough candidates --------------------
    #    scope: "inactive" (default) | "active" | "both" — qué catálogo barrer.
    #    El override (ejecución única) gana; si no viene, se usa la opción
    #    avanzada del plan.
    scope = (
        (override or {}).get("scope")
        or plan.effective_scope()
    )
    fetchers = []
    if scope in ("inactive", "both"):
        fetchers.append(("inactive", client.get_inactive_products))
    if scope in ("active", "both"):
        fetchers.append(("active", client.get_active_products))
    if not fetchers:
        fetchers.append(("inactive", client.get_inactive_products))
    logger.info("Extracción scope=%s", scope)

    # Productos ya conocidos (id o EAN en la BD) se saltean DURANTE la
    # caminata: no cuentan para el objetivo ni se re-insertan.  Se guardan los
    # primeros ``target_count`` para sincronizar sus campos con PrestaShop.
    known_ids, known_eans = _load_known()
    known_seen: list[dict] = []

    # Tope defensivo de la caminata: si el catálogo no tiene suficientes
    # productos NUEVOS, no escanear páginas sin fin buscando el cupo.
    max_walked = max(target_count * 10, BATCH_SIZE * 5)
    walked = 0

    candidates: list[dict] = []
    offsets = {name: 0 for name, _ in fetchers}

    while len(candidates) < target_count:
        progressed = False
        for scope_name, fetcher in fetchers:
            if len(candidates) >= target_count or walked >= max_walked:
                break
            products = fetcher(
                limit=min(max(target_count, BATCH_SIZE), 50), offset=offsets[scope_name],
            )
            if not products:
                logger.debug("No more %s products at offset %d", scope_name, offsets[scope_name])
                continue
            offsets[scope_name] += len(products)
            progressed = True

            pids = [int(p["id"]) for p in products if p["id"]]
            stock = client.get_stock_map(pids)

            for p in products:
                if len(candidates) >= target_count or walked >= max_walked:
                    break
                walked += 1

                pid = p["id"]
                qty = stock.get(int(pid), 0)
                if qty < 1:
                    logger.debug("  Product %s: qty=%d < 1, filtered", pid, qty)
                    continue

                # Plan con tipo de producto: el nombre debe ser similar al texto
                # objetivo (coincidencia por palabras, no subcategoría exacta).
                nombre = p.get("name") or ""
                if target_name and not plan.matches_name(target_name, nombre):
                    logger.debug(
                        "  Product %s: nombre '%s' no es similar a '%s', filtered",
                        pid, nombre, target_name,
                    )
                    continue

                ean = p.get("ean13") or None
                id_mfr = p.get("id_manufacturer")
                marca = manufacturers.get(int(id_mfr), "") if id_mfr else ""

                id_category = p.get("id_category_default")

                # Ya procesado en una corrida anterior: no consume el cupo.
                if ean in known_eans or int(pid) in known_ids:
                    logger.debug("  Product %s: already in DB, filtered", pid)
                    if len(known_seen) < target_count:
                        known_seen.append({
                            "id_prestashop": int(pid),
                            "ean": ean,
                            "mpn": p.get("mpn") or None,
                            "marca": marca,
                            "nombre": nombre,
                            "id_category_default": int(id_category) if id_category else None,
                        })
                    continue

                # Resolve modelo from product name
                from .official_scraper import _extract_model_from_name
                modelo = _extract_model_from_name(nombre, marca)

                candidates.append({
                    "id_prestashop": int(pid),
                    "ean": ean,
                    "mpn": p.get("mpn") or None,
                    "marca": marca,
                    "modelo": modelo,
                    "nombre": nombre,
                    "id_category_default": int(id_category) if id_category else None,
                })

        if not progressed:
            break

    logger.info("Candidates after stock filter: %d", len(candidates))

    # -- 3 / 4.  Short-circuit & insert --------------------------------------
    pending: list[dict] = []
    inserted = 0
    conn = get_connection()
    try:
        # Sync fields for already-known products encountered during the walk
        # (PrestaShop is source of truth for marca/modelo/categoría).
        for p in known_seen:
            if not dry_run:
                updated = sync_producto_from_prestashop(
                    conn, p["id_prestashop"], p["ean"], p["mpn"], p["marca"],
                    p.get("nombre"), p.get("id_category_default"),
                )
                if updated:
                    logger.info("  SYNC  id=%d  campos=%s", p["id_prestashop"], updated)

        for p in candidates:
            pid = p["id_prestashop"]
            ean = p["ean"]

            logger.info(
                "  Procesando id=%d — %s (%s)",
                pid, p.get("nombre") or "(sin nombre)", p["marca"] or "sin marca",
            )
            pipeline_state.add_log(
                f"Extrayendo id={pid} — {p.get('nombre') or '(sin nombre)'}"
            )

            if not dry_run:
                # Resolve subcategory from PrestaShop's id_category_default
                ps_cat_id = p.get("id_category_default")
                sub_id = get_subcategoria_by_ps_category(conn, ps_cat_id) if ps_cat_id else None
                if sub_id is None:
                    sub_id = ensure_subcategoria(conn, "SIN CLASIFICAR")

                ok = insert_product(
                    conn,
                    id_prestashop=pid,
                    id_subcategoria=sub_id or 1,
                    ean=ean,
                    mpn=p["mpn"],
                    marca=p["marca"],
                    modelo=p["modelo"],
                    nombre=p.get("nombre"),
                )
                if not ok:
                    logger.info(
                        "  SKIP  id=%d  (collision on insert)", pid,
                    )
                    continue
                inserted += 1

            pending.append(p)
            logger.info(
                "  QUEUE id=%d  EAN=%s  marca=%s",
                pid, ean or "(sin EAN)", p["marca"],
            )

        if not dry_run:
            conn.commit()
            logger.info(
                "Inserted %d new products (%d known synced)",
                inserted, len(known_seen),
            )
    finally:
        conn.close()

    return pending
