#!/usr/bin/env python3
#"""Mock minimal de la API REST de PrestaShop para desarrollo y tests."""

import json
import logging
import time
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from flask import Flask, make_response, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MOCK] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mock")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Datos semilla: productos inactivos (active=0) con stock >= 1,
# manufacturer y stock_available.
# ---------------------------------------------------------------------------

MANUFACTURERS = {
    1: "HP",
    2: "Creality",
    3: "Logitech",
    4: "Samsung",
}

PRODUCTS = {
    101: {
        "id": "101",
        "active": "0",
        "ean13": "8412345678901",
        "mpn": "HP-PAV-15",
        "id_manufacturer": "1",
        "manufacturer_name": "HP",
        "id_category_default": "19",        # NOTEBOOKS
        "name": "HP Pavilion 15",
        "description": "HP Pavilion 15 original",
        "description_short": "Pavilion 15",
    },
    102: {
        "id": "102",
        "active": "0",
        "ean13": "8412345678902",
        "mpn": "CR-E3-01",
        "id_manufacturer": "2",
        "manufacturer_name": "Creality",
        "id_category_default": "22",        # IMPRESORAS FDM
        "name": "Impresora 3D Ender 3",
        "description": "Impresora 3D Ender 3 original",
        "description_short": "Ender 3",
    },
    103: {
        "id": "103",
        "active": "0",
        "ean13": "",
        "mpn": "LOG-G502",
        "id_manufacturer": "3",
        "manufacturer_name": "Logitech",
        "id_category_default": "26",        # MOUSES CON CABLE
        "name": "Mouse Logitech G502",
        "description": "Mouse G502 original",
        "description_short": "G502",
    },
    104: {
        "id": "104",
        "active": "0",
        "ean13": "8412345678903",
        "mpn": "S24-ULTRA",
        "id_manufacturer": "4",
        "manufacturer_name": "Samsung",
        "id_category_default": "16",        # CELULARES LIBRES
        "name": "Samsung Galaxy S24 Ultra",
        "description": "Samsung S24 Ultra original",
        "description_short": "S24 Ultra",
    },
    105: {
        "id": "105",
        "active": "0",
        "ean13": "8412345678904",
        "mpn": "UE43CU7100",
        "id_manufacturer": "4",
        "manufacturer_name": "Samsung",
        "id_category_default": "28",        # SMART TV
        "name": "Smart TV Samsung 43\" Crystal UHD 4K",
        "description": "Smart TV Samsung 43\" Crystal UHD 4K",
        "description_short": "TV Samsung 43\" 4K",
    },
    # Producto activo (debería ser ignorado por el filtro)
    201: {
        "id": "201",
        "active": "1",
        "ean13": "8412345678999",
        "mpn": "ACTIVE-01",
        "id_manufacturer": "1",
        "manufacturer_name": "HP",
        "id_category_default": "19",        # NOTEBOOKS
        "name": "Producto activo",
        "description": "Producto activo",
        "description_short": "Activo",
    },
}

STOCK = {
    101: 5,
    102: 3,
    103: 1,
    104: 0,  # sin stock → debe filtrarse
    105: 2,
    201: 10,
}

# ---------------------------------------------------------------------------
# helpers XML
# ---------------------------------------------------------------------------

PRESTASHOP_XMLNS = {"xmlns:xlink": "http://www.w3.org/1999/xlink"}


def _prestashop_root(tag: str = "prestashop") -> Element:
    return Element(tag, PRESTASHOP_XMLNS)


def _child(parent: Element, tag: str, text: str | None = None) -> Element:
    el = SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _product_xml(p: dict) -> Element:
    prod = Element("product")
    for k in ("id", "active", "ean13", "mpn", "id_manufacturer", "manufacturer_name", "id_category_default"):
        if k in p:
            _child(prod, k, p[k])
    # description multi-lenguaje
    desc = SubElement(prod, "description")
    _child(desc, "language", p.get("description", "")).set("id", "1")
    desc_short = SubElement(prod, "description_short")
    _child(desc_short, "language", p.get("description_short", "")).set("id", "1")
    return prod


def _stock_available_xml(pid: int) -> Element:
    sa = Element("stock_available")
    _child(sa, "id", str(pid + 1000))  # id interno
    _child(sa, "id_product", str(pid))
    _child(sa, "quantity", str(STOCK.get(pid, 0)))
    return sa


def _xml_response(root: Element, status: int = 200):
    rough = tostring(root, encoding="unicode", xml_declaration=True)
    dom = minidom.parseString(rough.encode())
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8")
    resp = make_response(pretty, status)
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    return resp


def _json_response(data, status: int = 200):
    resp = make_response(json.dumps({"prestashop": data}, ensure_ascii=False), status)
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    return resp


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.route("/api/manufacturers")
def api_manufacturers():
    root = _prestashop_root()
    mfrs = SubElement(root, "manufacturers")
    for mid, name in MANUFACTURERS.items():
        m = SubElement(mfrs, "manufacturer")
        _child(m, "id", str(mid))
        _child(m, "name", name)
    return _xml_response(root)


@app.route("/api/products")
def api_products():
    display = request.args.get("display", "")
    active_filter = request.args.get("filter[active]", "")
    limit = request.args.get("limit", "0,10")

    # parsear limit
    parts = limit.split(",")
    offset = int(parts[0]) if len(parts) > 1 else 0
    count = int(parts[-1]) if parts else 10

    # filtrar por active
    show_active = True
    show_inactive = True
    if active_filter == "[0]":
        show_active = False
    elif active_filter == "[1]":
        show_inactive = False

    filtered = [
        p for p in PRODUCTS.values()
        if (p["active"] == "1" and show_active)
        or (p["active"] == "0" and show_inactive)
    ]

    # paginar
    page = filtered[offset: offset + count]

    root = _prestashop_root()
    products_el = SubElement(root, "products")
    for p in page:
        prod = SubElement(products_el, "product")
        fields = ["id", "active", "ean13", "mpn", "id_manufacturer", "id_category_default"]
        if "manufacturer_name" in display or display == "full":
            fields.append("manufacturer_name")
        if "name" in display or display == "full":
            name_el = SubElement(prod, "name")
            _child(name_el, "language", p.get("name", "")).set("id", "1")
        for k in fields:
            _child(prod, k, p[k])

    return _xml_response(root)


@app.route("/api/stock_availables")
def api_stock():
    id_filter = request.args.get("filter[id_product]", "")
    display = request.args.get("display", "")

    root = _prestashop_root()
    stock_el = SubElement(root, "stock_availables")

    # parsear IDs
    ids: list[int] = []
    if id_filter.startswith("[") and id_filter.endswith("]"):   # [1|2|3]
        ids = [int(x) for x in id_filter[1:-1].split("|") if x]

    for pid in ids:
        stock_el.append(_stock_available_xml(pid))

    return _xml_response(root)


# In-memory product images (keyed by product_id, list of image IDs)
_PRODUCT_IMAGES: dict[int, list[int]] = {}
_IMAGE_ID_COUNTER = 1000


@app.route("/api/images/products/<int:pid>", methods=["POST"])
def api_product_image_upload(pid: int):
    if pid not in PRODUCTS:
        return _xml_response(_prestashop_root("error"), 404)

    global _IMAGE_ID_COUNTER
    _IMAGE_ID_COUNTER += 1
    img_id = _IMAGE_ID_COUNTER

    _PRODUCT_IMAGES.setdefault(pid, []).append(img_id)

    root = _prestashop_root()
    img_el = SubElement(root, "image")
    _child(img_el, "id", str(img_id))
    _child(img_el, "id_product", str(pid))

    logger.info("  IMAGE %d uploaded for product %d", img_id, pid)
    return _xml_response(root, 201)


@app.route("/api/products/<int:pid>", methods=["GET", "PUT"])
def api_product_detail(pid: int):
    if pid not in PRODUCTS:
        return _xml_response(_prestashop_root("error"), 404)

    if request.method == "GET":
        output = request.args.get("output_format", "xml")
        p = PRODUCTS[pid]
        if output == "JSON":
            return _json_response({"product": p})
        root = _prestashop_root()
        root.append(_product_xml(p))
        return _xml_response(root)

    # PUT
    if request.content_type == "application/json":
        data = request.get_json()
        updates = data.get("prestashop", {}).get("product", {})
    else:
        # XML — parsear campos simples
        updates = {}
        xml_data = request.data.decode()
        # extracción básica: buscar <active>, <description>, etc.
        import re
        for tag in ("active", "mpn", "ean13", "id_manufacturer"):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml_data)
            if m:
                updates[tag] = m.group(1)
        # description multi-lenguaje
        m = re.search(r"<language[^>]*>(.*?)</language>", xml_data)
        if m:
            updates["description"] = m.group(1)

    # aplicar cambios
    p = PRODUCTS[pid]
    for k, v in updates.items():
        if k in p:
            p[k] = v
            logger.info("  → %s.%s = %s", pid, k, v)

    root = _prestashop_root()
    root.append(_product_xml(p))
    return _xml_response(root)


# ---------------------------------------------------------------------------
# status helper para ver el estado interno
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# página principal informativa
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Mock PrestaShop</title></head>
<body style="font-family:sans-serif;padding:2em">
  <h1>Mock PrestaShop API</h1>
  <p>Productos: {len(PRODUCTS)} ({sum(1 for p in PRODUCTS.values() if p['active']=='1')} activos, {sum(1 for p in PRODUCTS.values() if p['active']=='0')} inactivos)</p>
  <p>Fabricantes: {len(MANUFACTURERS)}</p>
  <ul>
    <li><a href="/api/manufacturers">/api/manufacturers</a></li>
    <li><a href="/api/products">/api/products</a></li>
    <li><a href="/_status">/_status</a></li>
  </ul>
</body>
</html>"""


@app.route("/_status")
def status():
    info = {
        "productos": len(PRODUCTS),
        "manufacturers": len(MANUFACTURERS),
        "productos_activos": sum(1 for p in PRODUCTS.values() if p["active"] == "1"),
        "productos_inactivos": sum(1 for p in PRODUCTS.values() if p["active"] == "0"),
        "stock": STOCK,
    }
    return json.dumps(info, indent=2), 200, {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mock PrestaShop API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logger.info("Mock PrestaShop escuchando en http://%s:%s/api", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
