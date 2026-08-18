"""Admin UI — Flask application (RF-11 … RF-14)."""

import json
import logging
import os
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from middleware.characteristics import build_description_html, merge_characteristics
from middleware.config import DAEMON_INTERVAL
from middleware.db import get_connection, write_eav
from middleware.descriptions import get_description
from middleware.official_scraper import scrape_from_direct_url
from middleware.spec_extractors import normalize_product, normalize_text
from middleware.users import verify_user

from .prestashop import AdminPrestashopClient, PrestashopError

logger = logging.getLogger(__name__)

app = Flask(__name__)


def _load_secret_key() -> str:
    """Clave de sesión: env SECRET_KEY → config DB → aleatoria persistida."""
    from middleware.config import get_config, set_config

    key = os.getenv("SECRET_KEY") or get_config("SECRET_KEY")
    if key:
        return key
    key = secrets.token_hex(32)
    try:
        set_config("SECRET_KEY", key)
    except Exception:
        logger.warning("No se pudo persistir SECRET_KEY; las sesiones se invalidan al reiniciar")
    return key


app.secret_key = _load_secret_key()


@app.after_request
def _no_cache_api(resp):
    """Desactivar cache del navegador en endpoints JSON (polling en vivo)."""
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp


# ======================================================================
# Autenticación (login + roles)
# ======================================================================

_PUBLIC_ENDPOINTS = {"login", "logout", "static"}


@app.context_processor
def _inject_current_user():
    return {
        "current_user": session.get("usuario"),
        "current_role": session.get("rol"),
    }


@app.before_request
def _require_login():
    """Bloquear toda la UI salvo login/logout/static si no hay sesión.

    Los endpoints /api/* responden 401 JSON (para el polling); el resto
    redirige al login.
    """
    from middleware.users import count_users

    if request.endpoint in _PUBLIC_ENDPOINTS:
        return None

    if session.get("usuario"):
        if request.method == "POST" and session.get("rol") == "lectura":
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Permiso de solo lectura."}), 403
            return "Tu usuario tiene permiso de solo lectura.", 403
        return None

    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "No autenticado."}), 401

    # Sin usuarios todavía → primera configuración: crear el admin inicial
    if count_users() == 0:
        return redirect(url_for("setup"))
    return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    from middleware.users import count_users

    if session.get("usuario"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        user = verify_user(request.form.get("usuario", ""), request.form.get("clave", ""))
        if user:
            session.clear()
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            next_url = request.form.get("next") or ""
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        error = "Usuario o contraseña incorrectos."

    return render_template(
        "login.html",
        error=error,
        hay_usuarios=count_users() > 0,
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Primera configuración: crear el usuario admin inicial (solo sin usuarios)."""
    from middleware.users import count_users, create_user

    if count_users() > 0:
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        clave2 = request.form.get("clave2", "")
        if not usuario or not clave:
            error = "Completá usuario y contraseña."
        elif clave != clave2:
            error = "Las contraseñas no coinciden."
        else:
            ok, err = create_user(usuario, clave, "admin")
            if ok:
                session["usuario"] = usuario
                session["rol"] = "admin"
                return redirect(url_for("dashboard"))
            error = err
    return render_template("setup.html", error=error)


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


def _lock_held(conn) -> bool:
    """¿El lock está tomado por un proceso vivo?

    El valor guarda el PID del proceso que tomó el lock. Si ese PID ya no
    existe (el admin se cortó en medio de un pipeline), el lock es obsoleto
    y se puede tomar. El valor legacy ``'1'`` se trata como tomado.
    """
    row = conn.execute(
        "SELECT valor FROM config WHERE clave = ?", (_LOCK_KEY,)
    ).fetchone()
    if row is None:
        return False
    value = row["valor"]
    if value == "1":
        # Legacy: lo escribió el código viejo (sin PID). Como ese proceso
        # ya no corre código nuevo, no se puede verificar → se asume
        # obsoleto y se puede re-tomar.
        return False
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return True
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _is_pipeline_running() -> bool:
    conn = get_connection()
    try:
        return _lock_held(conn)
    finally:
        conn.close()


def _acquire_pipeline_lock() -> bool:
    conn = get_connection()
    try:
        if _lock_held(conn):
            return False
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
            (_LOCK_KEY, str(os.getpid())),
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

    conn = get_connection()
    try:
        pending = conn.execute(
            """SELECT COUNT(*) FROM productos
               WHERE estado_actualizacion IN ('desactualizado', 'pendiente_revision')
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

        from middleware import plan
        plan_today = plan.get_today_plan()
        plan_label = plan.describe_plan(conn)

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
        plan_today=plan_today,
        plan_label=plan_label,
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
                          proposal_json IS NOT NULL AS tiene_propuesta
                   FROM productos"""

        if status == "pending":
            query += " WHERE proposal_json IS NOT NULL"
        elif status == "to_activate":
            query += " WHERE pendiente_activar = 1"
        elif status == "approved":
            query += " WHERE estado_actualizacion = 'actualizado'"
        elif status == "errors":
            query += " WHERE product_not_found = 1"
        elif status == "to_enrich":
            query += (
                " WHERE proposal_json IS NULL AND product_not_found = 0"
                " AND estado_actualizacion = 'desactualizado'"
            )

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

        # Parse proposal_json for the diff view
        raw_json = product.get("proposal_json")
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
    actor = request.form.get("actor", session.get("usuario") or "admin")

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

        # Parse proposal from proposal_json
        raw_json = product.get("proposal_json")
        proposal = None
        if raw_json:
            try:
                proposal = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            except (json.JSONDecodeError, TypeError):
                proposal = None
        if proposal is None:
            return f"Producto {pid} no tiene datos pendientes", 400

        subcat_name = product.get("subcat_name") or ""

        # -- apply characteristics edited in the diff form ------------------
        # The diff template posts char_name[]/char_value[] pairs; if the form
        # was used, the user's edits override the proposal's characteristics.
        edited_names = request.form.getlist("char_name[]")
        edited_values = request.form.getlist("char_value[]")
        if edited_names:
            edited_chars = []
            for name, value in zip(edited_names, edited_values):
                name = (name or "").strip()
                value = (value or "").strip()
                if not name and not value:
                    continue
                if not name:
                    name = "Característica"
                edited_chars.append({"nombre": name, "valor": value})
            proposal["caracteristicas"] = edited_chars

        # -- push to PrestaShop -------------------------------------------
        activate = request.form.get("activate", "0") == "1"

        # Normalize entity-coded / mojibake text before it reaches PrestaShop.
        proposal = normalize_product(proposal)

        # Build description from characteristics only:  *nombre*: valor
        chars = proposal.get("caracteristicas") or []
        merged_chars = merge_characteristics(chars, subcat_name)
        desc = build_description_html(merged_chars)

        updates: dict[str, Any] = {
            "description": desc,
            "description_short": normalize_text(
                get_description(subcat_name)["descripcion_corta"]
            ),
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
                   proposal_json = NULL,
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
                from middleware.check_active import (
                    check_product_completeness,
                    complete_incomplete_product,
                )
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
    actor = request.form.get("actor", session.get("usuario") or "admin")

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE productos SET proposal_json = NULL WHERE id_prestashop = ?",
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
    actor = request.form.get("actor", session.get("usuario") or "admin")

    conn = get_connection()
    try:
        conn.execute(
            """UPDATE productos
               SET product_not_found = 0,
                   proposal_json = NULL,
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
    from middleware.enrich import run as enrich_run
    from middleware.extract import run as extract_run

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


@app.route("/run-once", methods=["POST"])
def run_once():
    """Ejecución única: corre el pipeline UNA vez con el objetivo indicado
    (tipo + cantidad), sin modificar el plan configurado."""
    from middleware import plan
    from middleware.db import get_connection

    sub = (request.form.get("run_sub", "") or "").strip()
    try:
        cant = int(request.form.get("run_cant", "") or 0)
    except (TypeError, ValueError):
        cant = 0
    scope = (request.form.get("run_scope", "") or "inactive").strip() or "inactive"
    if scope not in ("inactive", "active", "both"):
        scope = "inactive"
    dry_run = request.form.get("run_dry_run", "0") == "1"
    skip_extract = request.form.get("run_skip_extract", "0") == "1"
    modo = (request.form.get("run_modo", "") or "publicar").strip()
    if modo not in ("publicar", "preparar"):
        modo = "publicar"
    override = {
        "subcategoria": sub or None,
        "cantidad": cant or None,
        "scope": scope,
        "modo": modo,
    }
    if not override["subcategoria"] and not override["cantidad"]:
        return jsonify({"ok": False, "error": "Indicá tipo y/o cantidad"}), 400

    conn = get_connection()
    try:
        objetivo = plan.describe_target(conn, override["subcategoria"], override["cantidad"])
    finally:
        conn.close()

    if not _acquire_pipeline_lock():
        return jsonify({"ok": False, "error": "El pipeline ya está ejecutándose"}), 409

    from middleware import pipeline_state
    from middleware.enrich import run as enrich_run
    from middleware.extract import run as extract_run

    scope_label = {"inactive": "inactivos", "active": "activos", "both": "activos+inactivos"}[scope]
    extras = [f"productos {scope_label}"]
    if modo == "preparar":
        extras.append("solo preparar (no modificar PrestaShop)")
    if dry_run:
        extras.append("dry-run (sin escribir en PrestaShop)")
    if skip_extract:
        extras.append("solo enriquecer")

    def _run():
        try:
            pipeline_state.add_log(
                f"Ejecución única iniciada: {objetivo} — {', '.join(extras)}"
            )
            if not skip_extract:
                extract_run(dry_run=dry_run, override=override)
            enrich_run(dry_run=dry_run, override=override)
            pipeline_state.add_log(f"Ejecución única finalizada: {objetivo}")
        except Exception as exc:
            logger.error("Run-once error: %s", exc)
            pipeline_state.add_log(f"ERROR: {exc}")
        finally:
            pipeline_state.finish()
            _release_pipeline_lock()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"ok": True, "objetivo": objetivo, "redirect": url_for("dashboard")})


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
    ("PRESTASHOP_API_KEY", "PrestaShop API Key", True),
    ("BATCH_SIZE", "Batch Size"),
    ("API_SLEEP", "API Sleep (segundos)"),
    ("DAEMON_INTERVAL", "Daemon Interval (segundos)"),
    ("PS_COMPAT_81", "PrestaShop 8.1 compat (1=workarounds activos)"),
    ("PS_CREATE_FEATURES", "Crear características nuevas en PS (1=sí, 0=solo usar existentes)"),
    ("PS_MPN_FIELD", "Campo de modelo en la API (mpn=1.7+; reference para 1.6)"),
    ("PS_API_TIMEOUT", "Timeout API PrestaShop (segundos; 0 = sin timeout)"),
    ("PS_API_RETRIES", "Reintentos API PrestaShop (errores de conexión / 5xx)"),
]


@app.route("/settings", methods=["GET"])
def settings():
    from middleware import plan
    from middleware.config import DEFAULTS, _get
    values = {}
    for entry in _SETTINGS_KEYS:
        key, label = entry[0], entry[1]
        values[key] = {
            "label": label,
            "value": _get(key),
            "default": DEFAULTS.get(key, ""),
            "password": len(entry) > 2 and entry[2],
        }
    conn = get_connection()
    try:
        subcategorias = plan.list_subcategorias(conn)
        plan_label = plan.describe_plan(conn)
    finally:
        conn.close()

    active = plan.get_active_plan()
    weekly = plan.get_weekly()
    plan_options = plan.get_options()
    plan_week = []
    for label, day in plan.WEEKDAYS:
        entry = weekly.get(day, {})
        plan_week.append({
            "label": label,
            "day": day,
            "subcategoria": entry.get("subcategoria") or "",
            "cantidad": entry.get("cantidad") or "",
        })

    saved = request.args.get("saved")
    return render_template(
        "settings.html",
        fields=values,
        saved=saved,
        subcategorias=subcategorias,
        plan_active_sub=(active or {}).get("subcategoria") or "",
        plan_active_cantidad=(active or {}).get("cantidad") or "",
        plan_options=plan_options,
        plan_week=plan_week,
        today_plan=plan.get_today_plan(),
        plan_label=plan_label,
    )


@app.route("/plan/save", methods=["POST"])
def plan_save():
    """Guardar plan activo + agenda semanal + opciones avanzadas."""
    from middleware import plan
    plan.set_active(
        request.form.get("plan_subcategoria", ""),
        request.form.get("plan_cantidad", ""),
    )
    plan.set_options(
        scope=request.form.get("plan_scope", ""),
        modo=request.form.get("plan_modo", ""),
        skip_extract=request.form.get("plan_skip_extract", "0") == "1",
        dry_run=request.form.get("plan_dry_run", "0") == "1",
    )
    weekly = {}
    for _, day in plan.WEEKDAYS:
        sub = (request.form.get(f"week_sub_{day}", "") or "").strip()
        cant = (request.form.get(f"week_cant_{day}", "") or "").strip()
        if sub or cant:
            weekly[str(day)] = {"subcategoria": sub, "cantidad": cant}
    plan.set_weekly(weekly)
    return redirect(url_for("settings", saved=1))


@app.route("/settings", methods=["POST"])
def settings_save():
    from middleware.config import reload_db_config
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


_GENERIC_RESULT_SELECTOR = (
    "a[href*='product'], a[href*='/p/'], a[href*='MLA-'], a[href*='model'], "
    ".product-card a, a[class*='product'], .s-result-item h2 a"
)


def _brand_slug(name: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def _detect_search_type(entry: dict) -> str:
    """Deducir el método de búsqueda simple desde una entrada guardada."""
    if entry.get("strategy") == "sitemap":
        return "sitemap"
    if entry.get("strategy") == "pdf_sitemap":
        return "pdf_sitemap"
    url = (entry.get("search_url") or "").lower()
    if "mercadolibre" in url:
        return "mercadolibre"
    if "google.com" in url and "/search" in url:
        return "google"
    return "site"


def _build_brand_entry(form) -> dict:
    """Construir la entrada de brands_mapping.json desde el formulario simple.

    El usuario final solo completa: nombre, método de búsqueda y sitio web.
    Los campos avanzados (URL exacta, selector CSS, sitemap) sobreescriben a
    los generados automáticamente.
    """
    name = (form.get("name", "") or "").strip().lower()
    search_type = (form.get("search_type", "site") or "site").strip().lower()
    site_url = (form.get("site_url", "") or "").strip().lower().replace("https://", "").replace("http://", "")
    search_url = (form.get("search_url", "") or "").strip()
    result_selector = (form.get("result_selector", "") or "").strip()
    sitemap_url = (form.get("sitemap_url", "") or "").strip()
    url_pattern = (form.get("url_pattern", "") or "").strip()
    direct_url_pattern = (form.get("direct_url_pattern", "") or "").strip()
    has_pdf = form.get("has_pdf") == "1"

    entry: dict[str, Any] = {}

    if search_type == "sitemap":
        entry["strategy"] = "sitemap"
        if sitemap_url:
            entry["sitemap_url"] = sitemap_url
        if url_pattern:
            entry["url_pattern"] = url_pattern
    elif search_type == "pdf_sitemap":
        entry["strategy"] = "pdf_sitemap"
        if sitemap_url:
            entry["sitemap_url"] = sitemap_url
    else:
        if not search_url:
            slug = _brand_slug(name)
            if search_type == "mercadolibre":
                search_url = f"https://listado.mercadolibre.com.ar/{slug}-{{mpn}}"
            elif search_type == "google":
                search_url = f"https://www.google.com/search?q={slug}+{{mpn}}"
            else:  # site
                site = site_url or (f"www.{name}.com" if name else "")
                if site:
                    search_url = f"https://{site}/search?q={{mpn}}"
        if search_url:
            entry["search_url"] = search_url
        if result_selector:
            entry["result_selector"] = result_selector

    if direct_url_pattern:
        entry["direct_url_pattern"] = direct_url_pattern
    if has_pdf:
        entry["has_pdf"] = True
    return entry


@app.route("/brands")
def brands():
    data = _load_brands()
    sorted_brands = sorted(data.items(), key=lambda x: x[0].lower())
    enriched = []
    for name, info in sorted_brands:
        row = dict(info)
        row["search_type"] = _detect_search_type(row)
        row["site_url"] = ""
        row["search_url"] = row.get("search_url", "")
        row["result_selector"] = row.get("result_selector", "")
        row["sitemap_url"] = row.get("sitemap_url", "")
        row["url_pattern"] = row.get("url_pattern", "")
        row["direct_url_pattern"] = row.get("direct_url_pattern", "")
        enriched.append((name, row))
    saved = request.args.get("saved")
    deleted = request.args.get("deleted")
    return render_template(
        "brands.html", brands=enriched, saved=saved, deleted=deleted,
        generic_selector=_GENERIC_RESULT_SELECTOR,
    )


@app.route("/brands/add", methods=["POST"])
def brands_add():
    name = (request.form.get("name", "") or "").strip().lower()
    if not name:
        return redirect(url_for("brands"))
    entry = _build_brand_entry(request.form)
    if not entry:
        return redirect(url_for("brands"))
    data = _load_brands()
    data[name] = entry
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
    name = (request.form.get("name", "") or "").strip().lower()
    data = _load_brands()
    if not name or name not in data:
        return redirect(url_for("brands"))
    entry = _build_brand_entry(request.form)
    if not entry:
        return redirect(url_for("brands"))
    data[name] = entry
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

    from middleware import pipeline_state
    from middleware.check_active import check_all_active

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

    import os
    import subprocess
    import sys

    interval = request.form.get("interval", type=int) or DAEMON_INTERVAL
    dry_run = request.form.get("dry_run", "0") == "1"
    check_inactive = request.form.get("check_inactive", "0") == "1"
    no_initial_pipeline = request.form.get("no_initial_pipeline", "0") == "1"

    cmd = [sys.executable, "daemon.py", "--interval", str(interval)]
    if check_inactive:
        cmd.append("--check-inactive")
    if dry_run:
        cmd.append("--dry-run")
    if no_initial_pipeline:
        cmd.append("--no-initial-pipeline")
    if request.form.get("verbose", "0") == "1":
        cmd.append("-v")

    try:
        popen_kwargs: dict[str, Any] = {
            "stdout": None,
            "stderr": None,
            "cwd": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **popen_kwargs)
        _daemon_process = proc

        # Write initial state to SQLite so the UI sees it immediately
        from middleware.daemon_state import set_pid
        from middleware.daemon_state import start as ds_start
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

    from middleware.daemon_state import get_state
    from middleware.daemon_state import stop as ds_stop
    state = get_state()

    if not state["running"] and _daemon_process is None:
        return jsonify({"ok": False, "error": "El daemon no está ejecutándose"}), 400

    # Request a graceful stop via SQLite flag (portable, works on any OS)
    from middleware.daemon_state import request_stop
    request_stop()

    # Best-effort SIGTERM on POSIX for immediate termination
    pid = state.get("pid") or (_daemon_process.pid if _daemon_process else None)
    if pid:
        import os
        import signal
        if hasattr(signal, "SIGTERM"):
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info("Sent SIGTERM to daemon PID %d", pid)
            except (ProcessLookupError, PermissionError):
                pass

    # Write stopped state to SQLite immediately
    ds_stop()
    _daemon_process = None
    return jsonify({"ok": True})
