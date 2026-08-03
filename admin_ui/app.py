"""Admin UI — Flask application (RF-11 … RF-14)."""

import json
import logging
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template, request, url_for

from middleware.config import DAEMON_INTERVAL
from middleware.db import get_connection, write_eav
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

        para_activar = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE pendiente_activar = 1"
        ).fetchone()[0]

        activos = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE active_verified = 1"
        ).fetchone()[0]

    finally:
        conn.close()

    from middleware.daemon_state import get_state
    daemon = get_state()

    return render_template(
        "dashboard.html",
        pending=pending,
        listos=listos,
        para_activar=para_activar,
        activos=activos,
        daemon=daemon,
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
                          pendiente_activar,
                          icecat_json IS NOT NULL AS tiene_propuesta
                   FROM productos"""

        if status == "pending":
            query += " WHERE icecat_json IS NOT NULL"
        elif status == "to_activate":
            query += " WHERE pendiente_activar = 1"
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

            # upload images if available
            imagen_urls = proposal.get("imagen_urls") or []
            if imagen_urls:
                uploaded_ids = client.upload_product_images(pid, imagen_urls)
                if uploaded_ids:
                    updates["imagen_subida"] = uploaded_ids[0]
                else:
                    updates["imagen_subida"] = False
            else:
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

        if activate:
            conn.execute(
                "UPDATE productos SET pendiente_activar = 0 WHERE id_prestashop = ?",
                (pid,),
            )

        # write merged characteristics locally (EAV)
        write_eav(conn, pid, merged_chars)

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

    return jsonify({"ok": True, "redirect": url_for("diff", pid=pid)})


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

    return jsonify({"ok": True, "redirect": url_for("diff", pid=pid)})


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

    return jsonify({"ok": True, "redirect": url_for("diff", pid=pid)})


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
        cleared=request.args.get("cleared") == "1",
    )


@app.route("/audit/clear", methods=["POST"])
def audit_clear():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM audit_log")
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("audit", cleared=1))


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
    has_pdf = request.form.get("has_pdf") == "1"
    if not name or not search_url:
        return redirect(url_for("brands"))
    data = _load_brands()
    data[name] = {
        "search_url": search_url,
        "result_selector": result_selector or "a[href*='product'], .product-card a, a[class*='product']",
        "has_pdf": has_pdf,
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
    has_pdf = request.form.get("has_pdf") == "1"
    if not name or not search_url:
        return redirect(url_for("brands"))
    data = _load_brands()
    if name not in data:
        return redirect(url_for("brands"))
    data[name] = {
        "search_url": search_url,
        "result_selector": result_selector or "a[href*='product'], .product-card a, a[class*='product']",
        "has_pdf": has_pdf,
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


# ======================================================================
# Daemon control
# ======================================================================

_daemon_process = None


@app.route("/api/daemon-status")
def daemon_status():
    """Return daemon state as JSON (polled by dashboard)."""
    from middleware.daemon_state import get_state
    return jsonify(get_state())


@app.route("/start-daemon", methods=["POST"])
def start_daemon():
    """Start the daemon as a background subprocess."""
    global _daemon_process

    from middleware.daemon_state import get_state
    state = get_state()
    if state["running"]:
        return jsonify({"ok": False, "error": "El daemon ya está ejecutándose"}), 409

    import subprocess
    import sys
    import os

    interval = request.form.get("interval", type=int) or DAEMON_INTERVAL
    dry_run = request.form.get("dry_run", "0") == "1"
    check_inactive = request.form.get("check_inactive", "0") == "1"

    cmd = [sys.executable, "daemon.py", "--interval", str(interval)]
    if check_inactive:
        cmd.append("--check-inactive")
    if dry_run:
        cmd.append("--dry-run")
    if request.form.get("verbose", "0") == "1":
        cmd.append("-v")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            start_new_session=True,
        )
        _daemon_process = proc

        # Write initial state to SQLite so the UI sees it immediately
        from middleware.daemon_state import start as ds_start, set_pid
        ds_start(interval, dry_run, check_inactive)
        set_pid(proc.pid)

        logger.info("Daemon started with PID %d", proc.pid)
        return jsonify({"ok": True, "pid": proc.pid})
    except Exception as exc:
        logger.error("Failed to start daemon: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/stop-daemon", methods=["POST"])
def stop_daemon():
    """Stop the daemon process."""
    global _daemon_process

    from middleware.daemon_state import get_state, stop as ds_stop
    state = get_state()

    if not state["running"] and _daemon_process is None:
        return jsonify({"ok": False, "error": "El daemon no está ejecutándose"}), 400

    # Try to stop via stored PID
    pid = state.get("pid") or (_daemon_process.pid if _daemon_process else None)
    if pid:
        try:
            import os
            import signal
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to daemon PID %d", pid)
        except (ProcessLookupError, PermissionError):
            pass

    # Write stopped state to SQLite immediately
    ds_stop()
    _daemon_process = None
    return jsonify({"ok": True})
