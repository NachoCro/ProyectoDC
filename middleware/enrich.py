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

from . import pipeline_state, plan
from .characteristics import build_description_html, merge_characteristics
from .config import BATCH_SIZE
from .db import get_connection, mark_not_found, write_eav
from .descriptions import get_description
from .embedding import embedding_to_bytes, generate_embedding, score_match
from .spec_extractors import is_template_placeholder, normalize_product, normalize_text
from .translate import translate_product

logger = logging.getLogger(__name__)


def _brands_match(a: str, b: str) -> bool:
    """¿Dos marcas representan la misma? (sub-marcas y variantes aceptadas).

    Ej: "Logitech G" == Logitech, "HP Inc" == HP, "Samsung Electronics" ==
    Samsung.
    """
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    a_words = set(a.replace("-", " ").split())
    b_words = set(b.replace("-", " ").split())
    if a_words & b_words:
        return True
    return (len(a) >= 3 and a in b) or (len(b) >= 3 and b in a)


def _validate_name_coherence(
    product_data: dict | None,
    nombre: str,
    marca_db: str,
    reference: str | None = None,
) -> bool:
    """Rechaza datos enriquecidos cuya marca contradiga el nombre original.

    Un producto "Smart TV Samsung UE55..." no puede quedar enriquecido como
    "Fravega": si el nombre tiene una marca reconocible (o la DB tiene marca),
    la marca resultante debe ser coherente con ella.  Un cambio drástico de
    identidad significa que se scrapeó el producto equivocado.
    """
    if not product_data or not nombre:
        return True

    from .official_scraper import _infer_brand_from_name

    # Marca de referencia: la inferida del nombre, o la de la BD.
    if reference is None:
        reference = _infer_brand_from_name(nombre) or marca_db.strip().lower() or None
    if not reference:
        return True

    scraped_marca = (product_data.get("marca") or "").strip()
    scraped_title = (product_data.get("title") or product_data.get("titulo") or "").strip()

    # Marca explícita del resultado scrapeado.
    if scraped_marca and not _brands_match(scraped_marca, reference):
        logger.warning(
            "  COHERENCE  marca extraída %r no coincide con la del nombre %r",
            scraped_marca, reference,
        )
        return False

    # Marca inferida del título scrapeado.
    if scraped_title:
        title_brand = _infer_brand_from_name(scraped_title)
        if title_brand and not _brands_match(title_brand, reference):
            logger.warning(
                "  COHERENCE  título %r sugiere marca %r distinta de %r",
                scraped_title[:60], title_brand, reference,
            )
            return False

    return True


def _build_description(product_data: dict, caracteristicas: list | None = None) -> str:
    """Build full description from characteristics as ``*nombre*: valor`` lines."""
    chars = caracteristicas or product_data.get("caracteristicas") or []
    return build_description_html(chars)


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
    # Normalize names/values (entities + mojibake) before they reach
    # PrestaShop features, the local EAV and the description.
    for ch in merged_caracteristicas:
        ch["nombre"] = normalize_text(ch.get("nombre") or "")
        ch["valor"] = normalize_text(ch.get("valor") or "")
    desc = _build_description(product_data, merged_caracteristicas)

    excel_desc = get_description(subcat_name)
    updates = {
        "description": desc,
        "description_short": normalize_text(excel_desc["descripcion_corta"]),
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

    # Marca de referencia: la inferida del nombre original, o la de la BD.
    # Se usa tanto para el chequeo de coherencia (check 4) como para decidir
    # cuán estricto es el matching de tokens (check 3): un producto genérico
    # sin marca ni código de modelo solo se acepta con solapamiento fuerte.
    from .official_scraper import _infer_brand_from_name
    reference_brand = _infer_brand_from_name(nombre) or marca.strip().lower() or None

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
    #
    # "soporte" is deliberately NOT in the list: in Spanish it also means
    # "mount/stand" (e.g. "SOPORTE TV DE 17 A 42" → TV mount), so it would
    # reject legitimate product pages.  English "support" is kept.
    scraped_url = (product_data.get("url") or product_data.get("source_url") or "").lower()
    scraped_title = (product_data.get("title") or product_data.get("titulo") or "").lower()

    junk_patterns = ('manual', 'manual de usuario', 'guia', 'guía', 'tutorial',
                     'support', 'faq', 'preguntas', 'solucion', 'troubleshoot',
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
    if scraped_title:
        import re as _re
        import unicodedata as _ud
        from difflib import SequenceMatcher as _SeqMatcher

        def _norm(s: str) -> str:
            s = _ud.normalize("NFKD", s.lower())
            return "".join(c for c in s if not _ud.combining(c))

        def _alnum(s: str) -> str:
            return "".join(c for c in _norm(s) if c.isalnum())

        nombre_lower = nombre.lower()

        # (letter+digit, e.g. "GND307", "DCP1617NW", "un75u").  Negative
        # lookbehind: "st15" must NOT fragment out of "nm-st15" (a hyphenated
        # part code is one token, not a "st" + "15" pair).
        model_tokens = [
            t for t in _re.findall(
                r'(?<![a-z0-9\-])[a-z]{2,}[-]?\d{1,}[a-z]{0,4}', nombre_lower,
            )
            if len(t) >= 3
        ]
        sig_words = [
            w for w in nombre_lower.split()
            if len(w) >= 3 and w not in (
                'impresora', 'monitor', 'smart', 'mouse', 'wireless', 'laser',
                'multifuncion', 'multifuncional', 'brother', 'logitech', 'samsung',
            )
        ]

        # Normalize: remove accents/dashes/spaces for flexible matching
        # (dcp-1617nw == dcp1617nw).
        scraped_norm = _alnum(scraped_title)

        matched_models = [t for t in model_tokens if _alnum(t) in scraped_norm]

        # (a) Si el nombre tiene un token tipo modelo (letras+digitos, p. ej.
        # GND307), es un identificador decisivo: al menos uno DEBE aparecer en
        # el título scrapeado.  Sin esto, "KIT DIAFRAGMA GND307" se enriquece
        # con una página de "GeForce RTX 3070".
        if model_tokens and not matched_models:
            logger.warning(
                "  VALIDATE  id=%d  model token missing: scraped_title=%r, expected_models=%s",
                pid, scraped_title[:80], model_tokens[:5],
            )
            return False

        matched_words = [w for w in sig_words if _alnum(w) in scraped_norm]

        # (b) Sin token tipo modelo, al menos una palabra significativa debe
        # coincidir.
        if not matched_models and not matched_words:
            logger.warning(
                "  VALIDATE  id=%d  no token match: scraped_title=%r, expected_tokens=%s",
                pid, scraped_title[:80], (sig_words or model_tokens)[:5],
            )
            return False

        # (c) Nombres genéricos (sin marca ni código de modelo) son ambiguos:
        # un solapamiento suelto de una palabra ("tapa"/"combustible") puede
        # caer en un producto no relacionado (p. ej. una tapa de registro de
        # camión cisterna).  Exigir solapamiento de palabras + similitud global.
        if not matched_models and not reference_brand:
            ratio = _SeqMatcher(None, _norm(nombre), _norm(scraped_title)).ratio()
            # ≥ 2 palabras coincidentes con similitud ≥ 0.40, o una coincidencia
            # con similitud alta.
            if not (
                (len(matched_words) >= 2 and ratio >= 0.40)
                or ratio >= 0.50
            ):
                logger.warning(
                    "  VALIDATE  id=%d  weak generic match ratio=%.2f words=%d: scraped_title=%r",
                    pid, ratio, len(matched_words), scraped_title[:80],
                )
                return False

    # Check 4: la marca enriquecida debe ser coherente con el nombre original.
    # Un "Smart TV Samsung" no puede quedar como "Fravega" (retailer).
    if not _validate_name_coherence(product_data, nombre, marca, reference=reference_brand):
        logger.warning(
            "  VALIDATE  id=%d  nombre/marca incoherentes — descartando", pid,
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

    # ── 0. Brand site search (official site → product page → scrape) ──────
    if marca and nombre and not dry_run:
        from .official_scraper import _search_brand_site, scrape_from_direct_url

        logger.info("  BRAND_SEARCH  id=%d  buscando en sitio de %s...", pid, marca)
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
        pipeline_state.add_log("Buscando con AI agent web search...")

        # When marca is empty, AI agent may return data from reseller pages with
        # no characteristics — require at least MIN_CHARS_WITHOUT_MARCA.  The
        # validator is passed in so enrich_with_ai skips rejected candidates and
        # keeps trying the next-ranked search result.
        MIN_CHARS_WITHOUT_MARCA = 5

        def _accept_ai(data: dict) -> bool:
            if marca:
                return _validate_scraped_data(data, marca, nombre, pid)
            return (
                len(data.get("caracteristicas") or []) >= MIN_CHARS_WITHOUT_MARCA
                and _validate_scraped_data(data, "", nombre, pid)
            )

        ai_data = enrich_with_ai(ai_marca, nombre, accept=_accept_ai)
        if ai_data is not None:
            ai_chars = len(ai_data.get("caracteristicas") or [])
            logger.info("  AI_AGENT  id=%d  succeeded (%d characteristics)", pid, ai_chars)
            pipeline_state.add_log(f"AI agent OK: {ai_chars} características extraídas")
            # Keep whichever source has more characteristics
            if brand_data_low:
                brand_chars = len((product_data or {}).get("caracteristicas") or [])
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
            _infer_brand_from_name,
            _search_brand_site,
            scrape_from_direct_url,
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
                pipeline_state.add_log("Brand site no encontrado, buscando con AI agent...")
                product_data = enrich_with_ai(
                    inferred_brand, nombre,
                    accept=lambda data: _validate_scraped_data(
                        data, inferred_brand, nombre, pid
                    ),
                )
                if product_data is not None:
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
            pipeline_state.add_log("Sin datos — sin marca ni nombre, marcando not_found")
            logger.info("  SKIP  id=%d  (no brand, no name) — marking not found", pid)
            if not dry_run:
                mark_not_found(pid)
        else:
            pipeline_state.add_log("Reintentar después — datos insuficientes")
            logger.warning("  RETRY-LATER  id=%d  (brand=%s name=%s)", pid, marca, nombre)
        return None, None, ""

    # Backfill marca/modelo from product name if scraper didn't find them
    if not product_data.get("marca") or not product_data.get("modelo"):
        from .official_scraper import _extract_model_from_name, _infer_brand_from_name
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


def run(dry_run: bool = False, override: dict | None = None) -> int:
    """Enrich pending products and push to PrestaShop.

    Two entry paths:
    - Products with existing data (stuck from previous runs)
      → parse existing data and push without re-fetching.
    - Products without data → fetch from brand site search / AI agent, then push.

    Not-found products are flagged ``product_not_found = 1`` and
    remain in the queue for manual URL enrichment via the Admin UI.

    ``override`` (opcional) es un dict ``{'subcategoria': str, 'cantidad': int}``
    para una ejecución única: se usa ESE objetivo en vez del plan configurado,
    sin modificarlo.  El override también puede traer ``'modo'``:

    - ``"publicar"`` (default): enriquece y **modifica** el producto en
      PrestaShop (descripción + características).
    - ``"preparar"``: enriquece y guarda la propuesta localmente sin tocar
      PrestaShop (``estado_actualizacion = 'pendiente_revision'``) para que la
      revise y acepte el usuario desde la página del producto.

    On success: ``estado_actualizacion = 'actualizado'``, EAV written, audit logged.
    On failure: data kept so admin UI can retry.
    """
    processed = 0

    plan_sub = (
        (override or {}).get("subcategoria")
        or plan.effective_subcategoria()
    )
    plan_limit = (
        (override or {}).get("cantidad")
        or plan.effective_cantidad(BATCH_SIZE)
    )
    # El override (ejecución única) gana; si no viene, se usa la opción
    # avanzada del plan.
    modo = (override or {}).get("modo") or plan.effective_modo()
    if modo not in ("publicar", "preparar"):
        modo = "publicar"
    conn = get_connection()
    try:
        objetivo = (
            plan.describe_target(conn, plan_sub, plan_limit)
            if override
            else plan.describe_plan(conn)
        )
        logger.info(
            "Plan de trabajo: %s (límite %d por ciclo)",
            objetivo, plan_limit,
        )
        query = """SELECT p.id_prestashop, p.ean, p.mpn, p.marca, p.modelo, p.nombre,
                      p.proposal_json, p.id_subcategoria,
                      COALESCE(s.nombre_subcategoria, '') AS subcat_name
               FROM productos p
               LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
               WHERE p.product_not_found = 0
                 AND p.estado_actualizacion = 'desactualizado'"""
        if override:
            # Ejecución única: procesar primero los productos recién extraídos
            # (mayor rowid), en vez de mezclarse con retries viejos del plan.
            query += " ORDER BY p.rowid DESC"
        params: list = []
        fetch_limit = plan_limit
        if plan_sub:
            # Filtro por similitud con el nombre del producto: se traen más
            # candidatos y se refinan en Python (SQLite no hace SequenceMatcher).
            from .plan import matches_name
            fetch_limit = max(plan_limit * 20, 200)
        query += " LIMIT ?"
        params.append(fetch_limit)

        rows = conn.execute(query, params).fetchall()

        if plan_sub:
            rows = [
                r for r in rows if matches_name(plan_sub, r["nombre"] or "")
            ][:plan_limit]

        if not rows:
            logger.info("No products pending enrichment")
            return 0

        if plan_sub and len(rows) < plan_limit:
            logger.warning(
                "  Solo %d producto(s) pendiente(s) coinciden con '%s' (se pidieron %d)",
                len(rows), plan_sub, plan_limit,
            )
            pipeline_state.add_log(
                f"Solo {len(rows)} producto(s) pendiente(s) coinciden con '{plan_sub}' "
                f"(se pidieron {plan_limit})"
            )

        logger.info("Processing %d products", len(rows))
        pipeline_state.start(len(rows), phase="Enriqueciendo productos")

        for i, row in enumerate(rows, 1):
            pid = row["id_prestashop"]
            ean = row["ean"]
            mpn = row["mpn"]
            marca = row["marca"] or ""
            modelo = row["modelo"] or ""
            nombre = row["nombre"] or ""

            pipeline_state.update(i, pid, nombre)
            logger.info(
                "  [%d/%d] Procesando id=%d — %s",
                i, len(rows), pid, nombre or "(sin nombre)",
            )

            existing_json = row["proposal_json"]
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
                # Los datos guardados pueden contener entidades HTML sin
                # decodificar o mojibake (Ã³ en vez de ó) de fuentes terceras —
                # normalizar antes de reutilizarlos o re-empujarlos.
                if parsed:
                    parsed = normalize_product(parsed)
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
                    # Guard de coherencia: no re-empujar datos cuya marca
                    # contradiga el nombre original (ej. "tele" → "Fravega").
                    if not _validate_name_coherence(parsed, nombre, marca):
                        stored_valid = False
                        logger.info(
                            "  EXISTING  id=%d  — stored data incoherent with name, re-scraping",
                            pid,
                        )
                        pipeline_state.add_log(
                            f"Datos guardados incoherentes con el nombre, re-scrapeando id={pid}"
                        )
                    # Guard de identidad: datos guardados de un scrapeo ajeno al
                    # producto (p. ej. "GeForce RTX 3070" para un diafragma)
                    # también se re-scrapean.
                    elif not _validate_scraped_data(parsed, marca, nombre, pid):
                        stored_valid = False
                        logger.info(
                            "  EXISTING  id=%d  — stored data wrong product, re-scraping",
                            pid,
                        )
                        pipeline_state.add_log(
                            f"Datos guardados no coinciden con el producto, re-scrapeando id={pid}"
                        )
                if stored_valid:
                    product_data = parsed
                    translated = parsed
                    logger.info(
                        "  EXISTING  id=%d  — pushing stored data (%d chars)",
                        pid,
                        len(parsed["caracteristicas"]),
                    )
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
                           SET proposal_json = ?,
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
                from .official_scraper import _extract_model_from_name, _infer_brand_from_name
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

                # ── Modo "preparar": guardar propuesta local, no tocar
                # PrestaShop.  El producto queda 'pendiente_revision' para que
                # el usuario lo revise/acepte desde la página del producto.
                if modo == "preparar":
                    merged_chars = merge_characteristics(
                        product_data.get("caracteristicas") or [], subcat_name,
                    )
                    for ch in merged_chars:
                        ch["nombre"] = normalize_text(ch.get("nombre") or "")
                        ch["valor"] = normalize_text(ch.get("valor") or "")

                    conn.execute(
                        """UPDATE productos
                           SET estado_actualizacion = 'pendiente_revision',
                               fecha_sincronizacion = datetime('now')
                           WHERE id_prestashop = ?""",
                        (pid,),
                    )
                    conn.commit()

                    write_eav(conn, pid, merged_chars)
                    conn.execute(
                        """INSERT INTO audit_log (id_producto, actor, accion, detalle)
                           VALUES (?, ?, ?, ?)""",
                        (pid, "pipeline", "preparado",
                         json.dumps({"marca": marca_final, "modelo": modelo_final},
                                    ensure_ascii=False)),
                    )
                    conn.commit()

                    processed += 1
                    pipeline_state.add_log(
                        f"PREPARADO id={pid} — {marca_final} {modelo_final} (pendiente de revisión)"
                    )
                    logger.info(
                        "  PREPARED  id=%d  marca=%s  modelo=%s  (no publicado)",
                        pid, marca_final, modelo_final,
                    )
                    continue

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
