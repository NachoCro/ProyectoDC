"""Sync local categories/subcategories → PrestaShop categories.

Creates PrestaShop category nodes matching local categorias + subcategorias,
stores the PS category IDs in `subcategorias.id_prestashop_categoria`,
and assigns existing products to their subcategory's PS category.
"""

import logging
import sys
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import SubElement
sys.path.insert(0, '.')
from middleware.db import get_connection
from admin_ui.prestashop import AdminPrestashopClient
from middleware.config import PRESTASHOP_API_URL, PRESTASHOP_API_KEY

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('sync_categories')

client = AdminPrestashopClient()
conn = get_connection()

# ── 1. Ensure column exists ────────────────────────────────────────────────
try:
    conn.execute("ALTER TABLE subcategorias ADD COLUMN id_prestashop_categoria INTEGER NULL")
    conn.commit()
    logger.info("Added id_prestashop_categoria column to subcategorias")
except Exception:
    conn.rollback()
    logger.info("Column id_prestashop_categoria already exists")

# ── 2. Fetch existing PS categories ─────────────────────────────────────────
existing = {}
resp = client._session.get(
    f'{PRESTASHOP_API_URL}/categories?display=[id,id_parent,name]&limit=1000',
    timeout=10
)
root = ET.fromstring(resp.content)
for cat in root.findall('.//category'):
    cid = int(cat.findtext('id'))
    parent = int(cat.findtext('id_parent'))
    name = cat.findtext('name/language')
    existing[name] = {'id': cid, 'parent': parent}

def create_category(name, parent_id):
    if name in existing:
        logger.info(f"  EXISTS '{name}' id={existing[name]['id']}")
        return existing[name]['id']
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
  <category>
    <id_parent>{parent_id}</id_parent>
    <active>1</active>
    <name><language id="1">{name}</language></name>
    <link_rewrite><language id="1">{name.lower().replace(' ', '-').replace('ñ','n').replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u')}</language></link_rewrite>
    <description><language id="1"></language></description>
  </category>
</prestashop>"""
    resp = client._session.post(
        f'{PRESTASHOP_API_URL}/categories',
        data=xml.encode('utf-8'),
        headers={'Content-Type': 'application/xml'},
        timeout=10
    )
    if resp.status_code != 201:
        logger.error(f"  FAILED '{name}': {resp.status_code} {resp.text[:200]}")
        return None
    new_root = ET.fromstring(resp.content)
    new_id = int(new_root.findtext('.//category/id'))
    existing[name] = {'id': new_id, 'parent': parent_id}
    logger.info(f"  CREATED '{name}' id={new_id}")
    return new_id

# ── 3. Create parent categories (categorias) under Inicio (id=2) ────────────
cats = conn.execute('SELECT * FROM categorias ORDER BY id_categoria').fetchall()
cat_map = {}
for row in cats:
    name = row['nombre_categoria'].title().replace(' Y ', ' y ')
    ps_id = create_category(name, 2)
    if ps_id:
        cat_map[row['id_categoria']] = ps_id

# ── 4. Create subcategories under their parent ──────────────────────────────
subcats = conn.execute('SELECT * FROM subcategorias ORDER BY id_subcategoria').fetchall()
subcat_map = {}
for row in subcats:
    parent_ps_id = cat_map.get(row['id_categoria'])
    if not parent_ps_id:
        logger.warning(f"  No parent PS cat for subcat #{row['id_subcategoria']} '{row['nombre_subcategoria']}'")
        continue
    ps_id = create_category(row['nombre_subcategoria'], parent_ps_id)
    if ps_id:
        subcat_map[row['id_subcategoria']] = ps_id
        conn.execute(
            'UPDATE subcategorias SET id_prestashop_categoria = ? WHERE id_subcategoria = ?',
            (ps_id, row['id_subcategoria'])
        )
conn.commit()
logger.info("Stored PS category IDs in subcategorias.id_prestashop_categoria")

# ── 5. Assign existing products to their PS subcategory ─────────────────────
# PrestaShop requires PUTting the full product XML with category associations
prods = conn.execute('SELECT id_prestashop, id_subcategoria FROM productos').fetchall()
for p in prods:
    ps_cat_id = subcat_map.get(p['id_subcategoria'])
    if not ps_cat_id:
        logger.info(f"  SKIP product {p['id_prestashop']} (no PS subcategory)")
        continue

    # Fetch current product XML
    root = client._request(f'products/{p["id_prestashop"]}')
    product_el = root.find('.//product')
    if product_el is None:
        logger.error(f"  No <product> element for {p['id_prestashop']}")
        continue

    # Ensure <associations><categories> exists
    assoc_el = product_el.find('associations')
    if assoc_el is None:
        assoc_el = SubElement(product_el, 'associations')
    cats_el = assoc_el.find('categories')
    if cats_el is None:
        cats_el = SubElement(assoc_el, 'categories')

    # Collect existing category IDs + add the new one
    current_ids = set()
    for cat_item in cats_el.findall('category'):
        cid_el = cat_item.find('id')
        if cid_el is not None and cid_el.text:
            current_ids.add(cid_el.text)
    if str(ps_cat_id) in current_ids:
        logger.info(f"  Product {p['id_prestashop']} already in category {ps_cat_id}")
        continue

    # Add the new category
    cat_item = SubElement(cats_el, 'category')
    cid_el = SubElement(cat_item, 'id')
    cid_el.text = str(ps_cat_id)
    current_ids.add(str(ps_cat_id))

    # Remove read-only fields to avoid 400 errors
    for tag in list(product_el):
        if tag.tag in {'manufacturer_name', 'supplier_name', 'date_add', 'date_upd',
                       'state', 'position_in_category', 'cache_default_attribute',
                       'id_default_image', 'id_default_combination', 'quantity',
                       'id_supplier'}:
            product_el.remove(tag)

    xml_str = ET.tostring(root, encoding='unicode', xml_declaration=True)
    from admin_ui.prestashop import _wrap_language_cdata
    xml_str = _wrap_language_cdata(xml_str)

    resp = client._session.put(
        f'{PRESTASHOP_API_URL}/products/{p["id_prestashop"]}',
        data=xml_str.encode('utf-8'),
        headers={'Content-Type': 'application/xml'},
        timeout=10
    )
    if resp.status_code in (200, 201):
        logger.info(f"  Product {p['id_prestashop']} → category {ps_cat_id} OK")
    else:
        logger.error(f"  Product {p['id_prestashop']} FAILED: {resp.status_code} {resp.text[:300]}")

conn.close()
logger.info("Done!")
