"""Active product completeness check and auto-completion.

Checks active products (active=1) in PrestaShop for completeness:
- Image: product has at least one image
- Description: product has a non-empty description
- Characteristics: product has product_features assigned

Incomplete products are automatically completed using the enrichment pipeline.
"""

import json
import logging

from .db import (
    get_connection,
    get_subcategoria_by_ps_category,
    ensure_subcategoria,
    insert_product,
)
from . import pipeline_state

logger = logging.getLogger(__name__)


def _ensure_product_in_db(pid: int) -> dict | None:
    """Ensure the product exists in the local DB with fresh data from PrestaShop.

    Always fetches the latest data from PrestaShop and upserts into the local DB.
    Returns the product row as a dict, or None if it couldn't be created.
    """
    from admin_ui.prestashop import AdminPrestashopClient

    conn = get_connection()
    try:
        client = AdminPrestashopClient()
        ps_product = client.get_product(pid)

        # Get manufacturer name
        id_mfr = ps_product.get("id_manufacturer")
        marca = ""
        if id_mfr:
            try:
                manufacturers = client.get_manufacturers()
                marca = manufacturers.get(int(id_mfr), "")
            except Exception:
                pass

        # Resolve subcategory from id_category_default
        id_category = ps_product.get("id_category_default")
        ps_cat_id = int(id_category) if id_category else None
        sub_id = get_subcategoria_by_ps_category(conn, ps_cat_id) if ps_cat_id else None
        if sub_id is None:
            sub_id = ensure_subcategoria(conn, "SIN CLASIFICAR")

        # Extract name (multi-language, JSON format uses "value" key)
        nombre = None
        name_el = ps_product.get("name", "")
        if isinstance(name_el, list):
            for n in name_el:
                if isinstance(n, dict):
                    val = n.get("value") or n.get("#text")
                    if val:
                        nombre = val
                        break
                elif isinstance(n, str) and n:
                    nombre = n
                    break
        elif isinstance(name_el, str) and name_el:
            nombre = name_el

        # Extract EAN
        ean = ps_product.get("ean13") or None
        if isinstance(ean, str) and not ean.strip():
            ean = None

        # Extract MPN
        mpn = ps_product.get("mpn") or None
        if isinstance(mpn, str) and not mpn.strip():
            mpn = None

        # Upsert into local DB
        existing = conn.execute(
            "SELECT id_prestashop FROM productos WHERE id_prestashop = ?", (pid,)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE productos
                   SET nombre = ?, ean = ?, mpn = ?, marca = ?,
                       id_subcategoria = ?
                   WHERE id_prestashop = ?""",
                (nombre, ean, mpn, marca, sub_id or 1, pid),
            )
        else:
            insert_product(
                conn,
                id_prestashop=pid,
                id_subcategoria=sub_id or 1,
                ean=ean,
                mpn=mpn,
                marca=marca,
                modelo="",
                nombre=nombre,
            )
        conn.commit()

        # Re-fetch the row
        row = conn.execute(
            """SELECT p.*, COALESCE(s.nombre_subcategoria, '') AS subcat_name
               FROM productos p
               LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
               WHERE p.id_prestashop = ?""", (pid,)
        ).fetchone()

        return dict(row) if row else None

    finally:
        conn.close()


def check_product_completeness(pid: int) -> dict:
    """Check if a single product is complete in PrestaShop.

    Returns a dict with:
    - ``is_complete``: True if all fields are present
    - ``missing``: list of missing field names ('image', 'description', 'characteristics')
    """
    from admin_ui.prestashop import AdminPrestashopClient, PrestashopError

    client = AdminPrestashopClient()

    try:
        result = client.get_product_completeness(pid)
        return result
    except PrestashopError as exc:
        logger.error("Error checking completeness for product %d: %s", pid, exc)
        return {"is_complete": False, "missing": ["error"], "product": None}


def complete_incomplete_product(pid: int, dry_run: bool = False) -> bool:
    """Complete an incomplete product by running the enrichment pipeline.

    Only fills in missing fields (image, description, characteristics).
    Does not overwrite existing data.

    Returns True if the product was completed successfully.
    """
    from admin_ui.prestashop import AdminPrestashopClient, PrestashopError
    from .enrich import _build_description
    from .db import write_eav
    from .characteristics import merge_characteristics
    from .descriptions import get_description

    # Ensure product exists in local DB (inserts if missing)
    product = _ensure_product_in_db(pid)
    if product is None:
        logger.warning("Product %d could not be loaded into local DB", pid)
        return False

    # Skip if already verified as complete
    if product.get("active_verified"):
        logger.debug("Product %d already verified as complete, skipping", pid)
        return True

    # Check completeness
    completeness = check_product_completeness(pid)
    if completeness["is_complete"]:
        logger.info("Product %d is already complete, marking as verified", pid)
        if not dry_run:
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE productos SET active_verified = 1 WHERE id_prestashop = ?",
                    (pid,),
                )
                conn.commit()
            finally:
                conn.close()
        return True

    missing = completeness["missing"]
    logger.info("Product %d is incomplete, missing: %s", pid, missing)

    if dry_run:
        logger.info("  DRY RUN — would complete product %d (missing: %s)", pid, missing)
        return True

    conn = get_connection()
    try:
        subcat_name = product.get("subcat_name") or ""
        icecat_json = product.get("icecat_json")

        # Parse existing proposal if available
        proposal = None
        if icecat_json:
            try:
                proposal = json.loads(icecat_json) if isinstance(icecat_json, str) else icecat_json
            except (json.JSONDecodeError, TypeError):
                proposal = None

        # If no proposal exists, we need to fetch data first
        if proposal is None:
            logger.info("Product %d has no proposal data, running enrichment first", pid)
            from .enrich import _fetch_and_prepare

            product_data, translated, description = _fetch_and_prepare(
                pid,
                product.get("ean"),
                product.get("mpn"),
                product.get("marca") or "",
                product.get("modelo") or "",
                product.get("nombre") or "",
                dry_run=False,
            )

            if product_data is None:
                logger.warning("Could not fetch data for product %d", pid)
                return False

            proposal = translated or product_data

            # Store the proposal
            conn.execute(
                """UPDATE productos
                   SET icecat_json = ?,
                       marca = ?,
                       modelo = ?,
                       imagen_url = ?
                   WHERE id_prestashop = ?""",
                (
                    json.dumps(proposal, ensure_ascii=False),
                    (product_data.get("marca") or "").strip() or product.get("marca"),
                    (product_data.get("modelo") or "").strip() or product.get("modelo"),
                    (product_data.get("imagen_url") or "").strip() or None,
                    pid,
                ),
            )
            conn.commit()

        # Now complete the missing fields
        client = AdminPrestashopClient()

        try:
            # Get current product from PrestaShop
            ps_product = client.get_product(pid)

            # Build updates dict
            updates = {}

            # Complete description if missing
            if "description" in missing:
                chars = proposal.get("caracteristicas") or []
                merged_chars = merge_characteristics(chars, subcat_name)
                desc = _build_description(proposal, merged_chars)
                if desc:
                    updates["description"] = desc

                # Also set description_short if empty
                desc_short = ps_product.get("description_short", "")
                if not desc_short or (isinstance(desc_short, str) and not desc_short.strip()):
                    excel_desc = get_description(subcat_name)
                    if excel_desc.get("descripcion_corta"):
                        updates["description_short"] = excel_desc["descripcion_corta"]

            # Complete characteristics if missing
            feature_pairs = None
            if "characteristics" in missing:
                chars = proposal.get("caracteristicas") or []
                merged_chars = merge_characteristics(chars, subcat_name)
                if merged_chars:
                    feature_pairs = client.sync_characteristics_as_features(merged_chars)

            # Push updates to PrestaShop
            if updates or feature_pairs:
                client.put_product(
                    pid, updates,
                    feature_pairs=feature_pairs or None,
                )
                logger.info("  Updated product %d: %s", pid, list(updates.keys()))

            # Upload images if missing
            if "image" in missing:
                imagen_urls = proposal.get("imagen_urls") or []
                if imagen_urls:
                    uploaded_ids = client.upload_product_images(pid, imagen_urls)
                    if uploaded_ids:
                        logger.info("  Uploaded %d images for product %d", len(uploaded_ids), pid)
                    else:
                        logger.warning("  Failed to upload images for product %d", pid)
                else:
                    imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""
                    if imagen_url:
                        img_id = client.upload_product_image(pid, imagen_url)
                        if img_id:
                            logger.info("  Uploaded image for product %d: %s", pid, imagen_url)
                        else:
                            logger.warning("  Failed to upload image for product %d", pid)

            # Update local DB
            marca_final = proposal.get("marca") or product.get("marca") or ""
            modelo_final = proposal.get("modelo") or product.get("modelo") or ""
            imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""

            conn.execute(
                """UPDATE productos
                   SET marca = ?,
                       modelo = ?,
                       imagen_url = ?,
                       active_verified = 1,
                       product_not_found = 0,
                       estado_actualizacion = 'actualizado',
                       fecha_sincronizacion = datetime('now')
                   WHERE id_prestashop = ?""",
                (marca_final, modelo_final, imagen_url or None, pid),
            )

            # Write characteristics locally if we have them
            if "characteristics" in missing:
                chars = proposal.get("caracteristicas") or []
                merged_chars = merge_characteristics(chars, subcat_name)
                if merged_chars:
                    write_eav(conn, pid, merged_chars)

            # Audit log
            detalle = json.dumps({
                "action": "auto_complete",
                "missing": missing,
                "marca": marca_final,
                "modelo": modelo_final,
            }, ensure_ascii=False)
            conn.execute(
                "INSERT INTO audit_log (id_producto, actor, accion, detalle) VALUES (?, ?, ?, ?)",
                (pid, "check_active", "auto_completado", detalle),
            )
            conn.commit()

            logger.info("  COMPLETED product %d — filled: %s", pid, missing)
            return True

        except PrestashopError as exc:
            logger.error("Error completing product %d: %s", pid, exc)
            return False

    finally:
        conn.close()


def check_all_active(dry_run: bool = False) -> dict:
    """Check all active products for completeness and complete incomplete ones.

    Returns a dict with:
    - ``total``: total active products checked
    - ``complete``: number of complete products
    - ``incomplete``: number of incomplete products
    - ``completed``: number of products that were auto-completed
    - ``failed``: number of products that failed to complete
    - ``details``: list of dicts with product info and status
    """
    from middleware.prestashop import PrestashopClient

    client = PrestashopClient()
    details = []
    total = 0
    complete_count = 0
    incomplete_count = 0
    completed_count = 0
    failed_count = 0

    # Fetch all active products (paginated)
    offset = 0
    limit = 50
    while True:
        products = client.get_active_products(limit=limit, offset=offset)
        if not products:
            break

        for p in products:
            pid = int(p["id"])
            total += 1
            name = p.get("name") or f"Product {pid}"

            # Skip if already verified as complete in local DB
            conn_check = get_connection()
            try:
                row_check = conn_check.execute(
                    "SELECT active_verified FROM productos WHERE id_prestashop = ?",
                    (pid,),
                ).fetchone()
                if row_check and row_check["active_verified"]:
                    complete_count += 1
                    logger.debug("  SKIP  id=%d  %s — already verified", pid, name)
                    continue
            finally:
                conn_check.close()

            pipeline_state.add_log(f"Verificando producto activo: {name} (id={pid})")

            # Check completeness
            completeness = check_product_completeness(pid)
            is_complete = completeness["is_complete"]
            missing = completeness["missing"]

            detail = {
                "id": pid,
                "name": name,
                "is_complete": is_complete,
                "missing": missing,
                "completed": False,
            }

            if is_complete:
                complete_count += 1
                logger.info("  OK  id=%d  %s — complete", pid, name)
                # Mark as verified in local DB
                if not dry_run:
                    conn_mark = get_connection()
                    try:
                        conn_mark.execute(
                            "UPDATE productos SET active_verified = 1 WHERE id_prestashop = ?",
                            (pid,),
                        )
                        conn_mark.commit()
                    finally:
                        conn_mark.close()
            else:
                incomplete_count += 1
                logger.info("  INCOMPLETE  id=%d  %s — missing: %s", pid, name, missing)

                # Try to complete
                if not dry_run:
                    success = complete_incomplete_product(pid, dry_run=False)
                    if success:
                        completed_count += 1
                        detail["completed"] = True
                        logger.info("  AUTO-COMPLETED  id=%d  %s", pid, name)
                    else:
                        failed_count += 1
                        logger.warning("  FAILED TO COMPLETE  id=%d  %s", pid, name)
                else:
                    logger.info("  DRY RUN — would complete id=%d  %s", pid, name)

            details.append(detail)

        offset += limit

    result = {
        "total": total,
        "complete": complete_count,
        "incomplete": incomplete_count,
        "completed": completed_count,
        "failed": failed_count,
        "details": details,
    }

    logger.info(
        "Check complete: %d total, %d complete, %d incomplete, %d auto-completed, %d failed",
        total, complete_count, incomplete_count, completed_count, failed_count,
    )

    return result


def _mark_pending_activation(pid: int) -> None:
    """Mark an inactive product as ready to be activated (pendiente_activar = 1)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE productos SET pendiente_activar = 1 WHERE id_prestashop = ?",
            (pid,),
        )
        conn.commit()
    finally:
        conn.close()


def check_inactive_pending(dry_run: bool = False) -> dict:
    """Check inactive products with stock (qty >= 1) for completeness.

    Complete products are marked with ``pendiente_activar = 1`` so they show
    up as "para activar" in the admin UI. Incomplete ones are auto-completed
    through the enrichment pipeline (mirrors active verification).

    Returns a dict with:
    - ``total``: total inactive products seen
    - ``with_stock``: number of inactive products with stock >= 1
    - ``complete``: number of complete products (incl. previously marked)
    - ``marked``: number of products newly marked as ready to activate
    - ``incomplete``: number of incomplete products
    - ``completed``: number of products auto-completed
    - ``failed``: number of products that failed to complete
    """
    from middleware.prestashop import PrestashopClient

    client = PrestashopClient()
    total = 0
    with_stock = 0
    complete_count = 0
    marked = 0
    incomplete_count = 0
    completed_count = 0
    failed_count = 0

    offset = 0
    limit = 50
    while True:
        products = client.get_inactive_products(limit=limit, offset=offset)
        if not products:
            break

        stock = client.get_stock_map([int(p["id"]) for p in products])

        for p in products:
            pid = int(p["id"])
            total += 1
            if stock.get(pid, 0) < 1:
                continue
            with_stock += 1
            name = p.get("name") or f"Product {pid}"

            # Skip products already marked as ready to activate
            conn_check = get_connection()
            try:
                row_check = conn_check.execute(
                    "SELECT pendiente_activar FROM productos WHERE id_prestashop = ?",
                    (pid,),
                ).fetchone()
                if row_check and row_check["pendiente_activar"]:
                    complete_count += 1
                    logger.debug("  SKIP  id=%d  %s — already marked for activation", pid, name)
                    continue
            finally:
                conn_check.close()

            pipeline_state.add_log(f"Verificando producto inactivo: {name} (id={pid})")

            completeness = check_product_completeness(pid)
            if completeness["is_complete"]:
                complete_count += 1
                logger.info("  OK  id=%d  %s — complete, marking for activation", pid, name)
                if not dry_run:
                    _mark_pending_activation(pid)
                    marked += 1
                else:
                    logger.info("  DRY RUN — would mark id=%d as ready to activate", pid)
            else:
                incomplete_count += 1
                logger.info(
                    "  INCOMPLETE  id=%d  %s — missing: %s",
                    pid, name, completeness["missing"],
                )

                if not dry_run:
                    success = complete_incomplete_product(pid, dry_run=False)
                    if success:
                        completed_count += 1
                        # Re-check after auto-completion; mark only if fully complete
                        recheck = check_product_completeness(pid)
                        if recheck["is_complete"]:
                            _mark_pending_activation(pid)
                            marked += 1
                        logger.info("  AUTO-COMPLETED  id=%d  %s", pid, name)
                    else:
                        failed_count += 1
                        logger.warning("  FAILED TO COMPLETE  id=%d  %s", pid, name)
                else:
                    logger.info("  DRY RUN — would complete id=%d  %s", pid, name)

        offset += limit

    result = {
        "total": total,
        "with_stock": with_stock,
        "complete": complete_count,
        "marked": marked,
        "incomplete": incomplete_count,
        "completed": completed_count,
        "failed": failed_count,
    }

    logger.info(
        "Inactive check complete: %d total, %d with stock, %d marked for activation, "
        "%d incomplete, %d auto-completed, %d failed",
        total, with_stock, marked, incomplete_count, completed_count, failed_count,
    )

    return result
