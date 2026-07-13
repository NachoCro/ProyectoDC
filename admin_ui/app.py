"""Admin UI — Flask application (RF-11 … RF-14)."""

import json
import logging
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template, request, url_for

from middleware.db import get_connection, get_subcategoria_id, insert_product
from middleware.characteristics import merge_characteristics
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


def _parse_icecat(product: dict) -> dict | None:
    raw = product.get("icecat_json")
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# ======================================================================
# Dashboard  (RF-11)
# ======================================================================

@app.route("/")
def dashboard():
    conn = get_connection()
    try:
        queue = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE icecat_json IS NOT NULL"
        ).fetchone()[0]

        pending_enrichment = conn.execute(
            """SELECT COUNT(*) FROM productos
               WHERE icecat_json IS NULL AND product_not_found = 0
                 AND icecat_not_found = 0
                 AND estado_actualizacion = 'desactualizado'"""
        ).fetchone()[0]

        icecat_not_found = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE icecat_not_found = 1"
        ).fetchone()[0]

        pending_24h = conn.execute(
            """SELECT COUNT(*) FROM audit_log
               WHERE accion = 'aprobado' AND timestamp >= datetime('now', '-1 day')""",
        ).fetchone()[0]

        errors_24h = conn.execute(
            """SELECT COUNT(*) FROM audit_log
               WHERE accion = 'error' AND timestamp >= datetime('now', '-1 day')""",
        ).fetchone()[0]

        total_aprobados = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE estado_actualizacion = 'actualizado'"
        ).fetchone()[0]

        total_products = conn.execute(
            "SELECT COUNT(*) FROM productos"
        ).fetchone()[0]

        alerts = conn.execute(
            """SELECT id_producto, timestamp, detalle
               FROM audit_log WHERE accion = 'error'
               ORDER BY timestamp DESC LIMIT 10"""
        ).fetchall()

        completados_hoy = conn.execute(
            """SELECT COUNT(*) FROM audit_log
               WHERE accion = 'aprobado' AND timestamp >= ?""",
            (_today(),),
        ).fetchone()[0]

    finally:
        conn.close()

    return render_template(
        "dashboard.html",
        queue=queue,
        pending_enrichment=pending_enrichment,
        icecat_not_found=icecat_not_found,
        pending_24h=pending_24h,
        errors_24h=errors_24h,
        total_aprobados=total_aprobados,
        total_products=total_products,
        alerts=alerts,
        completados_hoy=completados_hoy,
    )


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
        elif status == "icecat_not_found":
            query += " WHERE icecat_not_found = 1"
        elif status == "approved":
            query += " WHERE estado_actualizacion = 'actualizado'"
        elif status == "errors":
            query += " WHERE product_not_found = 1"
        elif status == "to_enrich":
            query += " WHERE icecat_json IS NULL AND product_not_found = 0 AND icecat_not_found = 0 AND estado_actualizacion = 'desactualizado'"

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
        icecat = _parse_icecat(product)

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
        icecat=icecat,
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
        icecat = _parse_icecat(product)
        if icecat is None:
            return f"Producto {pid} no tiene datos Icecat pendientes", 400

        subcat_name = product.get("subcat_name") or ""

        # -- push to PrestaShop -------------------------------------------
        activate = request.form.get("activate", "0") == "1"

        # Build description from characteristics only:  *nombre*: valor
        chars = icecat.get("caracteristicas") or []
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
            "description_short": "",
        }
        if activate:
            updates["active"] = "1"
        try:
            client = AdminPrestashopClient()

            # sync merged characteristics as PrestaShop features
            feature_pairs = client.sync_characteristics_as_features(merged_chars)

            client.put_product(pid, updates, feature_pairs=feature_pairs or None)

            # upload image if available
            imagen_url = icecat.get("imagen_url") or product.get("imagen_url") or ""
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
        marca_icecat = icecat.get("marca") or product["marca"]
        modelo_icecat = icecat.get("modelo") or product["modelo"]
        imagen_url = icecat.get("imagen_url") or product.get("imagen_url") or ""

        conn.execute(
            """UPDATE productos
               SET marca = ?, modelo = ?,
                   estado_actualizacion = 'actualizado',
                   icecat_json = NULL,
                   imagen_url = ?,
                   fecha_sincronizacion = datetime('now')
               WHERE id_prestashop = ?""",
            (marca_icecat, modelo_icecat, imagen_url or None, pid),
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
            "marca": marca_icecat,
            "modelo": modelo_icecat,
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
                   icecat_not_found = 0,
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
    """Run the Icecat enrichment pipeline for pending products."""
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
    from middleware.extract import run as extract_run

    try:
        inserted = extract_run(dry_run=False)
    except Exception as exc:
        logger.error("Extraction error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "inserted": inserted, "redirect": url_for("dashboard")})


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
