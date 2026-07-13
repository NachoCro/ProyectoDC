import logging

from .config import BATCH_SIZE
from .db import (
    get_connection,
    get_subcategoria_id,
    get_subcategoria_by_ps_category,
    has_ean_in_db,
    has_product_not_found,
    has_id_in_db,
    insert_product,
    sync_producto_from_prestashop,
)
from .prestashop import PrestashopClient

logger = logging.getLogger(__name__)


def _short_circuit(id_prestashop: int, ean: str | None) -> bool:
    """Check whether this product can be skipped.

    RF-04 — EAN already exists in local DB.
    RF-05 — product was previously marked as not found in Icecat.
    """
    if ean and has_ean_in_db(ean):
        return True
    if has_id_in_db(id_prestashop):
        return True
    if has_product_not_found(ean, id_prestashop):
        return True
    return False


def run(dry_run: bool = False) -> list[dict]:
    """Extraction pipeline (RF-01, RF-02, RF-04, RF-05, RF-10).

    Steps
    -----
    1. Fetch manufacturer name map from PrestaShop.
    2. Walk inactive products in pages, checking stock (RF-01 / RF-02).
    3. Cross-reference EAN / id_prestashop against local DB — short-circuit if
       already known (RF-04, RF-05).
    4. Insert new products into ``productos`` with
       ``estado_actualizacion = 'desactualizado'`` for later Icecat processing.
    5. Respect batch-size limit and API throttle (RF-10).
    """
    client = PrestashopClient()

    # -- 1. Manufacturer map (for brand name) --------------------------------
    manufacturers = client.get_manufacturers()
    logger.info("Loaded %d manufacturers", len(manufacturers))

    # -- 2. Walk inactive products until we have enough candidates -----------
    candidates: list[dict] = []
    offset = 0

    while len(candidates) < BATCH_SIZE:
        products = client.get_inactive_products(limit=BATCH_SIZE, offset=offset)
        if not products:
            logger.debug("No more inactive products at offset %d", offset)
            break

        pids = [int(p["id"]) for p in products if p["id"]]
        stock = client.get_stock_map(pids)

        for p in products:
            if len(candidates) >= BATCH_SIZE:
                break

            pid = p["id"]
            qty = stock.get(int(pid), 0)
            if qty < 1:
                logger.debug("  Product %s: qty=%d < 1, filtered", pid, qty)
                continue

            id_mfr = p.get("id_manufacturer")
            marca = manufacturers.get(int(id_mfr), "") if id_mfr else ""

            id_category = p.get("id_category_default")
            candidates.append({
                "id_prestashop": int(pid),
                "ean": p.get("ean13") or None,
                "mpn": p.get("mpn") or None,
                "marca": marca,
                "modelo": "",  # resolved from product name — deferred
                "nombre": p.get("name"),  # product name from PrestaShop
                "id_category_default": int(id_category) if id_category else None,
            })

        offset += len(products)

    logger.info("Candidates after stock filter: %d", len(candidates))

    # -- 3 / 4.  Short-circuit & insert --------------------------------------
    pending: list[dict] = []
    inserted = 0
    conn = get_connection()
    try:
        for p in candidates:
            pid = p["id_prestashop"]
            ean = p["ean"]

            # RF-04 / RF-05: skip if already in local DB
            if _short_circuit(pid, ean):
                if not dry_run:
                    updated = sync_producto_from_prestashop(
                        conn, pid, ean, p["mpn"], p["marca"],
                        p.get("nombre"), p.get("id_category_default"),
                    )
                    if updated:
                        logger.info("  SYNC  id=%d  campos=%s", pid, updated)
                logger.info("  SKIP  id=%d  EAN=%s  (already in DB)", pid, ean)
                continue

            if not dry_run:
                # Resolve subcategory from PrestaShop's id_category_default
                ps_cat_id = p.get("id_category_default")
                sub_id = get_subcategoria_by_ps_category(conn, ps_cat_id) if ps_cat_id else None
                if sub_id is None:
                    sub_id = get_subcategoria_id(conn, "SIN CLASIFICAR")
                if sub_id is None:
                    conn.execute(
                        "INSERT OR IGNORE INTO subcategorias "
                        "(id_categoria, nombre_subcategoria) VALUES (?, ?)",
                        (1, "SIN CLASIFICAR"),
                    )
                    conn.commit()
                    sub_id = get_subcategoria_id(conn, "SIN CLASIFICAR")

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
                "Inserted %d new products (%d already known)",
                inserted, len(candidates) - inserted,
            )
    finally:
        conn.close()

    return pending
