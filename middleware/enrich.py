"""Enrichment pipeline: DB cache → brand site search → Icecat → translate → embed → score → store → push.

Automated pipeline tries sources in order:
1. Local DB (existing ``icecat_json`` from previous run)
2. Brand site search (official site → first product result → scrape)
3. Icecat (by EAN → Brand+MPN fallback)
4. AI agent (DuckDuckGo web search, last resort)

Manual URL enrichment is handled separately via the Admin UI
(``scrape_from_direct_url``).

Implements RF-06 (vector similarity scoring) and RF-07 (glossary-protected
translation).
"""

import json
import logging

from .config import BATCH_SIZE
from .db import get_connection, mark_not_found, mark_icecat_not_found
from .embedding import embedding_to_bytes, generate_embedding, score_match
from .icecat import IcecatClient, IcecatError
from .translate import translate_product
from .characteristics import merge_characteristics

logger = logging.getLogger(__name__)

_NOT_FOUND = object()
_TRANSIENT_ERROR = object()


def _try_fetch(
    icecat: IcecatClient,
    label: str,
    fetch_fn,
    dry_run: bool,
    pid: int,
) -> dict | None:
    """Call *fetch_fn*, returning data on success or sentinel on failure.

    Returns ``None`` when Icecat cleanly reports "not found".
    Returns ``_NOT_FOUND`` when we should mark ``product_not_found``.
    Returns ``_TRANSIENT_ERROR`` on transport / parse errors (retry next run).
    """
    try:
        data = fetch_fn()
    except IcecatError as exc:
        logger.error("  ERROR  id=%d  %s  %s", pid, label, exc)
        return _TRANSIENT_ERROR

    if data is None:
        logger.info("  NOT FOUND  id=%d  %s", pid, label)
        return _NOT_FOUND

    return data


def _build_description(icecat_data: dict, caracteristicas: list | None = None) -> str:
    """Build full description from characteristics as ``*nombre*: valor`` lines."""
    chars = caracteristicas or icecat_data.get("caracteristicas") or []
    if not chars:
        return ""
    lines = "".join(
        f"<p><strong>{ch['nombre']}:</strong> {ch['valor']}</p>"
        for ch in chars if ch.get("nombre") and ch.get("valor")
    )
    return f'<div class="caracteristicas">{lines}</div>'


def _write_eav(conn, pid: int, caracteristicas: list[dict]) -> None:
    """Write Icecat characteristics into local EAV tables."""
    conn.execute(
        "DELETE FROM producto_caracteristicas WHERE id_prestashop = ?", (pid,)
    )
    for ch in caracteristicas:
        nombre = ch.get("nombre", "").strip()
        valor = ch.get("valor", "").strip()
        if not nombre or not valor:
            continue
        row_c = conn.execute(
            "SELECT id_caracteristica FROM caracteristicas WHERE nombre_caracteristica = ?",
            (nombre,),
        ).fetchone()
        if row_c:
            cid = row_c["id_caracteristica"]
        else:
            cur = conn.execute(
                "INSERT INTO caracteristicas (nombre_caracteristica) VALUES (?)",
                (nombre,),
            )
            cid = cur.lastrowid
        conn.execute(
            "INSERT OR REPLACE INTO producto_caracteristicas "
            "(id_prestashop, id_caracteristica, valor) VALUES (?, ?, ?)",
            (pid, cid, valor),
        )


def _push_to_prestashop(
    conn,
    pid: int,
    icecat_data: dict,
    marca: str,
    modelo: str,
    subcat_name: str,
    dry_run: bool,
) -> bool:
    """Push enriched data to PrestaShop.

    On success updates local DB (estado_actualizacion, EAV, audit).
    On failure keeps ``icecat_json`` so the admin UI can retry.
    """
    if dry_run:
        return True

    from admin_ui.prestashop import AdminPrestashopClient, PrestashopError

    client = AdminPrestashopClient()

    # Merge Icecat characteristics with default template
    merged_caracteristicas = merge_characteristics(
        icecat_data.get("caracteristicas") or [], subcat_name,
    )
    desc = _build_description(icecat_data, merged_caracteristicas)
    updates = {
        "description": desc,
        "description_short": "",
    }

    # Look up PrestaShop category for this subcategory
    ps_category_id = None
    if subcat_name:
        row_cat = conn.execute(
            "SELECT id_prestashop_categoria FROM subcategorias WHERE nombre_subcategoria = ?",
            (subcat_name,),
        ).fetchone()
        if row_cat:
            ps_category_id = row_cat["id_prestashop_categoria"]

    try:
        feature_pairs = client.sync_characteristics_as_features(
            merged_caracteristicas
        )
        client.put_product(
            pid, updates,
            feature_pairs=feature_pairs or None,
            category_ids=[ps_category_id] if ps_category_id else None,
        )
    except PrestashopError as exc:
        logger.error("  PUSH FAILED  id=%d  %s", pid, exc)
        return False

    # Upload image (non-blocking)
    imagen_url = icecat_data.get("imagen_url") or ""
    if imagen_url:
        client.upload_product_image(pid, imagen_url)

    # Update local DB — approve and clear pending data
    conn.execute(
        """UPDATE productos
           SET estado_actualizacion = 'actualizado',
               icecat_json = NULL,
               fecha_sincronizacion = datetime('now')
           WHERE id_prestashop = ?""",
        (pid,),
    )

    # Write characteristics locally (merged list)
    _write_eav(conn, pid, merged_caracteristicas)

    # Audit log
    detalle = json.dumps({"marca": marca, "modelo": modelo}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO audit_log (id_producto, actor, accion, detalle) VALUES (?, ?, ?, ?)",
        (pid, "pipeline", "aprobado", detalle),
    )
    conn.commit()

    logger.info("  PUSHED  id=%d  marca=%s  modelo=%s", pid, marca, modelo)
    return True


def _fetch_and_prepare(
    icecat: IcecatClient,
    pid: int,
    ean: str | None,
    mpn: str | None,
    marca: str,
    modelo: str,
    nombre: str,
    dry_run: bool,
) -> tuple[dict | None, dict | None, str]:
    """Fetch product data and prepare translated + scored payload.

    Automated pipeline tries sources in order:
    1. Brand site search (official site → first product result → scrape)
    2. Icecat by EAN
    3. Icecat by Brand + MPN
    4. AI agent (web search + extraction, last resort before not-found)
    5. Name-only search (infer brand from product name, search brand site)
    6. not_found / icecat_not_found

    Returns ``(product_data, translated, icecat_desc)`` or
    ``(None, None, '')`` on failure.
    """
    product_data = None
    tried = False
    was_not_found = False

    # ── 0. Brand site search (official site → product page → scrape) ──────
    if marca and mpn and not dry_run:
        from .official_scraper import _search_brand_site, scrape_from_direct_url

        found_url = _search_brand_site(marca, mpn, nombre)
        if found_url:
            logger.info("  BRAND_SEARCH  id=%d  scraping %s", pid, found_url)
            product_data = scrape_from_direct_url(found_url, pid)
            if product_data is not None:
                n_chars = len(product_data.get("caracteristicas") or [])
                logger.info("  BRAND_SEARCH  id=%d  succeeded (%d characteristics)", pid, n_chars)

    # 1. Icecat by EAN
    if not product_data and ean:
        tried = True
        result = _try_fetch(
            icecat, f"EAN={ean}",
            lambda e=ean: icecat.get_product_by_ean(e),
            dry_run, pid,
        )
        if isinstance(result, dict):
            product_data = result
        elif result is _NOT_FOUND:
            was_not_found = True

    # 2. Icecat by Brand + MPN
    if not product_data and marca and mpn:
        tried = True
        result = _try_fetch(
            icecat, f"brand={marca} mpn={mpn}",
            lambda b=marca, m=mpn: icecat.get_product_by_brand_mpn(b, m),
            dry_run, pid,
        )
        if isinstance(result, dict):
            product_data = result
        elif result is _NOT_FOUND:
            was_not_found = True

    # ── 3. AI agent (web search + extraction, last resort before not-found) ──
    if not product_data and marca and mpn and not dry_run:
        from .ai_agent import enrich_with_ai

        logger.info("  AI_AGENT  id=%d  trying web search + extraction", pid)
        product_data = enrich_with_ai(marca, mpn, nombre)
        if product_data is not None:
            n_chars = len(product_data.get("caracteristicas") or [])
            logger.info("  AI_AGENT  id=%d  succeeded (%d characteristics)", pid, n_chars)

    # ── 4. Name-only search (no brand/MPN, but has a product name) ─────────
    if not product_data and nombre and not dry_run:
        from .official_scraper import (
            _infer_brand_from_name, _search_brand_site, scrape_from_direct_url,
        )

        inferred_brand = _infer_brand_from_name(nombre)
        if inferred_brand:
            logger.info(
                "  NAME_SEARCH  id=%d  inferred brand=%r from name=%r",
                pid, inferred_brand, nombre,
            )
            found_url = _search_brand_site(inferred_brand, mpn or "", nombre)
            if found_url:
                logger.info("  NAME_SEARCH  id=%d  scraping %s", pid, found_url)
                product_data = scrape_from_direct_url(found_url, pid)
                if product_data is not None:
                    n_chars = len(product_data.get("caracteristicas") or [])
                    logger.info(
                        "  NAME_SEARCH  id=%d  succeeded (%d characteristics)",
                        pid, n_chars,
                    )
        else:
            logger.debug(
                "  NAME_SEARCH  id=%d  no brand could be inferred from %r",
                pid, nombre,
            )

    if product_data is None:
        if not tried and not (marca and mpn):
            logger.info("  SKIP  id=%d  (no EAN, no MPN) — marking not found", pid)
            if not dry_run:
                mark_not_found(pid)
        elif was_not_found:
            logger.info("  NOT_FOUND  id=%d  (EAN=%s  brand=%s mpn=%s)", pid, ean, marca, mpn)
            if not dry_run:
                mark_icecat_not_found(pid)
        else:
            logger.warning("  RETRY-LATER  id=%d  (EAN=%s  brand=%s mpn=%s)", pid, ean, marca, mpn)
        return None, None, ""

    translated = translate_product(product_data)
    modelo_row = modelo or ""
    local_desc = f"{marca} {modelo_row}".strip()

    icecat_desc = " ".join(
        filter(None, [
            translated.get("Title") or translated.get("title")
            or translated.get("Titulo") or translated.get("titulo"),
            translated.get("Summary") or translated.get("summary")
            or translated.get("Resumen") or translated.get("resumen"),
            translated.get("Description") or translated.get("description")
            or translated.get("Descripcion") or translated.get("descripcion"),
        ])
    )

    similarity = score_match(local_desc, icecat_desc)
    translated["_score"] = round(similarity, 4)
    translated["_ean"] = ean or ""
    translated["_id_prestashop"] = pid

    return product_data, translated, icecat_desc


def run(dry_run: bool = False) -> int:
    """Enrich pending products via Icecat and push to PrestaShop.

    Two entry paths:
    - Products with ``icecat_json IS NULL`` → fetch data from Icecat, then push.
    - Products with ``icecat_json IS NOT NULL`` (stuck from previous runs)
      → parse existing data and push without re-fetching.

    Icecat-not-found products are flagged ``icecat_not_found = 1`` and
    remain in the queue for manual URL enrichment via the Admin UI.

    On success: ``estado_actualizacion = 'actualizado'``, EAV written, audit logged.
    On failure: ``icecat_json`` kept so admin UI can retry.
    """
    icecat = IcecatClient()
    processed = 0

    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT p.id_prestashop, p.ean, p.mpn, p.marca, p.modelo, p.nombre,
                      p.icecat_json, p.id_subcategoria,
                      COALESCE(s.nombre_subcategoria, '') AS subcat_name
               FROM productos p
               LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
               WHERE p.product_not_found = 0
                 AND p.icecat_not_found = 0
                 AND p.estado_actualizacion = 'desactualizado'
               LIMIT ?""",
            (BATCH_SIZE,),
        ).fetchall()

        if not rows:
            logger.info("No products pending enrichment")
            return 0

        logger.info("Processing %d products", len(rows))

        for row in rows:
            pid = row["id_prestashop"]
            ean = row["ean"]
            mpn = row["mpn"]
            marca = row["marca"] or ""
            modelo = row["modelo"] or ""
            nombre = row["nombre"] or ""

            existing_json = row["icecat_json"]
            icecat_data = None
            translated = None

            # ---- Path A: existing Icecat data (just push) -----------------
            if existing_json:
                try:
                    parsed = json.loads(existing_json) if isinstance(existing_json, str) else existing_json
                except (json.JSONDecodeError, TypeError):
                    parsed = None
                if parsed:
                    # Use stored data for push; icecat_data is the same payload
                    icecat_data = parsed
                    translated = parsed
                    logger.info("  EXISTING  id=%d  — pushing stored Icecat data", pid)

            # ---- Path B: fetch from Icecat --------------------------------
            if icecat_data is None:
                icecat_data, translated, icecat_desc = _fetch_and_prepare(
                    icecat, pid, ean, mpn, marca, modelo, nombre, dry_run,
                )
                if icecat_data is None:
                    continue

                # Store icecat_json + vector_descriptivo before pushing
                if not dry_run:
                    # Generate embedding from translated description
                    emb = generate_embedding(icecat_desc)
                    vec_bytes = embedding_to_bytes(emb) if emb is not None else None

                    conn.execute(
                        """UPDATE productos
                           SET icecat_json = ?,
                               vector_descriptivo = ?,
                               marca = ?,
                               modelo = ?,
                               imagen_url = ?
                           WHERE id_prestashop = ?""",
                        (
                            json.dumps(translated, ensure_ascii=False),
                            vec_bytes,
                            (icecat_data.get("marca") or "").strip() or marca,
                            (icecat_data.get("modelo") or "").strip() or modelo,
                            (icecat_data.get("imagen_url") or "").strip() or None,
                            pid,
                        ),
                    )
                    conn.commit()

            # ---- Push to PrestaShop ---------------------------------------
            marca_final = (icecat_data.get("marca") or "").strip() or marca
            modelo_final = (icecat_data.get("modelo") or "").strip() or modelo

            if not dry_run:
                if translated and "_score" not in translated:
                    modelo_row = modelo or ""
                    local_desc = f"{marca} {modelo_row}".strip()
                    icecat_desc = " ".join(filter(None, [
                        translated.get("Title") or translated.get("title"),
                        translated.get("Summary") or translated.get("summary"),
                        translated.get("Description") or translated.get("description"),
                    ]))
                    similarity = score_match(local_desc, icecat_desc)
                    translated["_score"] = round(similarity, 4)

                conn.execute(
                    """UPDATE productos
                       SET marca = ?,
                           modelo = ?,
                           imagen_url = ?,
                           fecha_sincronizacion = datetime('now')
                       WHERE id_prestashop = ?""",
                    (
                        marca_final,
                        modelo_final,
                        (icecat_data.get("imagen_url") or "").strip() or None,
                        pid,
                    ),
                )
                conn.commit()

                subcat_name = row["subcat_name"]
                push_ok = _push_to_prestashop(
                    conn, pid, icecat_data, marca_final, modelo_final,
                    subcat_name, dry_run,
                )
                if not push_ok:
                    logger.warning("  KEPT IN QUEUE  id=%d  (push failed, admin can retry)", pid)
                    continue

            processed += 1
            logger.info(
                "  COMPLETED  id=%d  marca=%s  modelo=%s  EAN=%s",
                pid, marca_final, modelo_final,
                ean or f"brand={marca} mpn={mpn}",
            )

    finally:
        conn.close()

    logger.info("Pipeline complete: %d products processed and pushed", processed)
    return processed
