"""Admin UI — Flask application (RF-11 … RF-14)."""

import json
import logging
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template, request, url_for

from middleware.db import get_connection, get_subcategoria_id, insert_product
from middleware.characteristics import merge_characteristics
from middleware.descriptions import get_description
from middleware.official_scraper import scrape_from_direct_url

from .prestashop import AdminPrestashopClient, PrestashopError

logger = logging.getLogger(__name__)

app = Flask(__name__)


# ======================================================================
# helpers
# ======================================================================

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _audit(conn, id_producto: int, actor: str, accion: str, detalle: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log (id_producto, actor, accion, detalle) VALUES (?, ?, ?, ?)",
        (id_producto, actor, accion, detalle),
    )


# ── pipeline lock ──────────────────────────────────────────────────────

_LOCK_KEY = "pipeline_lock"


def _is_pipeline_running() -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT valor FROM config WHERE clave = ?", (_LOCK_KEY,)
        ).fetchone()
        return row is not None and row["valor"] == "1"
    finally:
        conn.close()


def _acquire_pipeline_lock() -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT valor FROM config WHERE clave = ?", (_LOCK_KEY,)
        ).fetchone()
        if row and row["valor"] == "1":
            return False
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, '1')",
            (_LOCK_KEY,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _release_pipeline_lock() -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM config WHERE clave = ?", (_LOCK_KEY,))
        conn.commit()
    finally:
        conn.close()


# ======================================================================
# Dashboard  (RF-11)
# ======================================================================

@app.route("/")
def dashboard():
    from middleware.config import get_config

    conn = get_connection()
    try:
        pending = conn.execute(
            """SELECT COUNT(*) FROM productos
               WHERE estado_actualizacion = 'desactualizado'
                 AND product_not_found = 0"""
        ).fetchone()[0]

        listos = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE estado_actualizacion = 'actualizado'"
        ).fetchone()[0]

    finally:
        conn.close()

    # Parse pipeline_current: "2/5|123|Product Name" → (current, total, pid, name)
    pipeline_current_raw = get_config("pipeline_current", "")
    pipeline_current = None
    if pipeline_current_raw:
        try:
            parts = pipeline_current_raw.split("|")
            progress = parts[0].split("/")
            pipeline_current = {
                "current": int(progress[0]),
                "total": int(progress[1]),
                "pid": parts[1] if len(parts) > 1 else "",
                "name": parts[2] if len(parts) > 2 else "",
            }
        except (ValueError, IndexError):
            pipeline_current = None

    return render_template(
        "dashboard.html",
        pending=pending,
        listos=listos,
        pipeline_running=_is_pipeline_running(),
        pipeline_current=pipeline_current,
    )


@app.route("/api/pipeline-status")
def pipeline_status():
    """Return real-time pipeline state as JSON (polled by dashboard)."""
    from middleware.pipeline_state import get_state
    return jsonify(get_state())


# ======================================================================
# Product list  (RF-13)
# ======================================================================

@app.route("/products")
def products():
    status = request.args.get("status", "pending")

    conn = get_connection()
    try:
        query = """SELECT id_prestashop, ean, mpn, marca, modelo, nombre,
                          imagen_url, estado_actualizacion, product_not_found,
                          icecat_json IS NOT NULL AS tiene_propuesta
                   FROM productos"""

        if status == "pending":
            query += " WHERE icecat_json IS NOT NULL"
        elif status == "approved":
            query += " WHERE estado_actualizacion = 'actualizado'"
        elif status == "errors":
            query += " WHERE product_not_found = 1"
        elif status == "to_enrich":
            query += " WHERE icecat_json IS NULL AND product_not_found = 0 AND estado_actualizacion = 'desactualizado'"

        query += " ORDER BY id_prestashop DESC"

        rows = conn.execute(query).fetchall()
    finally:
        conn.close()

    return render_template("products.html", products=rows, current_status=status)


# ======================================================================
# Diff viewer  (RF-12)
# ======================================================================

@app.route("/products/<int:pid>/diff")
def diff(pid: int):
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT p.*, COALESCE(s.nombre_subcategoria, '') AS subcat_name
               FROM productos p
               LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
               WHERE p.id_prestashop = ?""", (pid,)
        ).fetchone()
        if row is None:
            return f"Producto {pid} no encontrado", 404

        product = dict(row)

        # Parse icecat_json for the diff view
        raw_json = product.get("icecat_json")
        proposal = None
        if raw_json:
            try:
                proposal = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            except (json.JSONDecodeError, TypeError):
                proposal = None

        # current characteristics from local DB
        curr_chars = conn.execute(
            """SELECT c.nombre_caracteristica, pc.valor
               FROM producto_caracteristicas pc
               JOIN caracteristicas c ON c.id_caracteristica = pc.id_caracteristica
               WHERE pc.id_prestashop = ?
               ORDER BY c.nombre_caracteristica""",
            (pid,),
        ).fetchall()
    finally:
        conn.close()

    return render_template(
        "diff.html",
        product=product,
        proposal=proposal,
        curr_chars=curr_chars,
    )


# ======================================================================
# Approve  (RF-13)
# ======================================================================

@app.route("/products/<int:pid>/approve", methods=["POST"])
def approve(pid: int):
    actor = request.form.get("actor", "admin")

    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT p.*, COALESCE(s.nombre_subcategoria, '') AS subcat_name
               FROM productos p
               LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
               WHERE p.id_prestashop = ?""", (pid,)
        ).fetchone()
        if row is None:
            return f"Producto {pid} no encontrado", 404

        product = dict(row)

        # Parse proposal from icecat_json
        raw_json = product.get("icecat_json")
        proposal = None
        if raw_json:
            try:
                proposal = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            except (json.JSONDecodeError, TypeError):
                proposal = None
        if proposal is None:
            return f"Producto {pid} no tiene datos pendientes", 400

        subcat_name = product.get("subcat_name") or ""

        # -- push to PrestaShop -------------------------------------------
        activate = request.form.get("activate", "0") == "1"

        # Build description from characteristics only:  *nombre*: valor
        chars = proposal.get("caracteristicas") or []
        merged_chars = merge_characteristics(chars, subcat_name)
        desc = ""
        if merged_chars:
            lines = "".join(
                f"<p><strong>{ch['nombre']}:</strong> {ch['valor']}</p>"
                for ch in merged_chars if ch.get("nombre") and ch.get("valor")
            )
            desc = f'<div class="caracteristicas">{lines}</div>'

        updates = {
            "description": desc,
            "description_short": get_description(subcat_name)["descripcion_corta"],
        }
        if activate:
            updates["active"] = "1"
        try:
            client = AdminPrestashopClient()

            # sync merged characteristics as PrestaShop features
            feature_pairs = client.sync_characteristics_as_features(merged_chars)

            client.put_product(pid, updates, feature_pairs=feature_pairs or None)

            # upload image if available
            imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""
            if imagen_url:
                img_id = client.upload_product_image(pid, imagen_url)
                if img_id is not None:
                    updates["imagen_subida"] = img_id
                else:
                    updates["imagen_subida"] = False
        except PrestashopError as exc:
            _audit(conn, pid, actor, "error", str(exc))
            conn.commit()
            return jsonify({"ok": False, "error": str(exc)}), 502

        # -- update local DB -----------------------------------------------
        marca_final = proposal.get("marca") or product["marca"]
        modelo_final = proposal.get("modelo") or product["modelo"]
        imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""

        conn.execute(
            """UPDATE productos
               SET marca = ?, modelo = ?,
                   estado_actualizacion = 'actualizado',
                   icecat_json = NULL,
                   imagen_url = ?,
                   fecha_sincronizacion = datetime('now')
               WHERE id_prestashop = ?""",
            (marca_final, modelo_final, imagen_url or None, pid),
        )

        # write merged characteristics locally (EAV)
        conn.execute(
            "DELETE FROM producto_caracteristicas WHERE id_prestashop = ?", (pid,)
        )
        for ch in merged_chars:
            nombre = ch.get("nombre", "").strip()
            valor = ch.get("valor", "").strip()
            if not nombre or not valor:
                continue

            # find or create characteristic entry in dictionary
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

        accion = "aprobado_y_activado" if activate else "aprobado"
        detalle = {
            "marca": marca_final,
            "modelo": modelo_final,
            "activate": activate,
        }
        img_status = updates.get("imagen_subida")
        if img_status is None:
            detalle["imagen"] = "sin_url"
        elif img_status is False:
            detalle["imagen"] = "fallo"
        else:
            detalle["imagen"] = f"ok_id_{img_status}"
        _audit(conn, pid, actor, accion,
               json.dumps(detalle, ensure_ascii=False))
        conn.commit()

        # Check completeness after activation and auto-complete if needed
        if activate:
            try:
                from middleware.check_active import check_product_completeness, complete_incomplete_product
                completeness = check_product_completeness(pid)
                if not completeness["is_complete"]:
                    logger.info(
                        "Product %d is incomplete after activation (missing: %s), auto-completing...",
                        pid, completeness["missing"]
                    )
                    complete_incomplete_product(pid, dry_run=False)
            except Exception as exc:
                logger.warning("Error checking completeness for product %d: %s", pid, exc)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({"ok": True, "redirect": url_for("products")})


# ======================================================================
# Reject  (RF-13)
# ======================================================================

@app.route("/products/<int:pid>/reject", methods=["POST"])
def reject(pid: int):
    actor = request.form.get("actor", "admin")

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE productos SET icecat_json = NULL WHERE id_prestashop = ?",
            (pid,),
        )
        _audit(conn, pid, actor, "rechazado")
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "redirect": url_for("products")})


# ======================================================================
# Force re-sync  (RF-13)
# ======================================================================

@app.route("/products/<int:pid>/re-sync", methods=["POST"])
def re_sync(pid: int):
    actor = request.form.get("actor", "admin")

    conn = get_connection()
    try:
        conn.execute(
            """UPDATE productos
               SET product_not_found = 0,
                   icecat_json = NULL,
                   estado_actualizacion = 'desactualizado'
               WHERE id_prestashop = ?""",
            (pid,),
        )
        _audit(conn, pid, actor, "re-sincronizado")
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "redirect": url_for("products")})


# ======================================================================
# Manual URL enrichment  (scrape_from_direct_url)
# ======================================================================

@app.route("/products/<int:pid>/scrape-url", methods=["POST"])
def scrape_url(pid: int):
    """Accept a verified official URL, scrape it, and save to DB."""
    actor = request.form.get("actor", "admin")
    url = (request.form.get("url") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "URL is required"}), 400

    # Basic URL validation
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "URL must start with http:// or https://"}), 400

    result = scrape_from_direct_url(url, pid)
    if result is None:
        return jsonify({"ok": False, "error": "Failed to scrape product data from URL"}), 502

    return jsonify({
        "ok": True,
        "redirect": url_for("diff", pid=pid),
        "message": f"Scraped {len(result.get('caracteristicas') or [])} characteristics",
    })


# ======================================================================
# Run enrichment pipeline
# ======================================================================

@app.route("/enrich", methods=["POST"])
def enrich():
    """Run the enrichment pipeline for pending products."""
    from middleware.enrich import run as enrich_run

    try:
        processed = enrich_run(dry_run=False)
    except Exception as exc:
        logger.error("Enrichment error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "processed": processed, "redirect": url_for("dashboard")})


# ======================================================================
# Run extraction pipeline
# ======================================================================

@app.route("/extract", methods=["POST"])
def extract():
    """Extract inactive products from PrestaShop into local DB."""
    if not _acquire_pipeline_lock():
        return jsonify({"ok": False, "error": "El pipeline ya está ejecutándose"}), 409
    from middleware.extract import run as extract_run
    try:
        try:
            inserted = extract_run(dry_run=False)
        except Exception as exc:
            logger.error("Extraction error: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True, "inserted": inserted, "redirect": url_for("dashboard")})
    finally:
        _release_pipeline_lock()


# ======================================================================
# Run full pipeline (extract + enrich, same as pipeline.py)
# ======================================================================

@app.route("/run-pipeline", methods=["POST"])
def run_pipeline():
    """Extract inactive products then enrich them — mirrors ``python pipeline.py``."""
    if not _acquire_pipeline_lock():
        return jsonify({"ok": False, "error": "El pipeline ya está ejecutándose"}), 409

    from middleware import pipeline_state
    from middleware.extract import run as extract_run
    from middleware.enrich import run as enrich_run

    def _run():
        try:
            extract_run(dry_run=False)
            enrich_run(dry_run=False)
        except Exception as exc:
            logger.error("Pipeline error: %s", exc)
            pipeline_state.add_log(f"ERROR: {exc}")
        finally:
            pipeline_state.finish()
            _release_pipeline_lock()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"ok": True, "redirect": url_for("dashboard")})


# ======================================================================
# Audit log  (RF-14)
# ======================================================================

@app.route("/audit")
def audit():
    page = request.args.get("page", 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        rows = conn.execute(
            """SELECT id, timestamp, id_producto, actor, accion, detalle
               FROM audit_log
               ORDER BY timestamp DESC
               LIMIT ? OFFSET ?""",
            (per_page, offset),
        ).fetchall()
    finally:
        conn.close()

    pages = (total + per_page - 1) // per_page

    return render_template(
        "audit.html",
        entries=rows,
        page=page,
        pages=pages,
        total=total,
    )


# ======================================================================
# Settings / Configuración
# ======================================================================

_SETTINGS_KEYS = [
    ("PRESTASHOP_API_URL", "PrestaShop API URL"),
    ("PRESTASHOP_API_KEY", "PrestaShop API Key"),
    ("BATCH_SIZE", "Batch Size"),
    ("API_SLEEP", "API Sleep (segundos)"),
    ("DAEMON_INTERVAL", "Daemon Interval (segundos)"),
]


@app.route("/settings", methods=["GET"])
def settings():
    from middleware.config import _get, DEFAULTS
    values = {}
    for key, label in _SETTINGS_KEYS:
        values[key] = {"label": label, "value": _get(key), "default": DEFAULTS.get(key, "")}
    saved = request.args.get("saved")
    return render_template("settings.html", fields=values, saved=saved)


@app.route("/settings", methods=["POST"])
def settings_save():
    from middleware.config import reload_db_config, DB_PATH
    conn = get_connection()
    try:
        for key, _ in _SETTINGS_KEYS:
            val = request.form.get(key, "").strip()
            conn.execute(
                "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
                (key, val),
            )
        conn.commit()
    finally:
        conn.close()
    reload_db_config()
    return redirect(url_for("settings", saved=1))


# ======================================================================
# Brands mapping
# ======================================================================

_BRANDS_PATH = __import__("pathlib").Path(__file__).resolve().parent.parent / "brands_mapping.json"


def _load_brands() -> dict:
    import json as _json
    with open(_BRANDS_PATH, encoding="utf-8") as f:
        return _json.load(f)


def _save_brands(data: dict) -> None:
    import json as _json
    with open(_BRANDS_PATH, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


@app.route("/brands")
def brands():
    data = _load_brands()
    sorted_brands = sorted(data.items(), key=lambda x: x[0].lower())
    saved = request.args.get("saved")
    deleted = request.args.get("deleted")
    return render_template("brands.html", brands=sorted_brands, saved=saved, deleted=deleted)


@app.route("/brands/add", methods=["POST"])
def brands_add():
    name = request.form.get("name", "").strip().lower()
    search_url = request.form.get("search_url", "").strip()
    result_selector = request.form.get("result_selector", "").strip()
    if not name or not search_url:
        return redirect(url_for("brands"))
    data = _load_brands()
    data[name] = {
        "search_url": search_url,
        "result_selector": result_selector or "a[href*='product'], .product-card a, a[class*='product']",
    }
    _save_brands(data)
    return redirect(url_for("brands", saved=name))


@app.route("/brands/delete", methods=["POST"])
def brands_delete():
    name = request.form.get("name", "").strip().lower()
    if name:
        data = _load_brands()
        data.pop(name, None)
        _save_brands(data)
    return redirect(url_for("brands", deleted=name))


@app.route("/brands/edit", methods=["POST"])
def brands_edit():
    name = request.form.get("name", "").strip().lower()
    search_url = request.form.get("search_url", "").strip()
    result_selector = request.form.get("result_selector", "").strip()
    if not name or not search_url:
        return redirect(url_for("brands"))
    data = _load_brands()
    if name not in data:
        return redirect(url_for("brands"))
    data[name] = {
        "search_url": search_url,
        "result_selector": result_selector or "a[href*='product'], .product-card a, a[class*='product']",
    }
    _save_brands(data)
    return redirect(url_for("brands", saved=name))


# ======================================================================
# Check active products completeness
# ======================================================================

@app.route("/check-active", methods=["POST"])
def check_active():
    """Check all active products for completeness and auto-complete incomplete ones."""
    if not _acquire_pipeline_lock():
        return jsonify({"ok": False, "error": "El pipeline ya está ejecutándose"}), 409

    from middleware.check_active import check_all_active
    from middleware import pipeline_state

    def _run():
        try:
            result = check_all_active(dry_run=False)
            pipeline_state.add_log(
                f"Verificación completada: {result['total']} productos, "
                f"{result['complete']} completos, {result['incomplete']} incompletos, "
                f"{result['completed']} auto-completados"
            )
        except Exception as exc:
            logger.error("Error checking active products: %s", exc)
            pipeline_state.add_log(f"ERROR: {exc}")
        finally:
            pipeline_state.finish()
            _release_pipeline_lock()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"ok": True, "redirect": url_for("dashboard")})
