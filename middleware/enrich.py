"""Enrichment pipeline: DB cache → brand site search → AI agent → translate → embed → score → store → push.

Automated pipeline tries sources in order:
1. Local DB (existing data from previous run)
2. Brand site search (official site → first product result → scrape)
3. AI agent (DuckDuckGo web search, last resort)

Manual URL enrichment is handled separately via the Admin UI
(``scrape_from_direct_url``).

Implements RF-06 (vector similarity scoring) and RF-07 (glossary-protected
translation).
"""

import json
import logging

from .config import BATCH_SIZE
from .db import get_connection, mark_not_found, write_eav
from .embedding import embedding_to_bytes, generate_embedding, score_match
from .translate import translate_product
from .characteristics import merge_characteristics
from .spec_extractors import is_template_placeholder
from .descriptions import get_description
from . import pipeline_state

logger = logging.getLogger(__name__)


def _build_description(product_data: dict, caracteristicas: list | None = None) -> str:
    """Build full description from characteristics as ``*nombre*: valor`` lines."""
    chars = caracteristicas or product_data.get("caracteristicas") or []
    if not chars:
        return ""
    lines = "".join(
        f"<p><strong>{ch['nombre']}:</strong> {ch['valor']}</p>"
        for ch in chars if ch.get("nombre") and ch.get("valor")
    )
    return f'<div class="caracteristicas">{lines}</div>'


def _push_to_prestashop(
    conn,
    pid: int,
    product_data: dict,
    marca: str,
    modelo: str,
    subcat_name: str,
    dry_run: bool,
) -> bool:
    """Push enriched data to PrestaShop.

    On success updates local DB (estado_actualizacion, EAV, audit).
    On failure keeps data so the admin UI can retry.
    """
    if dry_run:
        return True

    from admin_ui.prestashop import AdminPrestashopClient, PrestashopError

    client = AdminPrestashopClient()

    # Merge characteristics with default template
    merged_caracteristicas = merge_characteristics(
        product_data.get("caracteristicas") or [], subcat_name,
    )
    desc = _build_description(product_data, merged_caracteristicas)

    excel_desc = get_description(subcat_name)
    updates = {
        "description": desc,
        "description_short": excel_desc["descripcion_corta"],
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

    # Upload images (non-blocking)
    imagen_urls = product_data.get("imagen_urls") or []
    if imagen_urls:
        client.upload_product_images(pid, imagen_urls)
    elif product_data.get("imagen_url"):
        client.upload_product_image(pid, product_data["imagen_url"])

    # Update local DB — approve and clear pending data
    conn.execute(
        """UPDATE productos
           SET estado_actualizacion = 'actualizado',
               fecha_sincronizacion = datetime('now')
           WHERE id_prestashop = ?""",
        (pid,),
    )

    # Write characteristics locally (merged list)
    write_eav(conn, pid, merged_caracteristicas)

    # Audit log
    detalle = json.dumps({"marca": marca, "modelo": modelo}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO audit_log (id_producto, actor, accion, detalle) VALUES (?, ?, ?, ?)",
        (pid, "pipeline", "aprobado", detalle),
    )
    conn.commit()

    logger.info("  PUSHED  id=%d  marca=%s  modelo=%s", pid, marca, modelo)
    return True


def _validate_scraped_data(product_data: dict, marca: str, nombre: str, pid: int) -> bool:
    """Validate that scraped data corresponds to the expected product.

    Checks:
    1. Scraped brand matches expected brand (case-insensitive)
    2. Scraped title/name contains expected model number from product name

    Returns True if data looks correct, False if it should be rejected.
    """
    if not product_data:
        return False

    scraped_marca = (product_data.get("marca") or "").strip().lower()
    expected_marca = marca.strip().lower()

    def _brands_match(a: str, b: str) -> bool:
        if a == b:
            return True
        a_words = set(a.replace("-", " ").split())
        b_words = set(b.replace("-", " ").split())
        if a_words & b_words:
            return True
        return (len(a) >= 3 and a in b) or (len(b) >= 3 and b in a)

    # Check 1: brand must match (if both are present).  Sub-brand variants are
    # accepted: "Logitech G" == Logitech, "HP Inc" == HP, "Samsung Electronics"
    # == Samsung.
    if scraped_marca and expected_marca and not _brands_match(scraped_marca, expected_marca):
        logger.warning(
            "  VALIDATE  id=%d  brand mismatch: scraped=%r expected=%r",
            pid, scraped_marca, expected_marca,
        )
        return False

    # Check 2: reject manual/support/FAQ sites (not actual product pages).
    # Many brands host their authoritative specs on support/help subdomains
    # (support.logi.com/.../Technical-Specifications, support.hp.com specs),
    # so a "support" URL is only junk when it's NOT a specs page.  Pages whose
    # URL or title signals specifications are accepted.
    scraped_url = (product_data.get("url") or product_data.get("source_url") or "").lower()
    scraped_title = (product_data.get("title") or product_data.get("titulo") or "").lower()

    junk_patterns = ('manual', 'manual de usuario', 'guia', 'guía', 'tutorial',
                     'soporte', 'support', 'faq', 'preguntas', 'solucion', 'troubleshoot',
                     'service repair')
    spec_signals = ('specification', 'specs', 'especificacion', 'especificaciones',
                    'ficha tecnica', 'ficha-tecnica', 'technical-specification',
                    'technical specification', 'caracteristicas')
    def _is_specs_page(*texts: str) -> bool:
        return any(sig in t for t in texts for sig in spec_signals)

    if not _is_specs_page(scraped_url, scraped_title):
        if any(p in scraped_url for p in junk_patterns):
            logger.warning(
                "  VALIDATE  id=%d  rejected manual/support source: url=%r", pid, scraped_url[:120],
            )
            return False
    if any(p in scraped_title for p in junk_patterns) and not _is_specs_page(scraped_title):
        logger.warning(
            "  VALIDATE  id=%d  rejected manual/support title: %r", pid, scraped_title[:80],
        )
        return False

    # Check 2b: size disambiguation for TVs/monitors.  If the product name
    # specifies a size (e.g. 75") and the scraped title/specs mention a
    # different size, the scraper grabbed the wrong variant (55" U8000F vs
    # 75" U8000F share the same model tokens).  A size in the scraped title
    # that differs from the expected one is fatal.
    import re as _re
    wanted_size = _re.search(r"(\d{2})\s*(?:\"|''|pulgadas|inches|inch|')(?!\w)", nombre, _re.I)
    if wanted_size:
        wanted = wanted_size.group(1)
        scraped_size = _re.search(r"(\d{2})\s*(?:\"|''|pulgadas|inches|inch|')(?!\w)", scraped_title, _re.I)
        if scraped_size and scraped_size.group(1) != wanted:
            logger.warning(
                "  VALIDATE  id=%d  size mismatch: wanted %s\" scraped %s\" (title=%r)",
                pid, wanted, scraped_size.group(1), scraped_title[:80],
            )
            return False
        # Also check size inside characteristics if present.  Multi-variant
        # pages (Samsung, TCL, LG) list every size in the same DOM — e.g.
        # "tamaño = 50\"" body-text artifact alongside the correct
        # "Tamaño de pantalla = 75\"" — so a single mismatch is NOT fatal.
        # Reject only when NO size characteristic matches the wanted size
        # (i.e. the scraper grabbed a genuinely different variant).
        size_re = r"(\d{2})\s*(?:\"|''|pulgadas|inches|inch|')(?!\w)"
        wanted_re = _re.compile(rf"(?<![\d])({wanted})(?![\d])\s*(?:\"|''|pulgadas|inches|inch)", _re.I)
        size_names = ("tamaño de pantalla", "screen size", "pantalla", "tamaño", "size", "diagonal")
        size_exclude = ("paquete", "conjunto", "empaque", "caja", "pack", "stand", "dimensiones")
        sizes_found = []
        wanted_found = False
        for ch in (product_data.get("caracteristicas") or []):
            chv = str(ch.get("valor") or "")
            chn = str(ch.get("nombre") or "").lower()
            if not any(n in chn for n in size_names):
                continue
            if any(e in chn for e in size_exclude):
                continue
            if wanted_re.search(chv):
                wanted_found = True
            m = _re.search(size_re, chv, _re.I)
            if m:
                sizes_found.append(m.group(1))
        if sizes_found and not wanted_found:
            logger.warning(
                "  VALIDATE  id=%d  size mismatch in characteristics: wanted %s\" got sizes=%s",
                pid, wanted, sorted(set(sizes_found)),
            )
            return False

    # Check 3: scraped title should contain at least one significant token
    # from the expected product name (model number)
    nombre_lower = nombre.lower()

    if scraped_title:
        import re
        model_tokens = [
            t for t in re.findall(r'[a-z]{2,}[-]?\d{1,}[a-z]{0,4}', nombre_lower)
            if len(t) >= 3
        ]
        sig_words = [
            w for w in nombre_lower.split()
            if len(w) >= 3 and w not in (
                'impresora', 'monitor', 'smart', 'mouse', 'wireless', 'laser',
                'multifuncion', 'multifuncional', 'brother', 'logitech', 'samsung',
            )
        ]
        check_tokens = model_tokens + sig_words

        if check_tokens:
            # Normalize: remove dashes for flexible matching (dcp-1617nw == dcp1617nw)
            scraped_norm = scraped_title.replace('-', '').replace(' ', '')
            matches = sum(1 for t in check_tokens if t.replace('-', '') in scraped_norm)
            if matches == 0:
                logger.warning(
                    "  VALIDATE  id=%d  no token match: scraped_title=%r, expected_tokens=%s",
                    pid, scraped_title[:80], check_tokens[:5],
                )
                return False

    return True


def _fetch_and_prepare(
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
    2. AI agent (web search + extraction, last resort)
    3. Name-only search (infer brand from product name, search brand site)
    4. not_found

    Returns ``(product_data, translated, description)`` or
    ``(None, None, '')`` on failure.
    """
    product_data = None
    was_not_found = False

    # ── 0. Brand site search (official site → product page → scrape) ──────
    if marca and nombre and not dry_run:
        from .official_scraper import _search_brand_site, scrape_from_direct_url

        found_url = _search_brand_site(marca, nombre, pid)
        if found_url:
            logger.info("  BRAND_SEARCH  id=%d  scraping %s", pid, found_url)
            pipeline_state.add_log(f"Brand site encontrado, scrapeando: {found_url}")
            product_data = scrape_from_direct_url(found_url, pid)
            if product_data is not None:
                if not _validate_scraped_data(product_data, marca, nombre, pid):
                    logger.warning("  BRAND_SEARCH  id=%d  data rejected — wrong product", pid)
                    pipeline_state.add_log("Datos rechazados: no coincide con el producto esperado")
                    product_data = None
                else:
                    n_chars = len(product_data.get("caracteristicas") or [])
                    logger.info("  BRAND_SEARCH  id=%d  succeeded (%d characteristics)", pid, n_chars)
                    pipeline_state.add_log(f"Brand site OK: {n_chars} características extraídas")

    # ── 1. AI agent (web search + extraction) ─────────────────────────────
    # Try AI agent if: (a) brand site search failed, or (b) brand site returned
    # very few characteristics (< 10) — likely a JS-heavy page with limited data.
    MIN_CHARS_FOR_SUCCESS = 10
    brand_data_low = (
        product_data is not None
        and len(product_data.get("caracteristicas") or []) < MIN_CHARS_FOR_SUCCESS
    )
    if (not product_data or brand_data_low) and nombre and not dry_run:
        from .ai_agent import enrich_with_ai

        # Use marca if available, otherwise try with just the product name
        ai_marca = marca or ""
        logger.info("  AI_AGENT  id=%d  trying web search + extraction (marca=%r)", pid, ai_marca)
        pipeline_state.add_log(f"Buscando con AI agent web search...")
        ai_data = enrich_with_ai(ai_marca, nombre)
        if ai_data is not None:
            ai_chars = len(ai_data.get("caracteristicas") or [])
            logger.info("  AI_AGENT  id=%d  succeeded (%d characteristics)", pid, ai_chars)
            pipeline_state.add_log(f"AI agent OK: {ai_chars} características extraídas")
            # Validate AI data
            # When marca is empty, AI agent may return data from reseller pages with no characteristics
            # — require at least MIN_CHARS_FOR_SUCCESS characteristics to be useful
            MIN_CHARS_WITHOUT_MARCA = 5
            ai_valid = True
            if marca and not _validate_scraped_data(ai_data, marca, nombre, pid):
                ai_valid = False
            elif not marca and ai_chars < MIN_CHARS_WITHOUT_MARCA:
                ai_valid = False
                logger.info("  AI_AGENT  id=%d  data rejected — too few characteristics (%d) without brand", pid, ai_chars)
                pipeline_state.add_log(f"AI agent: solo {ai_chars} características, datos de página de reventa")
            if not ai_valid:
                logger.warning("  AI_AGENT  id=%d  data rejected — wrong product", pid)
                pipeline_state.add_log("AI agent: datos rechazados, no coincide con el producto")
            else:
                # Keep whichever source has more characteristics
                if brand_data_low:
                    brand_chars = len(product_data.get("caracteristicas") or [])
                    if ai_chars > brand_chars:
                        logger.info(
                            "  AI_AGENT  id=%d  replacing brand site result (%d > %d chars)",
                            pid, ai_chars, brand_chars,
                        )
                        product_data = ai_data
                    else:
                        logger.info(
                            "  AI_AGENT  id=%d  keeping brand site result (%d >= %d chars)",
                            pid, brand_chars, ai_chars,
                        )
                else:
                    product_data = ai_data

    # ── 2. Name-only search (no brand/MPN, but has a product name) ─────────
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
            found_url = _search_brand_site(inferred_brand, nombre, pid)
            if found_url:
                logger.info("  NAME_SEARCH  id=%d  scraping %s", pid, found_url)
                product_data = scrape_from_direct_url(found_url, pid)
                if product_data is not None:
                    if not _validate_scraped_data(product_data, inferred_brand, nombre, pid):
                        logger.warning("  NAME_SEARCH  id=%d  data rejected — wrong product", pid)
                        pipeline_state.add_log("Name search: datos rechazados, no coincide con el producto")
                        product_data = None
                    else:
                        n_chars = len(product_data.get("caracteristicas") or [])
                        logger.info(
                            "  NAME_SEARCH  id=%d  succeeded (%d characteristics)",
                            pid, n_chars,
                        )

            # Fallback: AI agent with inferred brand
            if not product_data:
                from .ai_agent import enrich_with_ai

                logger.info(
                    "  NAME_SEARCH  id=%d  brand site failed, trying AI agent with inferred brand=%r",
                    pid, inferred_brand,
                )
                pipeline_state.add_log(f"Brand site no encontrado, buscando con AI agent...")
                product_data = enrich_with_ai(inferred_brand, nombre)
                if product_data is not None:
                    if not _validate_scraped_data(product_data, inferred_brand, nombre, pid):
                        logger.warning("  NAME_SEARCH  id=%d  AI data rejected — wrong product", pid)
                        pipeline_state.add_log("AI agent: datos rechazados, no coincide con el producto")
                        product_data = None
                    else:
                        n_chars = len(product_data.get("caracteristicas") or [])
                        logger.info(
                            "  NAME_SEARCH  id=%d  AI agent succeeded (%d characteristics)",
                            pid, n_chars,
                        )
                        pipeline_state.add_log(f"AI agent OK: {n_chars} características extraídas")
        else:
            logger.debug(
                "  NAME_SEARCH  id=%d  no brand could be inferred from %r",
                pid, nombre,
            )

    if product_data is None:
        if not (marca or nombre):
            pipeline_state.add_log(f"Sin datos — sin marca ni nombre, marcando not_found")
            logger.info("  SKIP  id=%d  (no brand, no name) — marking not found", pid)
            if not dry_run:
                mark_not_found(pid)
        else:
            pipeline_state.add_log(f"Reintentar después — datos insuficientes")
            logger.warning("  RETRY-LATER  id=%d  (brand=%s name=%s)", pid, marca, nombre)
        return None, None, ""

    # Backfill marca/modelo from product name if scraper didn't find them
    if not product_data.get("marca") or not product_data.get("modelo"):
        from .official_scraper import _infer_brand_from_name, _extract_model_from_name
        if not product_data.get("marca") and nombre:
            inferred = _infer_brand_from_name(nombre)
            if inferred:
                product_data["marca"] = inferred.title()
        if not product_data.get("modelo") and nombre:
            model = _extract_model_from_name(nombre, product_data.get("marca") or "")
            if model:
                product_data["modelo"] = model

    translated = translate_product(product_data)
    modelo_row = modelo or ""
    local_desc = f"{marca} {modelo_row}".strip()

    description = " ".join(
        filter(None, [
            translated.get("Title") or translated.get("title")
            or translated.get("Titulo") or translated.get("titulo"),
            translated.get("Summary") or translated.get("summary")
            or translated.get("Resumen") or translated.get("resumen"),
            translated.get("Description") or translated.get("description")
            or translated.get("Descripcion") or translated.get("descripcion"),
        ])
    )

    similarity = score_match(local_desc, description)
    translated["_score"] = round(similarity, 4)
    translated["_ean"] = ean or ""
    translated["_id_prestashop"] = pid

    return product_data, translated, description


def run(dry_run: bool = False) -> int:
    """Enrich pending products and push to PrestaShop.

    Two entry paths:
    - Products with existing data (stuck from previous runs)
      → parse existing data and push without re-fetching.
    - Products without data → fetch from brand site search / AI agent, then push.

    Not-found products are flagged ``product_not_found = 1`` and
    remain in the queue for manual URL enrichment via the Admin UI.

    On success: ``estado_actualizacion = 'actualizado'``, EAV written, audit logged.
    On failure: data kept so admin UI can retry.
    """
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
                 AND p.estado_actualizacion = 'desactualizado'
               LIMIT ?""",
            (BATCH_SIZE,),
        ).fetchall()

        if not rows:
            logger.info("No products pending enrichment")
            return 0

        logger.info("Processing %d products", len(rows))
        pipeline_state.start(len(rows))

        for i, row in enumerate(rows, 1):
            pid = row["id_prestashop"]
            ean = row["ean"]
            mpn = row["mpn"]
            marca = row["marca"] or ""
            modelo = row["modelo"] or ""
            nombre = row["nombre"] or ""

            pipeline_state.update(i, pid, nombre)

            existing_json = row["icecat_json"]
            product_data = None
            translated = None

            # ---- Path A: existing data (just push) -------------------------
            # Only reuse stored data if it has actual characteristics.
            # Empty characteristics means the previous scrape failed to extract
            # specs — re-scrape instead of pushing empty data.  Stored data
            # whose characteristics are JS template placeholders ({{...}}) is
            # garbage and must be re-scraped too.
            if existing_json:
                try:
                    parsed = json.loads(existing_json) if isinstance(existing_json, str) else existing_json
                except (json.JSONDecodeError, TypeError):
                    parsed = None
                stored_valid = False
                if parsed and parsed.get("caracteristicas"):
                    stored_chars = parsed["caracteristicas"]
                    clean_chars = [
                        c for c in stored_chars
                        if not is_template_placeholder(str(c.get("nombre", "")))
                        and not is_template_placeholder(str(c.get("valor", "")))
                    ]
                    stored_valid = bool(clean_chars)
                if stored_valid:
                    product_data = parsed
                    translated = parsed
                    logger.info("  EXISTING  id=%d  — pushing stored data (%d chars)", pid, len(parsed["caracteristicas"]))
                    pipeline_state.add_log(f"Usando datos guardados para id={pid}")
                elif parsed:
                    logger.info("  EXISTING  id=%d  — stored data unusable, re-scraping", pid)
                    pipeline_state.add_log(f"Datos guardados no válidos, re-scrapeando id={pid}")

            # ---- Path B: fetch from brand site / AI agent ------------------
            if product_data is None:
                product_data, translated, description = _fetch_and_prepare(
                    pid, ean, mpn, marca, modelo, nombre, dry_run,
                )
                if product_data is None:
                    pipeline_state.add_log(f"Sin datos para id={pid}, saltando")
                    continue

                # Store data + vector_descriptivo before pushing
                if not dry_run:
                    emb = generate_embedding(description)
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
                            (product_data.get("marca") or "").strip() or marca,
                            (product_data.get("modelo") or "").strip() or modelo,
                            (product_data.get("imagen_url") or "").strip() or None,
                            pid,
                        ),
                    )
                    conn.commit()

            # ---- Push to PrestaShop ---------------------------------------
            marca_final = (product_data.get("marca") or "").strip() or marca
            modelo_final = (product_data.get("modelo") or "").strip() or modelo

            # Backfill from product name if still empty
            if not marca_final or not modelo_final:
                from .official_scraper import _infer_brand_from_name, _extract_model_from_name
                if not marca_final and nombre:
                    inferred = _infer_brand_from_name(nombre)
                    if inferred:
                        marca_final = inferred.title()
                if not modelo_final and nombre:
                    model = _extract_model_from_name(nombre, marca_final)
                    if model:
                        modelo_final = model

            if not dry_run:
                if translated and "_score" not in translated:
                    modelo_row = modelo or ""
                    local_desc = f"{marca} {modelo_row}".strip()
                    description = " ".join(filter(None, [
                        translated.get("Title") or translated.get("title"),
                        translated.get("Summary") or translated.get("summary"),
                        translated.get("Description") or translated.get("description"),
                    ]))
                    similarity = score_match(local_desc, description)
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
                        (product_data.get("imagen_url") or "").strip() or None,
                        pid,
                    ),
                )
                conn.commit()

                subcat_name = row["subcat_name"]
                pipeline_state.add_log(f"Enviando a PrestaShop id={pid}...")
                push_ok = _push_to_prestashop(
                    conn, pid, product_data, marca_final, modelo_final,
                    subcat_name, dry_run,
                )
                if not push_ok:
                    pipeline_state.add_log(f"FALLO push id={pid} — en cola para reintento")
                    logger.warning("  KEPT IN QUEUE  id=%d  (push failed, admin can retry)", pid)
                    continue

            processed += 1
            pipeline_state.add_log(f"COMPLETADO id={pid} — {marca_final} {modelo_final}")
            logger.info(
                "  COMPLETED  id=%d  marca=%s  modelo=%s  EAN=%s",
                pid, marca_final, modelo_final,
                ean or f"brand={marca} mpn={mpn}",
            )

    finally:
        pipeline_state.finish()
        conn.close()

    logger.info("Pipeline complete: %d products processed and pushed", processed)
    return processed
