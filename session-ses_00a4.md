# Mantener nombres originales de productos

**Session ID:** ses_00a403fd4ffe3bgteY2eqy5NvO
**Created:** 8/12/2026, 8:33:32 AM
**Updated:** 8/12/2026, 9:00:21 AM

---

## Assistant (Build · Big Pickle · 9.4s)

_Thinking:_

So `put_product` does NOT set the `name` field — it GETs the product and only modifies keys in `updates`. The `updates` dict contains `description`, `description_short`, `active`. So the pipeline push and approval don't change the name.

But wait — the user says there shouldn't be a name change. Where could the name change? Let me look at where the DB stores the name and where it might sync name. In `extract.py` — "syncs local fields with PrestaShop data (PrestaShop is source of truth)". Maybe the extraction syncs the name from PrestaShop and stores it locally, which changes the local name. But that's PrestaShop source of truth, so the name stays the same.

Actually the user's complaint: "No debe haber cambio de nombre en los productos, no tiene sentido eso, porque si yo quiero una cinta scotch de 5cm de espesor no tiene sentido que me de un celular 15c redmi". 

Wait, re-reading: "si yo quiero una cinta scotch de 5cm de espesor no tiene sentido que me de un celular 15c redmi". So it seems the enrichment is returning/displaying wrong products. The issue is about `_validate_name_coherence` / `_validate_scraped_data` — the scraped title could differ from the product name and it might be enriching a product with completely different data (a scotch tape getting enriched as a Redmi phone). But the user says "cambio de nombre" (name change).

Hmm, let me look more carefully. The user might have observed that when they look at products in PrestaShop, the name changed. Let me check if `put_product` or anywhere else changes the name. Since `put_product` only modifies keys passed in `updates`, and `updates` never contains "name", the name in PrestaShop shouldn't change... unless `_set_field` for "description" etc. somehow, no.

Wait, maybe the issue is in `extract.py` — the "syncs local fields with PrestaShop data (PrestaShop is source of truth)". Let me check extract.py to see if it updates the local name. Also there may be a `modelo` inferred from name. And the local `productos.nombre` could be updated.

Actually, let me re-read the user's message again: "No debe haber cambio de nombre en los productos, no tiene sentido eso, porque si yo quiero una cinta scotch de 5cm de espesor no tiene sentido que me de un celular 15c redmi"

I think the meaning: The system should not rename products. Because if the user wants a 5cm-wide scotch tape, it doesn't make sense for the system to give them a "Redmi 15C cell phone". 

So somewhere, maybe during enrichment, the product name displayed is being replaced with the scraped title from a wrong product. This is related to `_validate_name_coherence` which checks "rejects data whose enriched brand contradicts the original product name". But the user is saying there shouldn't be ANY name change at all.

Perhaps the proposal JSON stores a "nombre" from scraped data, and the diff UI displays it, or the DB `nombre` column is updated with the scraped name. Let me search for where the DB `nombre` column gets updated with scraped data. Let me grep for `SET nombre` and `update.*nombre`.

Let me also check `check_active.py` which has name handling — line 419 sets "name": name. Let me read that section.

El `put_product` no toca el campo `name`. Voy a revisar dónde se actualiza el `nombre` local y qué hace `check_active.py` con `name`.

**Tool: grep**

**Input:**
```json
{
  "include": "*.py",
  "path": "/home/icrocetti/dev/ProyectoDC",
  "pattern": "SET nombre|nombre = |update.*nombre|\\\"nombre\\\""
}
```

**Output:**
```
Found 100 matches (more matches available)
/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py:
  Line 42:     names = [f["nombre"] for f in feats]

  Line 61:     by_name = {f["nombre"]: f["valor"] for f in feats}

  Line 79:     by_name = {f["nombre"].lower(): f["valor"] for f in feats}

  Line 110:     chars = {c["nombre"]: c["valor"] for c in out["caracteristicas"]}

  Line 153:     by_name = {f["nombre"]: f["valor"] for f in feats}

  Line 176:     by_name = {f["nombre"]: f["valor"] for f in feats}


/home/icrocetti/dev/ProyectoDC/tests/test_enrich.py:
  Line 10:         {"nombre": "Color", "valor": "Negro"},

  Line 11:         {"nombre": "Peso", "valor": "1 kg"},

  Line 12:         {"nombre": "Vacio", "valor": ""},

  Line 68:         "caracteristicas": [{"nombre": "Tamaño de pantalla", "valor": '55"'}],

  Line 80:         "caracteristicas": [{"nombre": "Tamaño de pantalla", "valor": '75"'}],

  Line 112:         "caracteristicas": [{"nombre": "Muestras", "valor": "38197"}] * 8,

  Line 122:         "caracteristicas": [{"nombre": "Pantalla", "valor": "AMOLED"}] * 8,

  Line 132:         "caracteristicas": [{"nombre": "Material", "valor": "acero"}] * 8,

  Line 141:         "caracteristicas": [{"nombre": "Marca", "valor": "Decathlon"}] * 8,

  Line 151:         "caracteristicas": [{"nombre": "Material", "valor": "goma"}] * 8,

  Line 162:         "caracteristicas": [{"nombre": "Carga", "valor": "25 kg"}] * 8,

  Line 175:         "caracteristicas": [{"nombre": "Carga", "valor": "25 kg"}] * 8,


/home/icrocetti/dev/ProyectoDC/tests/test_db.py:
  Line 43:             "pendiente_activar", "product_not_found", "nombre"} <= cols

  Line 135:             {"nombre": "Color", "valor": "Negro"},

  Line 136:             {"nombre": "Peso", "valor": "1.5 kg"},

  Line 137:             {"nombre": "Basura", "valor": "  "},

  Line 147:         got = {r["nombre"]: r["valor"] for r in rows}


/home/icrocetti/dev/ProyectoDC/tests/test_characteristics.py:
  Line 8:         {"nombre": "Resolucion", "valor": "4K"},

  Line 9:         {"nombre": "{{upgrade.yesAttr.text}}", "valor": "Si"},

  Line 10:         {"nombre": "Color", "valor": "${state.color}"},

  Line 11:         {"nombre": "Peso", "valor": "  1.2 kg  "},

  Line 14:         {"nombre": "Resolucion", "valor": "4K"},

  Line 15:         {"nombre": "Peso", "valor": "1.2 kg"},

  Line 22:         [{"nombre": "  Peso ", "valor": "1 kg"}], "X"

  Line 24:     assert out == [{"nombre": "Peso", "valor": "1 kg"}]

  Line 29:         {"nombre": "Color", "valor_default": "Negro"},

  Line 30:         {"nombre": "Peso", "valor_default": "1 kg"},

  Line 35:         {"nombre": "COLOR", "valor": "Blanco"},

  Line 36:         {"nombre": "Extra", "valor": "123"},

  Line 37:         {"nombre": "{{garbage}}", "valor": "x"},

  Line 42:         {"nombre": "Color", "valor": "Blanco"},

  Line 43:         {"nombre": "Peso", "valor": "1 kg"},

  Line 44:         {"nombre": "Extra", "valor": "123"},

  Line 49:     template = [{"nombre": "Tipo de pantalla", "valor_default": "LED"}]

  Line 52:         [{"nombre": "Resolucion", "valor": "1080p"}], "X"

  Line 55:         {"nombre": "Tipo de pantalla", "valor": "LED"},

  Line 56:         {"nombre": "Resolucion", "valor": "1080p"},


/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py:
  Line 433:             nombre = (ch.get("nombre") or "").strip()


/home/icrocetti/dev/ProyectoDC/admin_ui/app.py:
  Line 433:                 for ch in merged_chars if ch.get("nombre") and ch.get("valor")


/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py:
  Line 143:             features.append({"nombre": display_name, "valor": value})

  Line 170:                     features.append({"nombre": name, "valor": value})

  Line 193:                 features.append({"nombre": label, "valor": value})

  Line 221:                     features.append({"nombre": name, "valor": value})

  Line 240:                         features.append({"nombre": prop_name.replace("_", " ").title(), "valor": value})

  Line 259:                 features.append({"nombre": name, "valor": value})

  Line 303:                 features.append({"nombre": name, "valor": value})

  Line 331:                     features.append({"nombre": name, "valor": value})

  Line 353:                         features.append({"nombre": name, "valor": value})

  Line 424:                     features.append({"nombre": n, "valor": v})

  Line 430:                 if not val or prop in {f["nombre"].lower() for f in features}:

  Line 437:                             "nombre": prop.title(),

  Line 441:                     features.append({"nombre": prop.title(), "valor": str(val)})

  Line 472:     Returns a list of ``{"nombre": ..., "valor": ...}`` dicts, or ``[]`` if

  Line 533:             features.append({"nombre": name, "valor": value})

  Line 612:                                 features.append({"nombre": name, "valor": value})

  Line 649:                         features.append({"nombre": display_key, "valor": val.strip()})

  Line 661:                             features.append({"nombre": display_key, "valor": f"{value} {unit}".strip()})

  Line 834:             features.append({"nombre": name, "valor": value})


/home/icrocetti/dev/ProyectoDC/middleware/pdf_scraper.py:
  Line 112:                         characteristics.append({"nombre": key, "valor": value})

  Line 167:                         characteristics.append({"nombre": key, "valor": value})

  Line 214:         existing_keys = {c["nombre"].lower() for c in chars}

  Line 216:             if tc["nombre"].lower() not in existing_keys:

  Line 218:                 existing_keys.add(tc["nombre"].lower())


/home/icrocetti/dev/ProyectoDC/middleware/characteristics.py:
  Line 38:         nombre = (ch.get("nombre") or "").strip()

  Line 42:         cleaned.append({"nombre": nombre, "valor": valor})

  Line 106:         nombre = (ch.get("nombre") or "").strip()

  Line 117:         nombre = (tpl.get("nombre") or "").strip()

  Line 124:         merged.append({"nombre": nombre, "valor": valor})

  Line 128:         nombre = (ch.get("nombre") or "").strip()

  Line 134:             merged.append({"nombre": nombre, "valor": valor})


/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py:
  Line 336:                 specs.append({"nombre": name, "valor": value})

  Line 1278:             if tf["nombre"].lower() not in seen:

  Line 1279:                 seen.add(tf["nombre"].lower())

  Line 1296:         features.append({"nombre": name, "valor": value})

  Line 1311:                     features.append({"nombre": name, "valor": value})

  Line 1328:         features.append({"nombre": name, "valor": value})

  Line 1345:         features.append({"nombre": name, "valor": value})

  Line 1360:                     features.append({"nombre": name, "valor": value})

  Line 1376:                     features.append({"nombre": name, "valor": value})

  Line 1478:                     features.append({"nombre": name, "valor": value})

  Line 1490:                 features.append({"nombre": name, "valor": value})

  Line 1514:                 features.append({"nombre": name, "valor": value})

  Line 1865:                 db_nombre = _row["nombre"] or ""

  Line 1888:         ch["nombre"].lower().strip()

  Line 1900:             if lf["nombre"].lower().strip() not in existing_names:

  Line 1902:                 existing_names.add(lf["nombre"].lower().strip())

  Line 1911:         if bf["nombre"].lower().strip() not in existing_names:

  Line 1913:             existing_names.add(bf["nombre"].lower().strip())

  Line 1927:                 if gf["nombre"].lower().strip() not in existing_names:

  Line 1929:                     existing_names.add(gf["nombre"].lower().strip())

  Line 1947:                 if bf["nombre"].lower().strip() not in existing_names:

  Line 1949:                     existing_names.add(bf["nombre"].lower().strip())

  Line 1963:                 if jf["nombre"].lower().strip() not in existing_names:

  Line 1965:                     existing_names.add(jf["nombre"].lower().strip())


(Results truncated. Consider using a more specific path or pattern.)
```

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "limit": 130,
  "offset": 370
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/check_active.py</path>
<type>file</type>
<content>
370:     conn_target = get_connection()
371:     try:
372:         target_name = _resolve_target(conn_target)
373:     finally:
374:         conn_target.close()
375:     if target_name:
376:         logger.info(
377:             "Verificación limitada al objetivo del plan: %r", target_name,
378:         )
379: 
380:     # Fetch all active products (paginated)
381:     offset = 0
382:     limit = 50
383:     while True:
384:         products = client.get_active_products(limit=limit, offset=offset)
385:         if not products:
386:             break
387: 
388:         for p in products:
389:             if not _matches_target(p, target_name):
390:                 continue
391:             pid = int(p["id"])
392:             total += 1
393:             name = p.get("name") or f"Product {pid}"
394: 
395:             # Skip if already verified as complete in local DB
396:             conn_check = get_connection()
397:             try:
398:                 row_check = conn_check.execute(
399:                     "SELECT active_verified FROM productos WHERE id_prestashop = ?",
400:                     (pid,),
401:                 ).fetchone()
402:                 if row_check and row_check["active_verified"]:
403:                     complete_count += 1
404:                     logger.debug("  SKIP  id=%d  %s — already verified", pid, name)
405:                     continue
406:             finally:
407:                 conn_check.close()
408: 
409:             pipeline_state.add_log(f"Verificando producto activo: {name} (id={pid})")
410:             logger.info("  Verificando id=%d — %s", pid, name)
411: 
412:             # Check completeness
413:             completeness = check_product_completeness(pid)
414:             is_complete = completeness["is_complete"]
415:             missing = completeness["missing"]
416: 
417:             detail = {
418:                 "id": pid,
419:                 "name": name,
420:                 "is_complete": is_complete,
421:                 "missing": missing,
422:                 "completed": False,
423:             }
424: 
425:             if is_complete:
426:                 complete_count += 1
427:                 logger.info("  OK  id=%d  %s — complete", pid, name)
428:                 # Mark as verified in local DB
429:                 if not dry_run:
430:                     conn_mark = get_connection()
431:                     try:
432:                         conn_mark.execute(
433:                             "UPDATE productos SET active_verified = 1 WHERE id_prestashop = ?",
434:                             (pid,),
435:                         )
436:                         conn_mark.commit()
437:                     finally:
438:                         conn_mark.close()
439:             else:
440:                 incomplete_count += 1
441:                 logger.info("  INCOMPLETE  id=%d  %s — missing: %s", pid, name, missing)
442: 
443:                 # Try to complete
444:                 if not dry_run:
445:                     success = complete_incomplete_product(pid, dry_run=False)
446:                     if success:
447:                         completed_count += 1
448:                         detail["completed"] = True
449:                         logger.info("  AUTO-COMPLETED  id=%d  %s", pid, name)
450:                     else:
451:                         failed_count += 1
452:                         logger.warning("  FAILED TO COMPLETE  id=%d  %s", pid, name)
453:                 else:
454:                     logger.info("  DRY RUN — would complete id=%d  %s", pid, name)
455: 
456:             details.append(detail)
457: 
458:         offset += limit
459: 
460:     result = {
461:         "total": total,
462:         "complete": complete_count,
463:         "incomplete": incomplete_count,
464:         "completed": completed_count,
465:         "failed": failed_count,
466:         "details": details,
467:     }
468: 
469:     logger.info(
470:         "Check complete: %d total, %d complete, %d incomplete, %d auto-completed, %d failed",
471:         total, complete_count, incomplete_count, completed_count, failed_count,
472:     )
473: 
474:     return result
475: 
476: 
477: def _resolve_target(conn) -> str | None:
478:     """Texto objetivo del plan de hoy (tipo de producto), o None.
479: 
480:     La selección de productos se hace por similitud del nombre con este texto
481:     (ver ``plan.matches_name``), no por subcategoría exacta.
482:     """
483:     from . import plan
484:     return plan.effective_subcategoria() or None
485: 
486: 
487: def _matches_target(p: dict, target_name: str | None) -> bool:
488:     """¿El producto PrestaShop ``p`` cumple el objetivo del plan?
489: 
490:     Mismo criterio que ``middleware/extract.py``: el nombre del producto debe
491:     ser similar al tipo de producto objetivo.
492:     """
493:     if not target_name:
494:         return True
495:     from . import plan
496:     nombre = p.get("name") or ""
497:     return plan.matches_name(target_name, nombre)
498: 
499: 

(Showing lines 370-499 of 637. Use offset=500 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 2.9s)

_Thinking:_

The `check_active.py` doesn't change names either. Let me look at extract.py to see if the name is updated there. The user's complaint is that the product name changes. Let me look at extract.py lines around 110-160 where nombre is stored.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/extract.py",
  "limit": 130,
  "offset": 100
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/extract.py</path>
<type>file</type>
<content>
100:         pids = [int(p["id"]) for p in products if p["id"]]
101:         stock = client.get_stock_map(pids)
102: 
103:         for p in products:
104:             if len(candidates) >= target_count:
105:                 break
106: 
107:             pid = p["id"]
108:             qty = stock.get(int(pid), 0)
109:             if qty < 1:
110:                 logger.debug("  Product %s: qty=%d < 1, filtered", pid, qty)
111:                 continue
112: 
113:             # Plan con tipo de producto: el nombre debe ser similar al texto
114:             # objetivo (coincidencia por palabras, no subcategoría exacta).
115:             nombre = p.get("name") or ""
116:             if target_name and not plan.matches_name(target_name, nombre):
117:                 logger.debug(
118:                     "  Product %s: nombre '%s' no es similar a '%s', filtered",
119:                     pid, nombre, target_name,
120:                 )
121:                 continue
122: 
123:             id_mfr = p.get("id_manufacturer")
124:             marca = manufacturers.get(int(id_mfr), "") if id_mfr else ""
125: 
126:             id_category = p.get("id_category_default")
127: 
128:             # Resolve modelo from product name
129:             from .official_scraper import _extract_model_from_name
130:             modelo = _extract_model_from_name(nombre, marca)
131: 
132:             candidates.append({
133:                 "id_prestashop": int(pid),
134:                 "ean": p.get("ean13") or None,
135:                 "mpn": p.get("mpn") or None,
136:                 "marca": marca,
137:                 "modelo": modelo,
138:                 "nombre": nombre,
139:                 "id_category_default": int(id_category) if id_category else None,
140:             })
141: 
142:         offset += len(products)
143: 
144:     logger.info("Candidates after stock filter: %d", len(candidates))
145: 
146:     # -- 3 / 4.  Short-circuit & insert --------------------------------------
147:     pending: list[dict] = []
148:     inserted = 0
149:     conn = get_connection()
150:     try:
151:         for p in candidates:
152:             pid = p["id_prestashop"]
153:             ean = p["ean"]
154: 
155:             logger.info(
156:                 "  Procesando id=%d — %s (%s)",
157:                 pid, p.get("nombre") or "(sin nombre)", p["marca"] or "sin marca",
158:             )
159:             pipeline_state.add_log(
160:                 f"Extrayendo id={pid} — {p.get('nombre') or '(sin nombre)'}"
161:             )
162: 
163:             # RF-04 / RF-05: skip if already in local DB
164:             if _short_circuit(pid, ean):
165:                 if not dry_run:
166:                     updated = sync_producto_from_prestashop(
167:                         conn, pid, ean, p["mpn"], p["marca"],
168:                         p.get("nombre"), p.get("id_category_default"),
169:                     )
170:                     if updated:
171:                         logger.info("  SYNC  id=%d  campos=%s", pid, updated)
172:                 logger.info("  SKIP  id=%d  EAN=%s  (already in DB)", pid, ean)
173:                 continue
174: 
175:             if not dry_run:
176:                 # Resolve subcategory from PrestaShop's id_category_default
177:                 ps_cat_id = p.get("id_category_default")
178:                 sub_id = get_subcategoria_by_ps_category(conn, ps_cat_id) if ps_cat_id else None
179:                 if sub_id is None:
180:                     sub_id = ensure_subcategoria(conn, "SIN CLASIFICAR")
181: 
182:                 ok = insert_product(
183:                     conn,
184:                     id_prestashop=pid,
185:                     id_subcategoria=sub_id or 1,
186:                     ean=ean,
187:                     mpn=p["mpn"],
188:                     marca=p["marca"],
189:                     modelo=p["modelo"],
190:                     nombre=p.get("nombre"),
191:                 )
192:                 if not ok:
193:                     logger.info(
194:                         "  SKIP  id=%d  (collision on insert)", pid,
195:                     )
196:                     continue
197:                 inserted += 1
198: 
199:             pending.append(p)
200:             logger.info(
201:                 "  QUEUE id=%d  EAN=%s  marca=%s",
202:                 pid, ean or "(sin EAN)", p["marca"],
203:             )
204: 
205:         if not dry_run:
206:             conn.commit()
207:             logger.info(
208:                 "Inserted %d new products (%d already known)",
209:                 inserted, len(candidates) - inserted,
210:             )
211:     finally:
212:         conn.close()
213: 
214:     return pending

(End of file - total 214 lines)
</content>
```

---

## Assistant (Build · Big Pickle · 2.6s)

_Thinking:_

Let me look at `sync_producto_from_prestashop` — it might update the local `nombre`. And let me check if `put_product` or anywhere sets the name. Let me look at the DB helper `sync_producto_from_prestashop`.

**Tool: grep**

**Input:**
```json
{
  "include": "*.py",
  "path": "/home/icrocetti/dev/ProyectoDC",
  "pattern": "def sync_producto_from_prestashop|def insert_product|UPDATE productos SET"
}
```

**Output:**
```
Found 9 matches
/home/icrocetti/dev/ProyectoDC/admin_ui/app.py:
  Line 490:                 "UPDATE productos SET pendiente_activar = 0 WHERE id_prestashop = ?",

  Line 551:             "UPDATE productos SET proposal_json = NULL WHERE id_prestashop = ?",


/home/icrocetti/dev/ProyectoDC/middleware/check_active.py:
  Line 174:                     "UPDATE productos SET active_verified = 1 WHERE id_prestashop = ?",

  Line 433:                             "UPDATE productos SET active_verified = 1 WHERE id_prestashop = ?",

  Line 505:             "UPDATE productos SET pendiente_activar = 1 WHERE id_prestashop = ?",


/home/icrocetti/dev/ProyectoDC/middleware/db.py:
  Line 295: def insert_product(

  Line 321:             "UPDATE productos SET product_not_found = 1 WHERE id_prestashop = ?",

  Line 329: def sync_producto_from_prestashop(

  Line 376:         f"UPDATE productos SET {', '.join(set_parts)} WHERE id_prestashop = ?",

```

---

## Assistant (Build · Big Pickle · 2.9s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/db.py",
  "limit": 100,
  "offset": 295
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/db.py</path>
<type>file</type>
<content>
295: def insert_product(
296:     conn: sqlite3.Connection,
297:     id_prestashop: int,
298:     id_subcategoria: int,
299:     ean: str | None,
300:     mpn: str | None,
301:     marca: str,
302:     modelo: str,
303:     nombre: str | None = None,
304: ) -> bool:
305:     """Insert a product row. Returns True if a new row was inserted."""
306:     cur = conn.execute(
307:         """INSERT OR IGNORE INTO productos
308:            (id_prestashop, id_subcategoria, ean, mpn, marca, modelo, nombre,
309:             estado_actualizacion, product_not_found)
310:            VALUES (?, ?, ?, ?, ?, ?, ?, 'desactualizado', 0)""",
311:         (id_prestashop, id_subcategoria, ean, mpn, marca, modelo, nombre),
312:     )
313:     return cur.rowcount > 0
314: 
315: 
316: def mark_not_found(id_prestashop: int) -> None:
317:     """Set `product_not_found = True` so the product is excluded from future runs (RF-05)."""
318:     conn = get_connection()
319:     try:
320:         conn.execute(
321:             "UPDATE productos SET product_not_found = 1 WHERE id_prestashop = ?",
322:             (id_prestashop,),
323:         )
324:         conn.commit()
325:     finally:
326:         conn.close()
327: 
328: 
329: def sync_producto_from_prestashop(
330:     conn: sqlite3.Connection,
331:     id_prestashop: int,
332:     ean: str | None,
333:     mpn: str | None,
334:     marca: str,
335:     nombre: str | None,
336:     id_category_default: int | None,
337: ) -> list[str]:
338:     """Sync a local product row with current PrestaShop data.
339: 
340:     PrestaShop is the source of truth.  Updates fields where the local value
341:     is empty or differs from PrestaShop.  Also resets ``product_not_found``
342:     if the product exists in PrestaShop (it was found).
343:     Returns a list of updated field names (empty list = nothing changed).
344:     """
345:     row = conn.execute(
346:         "SELECT ean, mpn, marca, nombre, product_not_found FROM productos WHERE id_prestashop = ?",
347:         (id_prestashop,),
348:     ).fetchone()
349:     if not row:
350:         return []
351: 
352:     set_parts: list[str] = []
353:     params: list[str | int | None] = []
354: 
355:     # Field sync: update if local is empty/different AND PS has a value
356:     for col, ps_val in [
357:         ("ean", ean),
358:         ("mpn", mpn),
359:         ("marca", marca),
360:         ("nombre", nombre),
361:     ]:
362:         local_val = row[col]
363:         if ps_val and ps_val != local_val:
364:             set_parts.append(f"{col} = ?")
365:             params.append(ps_val)
366: 
367:     # Reset product_not_found if it was set — product exists in PrestaShop
368:     if row["product_not_found"]:
369:         set_parts.append("product_not_found = 0")
370: 
371:     if not set_parts:
372:         return []
373: 
374:     params.append(id_prestashop)
375:     conn.execute(
376:         f"UPDATE productos SET {', '.join(set_parts)} WHERE id_prestashop = ?",
377:         params,
378:     )
379: 
380:     return [p.split(" =")[0] for p in set_parts]
381: 
382: 
383: def get_subcategoria_id(conn: sqlite3.Connection, nombre: str) -> int | None:
384:     row = conn.execute(
385:         "SELECT id_subcategoria FROM subcategorias WHERE nombre_subcategoria = ?", (nombre,)
386:     ).fetchone()
387:     return row["id_subcategoria"] if row else None
388: 
389: 
390: def get_subcategoria_by_ps_category(conn: sqlite3.Connection, ps_category_id: int) -> int | None:
391:     row = conn.execute(
392:         "SELECT id_subcategoria FROM subcategorias WHERE id_prestashop_categoria = ?",
393:         (ps_category_id,),
394:     ).fetchone()

(Showing lines 295-394 of 444. Use offset=395 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 5.4s)

_Thinking:_

So the DB side: PrestaShop is the source of truth for the name. The local `nombre` is synced FROM PrestaShop. The name change on PrestaShop would need to come from `put_product` with a "name" key in `updates`. Neither enrich.py nor app.py approve route includes "name" in updates.

Let me search for where a `nombre`/`name` might be set from scraped data and written to the proposal or DB. Let me check the `scrape_from_direct_url` and where proposal_json gets stored. Maybe the scraper stores `nombre`/`name` in the proposal JSON, and the diff UI displays it as the "new name". Actually, the user says "cambio de nombre" — maybe when they approve a product, the name in PrestaShop changes. Let me search more thoroughly for `name` assignments in enrich.py and where `proposal_json` is constructed.

Actually wait — let me re-read the AGENTS.md: "_validate_name_coherence rejects data whose enriched brand contradicts the original product name (a "Smart TV Samsung" can't end up as "Fravega")". This is about validation. The user is saying: "No debe haber cambio de nombre en los productos". Perhaps they saw in the admin diff UI that the proposal includes a different name/title, and it's being shown as if the product name would change.

Let me look at where proposal JSON gets a "nombre" or "name" key, e.g. from the scraper output (JSON-LD "name" → proposal). Let me look at enrich.py's _store / the part that constructs proposal_json. Let me grep for proposal_json in enrich.py and official_scraper.py.

**Tool: grep**

**Input:**
```json
{
  "include": "*.py",
  "path": "/home/icrocetti/dev/ProyectoDC",
  "pattern": "proposal_json|proposal =|proposal\\["
}
```

**Output:**
```
Found 32 matches
/home/icrocetti/dev/ProyectoDC/admin_ui/app.py:
  Line 315:                           proposal_json IS NOT NULL AS tiene_propuesta

  Line 319:             query += " WHERE proposal_json IS NOT NULL"

  Line 328:                 " WHERE proposal_json IS NULL AND product_not_found = 0"

  Line 360:         # Parse proposal_json for the diff view

  Line 361:         raw_json = product.get("proposal_json")

  Line 362:         proposal = None

  Line 365:                 proposal = json.loads(raw_json) if isinstance(raw_json, str) else raw_json

  Line 367:                 proposal = None

  Line 410:         # Parse proposal from proposal_json

  Line 411:         raw_json = product.get("proposal_json")

  Line 412:         proposal = None

  Line 415:                 proposal = json.loads(raw_json) if isinstance(raw_json, str) else raw_json

  Line 417:                 proposal = None

  Line 481:                    proposal_json = NULL,

  Line 551:             "UPDATE productos SET proposal_json = NULL WHERE id_prestashop = ?",

  Line 575:                    proposal_json = NULL,


/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py:
  Line 1708:     - Updates ``productos.proposal_json``, ``productos.marca``,

  Line 2087:                SET proposal_json = ?,


/home/icrocetti/dev/ProyectoDC/middleware/enrich.py:
  Line 635:                       p.proposal_json, p.id_subcategoria,

  Line 679:             existing_json = row["proposal_json"]

  Line 756:                            SET proposal_json = ?,


/home/icrocetti/dev/ProyectoDC/middleware/db.py:
  Line 78:             # Migration 001 (admin UI): icecat_json (renamed to proposal_json by 008) + audit_log

  Line 140:             # Migration 008: rename icecat_json → proposal_json (the column stores

  Line 144:                     "ALTER TABLE productos RENAME COLUMN icecat_json TO proposal_json"


/home/icrocetti/dev/ProyectoDC/tests/test_db.py:
  Line 42:     assert {"proposal_json", "imagen_url", "active_verified",


/home/icrocetti/dev/ProyectoDC/middleware/check_active.py:
  Line 192:         proposal_json = product.get("proposal_json")

  Line 195:         proposal = None

  Line 196:         if proposal_json:

  Line 198:                 proposal = json.loads(proposal_json) if isinstance(proposal_json, str) else proposal_json

  Line 200:                 proposal = None

  Line 221:             proposal = translated or product_data

  Line 226:                    SET proposal_json = ?,

```

---

## Assistant (Build · Big Pickle · 3.0s)

_Thinking:_

Let me look at the diff view in app.py (line 360-460) and also see how the proposal JSON gets constructed in enrich.py (around line 630-760). Let me also check the diff.html template to see what's displayed. The user's concern is that the product name changes. Maybe the diff page shows the scraped product "name"/"title" as a new name field that could be applied.

Let me read enrich.py around 630-770.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "limit": 180,
  "offset": 600
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/enrich.py</path>
<type>file</type>
<content>
600:       → parse existing data and push without re-fetching.
601:     - Products without data → fetch from brand site search / AI agent, then push.
602: 
603:     Not-found products are flagged ``product_not_found = 1`` and
604:     remain in the queue for manual URL enrichment via the Admin UI.
605: 
606:     ``override`` (opcional) es un dict ``{'subcategoria': str, 'cantidad': int}``
607:     para una ejecución única: se usa ESE objetivo en vez del plan configurado,
608:     sin modificarlo.
609: 
610:     On success: ``estado_actualizacion = 'actualizado'``, EAV written, audit logged.
611:     On failure: data kept so admin UI can retry.
612:     """
613:     processed = 0
614: 
615:     plan_sub = (
616:         (override or {}).get("subcategoria")
617:         or plan.effective_subcategoria()
618:     )
619:     plan_limit = (
620:         (override or {}).get("cantidad")
621:         or plan.effective_cantidad(BATCH_SIZE)
622:     )
623:     conn = get_connection()
624:     try:
625:         objetivo = (
626:             plan.describe_target(conn, plan_sub, plan_limit)
627:             if override
628:             else plan.describe_plan(conn)
629:         )
630:         logger.info(
631:             "Plan de trabajo: %s (límite %d por ciclo)",
632:             objetivo, plan_limit,
633:         )
634:         query = """SELECT p.id_prestashop, p.ean, p.mpn, p.marca, p.modelo, p.nombre,
635:                       p.proposal_json, p.id_subcategoria,
636:                       COALESCE(s.nombre_subcategoria, '') AS subcat_name
637:                FROM productos p
638:                LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
639:                WHERE p.product_not_found = 0
640:                  AND p.estado_actualizacion = 'desactualizado'"""
641:         params: list = []
642:         fetch_limit = plan_limit
643:         if plan_sub:
644:             # Filtro por similitud con el nombre del producto: se traen más
645:             # candidatos y se refinan en Python (SQLite no hace SequenceMatcher).
646:             from .plan import matches_name
647:             fetch_limit = max(plan_limit * 20, 200)
648:         query += " LIMIT ?"
649:         params.append(fetch_limit)
650: 
651:         rows = conn.execute(query, params).fetchall()
652: 
653:         if plan_sub:
654:             rows = [
655:                 r for r in rows if matches_name(plan_sub, r["nombre"] or "")
656:             ][:plan_limit]
657: 
658:         if not rows:
659:             logger.info("No products pending enrichment")
660:             return 0
661: 
662:         logger.info("Processing %d products", len(rows))
663:         pipeline_state.start(len(rows))
664: 
665:         for i, row in enumerate(rows, 1):
666:             pid = row["id_prestashop"]
667:             ean = row["ean"]
668:             mpn = row["mpn"]
669:             marca = row["marca"] or ""
670:             modelo = row["modelo"] or ""
671:             nombre = row["nombre"] or ""
672: 
673:             pipeline_state.update(i, pid, nombre)
674:             logger.info(
675:                 "  [%d/%d] Procesando id=%d — %s",
676:                 i, len(rows), pid, nombre or "(sin nombre)",
677:             )
678: 
679:             existing_json = row["proposal_json"]
680:             product_data = None
681:             translated = None
682: 
683:             # ---- Path A: existing data (just push) -------------------------
684:             # Only reuse stored data if it has actual characteristics.
685:             # Empty characteristics means the previous scrape failed to extract
686:             # specs — re-scrape instead of pushing empty data.  Stored data
687:             # whose characteristics are JS template placeholders ({{...}}) is
688:             # garbage and must be re-scraped too.
689:             if existing_json:
690:                 try:
691:                     parsed = json.loads(existing_json) if isinstance(existing_json, str) else existing_json
692:                 except (json.JSONDecodeError, TypeError):
693:                     parsed = None
694:                 stored_valid = False
695:                 if parsed and parsed.get("caracteristicas"):
696:                     stored_chars = parsed["caracteristicas"]
697:                     clean_chars = [
698:                         c for c in stored_chars
699:                         if not is_template_placeholder(str(c.get("nombre", "")))
700:                         and not is_template_placeholder(str(c.get("valor", "")))
701:                     ]
702:                     stored_valid = bool(clean_chars)
703:                 if stored_valid:
704:                     # Guard de coherencia: no re-empujar datos cuya marca
705:                     # contradiga el nombre original (ej. "tele" → "Fravega").
706:                     if not _validate_name_coherence(parsed, nombre, marca):
707:                         stored_valid = False
708:                         logger.info(
709:                             "  EXISTING  id=%d  — stored data incoherent with name, re-scraping",
710:                             pid,
711:                         )
712:                         pipeline_state.add_log(
713:                             f"Datos guardados incoherentes con el nombre, re-scrapeando id={pid}"
714:                         )
715:                     # Guard de identidad: datos guardados de un scrapeo ajeno al
716:                     # producto (p. ej. "GeForce RTX 3070" para un diafragma)
717:                     # también se re-scrapean.
718:                     elif not _validate_scraped_data(parsed, marca, nombre, pid):
719:                         stored_valid = False
720:                         logger.info(
721:                             "  EXISTING  id=%d  — stored data wrong product, re-scraping",
722:                             pid,
723:                         )
724:                         pipeline_state.add_log(
725:                             f"Datos guardados no coinciden con el producto, re-scrapeando id={pid}"
726:                         )
727:                 if stored_valid:
728:                     product_data = parsed
729:                     translated = parsed
730:                     logger.info(
731:                         "  EXISTING  id=%d  — pushing stored data (%d chars)",
732:                         pid,
733:                         len(parsed["caracteristicas"]),
734:                     )
735:                     pipeline_state.add_log(f"Usando datos guardados para id={pid}")
736:                 elif parsed:
737:                     logger.info("  EXISTING  id=%d  — stored data unusable, re-scraping", pid)
738:                     pipeline_state.add_log(f"Datos guardados no válidos, re-scrapeando id={pid}")
739: 
740:             # ---- Path B: fetch from brand site / AI agent ------------------
741:             if product_data is None:
742:                 product_data, translated, description = _fetch_and_prepare(
743:                     pid, ean, mpn, marca, modelo, nombre, dry_run,
744:                 )
745:                 if product_data is None:
746:                     pipeline_state.add_log(f"Sin datos para id={pid}, saltando")
747:                     continue
748: 
749:                 # Store data + vector_descriptivo before pushing
750:                 if not dry_run:
751:                     emb = generate_embedding(description)
752:                     vec_bytes = embedding_to_bytes(emb) if emb is not None else None
753: 
754:                     conn.execute(
755:                         """UPDATE productos
756:                            SET proposal_json = ?,
757:                                vector_descriptivo = ?,
758:                                marca = ?,
759:                                modelo = ?,
760:                                imagen_url = ?
761:                            WHERE id_prestashop = ?""",
762:                         (
763:                             json.dumps(translated, ensure_ascii=False),
764:                             vec_bytes,
765:                             (product_data.get("marca") or "").strip() or marca,
766:                             (product_data.get("modelo") or "").strip() or modelo,
767:                             (product_data.get("imagen_url") or "").strip() or None,
768:                             pid,
769:                         ),
770:                     )
771:                     conn.commit()
772: 
773:             # ---- Push to PrestaShop ---------------------------------------
774:             marca_final = (product_data.get("marca") or "").strip() or marca
775:             modelo_final = (product_data.get("modelo") or "").strip() or modelo
776: 
777:             # Backfill from product name if still empty
778:             if not marca_final or not modelo_final:
779:                 from .official_scraper import _extract_model_from_name, _infer_brand_from_name

(Showing lines 600-779 of 841. Use offset=780 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 6.3s)

_Thinking:_

I see that enrichment stores `marca` and `modelo` from scraped data in the local DB (lines 754-770), but never `nombre`. And the `put_product` calls only pass `description`, `description_short`. So neither PrestaShop name nor local `nombre` gets changed by the push.

Hmm, wait — the user might be referring to something else. Maybe the admin diff UI shows a "name" that comes from the scraped data? Or the `check_active.py` auto-completion? Let me check `complete_incomplete_product` and the `check_active.py` push around line 260-290.

Actually let me reconsider the user's statement. They say: "No debe haber cambio de nombre en los productos, no tiene sentido eso, porque si yo quiero una cinta scotch de 5cm de espesor no tiene sentido que me de un celular 15c redmi"

This sounds like the pipeline is enriching products with wrong data from a different product — specifically, the scraped "name" from a reseller page might be a totally different product. And the enriched proposal's title (from the scraped JSON-LD "name") is shown somewhere and might be applied as the product name.

But wait — the AGENTS.md documents `_validate_scraped_data` check 3 (token check) and the generic-name gate precisely to prevent a "scotch tape" getting enriched as a "Redmi 15C". So maybe the user is reporting this issue still happens. OR the user is making a design requirement: "No debe haber cambio de nombre" — they don't want the product name to be changeable/changed at all.

Let me look at the diff template and how name is displayed. Let me look at admin_ui/templates/diff.html. And also the diff route in app.py (lines 340-460).

Reviso la vista diff y el template para ver cómo se muestra el nombre.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/app.py",
  "limit": 70,
  "offset": 340
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/app.py</path>
<type>file</type>
<content>
340: 
341: # ======================================================================
342: # Diff viewer  (RF-12)
343: # ======================================================================
344: 
345: @app.route("/products/<int:pid>/diff")
346: def diff(pid: int):
347:     conn = get_connection()
348:     try:
349:         row = conn.execute(
350:             """SELECT p.*, COALESCE(s.nombre_subcategoria, '') AS subcat_name
351:                FROM productos p
352:                LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
353:                WHERE p.id_prestashop = ?""", (pid,)
354:         ).fetchone()
355:         if row is None:
356:             return f"Producto {pid} no encontrado", 404
357: 
358:         product = dict(row)
359: 
360:         # Parse proposal_json for the diff view
361:         raw_json = product.get("proposal_json")
362:         proposal = None
363:         if raw_json:
364:             try:
365:                 proposal = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
366:             except (json.JSONDecodeError, TypeError):
367:                 proposal = None
368: 
369:         # current characteristics from local DB
370:         curr_chars = conn.execute(
371:             """SELECT c.nombre_caracteristica, pc.valor
372:                FROM producto_caracteristicas pc
373:                JOIN caracteristicas c ON c.id_caracteristica = pc.id_caracteristica
374:                WHERE pc.id_prestashop = ?
375:                ORDER BY c.nombre_caracteristica""",
376:             (pid,),
377:         ).fetchall()
378:     finally:
379:         conn.close()
380: 
381:     return render_template(
382:         "diff.html",
383:         product=product,
384:         proposal=proposal,
385:         curr_chars=curr_chars,
386:     )
387: 
388: 
389: # ======================================================================
390: # Approve  (RF-13)
391: # ======================================================================
392: 
393: @app.route("/products/<int:pid>/approve", methods=["POST"])
394: def approve(pid: int):
395:     actor = request.form.get("actor", session.get("usuario") or "admin")
396: 
397:     conn = get_connection()
398:     try:
399:         row = conn.execute(
400:             """SELECT p.*, COALESCE(s.nombre_subcategoria, '') AS subcat_name
401:                FROM productos p
402:                LEFT JOIN subcategorias s ON p.id_subcategoria = s.id_subcategoria
403:                WHERE p.id_prestashop = ?""", (pid,)
404:         ).fetchone()
405:         if row is None:
406:             return f"Producto {pid} no encontrado", 404
407: 
408:         product = dict(row)
409: 

(Showing lines 340-409 of 1168. Use offset=410 to continue.)
</content>
```

**Tool: glob**

**Input:**
```json
{
  "pattern": "admin_ui/templates/*.html"
}
```

**Output:**
```
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/settings.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/dashboard.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/brands.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/base.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/setup.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/login.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/products.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/diff.html
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/audit.html
```

---

## Assistant (Build · Big Pickle · 2.5s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/templates/diff.html"
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/templates/diff.html</path>
<type>file</type>
<content>
1: {% extends "base.html" %}
2: {% block content %}
3: 
4: {% macro diff_cell(current, proposed) %}
5:   {% if current == proposed %}
6:     <td class="dc dc--same" data-label="Valor">{{ current or '—' }}</td>
7:   {% elif not current and proposed %}
8:     <td class="dc dc--old" data-label="Actual"><del class="dc__del">—</del></td>
9:     <td class="dc dc--new" data-label="Propuesta"><ins class="dc__ins">{{ proposed }}</ins></td>
10:   {% elif current and not proposed %}
11:     <td class="dc dc--old" data-label="Actual"><del class="dc__del">{{ current }}</del></td>
12:     <td class="dc dc--new" data-label="Propuesta"><ins class="dc__ins">—</ins></td>
13:   {% else %}
14:     <td class="dc dc--old" data-label="Actual"><del class="dc__del">{{ current }}</del></td>
15:     <td class="dc dc--new" data-label="Propuesta"><ins class="dc__ins">{{ proposed }}</ins></td>
16:   {% endif %}
17: {% endmacro %}
18: 
19: {% macro row(label, current, proposed) %}
20:   <tr>
21:     <th class="dc__label">{{ label }}</th>
22:     {{ diff_cell(current, proposed) }}
23:   </tr>
24: {% endmacro %}
25: 
26: {% set changes = namespace(count=0) %}
27: 
28: <div class="diff-page">
29:   <div class="diff-header">
30:     <h1 class="diff-header__title">
31:       {{ product.nombre or 'Producto #' ~ product.id_prestashop }}
32:       {% if proposal and proposal.get('_score') %}
33:         <span class="diff-header__score">Coincidencia: {{ '%.0f'|format(proposal['_score'] * 100) }}%</span>
34:       {% endif %}
35:     </h1>
36:     <div class="diff-header__meta">
37:       <span>ID: <strong>{{ product.id_prestashop }}</strong></span>
38:       <span>EAN: <strong>{{ product.ean or '—' }}</strong></span>
39:       <span>MPN: <strong>{{ product.mpn or '—' }}</strong></span>
40:       {% if product.subcat_name %}
41:         <span>Categoría: <strong>{{ product.subcat_name }}</strong></span>
42:       {% endif %}
43:     </div>
44:   </div>
45: 
46:   {% if not proposal %}
47:     <div class="diff-page__empty">
48:       <p>No hay propuesta pendiente para este producto.</p>
49: 
50:       {# ── Manual URL enrichment ─────────────────────────────── #}
51:       <div class="diff-manual-url">
52:         <p class="diff-manual-url__hint">
53:           Ingresá una URL oficial del fabricante para enriquecer este producto.
54:         </p>
55:         <form method="post" action="{{ url_for('scrape_url', pid=product.id_prestashop) }}"
56:               class="diff-manual-url__form" id="scrapeForm">
57:           <input type="url" name="url" placeholder="https://www.samsung.com/us/tvs/..." required
58:                  class="diff-manual-url__input" id="scrapeUrl">
59:           <button type="submit" class="btn btn--scrape btn--lg">Scrapear URL oficial</button>
60:         </form>
61:       </div>
62: 
63:       <form method="post" action="{{ url_for('re_sync', pid=product.id_prestashop) }}"
64:             data-action="re-sync"
65:             class="diff-actions__form">
66:         <button class="btn btn--sync">Re-sincronizar</button>
67:       </form>
68:     </div>
69:   {% else %}
70:     {% set s = namespace(changed=false) %}
71:     {% for label, current, proposed_val in [
72:       ('Marca',      product.marca,  proposal.get('marca')),
73:       ('Modelo',     product.modelo, proposal.get('modelo')),
74:     ] %}
75:       {% if current != proposed_val %}{% set s.changed = true %}{% endif %}
76:     {% endfor %}
77:     {% set has_diff = s.changed %}
78: 
79:     {# ================================================================ #}
80:     {#  BANNER                                                            #}
81:     {# ================================================================ #}
82:     <div class="diff-banner {{ 'diff-banner--changed' if has_diff else 'diff-banner--clean' }}">
83:       <span class="diff-banner__icon">{{ '🔄' if has_diff else '✅' }}</span>
84:       <span class="diff-banner__text">
85:         {% if has_diff %}
86:           Este producto tiene cambios pendientes de publicar.
87:         {% else %}
88:           Los datos coinciden — solo falta publicar.
89:         {% endif %}
90:       </span>
91:     </div>
92: 
93:     {# ================================================================ #}
94:     {#  IMAGE PREVIEW                                                    #}
95:     {# ================================================================ #}
96:     {% set img_url = proposal.get('imagen_url') or product.imagen_url %}
97:     {% if img_url %}
98:     <div class="diff-image">
99:       <div class="diff-image__preview">
100:         <img src="{{ img_url }}" alt="{{ product.nombre or '' }}"
101:              onerror="this.parentElement.innerHTML='<span class=\\'diff-image__placeholder\\'>Imagen no disponible</span>'">
102:       </div>
103:       <div class="diff-image__info">
104:         <span class="diff-image__label">Imagen del producto</span>
105:         <a href="{{ img_url }}" target="_blank" class="diff-image__link">Abrir en nueva pestaña ↗</a>
106:       </div>
107:     </div>
108:     {% endif %}
109: 
110:     {# ================================================================ #}
111:     {#  DESCRIPTION PREVIEW                                              #}
112:     {# ================================================================ #}
113:     {% set desc = proposal.get('descripcion') or proposal.get('resumen') or '' %}
114:     {% set desc_corta = proposal.get('descripcion_corta') or '' %}
115:     {% if desc or desc_corta %}
116:     <div class="diff-desc">
117:       {% if desc_corta %}
118:       <div class="diff-desc__block">
119:         <h3 class="diff-desc__title">Descripción corta</h3>
120:         <p class="diff-desc__text">{{ desc_corta }}</p>
121:       </div>
122:       {% endif %}
123:       {% if desc %}
124:       <div class="diff-desc__block">
125:         <h3 class="diff-desc__title">Descripción</h3>
126:         <div class="diff-desc__text">{{ desc }}</div>
127:       </div>
128:       {% endif %}
129:     </div>
130:     {% endif %}
131: 
132:     {# ================================================================ #}
133:     {#  FIELD COMPARISON TABLE                                            #}
134:     {# ================================================================ #}
135:     <div class="diff-compare">
136:       <div class="diff-compare__header">
137:         <span class="diff-compare__col diff-compare__col--label">Campo</span>
138:         <span class="diff-compare__col diff-compare__col--old">Actual (PrestaShop)</span>
139:         <span class="diff-compare__col diff-compare__col--new">Propuesta</span>
140:       </div>
141:       <table class="diff-compare__table">
142:         {{ row('Nombre', product.nombre, proposal.get('title') or proposal.get('Titulo')) }}
143:         {{ row('Marca',  product.marca,  proposal.get('marca')) }}
144:         {{ row('Modelo', product.modelo, proposal.get('modelo')) }}
145:         {{ row('EAN',    product.ean,    product.ean) }}
146:         {{ row('MPN',    product.mpn,    product.mpn) }}
147: 
148:         {# --- Description fields --- #}
149:         {% for label, key in [
150:           ('Título',              'title'),
151:           ('Título (traducido)',  'titulo'),
152:           ('Descripción corta',   'descripcion_corta'),
153:           ('Descripción',         'descripcion'),
154:           ('Resumen',             'resumen'),
155:           ('Summary',             'summary'),
156:         ] %}
157:           {% set val = proposal.get(key) %}
158:           {% if val %}
159:             <tr>
160:               <th class="dc__label">{{ label }}</th>
161:               <td class="dc dc--old" data-label="Actual"><span class="dc__muted">(sin datos locales)</span></td>
162:               <td class="dc dc--new" data-label="Propuesta">{{ val }}</td>
163:             </tr>
164:           {% endif %}
165:         {% endfor %}
166:       </table>
167:     </div>
168: 
169:     {# ================================================================ #}
170:     {#  CHARACTERISTICS COMPARISON                                       #}
171:     {# ================================================================ #}
172:     {% if curr_chars or proposal.get('caracteristicas') %}
173:     <div class="diff-section">
174:       <h2 class="diff-section__title">
175:         Características técnicas
176:         {% set cc = curr_chars|list|length %}
177:         {% set pc = (proposal.get('caracteristicas') or [])|length %}
178:         <span class="diff-section__count">{{ cc }} actuales → {{ pc }} propuestas</span>
179:       </h2>
180: 
181:       {# build a lookup of current chars #}
182:       {% set curr_map = {} %}
183:       {% for c in curr_chars %}
184:         {% set _ = curr_map.update({c.nombre_caracteristica: c.valor}) %}
185:       {% endfor %}
186: 
187:       {# collect all keys #}
188:       {% set prop_chars = proposal.get('caracteristicas') or [] %}
189:       {% set all_keys = [] %}
190:       {% for k in curr_map.keys() %}
191:         {% set _ = all_keys.append(k) %}
192:       {% endfor %}
193:       {% for ch in prop_chars %}
194:         {% if ch.nombre not in all_keys %}
195:           {% set _ = all_keys.append(ch.nombre) %}
196:         {% endif %}
197:       {% endfor %}
198: 
199:       {# build proposed lookup #}
200:       {% set prop_map = {} %}
201:       {% for ch in prop_chars %}
202:         {% set _ = prop_map.update({ch.nombre: ch.valor}) %}
203:       {% endfor %}
204: 
205:       <table class="diff-compare__table">
206:         {% for key in all_keys %}
207:           {% set cv = curr_map.get(key) %}
208:           {% set pv = prop_map.get(key) %}
209:           {% if cv != pv %}{% set changes.count = changes.count + 1 %}{% endif %}
210:           {{ row(key, cv, pv) }}
211:         {% endfor %}
212:       </table>
213:     </div>
214:     {% endif %}
215: 
216:     {# ================================================================ #}
217:     {#  ACTIONS                                                          #}
218:     {# ================================================================ #}
219:     <div class="diff-actions">
220:       <form method="post" action="{{ url_for('approve', pid=product.id_prestashop) }}"
221:             data-action="activate"
222:             class="diff-actions__form">
223:         <input type="hidden" name="activate" value="1">
224:         <button class="btn btn--activate btn--lg">
225:           Aprobar y activar en PrestaShop
226:         </button>
227:         <p class="diff-actions__hint">
228:           Activa el producto (<strong>active = 1</strong>), actualiza
229:           descripción y características, y marca como sincronizado.
230:         </p>
231:       </form>
232: 
233:       <form method="post" action="{{ url_for('approve', pid=product.id_prestashop) }}"
234:             data-action="approve"
235:             class="diff-actions__form">
236:         <input type="hidden" name="activate" value="0">
237:         <button class="btn btn--approve btn--lg">
238:           Aprobar (sin activar)
239:         </button>
240:         <p class="diff-actions__hint">
241:           Solo actualiza descripción y características en PrestaShop.
242:           El producto <strong>no se activa</strong>.
243:         </p>
244:       </form>
245: 
246:       <form method="post" action="{{ url_for('reject', pid=product.id_prestashop) }}"
247:             data-action="reject"
248:             class="diff-actions__form">
249:         <button class="btn btn--reject btn--lg">Rechazar propuesta</button>
250:       </form>
251: 
252:       <form method="post" action="{{ url_for('re_sync', pid=product.id_prestashop) }}"
253:             data-action="re-sync"
254:             class="diff-actions__form">
255:         <button class="btn btn--sync btn--lg">Re-sincronizar</button>
256:       </form>
257:     </div>
258:   {% endif %}
259: </div>
260: 
261: <script>
262: function confirmApproval() {
263:   var msg = '¿Aprobar (sin activar)?\n\n'
264:           + '• Actualizar descripción\n'
265:           + '• Escribir características técnicas\n'
266:           + '• Marcar como sincronizado\n'
267:           + '• El producto NO se activa en PrestaShop\n\n'
268:           + '¿Confirmar?';
269:   return confirm(msg);
270: }
271: function confirmActivate() {
272:   var msg = '¿Aprobar y activar en PrestaShop?\n\n'
273:           + '• Activar producto (active = 1)\n'
274:           + '• Actualizar descripción\n'
275:           + '• Escribir características técnicas\n'
276:           + '• Marcar como sincronizado\n\n'
277:           + '¿Confirmar?';
278:   return confirm(msg);
279: }
280: 
281: // Manual URL scrape form
282: var scrapeForm = document.getElementById('scrapeForm');
283: if (scrapeForm) {
284:   scrapeForm.addEventListener('submit', function(e) {
285:     e.preventDefault();
286:     var btn = scrapeForm.querySelector('button[type="submit"]');
287:     var url = scrapeForm.querySelector('input[name="url"]').value;
288:     btn.disabled = true;
289:     btn.textContent = 'Scrapeando...';
290:     fetch(scrapeForm.action, {
291:       method: 'POST',
292:       headers: {'Content-Type': 'application/x-www-form-urlencoded'},
293:       body: 'url=' + encodeURIComponent(url)
294:     })
295:     .then(function(r) { return r.json(); })
296:     .then(function(data) {
297:       if (data.ok) {
298:         window.location.href = data.redirect;
299:       } else {
300:         alert('Error: ' + (data.error || 'Unknown error'));
301:         btn.disabled = false;
302:         btn.textContent = 'Scrapear URL oficial';
303:       }
304:     })
305:     .catch(function(err) {
306:       alert('Network error: ' + err);
307:       btn.disabled = false;
308:       btn.textContent = 'Scrapear URL oficial';
309:     });
310:   });
311: }
312: 
313: // Approve / reject / re-sync forms: submit via fetch and redirect to the
314: // returned URL (server responds with JSON, not a full page).
315: var ACTION_CONFIRMS = {
316:   activate: confirmActivate,
317:   approve: confirmApproval,
318:   reject: function() {
319:     return confirm('¿Descartar la propuesta? El producto quedará pendiente para una futura re-consulta.');
320:   },
321:   're-sync': function() {
322:     return confirm('¿Forzar re-sincronización? Se descartarán los datos actuales.');
323:   }
324: };
325: 
326: function submitActionForm(form) {
327:   var action = form.getAttribute('data-action');
328:   var confirmFn = ACTION_CONFIRMS[action];
329:   if (confirmFn && !confirmFn()) return;
330:   var btn = form.querySelector('button[type="submit"]');
331:   var original = btn.innerHTML;
332:   btn.disabled = true;
333:   btn.textContent = 'Procesando...';
334:   fetch(form.action, {
335:     method: 'POST',
336:     body: new FormData(form)
337:   })
338:   .then(function(r) { return r.json(); })
339:   .then(function(data) {
340:     if (data.ok && data.redirect) {
341:       window.location.href = data.redirect;
342:     } else {
343:       alert('Error: ' + (data.error || 'Error desconocido'));
344:       btn.disabled = false;
345:       btn.innerHTML = original;
346:     }
347:   })
348:   .catch(function(err) {
349:     alert('Error de red: ' + err);
350:     btn.disabled = false;
351:     btn.innerHTML = original;
352:   });
353: }
354: 
355: var actionForms = document.querySelectorAll('form.diff-actions__form');
356: for (var i = 0; i < actionForms.length; i++) {
357:   actionForms[i].addEventListener('submit', function(e) {
358:     e.preventDefault();
359:     submitActionForm(this);
360:   });
361: }
362: </script>
363: {% endblock %}

(End of file - total 363 lines)
</content>
```

---

## Assistant (Build · Big Pickle · 8.1s)

_Thinking:_

Now I see it. In `diff.html` line 142:

```
{{ row('Nombre', product.nombre, proposal.get('title') or proposal.get('Titulo')) }}
```

The diff view shows a "Nombre" row comparing the current product name against the proposal's `title` (the scraped product title from the web). This makes it look like the name will be changed. The user is saying: there should be NO name change — the product name should stay as-is (from PrestaShop). When the user wants a scotch tape, the proposal shouldn't come back with "celular 15c redmi" as the name.

So the fix: The product name should never be changed. This means:
1. Don't display the proposal `title` as a "Nombre" proposed change in the diff view (or clearly mark it's not applied).
2. Ensure `put_product` never sets `name` (it already doesn't).
3. Ensure the local DB `nombre` is never overwritten with the scraped title.

Actually, let me verify the claim "no name change" is fully true in the code. So far:
- `put_product` only modifies keys in `updates`; neither enrich.py nor approve route passes "name". Good.
- `sync_producto_from_prestashop` syncs `nombre` FROM PrestaShop (source of truth). That's fine — it keeps PS name.

But wait — the user's complaint mentions "cambio de nombre" — where did they see a name change? Probably in the diff view, they see the proposal "Nombre" field showing something like "Xiaomi Redmi 15C" for a "cinta scotch 5cm" product, implying the name would change. This is because the scraper scraped a wrong product page and put its title in proposal['title'], which gets shown as a proposed "Nombre".

So the design decision the user wants: don't show/apply a name change. The diff should not present the scraped title as the proposed product name. The validation (`_validate_scraped_data`) is supposed to prevent wrong products, but it doesn't always work — and the user wants a hard rule: the name NEVER changes.

Let me verify there's no other place where the name is set to the scraped title. Let me check `check_active.py` complete_incomplete_product push, and the `_fetch_and_prepare` in enrich.py — does it store `title` in the proposal? Also let me check ai_agent.py line 453: `cleaned_name = " ".join(cleaned_words[:5])` — what is that for? Let me look.

Also check `check_active.py` line 276 put_product call.

Let me confirm by checking the enrich push and check_active push, plus where proposal stores title.

Reviso cómo se construye el `title` en la propuesta y qué hace `check_active` en el push.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "limit": 130,
  "offset": 240
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/enrich.py</path>
<type>file</type>
<content>
240:                      'support', 'faq', 'preguntas', 'solucion', 'troubleshoot',
241:                      'service repair')
242:     spec_signals = ('specification', 'specs', 'especificacion', 'especificaciones',
243:                     'ficha tecnica', 'ficha-tecnica', 'technical-specification',
244:                     'technical specification', 'caracteristicas')
245:     def _is_specs_page(*texts: str) -> bool:
246:         return any(sig in t for t in texts for sig in spec_signals)
247: 
248:     if not _is_specs_page(scraped_url, scraped_title):
249:         if any(p in scraped_url for p in junk_patterns):
250:             logger.warning(
251:                 "  VALIDATE  id=%d  rejected manual/support source: url=%r", pid, scraped_url[:120],
252:             )
253:             return False
254:     if any(p in scraped_title for p in junk_patterns) and not _is_specs_page(scraped_title):
255:         logger.warning(
256:             "  VALIDATE  id=%d  rejected manual/support title: %r", pid, scraped_title[:80],
257:         )
258:         return False
259: 
260:     # Check 2b: size disambiguation for TVs/monitors.  If the product name
261:     # specifies a size (e.g. 75") and the scraped title/specs mention a
262:     # different size, the scraper grabbed the wrong variant (55" U8000F vs
263:     # 75" U8000F share the same model tokens).  A size in the scraped title
264:     # that differs from the expected one is fatal.
265:     import re as _re
266:     wanted_size = _re.search(r"(\d{2})\s*(?:\"|''|pulgadas|inches|inch|')(?!\w)", nombre, _re.I)
267:     if wanted_size:
268:         wanted = wanted_size.group(1)
269:         scraped_size = _re.search(r"(\d{2})\s*(?:\"|''|pulgadas|inches|inch|')(?!\w)", scraped_title, _re.I)
270:         if scraped_size and scraped_size.group(1) != wanted:
271:             logger.warning(
272:                 "  VALIDATE  id=%d  size mismatch: wanted %s\" scraped %s\" (title=%r)",
273:                 pid, wanted, scraped_size.group(1), scraped_title[:80],
274:             )
275:             return False
276:         # Also check size inside characteristics if present.  Multi-variant
277:         # pages (Samsung, TCL, LG) list every size in the same DOM — e.g.
278:         # "tamaño = 50\"" body-text artifact alongside the correct
279:         # "Tamaño de pantalla = 75\"" — so a single mismatch is NOT fatal.
280:         # Reject only when NO size characteristic matches the wanted size
281:         # (i.e. the scraper grabbed a genuinely different variant).
282:         size_re = r"(\d{2})\s*(?:\"|''|pulgadas|inches|inch|')(?!\w)"
283:         wanted_re = _re.compile(rf"(?<![\d])({wanted})(?![\d])\s*(?:\"|''|pulgadas|inches|inch)", _re.I)
284:         size_names = ("tamaño de pantalla", "screen size", "pantalla", "tamaño", "size", "diagonal")
285:         size_exclude = ("paquete", "conjunto", "empaque", "caja", "pack", "stand", "dimensiones")
286:         sizes_found = []
287:         wanted_found = False
288:         for ch in (product_data.get("caracteristicas") or []):
289:             chv = str(ch.get("valor") or "")
290:             chn = str(ch.get("nombre") or "").lower()
291:             if not any(n in chn for n in size_names):
292:                 continue
293:             if any(e in chn for e in size_exclude):
294:                 continue
295:             if wanted_re.search(chv):
296:                 wanted_found = True
297:             m = _re.search(size_re, chv, _re.I)
298:             if m:
299:                 sizes_found.append(m.group(1))
300:         if sizes_found and not wanted_found:
301:             logger.warning(
302:                 "  VALIDATE  id=%d  size mismatch in characteristics: wanted %s\" got sizes=%s",
303:                 pid, wanted, sorted(set(sizes_found)),
304:             )
305:             return False
306: 
307:     # Check 3: scraped title should contain at least one significant token
308:     # from the expected product name (model number)
309:     if scraped_title:
310:         import re as _re
311:         import unicodedata as _ud
312:         from difflib import SequenceMatcher as _SeqMatcher
313: 
314:         def _norm(s: str) -> str:
315:             s = _ud.normalize("NFKD", s.lower())
316:             return "".join(c for c in s if not _ud.combining(c))
317: 
318:         def _alnum(s: str) -> str:
319:             return "".join(c for c in _norm(s) if c.isalnum())
320: 
321:         nombre_lower = nombre.lower()
322: 
323:         # (letter+digit, e.g. "GND307", "DCP1617NW", "un75u").  Negative
324:         # lookbehind: "st15" must NOT fragment out of "nm-st15" (a hyphenated
325:         # part code is one token, not a "st" + "15" pair).
326:         model_tokens = [
327:             t for t in _re.findall(
328:                 r'(?<![a-z0-9\-])[a-z]{2,}[-]?\d{1,}[a-z]{0,4}', nombre_lower,
329:             )
330:             if len(t) >= 3
331:         ]
332:         sig_words = [
333:             w for w in nombre_lower.split()
334:             if len(w) >= 3 and w not in (
335:                 'impresora', 'monitor', 'smart', 'mouse', 'wireless', 'laser',
336:                 'multifuncion', 'multifuncional', 'brother', 'logitech', 'samsung',
337:             )
338:         ]
339: 
340:         # Normalize: remove accents/dashes/spaces for flexible matching
341:         # (dcp-1617nw == dcp1617nw).
342:         scraped_norm = _alnum(scraped_title)
343: 
344:         matched_models = [t for t in model_tokens if _alnum(t) in scraped_norm]
345: 
346:         # (a) Si el nombre tiene un token tipo modelo (letras+digitos, p. ej.
347:         # GND307), es un identificador decisivo: al menos uno DEBE aparecer en
348:         # el título scrapeado.  Sin esto, "KIT DIAFRAGMA GND307" se enriquece
349:         # con una página de "GeForce RTX 3070".
350:         if model_tokens and not matched_models:
351:             logger.warning(
352:                 "  VALIDATE  id=%d  model token missing: scraped_title=%r, expected_models=%s",
353:                 pid, scraped_title[:80], model_tokens[:5],
354:             )
355:             return False
356: 
357:         matched_words = [w for w in sig_words if _alnum(w) in scraped_norm]
358: 
359:         # (b) Sin token tipo modelo, al menos una palabra significativa debe
360:         # coincidir.
361:         if not matched_models and not matched_words:
362:             logger.warning(
363:                 "  VALIDATE  id=%d  no token match: scraped_title=%r, expected_tokens=%s",
364:                 pid, scraped_title[:80], (sig_words or model_tokens)[:5],
365:             )
366:             return False
367: 
368:         # (c) Nombres genéricos (sin marca ni código de modelo) son ambiguos:
369:         # un solapamiento suelto de una palabra ("tapa"/"combustible") puede

(Showing lines 240-369 of 841. Use offset=370 to continue.)
</content>
```

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "limit": 140,
  "offset": 160
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/check_active.py</path>
<type>file</type>
<content>
160: 
161:     # Skip if already verified as complete
162:     if product.get("active_verified"):
163:         logger.debug("Product %d already verified as complete, skipping", pid)
164:         return True
165: 
166:     # Check completeness
167:     completeness = check_product_completeness(pid)
168:     if completeness["is_complete"]:
169:         logger.info("Product %d is already complete, marking as verified", pid)
170:         if not dry_run:
171:             conn = get_connection()
172:             try:
173:                 conn.execute(
174:                     "UPDATE productos SET active_verified = 1 WHERE id_prestashop = ?",
175:                     (pid,),
176:                 )
177:                 conn.commit()
178:             finally:
179:                 conn.close()
180:         return True
181: 
182:     missing = completeness["missing"]
183:     logger.info("Product %d is incomplete, missing: %s", pid, missing)
184: 
185:     if dry_run:
186:         logger.info("  DRY RUN — would complete product %d (missing: %s)", pid, missing)
187:         return True
188: 
189:     conn = get_connection()
190:     try:
191:         subcat_name = product.get("subcat_name") or ""
192:         proposal_json = product.get("proposal_json")
193: 
194:         # Parse existing proposal if available
195:         proposal = None
196:         if proposal_json:
197:             try:
198:                 proposal = json.loads(proposal_json) if isinstance(proposal_json, str) else proposal_json
199:             except (json.JSONDecodeError, TypeError):
200:                 proposal = None
201: 
202:         # If no proposal exists, we need to fetch data first
203:         if proposal is None:
204:             logger.info("Product %d has no proposal data, running enrichment first", pid)
205:             from .enrich import _fetch_and_prepare
206: 
207:             product_data, translated, description = _fetch_and_prepare(
208:                 pid,
209:                 product.get("ean"),
210:                 product.get("mpn"),
211:                 product.get("marca") or "",
212:                 product.get("modelo") or "",
213:                 product.get("nombre") or "",
214:                 dry_run=False,
215:             )
216: 
217:             if product_data is None:
218:                 logger.warning("Could not fetch data for product %d", pid)
219:                 return False
220: 
221:             proposal = translated or product_data
222: 
223:             # Store the proposal
224:             conn.execute(
225:                 """UPDATE productos
226:                    SET proposal_json = ?,
227:                        marca = ?,
228:                        modelo = ?,
229:                        imagen_url = ?
230:                    WHERE id_prestashop = ?""",
231:                 (
232:                     json.dumps(proposal, ensure_ascii=False),
233:                     (product_data.get("marca") or "").strip() or product.get("marca"),
234:                     (product_data.get("modelo") or "").strip() or product.get("modelo"),
235:                     (product_data.get("imagen_url") or "").strip() or None,
236:                     pid,
237:                 ),
238:             )
239:             conn.commit()
240: 
241:         # Now complete the missing fields
242:         client = AdminPrestashopClient()
243: 
244:         try:
245:             # Get current product from PrestaShop
246:             ps_product = client.get_product(pid)
247: 
248:             # Build updates dict
249:             updates = {}
250: 
251:             # Complete description if missing
252:             if "description" in missing:
253:                 chars = proposal.get("caracteristicas") or []
254:                 merged_chars = merge_characteristics(chars, subcat_name)
255:                 desc = _build_description(proposal, merged_chars)
256:                 if desc:
257:                     updates["description"] = desc
258: 
259:                 # Also set description_short if empty
260:                 desc_short = ps_product.get("description_short", "")
261:                 if not desc_short or (isinstance(desc_short, str) and not desc_short.strip()):
262:                     excel_desc = get_description(subcat_name)
263:                     if excel_desc.get("descripcion_corta"):
264:                         updates["description_short"] = excel_desc["descripcion_corta"]
265: 
266:             # Complete characteristics if missing
267:             feature_pairs = None
268:             if "characteristics" in missing:
269:                 chars = proposal.get("caracteristicas") or []
270:                 merged_chars = merge_characteristics(chars, subcat_name)
271:                 if merged_chars:
272:                     feature_pairs = client.sync_characteristics_as_features(merged_chars)
273: 
274:             # Push updates to PrestaShop
275:             if updates or feature_pairs:
276:                 client.put_product(
277:                     pid, updates,
278:                     feature_pairs=feature_pairs or None,
279:                 )
280:                 logger.info("  Updated product %d: %s", pid, list(updates.keys()))
281: 
282:             # Upload images if missing
283:             if "image" in missing:
284:                 imagen_urls = proposal.get("imagen_urls") or []
285:                 if imagen_urls:
286:                     uploaded_ids = client.upload_product_images(pid, imagen_urls)
287:                     if uploaded_ids:
288:                         logger.info("  Uploaded %d images for product %d", len(uploaded_ids), pid)
289:                     else:
290:                         logger.warning("  Failed to upload images for product %d", pid)
291:                 else:
292:                     imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""
293:                     if imagen_url:
294:                         img_id = client.upload_product_image(pid, imagen_url)
295:                         if img_id:
296:                             logger.info("  Uploaded image for product %d: %s", pid, imagen_url)
297:                         else:
298:                             logger.warning("  Failed to upload image for product %d", pid)
299: 

(Showing lines 160-299 of 637. Use offset=300 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 6.3s)

_Thinking:_

OK. So the push paths never set the name. The only place a "name" appears to change is in the diff view showing proposal title as the proposed "Nombre" — and the user interprets this as a potential name change. Also, `_fetch_and_prepare` stores `title` in the proposal.

But actually, maybe the real issue the user saw: the DB `nombre` or PrestaShop name DID change. Let me check where `title` gets used. Let me look at `_fetch_and_prepare` to see the structure of the proposal. Also, is there anywhere that writes `nombre` from proposal? Let me search for `proposal.get("title"` and `\bname\b` usage near updates in enrich.py.

Actually, let me reconsider. The user might be complaining about the diff UI showing "Nombre" with a proposed value (the scraped title). Since approval doesn't apply the title, it's purely cosmetic — but it's misleading and confusing. The user says "no debe haber cambio de nombre". The fix should be to remove the "Nombre" row from the diff comparison (since name never changes), and remove title/Titulo proposed rows if they imply a name change.

But wait — maybe the user actually observed the name changing in PrestaShop. Let me double check that there is no other write path. Let me search for `"name"` assignments to the product XML beyond `_set_field` calls. In `put_product`, updates keys are applied via `_set_field`. Since neither caller passes "name", no change. Unless... `check_inactive_pending` or something else calls put_product with name. Let me check the whole codebase for put_product calls with "name".

Also there might be a `link_rewrite` sync issue. Actually, let me grep for `'name'` in enrich.py and check_active.py — we saw none.

Let me now confirm my hypothesis by checking git history / recent commits for name-related changes, and also look at where proposal title is produced (ai_agent, official_scraper). Let me look at enrich.py `_fetch_and_prepare` and where `title` is set.

**Tool: grep**

**Input:**
```json
{
  "include": "*.py",
  "path": "/home/icrocetti/dev/ProyectoDC/middleware",
  "pattern": "\"title\"|'title'|titulo"
}
```

**Output:**
```
Found 20 matches
/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py:
  Line 444:                 "title": name,

  Line 728:         "og:title": "title",

  Line 748:     if "title" not in result:

  Line 749:         t = soup.find("title")

  Line 751:             result["title"] = t.get_text(strip=True)


/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py:
  Line 1835:         if og_data.get("title"):

  Line 1837:                 "title": og_data.get("title", ""),

  Line 1875:                     title = result.get("title") or db_nombre

  Line 2167:         "title": "",


/home/icrocetti/dev/ProyectoDC/middleware/enrich.py:
  Line 73:     scraped_title = (product_data.get("title") or product_data.get("titulo") or "").strip()

  Line 237:     scraped_title = (product_data.get("title") or product_data.get("titulo") or "").lower()

  Line 578:             translated.get("Title") or translated.get("title")

  Line 579:             or translated.get("Titulo") or translated.get("titulo"),

  Line 794:                         translated.get("Title") or translated.get("title"),


/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py:
  Line 262:         if og_data.get("title"):

  Line 264:                 "title": og_data.get("title", ""),

  Line 377:     title = (data.get("title") or data.get("titulo") or "").lower()

  Line 508:         title = r.get("title", "")


/home/icrocetti/dev/ProyectoDC/middleware/pdf_scraper.py:
  Line 227:         "title": "",


/home/icrocetti/dev/ProyectoDC/middleware/translate.py:
  Line 86:         fields = ["titulo", "title", "descripcion", "description", "resumen", "summary"]

```

---

## Assistant (Build · Big Pickle · 14.7s)

_Thinking:_

So the proposal contains a `title` (scraped product title). The diff.html line 142 shows it as a proposed "Nombre". That's the misleading "name change".

The user's requirement: no name change on products. The diff UI should not imply that the name will change. The cleanest fix:
1. Remove the "Nombre" row from the diff comparison (line 142) and the 'Título'/'title' rows (lines 149-165) which imply a renamed product, OR at least remove 'Nombre' since the name never gets applied.
2. Also, `put_product` should never accept a "name" key — defensively strip it. That guarantees the name can never change regardless of caller.

Actually, let me think about what the user really wants. They want:
- The product name must never be changed. 
- The enrichment pipeline shouldn't return a different product (e.g., scotch tape → Redmi 15C). This is about identity validation.

The identity validation already exists (`_validate_scraped_data`). But the user saw the diff UI showing a "Nombre: ... Redmi 15C ..." proposed value. So even if the name isn't actually applied, the UI is confusing/misleading. The user explicitly says "No debe haber cambio de nombre en los productos".

The most robust implementation of "no name change":
1. Remove the "Nombre" comparison row from diff.html (and the title rows that could be read as a name change). The name is immutable.
2. Defensively guarantee `put_product` never modifies `name` (and `link_rewrite`?), by ignoring/removing those keys from `updates`.

Let me check the AGENTS.md Gotchas: "_set_field handles <language> creation for multi-language fields — but only for keys in its hardcoded list (description, description_short, name, link_rewrite, meta_title...)". So `name` is supported by _set_field, meaning a caller could pass it. To enforce "no name change", we should filter out "name" and possibly "link_rewrite" in put_product.

Let me confirm with the user before making changes? The instruction says to be proactive when asked. The user made a clear statement of intent: "No debe haber cambio de nombre en los productos". This is a requirement. I should implement it.

Let me check git log to see if there's recent context about name changes, and check if there was any recent change to _set_field allowing name. Let me look at git log briefly.

Actually, let me focus. The implementation:
1. `admin_ui/prestashop.py put_product`: filter out `name` (and maybe `link_rewrite`) from `updates` to guarantee immutability. Actually link_rewrite is derived from name; changing link_rewrite would also be a "name change" of sorts. The user said "cambio de nombre en los productos" — strictly name. I'll filter `name` and `link_rewrite` to be safe? Hmm, link_rewrite is URL slug. I think just `name` is what the user wants. But leaving link_rewrite could cause mismatch. Let me be conservative: strip `name` only, since that's what the user explicitly asked. Actually — I'll ask... no, keep it simple. The user is clear: no name changes. I'll strip `name` and `link_rewrite` both since link_rewrite must stay consistent with name (PrestaShop regenerates it anyway). Hmm, actually stripping link_rewrite might break nothing since callers never pass it. I'll strip `name` only to be minimal and precise.

Wait — but is there value in also keeping the diff UI? The user's core complaint is that a proposal for a scotch tape shows "celular 15c redmi". That's an identity-validation failure too. But the existing validation handles that. The user's framing is "no name change". I'll:
- Remove the "Nombre" row and the 'Título'/'title'/'Titulo' rows from the diff table (name and title are not applied on approve).

Actually the 'Título (traducido)' etc. are just informational display of the scraped page title — they're harmless but could confuse. The main fix: the "Nombre" row should not exist (or should be shown as "sin cambios").

Let me decide precisely what to change:

In diff.html:
- Line 142: `{{ row('Nombre', product.nombre, proposal.get('title') or proposal.get('Titulo')) }}` → remove the Nombre row entirely, since the name never changes. Or show it as a single cell "No se modifica". I'll remove it.

In the description fields loop (lines 149-165), 'Título'/'title' and 'Título (traducido)'/'titulo' are shown as proposed values. These are the scraped page title — they look like a name change proposal. Remove those two from the loop? The loop also shows Descripción corta, Descripción, Resumen, Summary which are legit content fields that don't change the name. But 'Título' rows imply name change. I'll remove the 'Título' and 'Título (traducido)' entries from that list.

In `put_product` (admin_ui/prestashop.py): enforce immutability — ignore "name" (and I'd argue "link_rewrite") keys in updates. Let me implement: at the top of the updates loop, `if key in ("name", "link_rewrite"): continue` — or remove from the XML element after setting. Better to skip setting. But also if a caller passes name, we should not silently... just skip. I'll add a guard.

Hmm wait, but the user might actually be reporting a real bug: that the name DID change in PrestaShop. Let me verify once more that nothing passes "name". Search for `"name"` in enrich.py and app.py and check_active.py as updates keys. Already searched — `updates` dicts contain description/description_short/active only. `_set_field` supports name but nothing calls with it.

But hold on — could the PrestaShop name change because `link_rewrite` is sent, or because of the GET-modify-PUT round trip? No — put_product re-sends all fields from GET untouched except modified ones. Name stays.

So the "name change" the user saw is almost certainly the diff UI showing the scraped title under "Nombre". Good.

Let me also double check: is there a `re_sync` or `scrape_url` path that writes `nombre`? `scrape_from_direct_url` updates proposal_json, marca, modelo, imagen_url — let me verify it doesn't touch nombre. Let me look at official_scraper.py lines 1700-2100.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "limit": 70,
  "offset": 2050
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py</path>
<type>file</type>
<content>
2050: 
2051:     logger.info(
2052:         "  MANUAL_URL  id=%d  extracted %d characteristics from %s",
2053:         product_id, len(result.get("caracteristicas") or []), final_url,
2054:     )
2055: 
2056:     # Store source URL for validation
2057:     result["url"] = url
2058: 
2059:     # 4. Persist to DB
2060:     _persist_scrape_result(product_id, result, source="manual_url", url=url)
2061: 
2062:     logger.info(
2063:         "  MANUAL_URL  id=%d  saved %s %s (%d chars)",
2064:         product_id,
2065:         (result.get("marca") or "").strip(),
2066:         (result.get("modelo") or "").strip(),
2067:         len(result.get("caracteristicas") or []),
2068:     )
2069:     return result
2070: 
2071: 
2072: def _persist_scrape_result(product_id: int, result: dict, source: str, url: str) -> None:
2073:     """Persist a scraped product result to the local DB.
2074: 
2075:     Updates ``productos`` (proposal JSON, marca/modelo, imagen, status) with
2076:     the *source* URL, appends an audit entry, and writes the EAV
2077:     characteristics — all in one transaction.
2078:     """
2079:     conn = get_connection()
2080:     try:
2081:         marca = (result.get("marca") or "").strip()
2082:         modelo = (result.get("modelo") or "").strip()
2083:         imagen = (result.get("imagen_url") or "").strip() or None
2084: 
2085:         conn.execute(
2086:             """UPDATE productos
2087:                SET proposal_json = ?,
2088:                    marca           = COALESCE(NULLIF(?, ''), marca),
2089:                    modelo          = COALESCE(NULLIF(?, ''), modelo),
2090:                    imagen_url      = COALESCE(?, imagen_url),
2091:                    estado_actualizacion = 'desactualizado',
2092:                    fecha_sincronizacion = datetime('now')
2093:                WHERE id_prestashop = ?""",
2094:             (
2095:                 json.dumps(result, ensure_ascii=False),
2096:                 marca,
2097:                 modelo,
2098:                 imagen,
2099:                 product_id,
2100:             ),
2101:         )
2102: 
2103:         # Audit
2104:         detalle = json.dumps({
2105:             "source": source,
2106:             "url": url,
2107:             "marca": marca,
2108:             "modelo": modelo,
2109:             "characteristics": len(result.get("caracteristicas") or []),
2110:         }, ensure_ascii=False)
2111:         conn.execute(
2112:             "INSERT INTO audit_log (id_producto, actor, accion, detalle) "
2113:             "VALUES (?, ?, ?, ?)",
2114:             (product_id, "admin", "scrape_manual_url", detalle),
2115:         )
2116: 
2117:         # Write EAV using the same connection
2118:         write_eav(conn, product_id, result.get("caracteristicas") or [])
2119:         conn.commit()

(Showing lines 2050-2119 of 2234. Use offset=2120 to continue.)
</content>
```

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "limit": 50,
  "offset": 780
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/enrich.py</path>
<type>file</type>
<content>
780:                 if not marca_final and nombre:
781:                     inferred = _infer_brand_from_name(nombre)
782:                     if inferred:
783:                         marca_final = inferred.title()
784:                 if not modelo_final and nombre:
785:                     model = _extract_model_from_name(nombre, marca_final)
786:                     if model:
787:                         modelo_final = model
788: 
789:             if not dry_run:
790:                 if translated and "_score" not in translated:
791:                     modelo_row = modelo or ""
792:                     local_desc = f"{marca} {modelo_row}".strip()
793:                     description = " ".join(filter(None, [
794:                         translated.get("Title") or translated.get("title"),
795:                         translated.get("Summary") or translated.get("summary"),
796:                         translated.get("Description") or translated.get("description"),
797:                     ]))
798:                     similarity = score_match(local_desc, description)
799:                     translated["_score"] = round(similarity, 4)
800: 
801:                 conn.execute(
802:                     """UPDATE productos
803:                        SET marca = ?,
804:                            modelo = ?,
805:                            imagen_url = ?,
806:                            fecha_sincronizacion = datetime('now')
807:                        WHERE id_prestashop = ?""",
808:                     (
809:                         marca_final,
810:                         modelo_final,
811:                         (product_data.get("imagen_url") or "").strip() or None,
812:                         pid,
813:                     ),
814:                 )
815:                 conn.commit()
816: 
817:                 subcat_name = row["subcat_name"]
818:                 pipeline_state.add_log(f"Enviando a PrestaShop id={pid}...")
819:                 push_ok = _push_to_prestashop(
820:                     conn, pid, product_data, marca_final, modelo_final,
821:                     subcat_name, dry_run,
822:                 )
823:                 if not push_ok:
824:                     pipeline_state.add_log(f"FALLO push id={pid} — en cola para reintento")
825:                     logger.warning("  KEPT IN QUEUE  id=%d  (push failed, admin can retry)", pid)
826:                     continue
827: 
828:             processed += 1
829:             pipeline_state.add_log(f"COMPLETADO id={pid} — {marca_final} {modelo_final}")

(Showing lines 780-829 of 841. Use offset=830 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 5.4s)

_Thinking:_

Confirmed: the pipeline never writes `nombre` and never passes `name` to `put_product`. The only place where a "name change" is suggested is the diff UI (diff.html line 142) showing the scraped `title` as the proposed "Nombre", plus the 'Título' rows.

Now let me implement the fix. My plan:

1. **Guarantee immutability at the write boundary** — `admin_ui/prestashop.py:put_product`: never allow `name` (and `link_rewrite`, which derives from name) to be written, even if a future caller passes it. This makes "no name change" structurally enforced.

2. **Remove the misleading "Nombre" row from diff.html** and the 'Título'/'Título (traducido)' proposal rows, since the name/title is never applied.

Let me also consider `admin_ui/app.py` line 439: description_short — fine.

Let me make the edits. First read the exact lines in prestashop.py around 238.

I already have lines 234-242:
```
234:         for tag in list(product_el):
235:             if tag.tag in _READ_ONLY_FIELDS:
236:                 product_el.remove(tag)
237: 
238:         for key, value in updates.items():
239:             if value is None:
240:                 continue
241:             self._set_field(product_el, key, str(value))
```

I'll add a guard to skip "name"/"link_rewrite" keys. Let me check _READ_ONLY_FIELDS to see if name is there. Let me read that section.

Confirmado: el pipeline nunca escribe `nombre` ni pasa `name` a `put_product`. El "cambio de nombre" aparece en la vista diff (diff.html:142), que muestra el `title` scrapeado como "Nombre" propuesto. Voy a hacerlo estructural: bloquear `name` en el PUT y quitar la fila engañosa del diff.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py",
  "limit": 45,
  "offset": 170
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py</path>
<type>file</type>
<content>
170:         has_image = False
171:         associations = product.get("associations", {})
172:         images = associations.get("images", [])
173:         if images and len(images) > 0:
174:             has_image = True
175:         if not has_image:
176:             missing.append("image")
177: 
178:         # Check description
179:         has_description = False
180:         description = product.get("description", "")
181:         if description:
182:             # Handle multi-language: could be string or list of dicts
183:             if isinstance(description, str) and description.strip():
184:                 has_description = True
185:             elif isinstance(description, list):
186:                 for desc in description:
187:                     if isinstance(desc, dict) and desc.get("#text", "").strip():
188:                         has_description = True
189:                         break
190:                     elif isinstance(desc, str) and desc.strip():
191:                         has_description = True
192:                         break
193:         if not has_description:
194:             missing.append("description")
195: 
196:         # Check characteristics (product_features)
197:         has_characteristics = False
198:         product_features = associations.get("product_features", [])
199:         if product_features and len(product_features) > 0:
200:             has_characteristics = True
201:         if not has_characteristics:
202:             missing.append("characteristics")
203: 
204:         return {
205:             "is_complete": len(missing) == 0,
206:             "missing": missing,
207:             "product": product,
208:         }
209: 
210:     # ------------------------------------------------------------------
211:     # write
212:     # ------------------------------------------------------------------
213: 
214:     def put_product(

(Showing lines 170-214 of 634. Use offset=215 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 2.8s)

_Thinking:_

Let me check `_READ_ONLY_FIELDS` definition.

**Tool: grep**

**Input:**
```json
{
  "include": "*.py",
  "path": "/home/icrocetti/dev/ProyectoDC/admin_ui",
  "pattern": "_READ_ONLY_FIELDS"
}
```

**Output:**
```
Found 2 matches
/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py:
  Line 32: _READ_ONLY_FIELDS = {

  Line 235:             if tag.tag in _READ_ONLY_FIELDS:

```

---

## Assistant (Build · Big Pickle · 2.6s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py",
  "limit": 55,
  "offset": 30
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py</path>
<type>file</type>
<content>
30: 
31: # Fields returned by GET that PrestaShop rejects on PUT
32: _READ_ONLY_FIELDS = {
33:     "manufacturer_name", "supplier_name",
34:     "date_add", "date_upd",
35:     "state", "position_in_category",
36:     "cache_default_attribute", "id_default_image",
37:     "id_default_combination", "quantity",
38:     "id_supplier",
39: }
40: 
41: 
42: def _wrap_language_cdata(xml_str: str) -> str:
43:     """Replace escaped HTML inside <language> tags with CDATA sections.
44: 
45:     ElementTree serializes text with XML escaping (e.g. ``&lt;p&gt;``).
46:     PrestaShop's API expects raw HTML wrapped in ``<![CDATA[...]]>``.
47:     This function finds each non-self-closing ``<language>`` tag with content,
48:     unescapes the content, and wraps it in a CDATA section.
49:     """
50:     import re
51:     from xml.sax.saxutils import unescape
52: 
53:     def _replace(m: re.Match) -> str:
54:         before = m.group(1)   # <language ...>
55:         content = m.group(2)
56:         after = m.group(3)    # </language>
57:         raw = unescape(content)
58:         return f"{before}<![CDATA[{raw}]]>{after}"
59: 
60:     # Match only non-self-closing <language> tags with content:
61:     #   <language ...>content</language>
62:     # Negative lookbehind ensures the opening tag doesn't end with /.
63:     return re.sub(
64:         r"(<language[^>]*[^/]>)(.*?)(</language>)",
65:         _replace,
66:         xml_str,
67:         flags=re.DOTALL,
68:     )
69: 
70: 
71: def _strip_prestashop_attrs(root: ET.Element) -> None:
72:     """Remove attributes that PrestaShop's PUT endpoint rejects.
73: 
74:     GET responses include ``xlink:href``, ``notFilterable``, ``nodeType``,
75:     ``api``, etc.  PrestaShop 8.1 chokes on these during PUT with a 500.
76:     This strips all attributes except ``id`` on ``<language>`` tags.
77:     """
78:     for el in root.iter():
79:         if el.tag == "language":
80:             # Keep only the id attribute
81:             lang_id = el.get("id")
82:             el.attrib.clear()
83:             if lang_id:
84:                 el.attrib["id"] = lang_id

(Showing lines 30-84 of 634. Use offset=85 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 10.3s)

_Thinking:_

Now I'll make the edits:

1. In `admin_ui/prestashop.py:put_product`, block name/link_rewrite keys from `updates`. I'll add `"name", "link_rewrite"` to the skip logic in the updates loop. Actually better: add a module constant `_IMMUTABLE_FIELDS` and skip them. Let me add to the loop:

```python
        for key, value in updates.items():
            if value is None:
                continue
            if key in _IMMUTABLE_FIELDS:
                continue
            self._set_field(product_el, key, str(value))
```

And define `_IMMUTABLE_FIELDS = {"name", "link_rewrite"}` near `_READ_ONLY_FIELDS`.

Wait — but `_set_field` is documented as supporting `name`. And there's a test `test_prestashop_helpers.py` line 81: `AdminPrestashopClient._set_field(parent, "name", "Nuevo")` — that's a direct _set_field test, not put_product. So blocking in put_product won't break the test.

Also `put_product` sets id_category_default... no name. Fine.

Let me also consider whether link_rewrite should be immutable. link_rewrite = URL slug derived from name. If someone passed a changed link_rewrite while keeping the name, that would be weird. PrestaShop itself keeps them in sync. I'll include it in immutable set to keep slug consistent with name.

2. In `diff.html`, remove the "Nombre" row (line 142) and the 'Título'/'Título (traducido)' entries from the description fields loop.

For the loop, the list is:
```
[('Título',              'title'),
 ('Título (traducido)',  'titulo'),
 ('Descripción corta',   'descripcion_corta'),
 ('Descripción',         'descripcion'),
 ('Resumen',             'resumen'),
 ('Summary',             'summary'),
]
```
Remove the 'Título' and 'Título (traducido)' entries. Keep the rest.

For the Nombre row (line 142), replace with a non-diff row that shows the name as unchanged? The user wants "no change". I'll replace the `row('Nombre', ...)` with a simple display row (same value on both sides). But `row()` macro shows a diff if different. Since proposed was the title, and we want to never show a proposed name, I'll just show the current name as a single line. Simplest: remove that row entirely. But keeping "Nombre" with only the actual value could be informative. I'll replace with a static row:

```
<tr>
  <th class="dc__label">Nombre</th>
  <td class="dc dc--same" colspan="2" data-label="Valor">{{ product.nombre or '—' }}</td>
</tr>
```

Actually the diff_cell macro produces one or two tds. Let me just do a plain row with colspan=2 spanning the "old" and "new" columns. Looking at the layout: header has 3 columns (Campo | Actual (PrestaShop) | Propuesta). A row with `<th>` + one `<td colspan="2">` would work.

But wait — there's also `has_diff` computation (line 71-77) which only checks Marca/Modelo, not name. So removing name row doesn't affect the banner. Good.

Let me also check that the "title"/"titulo" are still used for the score and description preview. The banner/score uses `_score`. The 'Título' rows were purely informational. Removing them is fine.

Now let me also double-check: does anything else display proposal title as a name? Let me check products.html and dashboard.html for 'title' usage.

Hago los cambios. Primero el bloqueo estructural en `put_product`:

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py",
  "oldString": "# Fields returned by GET that PrestaShop rejects on PUT\n_READ_ONLY_FIELDS = {\n    \"manufacturer_name\", \"supplier_name\",\n    \"date_add\", \"date_upd\",\n    \"state\", \"position_in_category\",\n    \"cache_default_attribute\", \"id_default_image\",\n    \"id_default_combination\", \"quantity\",\n    \"id_supplier\",\n}",
  "newString": "# Fields returned by GET that PrestaShop rejects on PUT\n_READ_ONLY_FIELDS = {\n    \"manufacturer_name\", \"supplier_name\",\n    \"date_add\", \"date_upd\",\n    \"state\", \"position_in_category\",\n    \"cache_default_attribute\", \"id_default_image\",\n    \"id_default_combination\", \"quantity\",\n    \"id_supplier\",\n}\n\n# Fields that must NEVER be modified by the middleware.  The product name is\n# owned by PrestaShop (source of truth) and the enrichment/approval pipeline\n# must not rename products — a scotch tape must not become a \"Redmi 15C\".\n_IMMUTABLE_FIELDS = {\"name\", \"link_rewrite\"}"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 3.3s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py",
  "newString": "        for key, value in updates.items():\n            if value is None:\n                continue\n            if key in _IMMUTABLE_FIELDS:\n                continue\n            self._set_field(product_el, key, str(value))",
  "oldString": "        for key, value in updates.items():\n            if value is None:\n                continue\n            self._set_field(product_el, key, str(value))"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 4.9s)

Ahora la vista diff: el nombre nunca cambia, así que no debe mostrarse como propuesta.

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/templates/diff.html",
  "newString": "        {{ row('Marca',  product.marca,  proposal.get('marca')) }}\n        {{ row('Modelo', product.modelo, proposal.get('modelo')) }}\n        {{ row('EAN',    product.ean,    product.ean) }}\n        {{ row('MPN',    product.mpn,    product.mpn) }}\n\n        {# --- Nombre: inmutable, nunca se propone cambio. El título scrapeado\n             no es el nombre del producto (no se aplica al aprobar). --- #}\n        <tr>\n          <th class=\"dc__label\">Nombre</th>\n          <td class=\"dc dc--same\" colspan=\"2\" data-label=\"Valor\">{{ product.nombre or '—' }}</td>\n        </tr>\n\n        {# --- Description fields --- #}\n        {% for label, key in [\n          ('Descripción corta',   'descripcion_corta'),\n          ('Descripción',         'descripcion'),\n          ('Resumen',             'resumen'),\n          ('Summary',             'summary'),\n        ] %}",
  "oldString": "        {{ row('Nombre', product.nombre, proposal.get('title') or proposal.get('Titulo')) }}\n        {{ row('Marca',  product.marca,  proposal.get('marca')) }}\n        {{ row('Modelo', product.modelo, proposal.get('modelo')) }}\n        {{ row('EAN',    product.ean,    product.ean) }}\n        {{ row('MPN',    product.mpn,    product.mpn) }}\n\n        {# --- Description fields --- #}\n        {% for label, key in [\n          ('Título',              'title'),\n          ('Título (traducido)',  'titulo'),\n          ('Descripción corta',   'descripcion_corta'),\n          ('Descripción',         'descripcion'),\n          ('Resumen',             'resumen'),\n          ('Summary',             'summary'),\n        ] %}"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 3.9s)

_Thinking:_

Now let me verify the diff.html renders properly (the colspan approach). Let me check the base.html CSS for `.dc--same` etc. to make sure a colspan=2 td fits. Let me check other usages. Also verify there are no other places showing the title as a product name (products.html, dashboard.html).

Verifico que no haya otras vistas mostrando el título como nombre propuesto y reviso el CSS del diff.

**Tool: grep**

**Input:**
```json
{
  "include": "*.html",
  "path": "/home/icrocetti/dev/ProyectoDC/admin_ui/templates",
  "pattern": "title|Titulo|Título|proposal"
}
```

**Output:**
```
Found 29 matches
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/settings.html:
  Line 2: {% block title %}Configuración — Admin{% endblock %}

  Line 47:   <h3 class="plan-week-title">Agenda semanal (opcional)</h3>


/home/icrocetti/dev/ProyectoDC/admin_ui/templates/dashboard.html:
  Line 45:           <span class="daemon-panel__title">Trabajo automático</span>

  Line 120:           <span class="terminal__title">Actividad</span>


/home/icrocetti/dev/ProyectoDC/admin_ui/templates/brands.html:
  Line 2: {% block title %}Marcas — Admin{% endblock %}

  Line 75:     <label class="brand-pdf-toggle" title="Publica especificaciones en PDF">


/home/icrocetti/dev/ProyectoDC/admin_ui/templates/base.html:
  Line 6:   <title>{% block title %}Admin — PrestaShop{% endblock %}</title>

  Line 29:     <span class="nav__user" title="Rol: {{ current_role }}">{{ current_user }}</span>

  Line 33:     <button class="nav__toggle" id="themeToggle" title="Tema claro u oscuro" aria-label="Cambiar entre tema claro y oscuro">


/home/icrocetti/dev/ProyectoDC/admin_ui/templates/setup.html:
  Line 6:   <title>Primera configuración — Panel de la tienda</title>


/home/icrocetti/dev/ProyectoDC/admin_ui/templates/login.html:
  Line 6:   <title>Iniciar sesión — Panel de la tienda</title>


/home/icrocetti/dev/ProyectoDC/admin_ui/templates/diff.html:
  Line 30:     <h1 class="diff-header__title">

  Line 32:       {% if proposal and proposal.get('_score') %}

  Line 33:         <span class="diff-header__score">Coincidencia: {{ '%.0f'|format(proposal['_score'] * 100) }}%</span>

  Line 46:   {% if not proposal %}

  Line 72:       ('Marca',      product.marca,  proposal.get('marca')),

  Line 73:       ('Modelo',     product.modelo, proposal.get('modelo')),

  Line 96:     {% set img_url = proposal.get('imagen_url') or product.imagen_url %}

  Line 113:     {% set desc = proposal.get('descripcion') or proposal.get('resumen') or '' %}

  Line 114:     {% set desc_corta = proposal.get('descripcion_corta') or '' %}

  Line 119:         <h3 class="diff-desc__title">Descripción corta</h3>

  Line 125:         <h3 class="diff-desc__title">Descripción</h3>

  Line 142:         {{ row('Marca',  product.marca,  proposal.get('marca')) }}

  Line 143:         {{ row('Modelo', product.modelo, proposal.get('modelo')) }}

  Line 161:           {% set val = proposal.get(key) %}

  Line 176:     {% if curr_chars or proposal.get('caracteristicas') %}

  Line 178:       <h2 class="diff-section__title">

  Line 181:         {% set pc = (proposal.get('caracteristicas') or [])|length %}

  Line 192:       {% set prop_chars = proposal.get('caracteristicas') or [] %}

```

**Tool: grep**

**Input:**
```json
{
  "include": "*.html",
  "path": "/home/icrocetti/dev/ProyectoDC/admin_ui/templates",
  "pattern": "dc--same|dc__label|diff-compare__table"
}
```

**Output:**
```
Found 7 matches
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/diff.html:
  Line 6:     <td class="dc dc--same" data-label="Valor">{{ current or '—' }}</td>

  Line 21:     <th class="dc__label">{{ label }}</th>

  Line 141:       <table class="diff-compare__table">

  Line 150:           <th class="dc__label">Nombre</th>

  Line 151:           <td class="dc dc--same" colspan="2" data-label="Valor">{{ product.nombre or '—' }}</td>

  Line 164:               <th class="dc__label">{{ label }}</th>

  Line 209:       <table class="diff-compare__table">

```

---

## Assistant (Build · Big Pickle · 4.4s)

_Thinking:_

Good. The diff view is now fixed. Let me verify the rendered diff.html compiles by running a quick template render test, if there's a test framework. There's no test framework configured. Let me at least do a syntax check of the Python file, and try rendering the template via Flask's Jinja environment.

Let me run a quick python check on the edited python file and render the template.

Verifico sintaxis y que el template compile:

**Tool: bash**

**Input:**
```json
{
  "command": "python -c \"import ast; ast.parse(open('admin_ui/prestashop.py').read()); print('OK sintaxis')\" && python -c \"\nfrom jinja2 import Environment, FileSystemLoader\nenv = Environment(loader=FileSystemLoader('admin_ui/templates'))\nt = env.get_template('diff.html')\nprint('OK template compila')\n\"",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
OK sintaxis
Traceback (most recent call last):
  File "<string>", line 2, in <module>
    from jinja2 import Environment, FileSystemLoader
ModuleNotFoundError: No module named 'jinja2'

```

---

## Assistant (Build · Big Pickle · 3.6s)

_Thinking:_

jinja2 isn't installed in the system python. Let me check if there's a venv.

**Tool: bash**

**Input:**
```json
{
  "command": "ls venv/bin/python 2>/dev/null && venv/bin/python -c \"from jinja2 import Environment, FileSystemLoader; env=Environment(loader=FileSystemLoader('admin_ui/templates')); env.get_template('diff.html'); print('OK template compila')\"",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
venv/bin/python
OK template compila

```

---

## Assistant (Build · Big Pickle · 27.5s)

_Thinking:_

Template compiles. Now let me double-check the `row()` macro is still used correctly and the "has_diff" logic. Also, I want to run the existing tests to make sure nothing breaks. There's a tests directory. Let me check if tests run with the venv.

Also, let me reconsider: should the diff still show 'title' as a 'Título' field anywhere? No, I removed it. But wait — the description preview at line 113 uses proposal.get('descripcion') etc., fine.

Let me also verify `_validate_name_coherence` doesn't get confused. That's about brand. Not relevant.

Let me run the tests.

Corro los tests existentes:

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python -m pytest tests/ -q 2>&1 | tail -20",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
        monkeypatch.setattr(ps, "API_SLEEP", 0)
    
        client = ps.AdminPrestashopClient()
        client._session = FakeSession()
        client.put_product(1, {})
    
        last = ET.fromstring(puts_sent[-1])
        body = last.find(".//product")
        body_tags = {child.tag for child in body}
        # Read-only fields must not be sent back to PrestaShop
        assert "position_in_category" not in body_tags
        # state is read-only on GET but re-forced to 1 by put_product (PS 8.1)
>       assert body.findtext("state") == "1"
E       AssertionError: assert None == '1'
E        +  where None = <built-in method findtext of xml.etree.ElementTree.Element object at 0x7fadda215030>('state')
E        +    where <built-in method findtext of xml.etree.ElementTree.Element object at 0x7fadda215030> = <Element 'product' at 0x7fadda215030>.findtext

tests/test_prestashop_helpers.py:136: AssertionError
=========================== short test summary info ============================
FAILED tests/test_prestashop_helpers.py::test_read_only_fields_removed_on_put

```

---

## Assistant (Build · Big Pickle · 5.6s)

_Thinking:_

The failing test is `test_read_only_fields_removed_on_put` which expects `state` to be set to "1" — but the test environment probably doesn't have PS_COMPAT_81 enabled, so ps81_workarounds_enabled() returns False. This failure is likely pre-existing (not related to my change). Let me verify by checking git stash / running on the original code. Let me check whether this test failed before my changes with `git stash`.

Actually, my change only added a skip for "name"/"link_rewrite". This test doesn't pass "name", so my change can't have caused this. Let me confirm it fails on the unmodified code too.

**Tool: bash**

**Input:**
```json
{
  "command": "git stash && venv/bin/python -m pytest tests/test_prestashop_helpers.py::test_read_only_fields_removed_on_put -q 2>&1 | tail -5; git stash pop",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
Saved working directory and index state WIP on VersionLinux: 424b710 :)
E        +    where <built-in method findtext of xml.etree.ElementTree.Element object at 0x7f1349954c20> = <Element 'product' at 0x7f1349954c20>.findtext

tests/test_prestashop_helpers.py:136: AssertionError
=========================== short test summary info ============================
FAILED tests/test_prestashop_helpers.py::test_read_only_fields_removed_on_put
On branch VersionLinux
Your branch is up to date with 'origin/VersionLinux'.

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   .gitignore
	modified:   AGENTS.md
	modified:   admin.py
	modified:   admin_ui/app.py
	modified:   admin_ui/prestashop.py
	modified:   admin_ui/static/style.css
	modified:   admin_ui/templates/base.html
	modified:   admin_ui/templates/brands.html
	modified:   admin_ui/templates/dashboard.html
	modified:   admin_ui/templates/diff.html
	modified:   admin_ui/templates/settings.html
	modified:   daemon.py
	modified:   middleware/ai_agent.py
	modified:   middleware/check_active.py
	modified:   middleware/config.py
	modified:   middleware/db.py
	modified:   middleware/enrich.py
	modified:   middleware/extract.py
	modified:   middleware/official_scraper.py
	modified:   middleware/pipeline_state.py
	modified:   middleware/prestashop.py
	modified:   middleware/spec_extractors.py
	modified:   pipeline.py
	modified:   requirements.txt
	modified:   tests/test_enrich.py
	modified:   tests/test_model_extraction.py
	modified:   tests/test_spec_extractors.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	Dockerfile
	LEGAL.md
	admin_ui/templates/login.html
	admin_ui/templates/setup.html
	docker-compose.client.yml
	instalar.sh
	middleware/plan.py
	middleware/users.py
	scripts/create_user.py
	scripts/entrypoint.sh
	scripts/new_client.py
	tests/test_plan.py
	tests/test_users.py

no changes added to commit (use "git add" and/or "git commit -a")
Dropped refs/stash@{0} (3091a7ea8386629d3c19dd015aca09c37563aa31)

```

---

## Assistant (Build · Big Pickle · 20.4s)

_Thinking:_

Confirmed: the test fails on unmodified code too — pre-existing failure (the test env doesn't have PS_COMPAT_81 set). Not caused by my change.

Now let me run the full test suite to check all other tests pass, filtering out that known-failing one.

El test fallido es pre-existente (no lo causó mi cambio). Corro el resto:

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python -m pytest tests/ -q --deselect tests/test_prestashop_helpers.py::test_read_only_fields_removed_on_put 2>&1 | tail -5",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
........................................................................ [ 58%]
...................................................                      [100%]

```

---

## Assistant (Build · Big Pickle · 5.2s)

_Thinking:_

All other tests pass. Let me summarize the changes made.

Changes:
1. `admin_ui/prestashop.py`: added `_IMMUTABLE_FIELDS = {"name", "link_rewrite"}` and skip them in `put_product` so the middleware can never rename a product.
2. `admin_ui/templates/diff.html`: removed the "Nombre" diff row that proposed the scraped title as a new name; the name now shows as an immutable single value. Removed the 'Título'/'Título (traducido)' rows that implied a name change.

Let me give a concise summary to the user in Spanish (they wrote in Spanish).

Listo. El pipeline ya nunca cambiaba el nombre en el PUT, pero la vista diff lo *sugería* mostrando el `title` scrapeado como "Nombre" propuesto (por eso una cinta scotch aparecía como "Redmi 15C"). Lo hice estructural:

- `admin_ui/prestashop.py:31` — nuevo `_IMMUTABLE_FIELDS = {"name", "link_rewrite"}`: `put_product` ignora esas claves aunque un caller futuro las pase, garantizando que el nombre jamás cambie.
- `admin_ui/templates/diff.html:149` — el nombre se muestra como valor fijo e inmutable (sin columna "Propuesta"); saqué las filas "Título"/"Título (traducido)" que insinuaban un renombrado.

La validación de identidad (`_validate_scraped_data`) sigue protegiendo contra enriquecer con un producto equivocado. Todos los tests pasan (el único fallo, `test_read_only_fields_removed_on_put`, ya fallaba antes de mis cambios).

---

## User

fijate si hay un error de compatibilidad de fuentes porque los acentos a veces no se escriben y en lugar de eso aparece un codigo

---

## Assistant (Build · Big Pickle · 6.1s)

_Thinking:_

The user is reporting that accents sometimes don't render and instead show a code. This sounds like a font encoding/mojibake issue — accents showing as codes could be:
1. HTML entities like `&aacute;` displayed literally instead of `á`
2. Unicode escapes like `\u00e1`
3. Encoding issues (latin-1 vs utf-8)

Let me search for places where text with accents is handled — translation, CDATA wrapping, XML serialization. The AGENTS.md mentions the CDATA wrapping in `_wrap_language_cdata` where ElementTree escapes HTML entities. If a description contains literal `&aacute;` or `&#225;` it might get double-escaped.

Actually "en lugar de eso aparece un codigo" - a code appears instead of the accent. This is likely HTML entity codes being shown literally, e.g. `&aacute;` or `&#225;` appearing in the rendered output, OR mojibake like `Ã¡` (utf-8 bytes decoded as latin-1).

Let me investigate. Let me look at the translation module (translate.py), the CDATA wrapping, and how descriptions are built. Also the _strip_prestashop_attrs. Let me look at translate.py since it mentions the glossary with U+FFFD issues.

Let me explore relevant code.

Voy a buscar dónde se maneja la codificación de acentos (traducción, CDATA, XML).

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/translate.py"
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/translate.py</path>
<type>file</type>
<content>
1: """Automatic translation module with protected glossary (RF-07)."""
2: 
3: import logging
4: from functools import lru_cache
5: 
6: try:
7:     from deep_translator import GoogleTranslator
8: 
9:     _TRANSLATOR_AVAILABLE = True
10: except ImportError:
11:     GoogleTranslator = None  # type: ignore
12:     _TRANSLATOR_AVAILABLE = False
13: 
14: logger = logging.getLogger(__name__)
15: 
16: # Protected technical terms — never translated.
17: # Sorted longest-first so compound terms match before their components.
18: GLOSSARY = sorted([
19:     "Super AMOLED", "IPS LCD", "Ray Tracing",
20:     "AMD Ryzen", "Intel Core",
21:     "USB-C", "microUSB", "DisplayPort",
22:     "HDMI 2.1", "HDMI 2.0", "USB 3.0", "USB 2.0",
23:     "G-Sync", "FreeSync",
24:     "QLED", "OLED", "AMOLED", "HDMI", "USB", "LED", "LCD", "IPS", "VA", "TN",
25:     "DDR5", "DDR4", "DDR3", "DDR", "SSD", "HDD", "NVMe", "M.2", "SATA", "PCIe",
26:     "WiFi", "Bluetooth", "NFC",
27:     "4K", "8K", "FHD", "UHD", "HDR",
28:     "Core i9", "Core i7", "Core i5", "Core i3",
29:     "Ryzen 9", "Ryzen 7", "Ryzen 5", "Ryzen 3",
30:     "RTX", "GTX", "RX", "GeForce", "Radeon",
31:     "DLSS", "RGB", "HDD",
32:     "Linux", "Windows", "macOS", "Android", "iOS", "iPadOS",
33: ], key=len, reverse=True)
34: 
35: 
36: def _protect_glossary(text: str) -> tuple[str, dict[str, str]]:
37:     """Replace protected terms with opaque placeholders.
38: 
39:     Uses a bracketed marker (survives GoogleTranslator verbatim).  NUL-based
40:     placeholders (``\\x00G{i}\\x00``) were silently rewritten to U+FFFD by
41:     the translator, so the restore never matched and leaked "G{i}".
42:     """
43:     placeholders: dict[str, str] = {}
44:     for i, term in enumerate(GLOSSARY):
45:         if term in text:
46:             key = f"[[GLOSS{i}]]"
47:             text = text.replace(term, key)
48:             placeholders[key] = term
49:     return text, placeholders
50: 
51: 
52: def _restore_glossary(text: str, placeholders: dict[str, str]) -> str:
53:     for key, term in placeholders.items():
54:         text = text.replace(key, term)
55:     return text
56: 
57: 
58: def is_available() -> bool:
59:     return _TRANSLATOR_AVAILABLE
60: 
61: 
62: @lru_cache(maxsize=1024)
63: def translate(text: str, target: str = "es") -> str:
64:     """Translate text to target language, preserving glossary terms."""
65:     if not text or not text.strip():
66:         return text
67:     if not _TRANSLATOR_AVAILABLE:
68:         return text
69: 
70:     protected, placeholders = _protect_glossary(text)
71:     if not protected.strip():
72:         return text
73: 
74:     try:
75:         translator = GoogleTranslator(source="auto", target=target)
76:         translated = translator.translate(protected)
77:         return _restore_glossary(translated, placeholders)
78:     except Exception as exc:
79:         logger.warning("Translation failed (%s): %s", type(exc).__name__, exc)
80:         return text
81: 
82: 
83: def translate_product(product_data: dict, fields: list[str] | None = None) -> dict:
84:     """Translate relevant fields of a product dict, preserving glossary."""
85:     if fields is None:
86:         fields = ["titulo", "title", "descripcion", "description", "resumen", "summary"]
87:     result = dict(product_data)
88:     for field in fields:
89:         value = result.get(field)
90:         if value and isinstance(value, str):
91:             result[field] = translate(value)
92:     return result

(End of file - total 92 lines)
</content>
```

---

## Assistant (Build · Big Pickle · 8.4s)

_Thinking:_

The translate.py looks fine. The issue is about "acentos a veces no se escriben y en lugar de eso aparece un codigo" — accents sometimes aren't written and instead a code appears.

This could be the HTML entity escaping issue. Let me look at `_wrap_language_cdata` — ElementTree escapes text, and if the text already contains literal `&aacute;` entities (from scraped pages or from GoogleTranslator), then after serialization it could become `&amp;aacute;` which renders literally as `&aacute;`.

Also "code" might be something like `\u00e9` or `&#233;`. Let me check where descriptions get built and pushed. The `put_product` flow: `_set_field` sets text on the element, then ElementTree serializes with `xml: etree.tostring`, then `_wrap_language_cdata` unescapes and wraps in CDATA.

If the scraped/translated text contains literal `&aacute;` (because deep-translator or the scraper returns HTML entities), then when it's set as element text, ElementTree escapes `&` → `&amp;`, so it becomes `&amp;aacute;`. `_wrap_language_cdata` uses `unescape()` which unescapes `&amp;` → `&`, producing `&aacute;` in the CDATA. Then the browser/PrestaShop renders `&aacute;`... actually in HTML `&aacute;` renders as `á`. Hmm, that would work.

But if the content was double-escaped, e.g. the text literally contains `&amp;aacute;` in DB, then unescape → `&aacute;` still... no wait, unescape only does one pass. Let me think: `unescape("&amp;amp;aacute;")` → `&amp;aacute;`. Then in HTML rendering `&amp;aacute;` renders as `&aacute;` literally — showing a code!

So the bug: if a description contains an HTML entity that got double-escaped somewhere, the user sees the raw code `&aacute;` instead of `á`.

Actually, let me reconsider what the user sees. "aparece un codigo" — could be:
- `&aacute;` (HTML entity code)
- `Ã¡` (mojibake of á in latin-1)
- `\u00e1` (unicode escape)

Let me look at how the description is built and pushed in detail, especially `_wrap_language_cdata` and `_set_field`, and also how Excel descriptions are loaded (descriptions.py) — the Excel file might have encoding issues. Also `check_active` reads description_short from excel.

Let me look at `_wrap_language_cdata` again (already seen lines 42-68) and `_set_field` (lines 609+). And let me check `decode_response` in spec_extractors.py which decodes HTTP responses — encoding handling there matters for scraped text.

Let me read spec_extractors.py decode_response and descriptions.py.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py",
  "limit": 78,
  "offset": 1
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py</path>
<type>file</type>
<content>
1: """Generic product specification extractors.
2: 
3: Shared extraction strategies used by both ``official_scraper`` and
4: ``ai_agent``.  These work across most manufacturer websites without
5: per-brand configuration.
6: """
7: 
8: import json
9: import logging
10: import re
11: from typing import cast
12: 
13: from bs4 import BeautifulSoup, Tag
14: 
15: logger = logging.getLogger(__name__)
16: 
17: 
18: def decode_response(resp) -> str:
19:     """Decode an HTTP response body to text honoring the *real* charset.
20: 
21:     ``requests`` falls back to ISO-8859-1 when the ``Content-Type`` header
22:     omits a charset (or declares latin-1 while the body is actually UTF-8),
23:     producing mojibake (``á`` → ``Ã¡``, ``ñ`` → ``Ã±``).  Charset resolution:
24: 
25:     1. HTML ``<meta charset=...>`` tag (skipping latin/ascii);
26:     2. ``Content-Type`` header charset — a latin-1 header usually *lies*
27:        (the body is UTF-8), so try strict UTF-8 first and only fall back to
28:        the declared charset if the bytes are not valid UTF-8;
29:     3. latin-1 declared by ``<meta>``;
30:     4. ``apparent_encoding`` (chardet heuristic);
31:     5. UTF-8 as last resort.
32:     """
33:     content = resp.content
34:     if not content:
35:         return ""
36: 
37:     _LATIN = ("iso-8859-1", "latin-1", "latin1", "ascii")
38:     header_enc = (getattr(resp, "encoding", None) or "").strip() or None
39: 
40:     head = content[:4096].decode("ascii", errors="ignore")
41:     meta = re.search(r'<meta[^>]+charset=["\']?\s*([a-zA-Z0-9_-]+)', head, re.I)
42: 
43:     if meta:
44:         enc = meta.group(1).strip()
45:         if enc.lower() not in _LATIN:
46:             try:
47:                 return content.decode(enc, errors="replace")
48:             except LookupError:
49:                 pass
50: 
51:     if header_enc:
52:         if header_enc.lower() in _LATIN:
53:             try:
54:                 return content.decode("utf-8")
55:             except UnicodeDecodeError:
56:                 return content.decode(header_enc, errors="replace")
57:         try:
58:             return content.decode(header_enc, errors="replace")
59:         except LookupError:
60:             pass
61: 
62:     if meta:
63:         try:
64:             return content.decode(meta.group(1).strip(), errors="replace")
65:         except LookupError:
66:             pass
67: 
68:     enc = getattr(resp, "apparent_encoding", None)
69:     if enc and enc.lower() not in _LATIN:
70:         try:
71:             return content.decode(enc, errors="replace")
72:         except (LookupError, UnicodeDecodeError):
73:             pass
74: 
75:     return content.decode("utf-8", errors="replace")
76: 
77: 
78: def is_template_placeholder(text: str) -> bool:

(Showing lines 1-78 of 836. Use offset=79 to continue.)
</content>
```

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py",
  "limit": 60,
  "offset": 609
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py</path>
<type>file</type>
<content>
609:         return uploaded_ids
610: 
611:     # ------------------------------------------------------------------
612:     # helpers
613:     # ------------------------------------------------------------------
614: 
615:     @staticmethod
616:     def _set_field(parent: ET.Element, key: str, value: str) -> None:
617:         """Set or create a scalar text field.
618: 
619:         Multi-language fields (with `<language>` children) get their first
620:         language element updated; if none exist, one is created with
621:         ``id="1"``.  Other fields are set directly.
622:         """
623:         field = parent.find(key)
624:         if field is None:
625:             field = ET.SubElement(parent, key)
626: 
627:         lang = field.find("language")
628:         if lang is not None:
629:             lang.text = value
630:             return
631: 
632:         if key in ("description", "description_short", "name",
633:                    "link_rewrite", "meta_title", "meta_description",
634:                    "meta_keywords", "delivery_in_stock", "delivery_out_stock",
635:                    "available_now", "available_later"):
636:             lang = ET.SubElement(field, "language")
637:             lang.set("id", LANG_ID)
638:             lang.text = value
639:             return
640: 
641:         field.text = value

(End of file - total 641 lines)
</content>
```

---

## Assistant (Build · Big Pickle · 13.2s)

_Thinking:_

The `_set_field` sets `lang.text = value` directly. ElementTree will escape `&` `<` `>` when serializing. `_wrap_language_cdata` then unescapes and wraps content in CDATA. So a description with `&` becomes `&amp;` then unescaped back to `&`. Good.

But wait — what about the `&` that came from HTML entities in scraped content? E.g. if scraped text contains literal `&aacute;` (from the source HTML, where BeautifulSoup text extraction already converts entities to unicode chars... actually BeautifulSoup `get_text()` does NOT convert HTML entities — it keeps them as-is in the text). Hmm, actually BeautifulSoup with html.parser does convert entities when parsing, but `get_text()` returns the text content with entities already decoded? No. Let me recall: BeautifulSoup stores text as unicode strings, decoding entities during parsing. So `&aacute;` in source becomes `á` in the text. So scraped text should have real unicode chars.

The translation via GoogleTranslator returns unicode text. So descriptions should have real `á`.

So where does "un codigo" appear? The user says "los acentos a veces no se escriben y en lugar de eso aparece un codigo". This sounds like: in the rendered product page / admin, instead of `á`, shows something like `&aacute;` or `Ã¡` or a numeric code.

Let me think about the CDATA wrapping bug more carefully. Let me read `_wrap_language_cdata` and how `put_product` serializes the XML.

`_wrap_language_cdata` regex: `r"(<language[^>]*[^/]>)(.*?)(</language>)"` with DOTALL. It matches `<language ...>content</language>`. It uses `unescape(content)` to unescape entities. `xml.sax.saxutils.unescape` only unescapes `&amp; &lt; &gt;` and quotes if given. So `&amp;` → `&`. Good — single pass.

But if the content legitimately contained the literal string `&aacute;` (5 chars), ElementTree would escape to `&amp;aacute;`. Then unescape → `&aacute;`. Then in HTML rendering, `&aacute;` → `á`. That's actually fine in a browser.

BUT PrestaShop might store the description with the literal `&aacute;` in the DB, and when the admin or front renders it, `&aacute;` renders as `á` in HTML. So it should be fine...

Unless the content is being stored with the literal text `&aacute;` and the front-end template escapes HTML (Jinja `{{ }}` autoescapes) — then it would show `&amp;aacute;` rendered as literal `&aacute;`! That's the "code" the user sees: the raw HTML entity string.

Hmm. Let me think about where "codigo" appears. Could be in the admin diff preview? The diff.html renders `{{ desc }}` in a `<div class="diff-desc__text">` — Jinja autoescape would escape the HTML. But that's the preview. On the PrestaShop front, the description is raw HTML.

Actually — maybe the issue is in the description built by `_build_description` in enrich.py (lines 100-105): it builds `<p><strong>{nombre}:</strong> {valor}</p>`. If `nombre` or `valor` contains characters like `á`, those are fine in UTF-8. If they contain `&`, `<`, `>`... a scraped value like "5cm de ancho" fine.

Wait — but what about the entity issue with GoogleTranslator? GoogleTranslator returns text; if the source text contains `&aacute;` literally (unlikely)...

Let me reconsider. Maybe the "code" is actually the mojibake `Ã¡`. That happens when UTF-8 bytes are decoded as latin-1. Where could that happen? In `decode_response`, they handle it. In `ai_agent` — uses requests + decode_response. In `official_scraper` — Selenium returns already-decoded unicode.

Alternatively — the Excel descriptions (`003 DESCRIPCIONES.xlsx`). `descriptions.py` reads the Excel. If openpyxl reads it fine, it's unicode.

Alternatively — the issue is the translation glossary placeholders leaking: the AGENTS.md says "the old NUL-based \x00G{i}\x00 was rewritten to U+FFFD by the translator, leaking G{i} into the output". U+FFFD is the replacement char — "acentos no se escriben" — that's a code/replacement char. But that was fixed with [[GLOSS{i}]].

Hmm, "un codigo" — let me consider the `[[GLOSS0]]` markers leaking. If `_restore_glossary` fails to restore (e.g., GoogleTranslator mangles the brackets or the term appears multiple times), the user would see `[[GLOSS3]]` literally. But that's not about accents.

Let me look at what the user actually means more concretely. They said "los acentos a veces no se escriben y en lugar de eso aparece un codigo" — accents sometimes aren't written, instead a code appears. This is classic mojibake or HTML-entity leak:
- `&aacute;` 
- `&#225;`
- `Ã¡`
- `\u00e1`

Let me look at git history to see if there was recent work on encoding. Also let me search the codebase for places that escape/unescape, and how the DB stores text. Let me look at descriptions.py and how the pipeline's description is stored and how approve builds description.

Actually, wait. Let me re-read the `_wrap_language_cdata` function and `put_product` more carefully — specifically the order of operations. Let me read the full put_product including the XML serialization and CDATA wrapping.

Reviso cómo se serializa el XML y se aplica el CDATA en `put_product`:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py",
  "limit": 80,
  "offset": 313
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py</path>
<type>file</type>
<content>
313:         shops_el = assoc_el.find("shop") if assoc_el is not None else None
314:         id_shop_def = product_el.findtext("id_shop_default")
315:         logger.debug(
316:             "  PUT product %d — assoc=%s cats=%s shops=%s "
317:             "active=%s id_category_default=%s id_shop_default=%s "
318:             "visibility=%s indexed=%s",
319:             product_id,
320:             assoc_el is not None,
321:             cats_el is not None,
322:             shops_el is not None,
323:             product_el.findtext("active"),
324:             product_el.findtext("id_category_default"),
325:             id_shop_def,
326:             product_el.findtext("visibility"),
327:             product_el.findtext("indexed"),
328:         )
329: 
330:         if ps81_workarounds_enabled():
331:             _strip_prestashop_attrs(root)
332:         xml_str = ET.tostring(root, encoding="unicode", xml_declaration=True)
333:         xml_str = _wrap_language_cdata(xml_str)
334: 
335:         url = f"{self._base}/products/{product_id}"
336:         headers = {"Content-Type": "application/xml"}
337:         resp = self._session.put(url, data=xml_str.encode(), headers=headers)
338: 
339:         logger.debug(
340:             "  PUT product %d → HTTP %d  body=%.200s",
341:             product_id, resp.status_code, resp.text[:200],
342:         )
343:         if resp.status_code >= 400:
344:             raise PrestashopError(
345:                 f"PUT products/{product_id} failed HTTP {resp.status_code}: "
346:                 f"{resp.text[:500]}"
347:             )
348:         time.sleep(API_SLEEP)
349: 
350:         # Verify: re-fetch and log critical fields
351:         root2 = self._request(f"products/{product_id}")
352:         product2 = root2.find(".//product")
353:         if product2 is not None:
354:             logger.debug(
355:                 "  POST-PUT product %d — active=%s id_category_default=%s "
356:                 "id_shop_default=%s id_manufacturer=%s has_assoc=%s "
357:                 "visibility=%s indexed=%s",
358:                 product_id,
359:                 product2.findtext("active"),
360:                 product2.findtext("id_category_default"),
361:                 product2.findtext("id_shop_default"),
362:                 product2.findtext("id_manufacturer"),
363:                 product2.find("associations") is not None,
364:                 product2.findtext("visibility"),
365:                 product2.findtext("indexed"),
366:             )
367: 
368:     # ------------------------------------------------------------------
369:     # features
370:     # ------------------------------------------------------------------
371: 
372:     def _fetch_all_features(self) -> dict[str, int]:
373:         """Fetch all product features, return ``{name_lower: id}`` map."""
374:         root = self._request("product_features", {"display": "[id,name]"})
375:         index: dict[str, int] = {}
376:         for f in root.findall(".//product_feature"):
377:             fid = f.findtext("id")
378:             if not fid:
379:                 continue
380:             for lang in f.findall("name/language"):
381:                 if lang.text:
382:                     index[lang.text.strip().lower()] = int(fid)
383:         return index
384: 
385:     def _fetch_all_feature_values(self) -> dict[tuple[int, str], int]:
386:         """Fetch all feature values, return ``{(feature_id, value_lower): id}``."""
387:         root = self._request("product_feature_values", {"display": "[id,id_feature,value]"})
388:         index: dict[tuple[int, str], int] = {}
389:         for fv in root.findall(".//product_feature_value"):
390:             fvid = fv.findtext("id")
391:             fid = fv.findtext("id_feature")
392:             if not fvid or not fid:

(Showing lines 313-392 of 641. Use offset=393 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 9.3s)

_Thinking:_

The `put_product` serializes with `encoding="unicode"` and wraps in CDATA. The `_wrap_language_cdata` uses `unescape` which only handles `&amp;`, `&lt;`, `&gt;`. 

Now, the key question: where do accents become "codes"? Let me think about the scenario with `_wrap_language_cdata`:

If the description text contains `&` followed by something that looks like an entity, e.g. a value like "&5cm" or a brand "AT&T" — ElementTree escapes `&` → `&amp;`, then unescape → `&`. Fine.

But here's a subtle issue: `unescape` in `_wrap_language_cdata` converts `&amp;` back to `&`, but what if the ORIGINAL text already contains a literal `&aacute;` string (5 characters: & a a c u t e ;)? Then ElementTree → `&amp;aacute;`, unescape → `&aacute;`. Now the CDATA contains `&aacute;`. PrestaShop stores it. When the front-end renders description as HTML, `&aacute;` → `á`. OK in HTML.

BUT — what about the case where the description is NOT wrapped in CDATA? `_wrap_language_cdata` only wraps `<language>` tags that match the regex `<language[^>]*[^/]>`. Look at the regex: `(<language[^>]*[^/]>)(.*?)(</language>)`. The `[^>]*[^/]` requires the opening tag to have at least one char before `>` that isn't `/`. For `<language id="1">`, `[^>]*` matches ` id="1"` and `[^/]` matches the `1`. OK matches. But for `<language>` (no attributes), `[^>]*` matches empty, then `[^/]` needs to match something that's not `/` but there's nothing before `>`. Actually `<language>` — `[^>]*` can't match empty and then `[^/]`... regex engine: `<language` then `[^>]*` matches zero chars, `[^/]` must match `>`? No, `>` is excluded by `[^>]`. So `<language>` without attributes does NOT match the regex → content not wrapped in CDATA → ElementTree's escaped entities remain escaped (e.g. `&lt;p&gt;`), and `&amp;` stays `&amp;` which renders as `&` in HTML... hmm, actually `&amp;` renders as `&` in the browser, that's fine, but `&lt;p&gt;` would render as literal `<p>` text.

But accents: if content has real `á` (unicode), there's no escaping issue — ElementTree keeps it as `á`. So where does the "code" come from?

Wait — maybe the issue is the opposite. Maybe the description content contains `&` that forms a numeric entity like `&#225;` and it's double-escaped somewhere, OR the source data has mojibake.

Let me step back and look for the actual source of accent codes. Let me check `descriptions.py` (Excel) since description_short comes from there. And let me check `ai_agent.py` and `official_scraper.py` for encoding. Actually, the AGENTS.md says the old glossary used NUL bytes which became U+FFFD — "acentos no se escriben" could be U+FFFD replacement chars appearing.

Let me search for where text might be HTML-escaped or entity-encoded. Let me grep for `html.unescape`, `html.escape`, `&amp;`, `&aacute;`, `&#`, `\u00`, `latin`, `iso-8859`, `encode`/`decode` in the codebase.

**Tool: grep**

**Input:**
```json
{
  "include": "*.py",
  "path": "/home/icrocetti/dev/ProyectoDC",
  "pattern": "html\\.unescape|html\\.escape|unescape\\(|&amp;|aacute|#\\d{2,4};|mojibake|replacement|U\\+FFFD|encode\\(|decode\\(|latin|iso-8859|windows-125"
}
```

**Output:**
```
Found 29 matches
/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py:
  Line 192:     resp = _FakeResp(body.encode("utf-8"), encoding=None)

  Line 196: def test_decode_response_meta_charset_beats_latin_header():

  Line 201:     resp = _FakeResp(body.encode("utf-8"), encoding="ISO-8859-1")

  Line 207:     resp = _FakeResp(body.encode("iso-8859-1"), encoding="ISO-8859-1")

  Line 214:     resp = _FakeResp(body.encode("utf-8"), encoding=None,


/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py:
  Line 22:     omits a charset (or declares latin-1 while the body is actually UTF-8),

  Line 23:     producing mojibake (``á`` → ``Ã¡``, ``ñ`` → ``Ã±``).  Charset resolution:

  Line 25:     1. HTML ``<meta charset=...>`` tag (skipping latin/ascii);

  Line 26:     2. ``Content-Type`` header charset — a latin-1 header usually *lies*

  Line 29:     3. latin-1 declared by ``<meta>``;

  Line 37:     _LATIN = ("iso-8859-1", "latin-1", "latin1", "ascii")

  Line 40:     head = content[:4096].decode("ascii", errors="ignore")

  Line 47:                 return content.decode(enc, errors="replace")

  Line 54:                 return content.decode("utf-8")

  Line 56:                 return content.decode(header_enc, errors="replace")

  Line 58:             return content.decode(header_enc, errors="replace")

  Line 64:             return content.decode(meta.group(1).strip(), errors="replace")

  Line 71:             return content.decode(enc, errors="replace")

  Line 75:     return content.decode("utf-8", errors="replace")

  Line 490:             raw = _html.unescape(str(page_data.get("value") or ""))

  Line 503:     selector_b64 = base64.b64encode(product_data_path.encode()).decode()


/home/icrocetti/dev/ProyectoDC/middleware/translate.py:
  Line 40:     placeholders (``\\x00G{i}\\x00``) were silently rewritten to U+FFFD by


/home/icrocetti/dev/ProyectoDC/middleware/embedding.py:
  Line 43:     emb = model.encode(text, normalize_embeddings=True)


/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py:
  Line 957:             "tinta", "drum", "recambio", "accesorio", "replacement",


/home/icrocetti/dev/ProyectoDC/scripts/sync_categories.py:
  Line 68:         data=xml.encode('utf-8'),

  Line 162:         data=xml_str.encode('utf-8'),


/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py:
  Line 62:         raw = unescape(content)

  Line 337:         resp = self._session.put(url, data=xml_str.encode(), headers=headers)

  Line 532:         logger.debug("  POST product_feature_values XML: %s", xml_body.decode())

```

---

## Assistant (Build · Big Pickle · 7.2s)

_Thinking:_

Found something interesting in spec_extractors.py line 490: `raw = _html.unescape(str(page_data.get("value") or ""))`. Let me look at that context. Also let me look at where `sync_characteristics_as_features` handles values (admin_ui/prestashop.py line 433) and where feature values get truncated/escaped.

But the "code" issue — let me think about `_html.unescape`. If the scraped value is a real `á`, unescape leaves it. If the value is literally `&aacute;`, unescape converts to `á`. So that's a fix, not a bug.

Actually, wait. Let me reconsider what "un codigo" looks like. Let me check what the description_short from Excel looks like. Let me look at descriptions.py. Also, there may be a case where the description contains `&` characters and the CDATA wrapping with `unescape` corrupts it.

Key issue I want to check: `_wrap_language_cdata` regex requires `<language[^>]*[^/]>`. When `_set_field` creates a new language element it sets `id="1"` — `_set_field` line 637: `lang.set("id", LANG_ID)`. So `<language id="1">`. Good.

But when `put_product` GETs the product first, the existing language elements from PrestaShop might be `<language id="1">...</language>` with content already wrapped or not. Fine.

Now here's the real potential bug: the GET returns the description with content. If description in PrestaShop DB contains actual HTML with entities like `&aacute;` (because PrestaShop stored it that way), ElementTree parses `&aacute;` → `á` (unicode). Then when we PUT back the same unmodified product, `ET.tostring` re-escapes → `&aacute;`, then `_wrap_language_cdata` unescapes → `&aacute;` in CDATA → stored again. OK stable.

Hmm. I'm not finding the smoking gun in these files. Let me look more broadly. The user's report: "los acentos a veces no se escriben y en lugar de eso aparece un codigo". Maybe it happens in the admin UI diff view (Jinja autoescape) — no wait, "no se escriben" implies in the output product page in PrestaShop.

Let me check the description_short from Excel, and how `get_description` reads. Let me read descriptions.py.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/descriptions.py"
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/descriptions.py</path>
<type>file</type>
<content>
1: """Load product descriptions from 003 DESCRIPCIONES.xlsx.
2: 
3: Reads the DESCRIPCIONES sheet, maps DB subcategory names to Excel entries
4: via ``descripcion_mapping.json``, and provides lookup functions.
5: """
6: 
7: import json
8: import logging
9: from pathlib import Path
10: 
11: logger = logging.getLogger(__name__)
12: 
13: _BASE = Path(__file__).resolve().parent.parent
14: _EXCEL_PATH = _BASE / "003 DESCRIPCIONES.xlsx"
15: 
16: _LOADED: dict[str, dict[str, str]] | None = None
17: 
18: _PLACEHOLDER_RE = __import__("re").compile(
19:     r"(?i)^ver\s+descripci[oó]n\s+de\s+",
20: )
21: 
22: 
23: def _load_mapping() -> dict:
24:     path = _BASE / "descripcion_mapping.json"
25:     if not path.exists():
26:         logger.warning("descripcion_mapping.json not found")
27:         return {}
28:     with open(path, encoding="utf-8") as f:
29:         return json.load(f)
30: 
31: 
32: def _load_excel() -> dict[str, dict[str, str]]:
33:     """Load descriptions from the Excel DESCRIPCIONES sheet.
34: 
35:     Returns ``{excel_subcat_name_lower: {"descripcion": …, "descripcion_corta": …}}``
36:     """
37:     try:
38:         import openpyxl
39:     except ImportError:
40:         logger.warning("openpyxl not installed — cannot load Excel descriptions")
41:         return {}
42: 
43:     if not _EXCEL_PATH.exists():
44:         logger.warning("003 DESCRIPCIONES.xlsx not found at %s", _EXCEL_PATH)
45:         return {}
46: 
47:     wb = openpyxl.load_workbook(_EXCEL_PATH, data_only=True, read_only=True)
48:     ws = wb["DESCRIPCIONES"]
49:     result: dict[str, dict[str, str]] = {}
50: 
51:     for row in ws.iter_rows(min_row=2, values_only=True):
52:         subcat = row[1]
53:         desc = row[3]
54:         short_desc = row[5] if len(row) > 5 else None
55:         if not subcat:
56:             continue
57:         key = str(subcat).strip().lower()
58:         result[key] = {
59:             "descripcion": str(desc).strip() if desc else "",
60:             "descripcion_corta": str(short_desc).strip() if short_desc else "",
61:         }
62: 
63:     wb.close()
64:     logger.info("Loaded %d descriptions from Excel", len(result))
65:     return result
66: 
67: 
68: def _get_all() -> dict[str, dict[str, str]]:
69:     global _LOADED
70:     if _LOADED is None:
71:         _LOADED = _load_excel()
72:     return _LOADED
73: 
74: 
75: def _is_placeholder(text: str) -> bool:
76:     """Return True if *text* is a placeholder like 'Ver descripción de X'."""
77:     return bool(text and _PLACEHOLDER_RE.match(text.strip()))
78: 
79: 
80: def get_description(subcat_name: str) -> dict[str, str]:
81:     """Return ``{"descripcion": …, "descripcion_corta": …}`` for a DB subcategory.
82: 
83:     Placeholder values (``"Ver descripción de …"``) are replaced with empty
84:     strings so callers never push meaningless text to PrestaShop.
85:     Falls back to empty strings if no mapping or Excel entry exists.
86:     """
87:     mapping = _load_mapping()
88:     excel_key = mapping.get(subcat_name, "")
89:     if not excel_key:
90:         return {"descripcion": "", "descripcion_corta": ""}
91: 
92:     all_descs = _get_all()
93:     entry = all_descs.get(excel_key.lower())
94:     if not entry:
95:         return {"descripcion": "", "descripcion_corta": ""}
96: 
97:     desc = entry["descripcion"]
98:     short = entry["descripcion_corta"]
99:     return {
100:         "descripcion": "" if _is_placeholder(desc) else desc,
101:         "descripcion_corta": "" if _is_placeholder(short) else short,
102:     }

(End of file - total 102 lines)
</content>
```

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py",
  "limit": 40,
  "offset": 470
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py</path>
<type>file</type>
<content>
470:     the family page (e.g. ``/content/brandsite-product/ar/es/tvs/c6k/55c6k``).
471: 
472:     Returns a list of ``{"nombre": ..., "valor": ...}`` dicts, or ``[]`` if
473:     the page is not a TCL family page / the API is unreachable.
474:     """
475:     import base64
476:     import html as _html
477:     import json as _json
478: 
479:     spec_component = soup.select_one("[data-api]")
480:     if not spec_component:
481:         return []
482:     data_api = str(spec_component.get("data-api") or "").strip()
483:     if not data_api:
484:         return []
485: 
486:     page_data = soup.find(id="pageData")
487:     product_data_path = ""
488:     if page_data is not None:
489:         try:
490:             raw = _html.unescape(str(page_data.get("value") or ""))
491:             data = _json.loads(raw)
492:             products = data.get("allproducts") or []
493:             selected = next(
494:                 (p for p in products if p.get("selected")), None
495:             )
496:             product_data_path = (selected or {}).get("productDataPath") or ""
497:         except (ValueError, TypeError, AttributeError):
498:             pass
499: 
500:     if not product_data_path:
501:         return []
502: 
503:     selector_b64 = base64.b64encode(product_data_path.encode()).decode()
504:     api_url = f"https://www.tcl.com{data_api}.{selector_b64}.json"
505: 
506:     logger.debug("  TCL_SPEC  fetching API: %s", api_url)
507:     try:
508:         import requests
509: 

(Showing lines 470-509 of 836. Use offset=510 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.4s)

_Thinking:_

Let me now check `sync_characteristics_as_features` in admin_ui/prestashop.py to see how feature values are handled (escaping). The `_set_field` for feature names is different. Let me read lines 393-540.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py",
  "limit": 150,
  "offset": 393
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/prestashop.py</path>
<type>file</type>
<content>
393:                 continue
394:             for lang in fv.findall("value/language"):
395:                 if lang.text:
396:                     index[(int(fid), lang.text.strip().lower())] = int(fvid)
397:         return index
398: 
399:     def sync_characteristics_as_features(
400:         self, characteristics: list[dict],
401:     ) -> list[tuple[int, int]]:
402:         """Resolve every characteristic to an existing PrestaShop Feature +
403:         Feature-Value pair.
404: 
405:         Fetches all existing features and values in just 2 GET calls.  Each
406:         characteristic is resolved in order:
407: 
408:         1. Exact match (case/accent-insensitive) on feature name, then on
409:            value within that feature.
410:         2. Fuzzy match by similarity (`_best_fuzzy_match`) — maps e.g.
411:            ``Resolución`` → ``Resolución de pantalla``.
412:         3. If nothing matches and ``PS_CREATE_FEATURES=1``, the missing
413:            feature/value is created (legacy behavior).  Otherwise the
414:            characteristic is skipped and logged as a warning.
415: 
416:         Returns ``[(id_feature, id_feature_value), …]`` ready to pass to
417:         :meth:`put_product`.
418:         """
419:         create_new = get_config("PS_CREATE_FEATURES", "0") == "1"
420: 
421:         feature_map = self._fetch_all_features()
422:         value_map = self._fetch_all_feature_values()
423: 
424:         # Normalized exact indexes + fuzzy candidate lists
425:         norm_features: dict[str, int] = {}
426:         feature_candidates: list[tuple[str, int]] = []
427:         for name, fid in feature_map.items():
428:             norm_features.setdefault(_normalize_name(name), fid)
429:             feature_candidates.append((name, fid))
430: 
431:         norm_values: dict[tuple[int, str], int] = {}
432:         values_by_feature: dict[int, list[tuple[str, int]]] = {}
433:         for (fid, value), fvid in value_map.items():
434:             norm_values.setdefault((fid, _normalize_name(value)), fvid)
435:             values_by_feature.setdefault(fid, []).append((value, fvid))
436: 
437:         pairs: list[tuple[int, int]] = []
438:         skipped: list[tuple[str, str, str]] = []
439:         for ch in characteristics:
440:             nombre = (ch.get("nombre") or "").strip()
441:             valor = (ch.get("valor") or "").strip()
442:             if not nombre or not valor:
443:                 continue
444: 
445:             # Resolve feature
446:             fid = norm_features.get(_normalize_name(nombre))
447:             if fid is None:
448:                 fid, matched_name, score = _best_fuzzy_match(nombre, feature_candidates)
449:                 if fid is not None:
450:                     logger.info(
451:                         "  Característica '%s' → feature '%s' (similitud %.2f)",
452:                         nombre, matched_name, score,
453:                     )
454:             if fid is None:
455:                 if create_new:
456:                     fid = self._create_feature(nombre)
457:                     norm_features.setdefault(_normalize_name(nombre), fid)
458:                     feature_candidates.append((nombre, fid))
459:                 else:
460:                     skipped.append((nombre, valor, "característica no existe en PrestaShop"))
461:                     continue
462: 
463:             # Resolve feature value (PrestaShop limit: 255 chars)
464:             valor_trunc = valor[:255]
465:             fvid = norm_values.get((fid, _normalize_name(valor_trunc)))
466:             if fvid is None:
467:                 fvid, matched_value, _ = _best_fuzzy_match(
468:                     valor_trunc, values_by_feature.get(fid, [])
469:                 )
470:                 if fvid is not None:
471:                     logger.info(
472:                         "  Valor '%s' → '%s' (feature %d, similitud %.2f)",
473:                         valor_trunc, matched_value, fid, _name_similarity(valor_trunc, matched_value),
474:                     )
475:             if fvid is None:
476:                 if create_new:
477:                     fvid = self._create_feature_value(fid, valor_trunc)
478:                     norm_values.setdefault((fid, _normalize_name(valor_trunc)), fvid)
479:                     values_by_feature.setdefault(fid, []).append((valor_trunc, fvid))
480:                 else:
481:                     skipped.append((nombre, valor, "valor no existe en PrestaShop"))
482:                     continue
483: 
484:             pairs.append((fid, fvid))
485: 
486:         if skipped:
487:             logger.warning(
488:                 "  %d característica(s) omitidas (no existen en PrestaShop): %s",
489:                 len(skipped),
490:                 "; ".join(f"{n} = {v} ({r})" for n, v, r in skipped[:10]),
491:             )
492:         return pairs
493: 
494:     def _create_feature(self, name: str) -> int:
495:         """POST a new feature, return its ID."""
496:         payload = Element("prestashop")
497:         feature_el = SubElement(payload, "product_feature")
498:         name_el = SubElement(feature_el, "name")
499:         lang_el = SubElement(name_el, "language")
500:         lang_el.set("id", LANG_ID)
501:         lang_el.text = name[:128]  # PrestaShop limit: 128 chars for feature name
502:         xml_body = ET.tostring(payload, encoding="utf-8", xml_declaration=True)
503:         resp = self._session.post(
504:             f"{self._base}/product_features",
505:             data=xml_body,
506:             headers={"Content-Type": "application/xml"},
507:         )
508:         if not resp.ok:
509:             logger.error("  PrestaShop error for feature '%s': %s", name, resp.text[:500])
510:             raise PrestashopError(
511:                 f"Create feature '{name}' failed HTTP {resp.status_code}: "
512:                 f"{resp.text[:500]}"
513:             )
514:         created = ET.fromstring(resp.content)
515:         fid = created.findtext(".//product_feature/id")
516:         if fid:
517:             logger.info("  Created feature '%s' → id=%s", name, fid)
518:             return int(fid)
519:         raise PrestashopError(f"Failed to create feature '{name}'")
520: 
521:     def _create_feature_value(self, feature_id: int, value: str) -> int:
522:         """POST a new feature value, return its ID."""
523:         payload = Element("prestashop")
524:         fv_el = SubElement(payload, "product_feature_value")
525:         idf_el = SubElement(fv_el, "id_feature")
526:         idf_el.text = str(feature_id)
527:         val_el = SubElement(fv_el, "value")
528:         lang_el = SubElement(val_el, "language")
529:         lang_el.set("id", LANG_ID)
530:         lang_el.text = value
531:         xml_body = ET.tostring(payload, encoding="utf-8", xml_declaration=True)
532:         logger.debug("  POST product_feature_values XML: %s", xml_body.decode())
533:         resp = self._session.post(
534:             f"{self._base}/product_feature_values",
535:             data=xml_body,
536:             headers={"Content-Type": "application/xml"},
537:         )
538:         if not resp.ok:
539:             logger.error("  PrestaShop 400 for value '%s' (feature %d): %s",
540:                          value, feature_id, resp.text[:500])
541:             raise PrestashopError(
542:                 f"Create feature value '{value}' (feature {feature_id}) failed HTTP "

(Showing lines 393-542 of 641. Use offset=543 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 11.1s)

_Thinking:_

These look fine — ET.tostring with utf-8 handles accents. The feature value creation uses `encoding="utf-8"` and posts. Fine.

Now let me reconsider. The user says "los acentos a veces no se escriben y en lugar de eso aparece un codigo". Perhaps it's the mojibake from the AI agent's web fetch, or from official scraper Selenium (which returns unicode). Or maybe it's the GoogleTranslator returning `&#225;`-style entities. Actually! GoogleTranslator (deep_translator) — when you translate a string containing HTML entities, it may return HTML-entity-encoded text? No.

Actually, let me reconsider the `_wrap_language_cdata` regex bug more carefully. Look again:

```python
r"(<language[^>]*[^/]>)(.*?)(</language>)"
```

For the element `<language id="1">`, `[^>]*` = ` id="1"` and `[^/]` matches `1`? Wait, `[^/]` is a single character class matching any char except `/`. After `<language`, `[^>]*` greedily matches ` id="1"`, then `[^/]` needs one char that's not `/` — the next char is `>`, which is excluded by `[^>]`? No — `[^/]` only excludes `/`, so `>` would be matched by `[^/]`. But wait `[^>]*` would greedily consume `>`? No, `[^>]*` excludes `>`, so it stops at `>`. Then `[^/]` must match `>`, but `>` is not `/`, so it matches! So the regex effectively matches `<language id="1">` — good.

But for a self-closing `<language/>` — the negative lookahead isn't there; `[^/]`... `<language/>`: after `<language`, `[^>]*` matches `/`? No, `/` is allowed in `[^>]*`. So `[^>]*` = `/`, then `[^/]` must match `>` — matches. Then `(.*?)` = empty, `</language>` — not present, so no match. OK.

This is fine. Let me now think about the actual scenario differently.

Maybe the issue isn't in the push at all. Maybe the user means the **admin diff UI** shows the accent as a code. In diff.html, `{{ desc }}` is rendered — Jinja autoescape would show `<p>...</p>` as literal text with tags visible, but accents as `á` fine. Hmm.

Actually — wait. Maybe the issue is the **`[[GLOSS{i}]]` placeholder leaking**. When a translated string still contains `[[GLOSS12]]` because GoogleTranslator returned text where the term wasn't found... no.

Let me re-read the user's words: "fijate si hay un error de compatibilidad de fuentes porque los acentos a veces no se escriben y en lugar de eso aparece un codigo". "error de compatibilidad de fuentes" — font compatibility error. "los acentos a veces no se escriben y en lugar de eso aparece un codigo" — accents sometimes aren't written, instead a code appears.

"Un codigo" — could be a numeric entity `&#243;` or `&#243;`-like codes. When does a numeric character reference appear? When someone HTML-encodes text with `html.escape` or `cgi.escape` with quote=True, non-ASCII characters stay as-is (html.escape only escapes & < > " '). So no.

When does `&#243;` appear? When text is encoded via `xml.sax.saxutils.escape` — that also only handles & < >. So no.

`&#243;` appears if someone does `html.entities`-style conversion. Hmm.

Alternatively "codigo" could be mojibake where accents show as sequences like `Ã³` (that's "ó" utf8 read as latin1) or `Â` (non-breaking space / middle dot).

Let me search the git log for recent encoding-related changes and see what the user might have just changed. Also let me check the ai_agent.py for encoding when fetching with ddgs / requests.

Actually — a very likely culprit: `requests` `resp.text`. In `ai_agent.py`, do they use `resp.text` directly instead of `decode_response`? Let me check ai_agent.py fetching code.

**Tool: grep**

**Input:**
```json
{
  "include": "*.py",
  "path": "/home/icrocetti/dev/ProyectoDC/middleware",
  "pattern": "resp\\.text|\\.text\\)|response\\.text|requests\\.get|\\.content|apparent_encoding|decode_response"
}
```

**Output:**
```
Found 17 matches
/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py:
  Line 18: def decode_response(resp) -> str:

  Line 30:     4. ``apparent_encoding`` (chardet heuristic);

  Line 33:     content = resp.content

  Line 68:     enc = getattr(resp, "apparent_encoding", None)

  Line 510:         resp = requests.get(api_url, timeout=30)


/home/icrocetti/dev/ProyectoDC/middleware/pdf_scraper.py:
  Line 59:         resp = requests.get(url, timeout=timeout, headers={

  Line 69:         if "pdf" not in content_type and not resp.content[:5] == b"%PDF-":

  Line 73:         return resp.content


/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py:
  Line 108:         return spec_extractors.decode_response(resp)


/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py:
  Line 91:             xml_bytes = resp.content

  Line 262:         soup = BeautifulSoup(spec_extractors.decode_response(resp), "lxml")

  Line 1601:         ".content [class*='product-card']",

  Line 1602:         ".content [class*='product-item']",

  Line 1616:         ".content [class*='filter']",

  Line 1617:         ".content [class*='facet']",


/home/icrocetti/dev/ProyectoDC/middleware/prestashop.py:
  Line 98:             return ET.fromstring(resp.content)

  Line 102:                 f"{resp.text[:200]}"

```

---

## Assistant (Build · Big Pickle · 7.3s)

_Thinking:_

The scraping paths all use `decode_response` which is solid. So the mojibake from scraping is handled.

Let me reconsider: maybe the "code" appears in the description pushed to PrestaShop because of the CDATA wrapping + `unescape`. Specifically: consider a description containing a literal ampersand that forms a "named entity-looking" sequence, e.g. "Samsung Galaxy S8" — no &. 

Or consider the description value from a reseller with `&` like "Tom & Jerry". ElementTree escapes `&` → `&amp;`, `_wrap_language_cdata` unescapes → `&`. CDATA stores `&`. Good.

Hmm what about a value containing `</language>`? Unlikely.

Let me think about the actual output "un codigo". Perhaps it's a character like `\x7f` or replacement char U+FFFD (�). The user says "acentos no se escriben y en lugar de eso aparece un codigo" — maybe what appears is a small box or `�` (replacement char). Where would U+FFFD be introduced?

In `decode_response`, `errors="replace"` produces U+FFFD when bytes can't be decoded. That could happen if content is declared as a wrong charset. E.g. a page is UTF-8 but `<meta>` says `windows-1252`, then `content.decode("windows-1252", errors="replace")` — actually windows-1252 can decode any byte, so no replacement. But if declared charset is something like `iso-8859-9` and content is UTF-8, you get mojibake or replacement chars.

But wait — the actual bug the user is pointing at: "compatibilidad de fuentes". Font compatibility. In the PrestaShop front-end, if the DB stores correctly encoded UTF-8 but the page is served as latin-1, accents break. But the middleware controls the PUT only.

Hmm, let me reconsider. Let me look at git log to understand recent changes around encoding — maybe there's a recent regression. Let me check git log for spec_extractors.py, translate.py, ai_agent.py.

**Tool: bash**

**Input:**
```json
{
  "command": "git log --oneline -15",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
424b710 :)
c62b2df :)
744700b :)
b9c9b5c guardado
27fc7c6 guardado
3b17ed9 guardado
72f5090 guardado
eb1ee80 guardado
a4a9e69 A

```

**Tool: bash**

**Input:**
```json
{
  "command": "git log --oneline -8 -- middleware/spec_extractors.py middleware/translate.py middleware/ai_agent.py admin_ui/prestashop.py",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
c62b2df :)
744700b :)
b9c9b5c guardado
27fc7c6 guardado
eb1ee80 guardado
a4a9e69 A

```

---

## Assistant (Build · Big Pickle · 8.7s)

_Thinking:_

Commit messages are not descriptive. Let me check the diff of the most recent commits that touched these files to understand recent changes. Actually, let me focus on reproducing the issue.

Let me reconsider the `_wrap_language_cdata` unescape path once more, because there's actually a real double-escaping bug possible:

Scenario: description contains the literal string `&aacute;` — no wait.

Let me trace precisely what happens with a description that contains HTML with accents, e.g.:
`<p><strong>Resolución:</strong> 4K Ultra HD</p>`

1. `_set_field` sets `lang.text = "<p><strong>Resolución:</strong> 4K Ultra HD</p>"`.
2. `ET.tostring(root, encoding="unicode")` → `<language id="1">&lt;p&gt;&lt;strong&gt;Resolución:&lt;/strong&gt; 4K Ultra HD&lt;/p&gt;</language>` (unicode, so `á` stays as `á`).
3. `_wrap_language_cdata` regex matches, `unescape(content)` → `<p><strong>Resolución:</strong> 4K Ultra HD</p>`, wrapped in CDATA.
4. PUT sends UTF-8 bytes. PrestaShop stores. Front renders `á`. 

That works. So accents in description should be fine...

UNLESS the description contains a literal `&` that isn't part of a valid entity and PrestaShop's own rendering treats it as the start of an entity. But that's PrestaShop-side, and it's a "code" only if the entity is incomplete.

Hmm wait, actually let me reconsider. What if `_wrap_language_cdata` does NOT match because the `<language>` element has NO id attribute? When would that happen? `_set_field` always sets id=LANG_ID. But in `_create_feature`/`_create_feature_value` they also set id. And for GET→PUT round trip, the existing language elements have ids. So CDATA wrapping always applies to language elements.

But actually there's a subtle scenario: what if `LANG_ID` differs and PrestaShop returns the language element as `<language id="2" xlink:href=...>`. Then `_strip_prestashop_attrs` runs (PS 8.1 workaround) BEFORE tostring — it keeps only id attr. So `<language id="2">`. Regex matches. Fine.

OK let me approach from a totally different angle: search the DB to see actual stored content with codes. Maybe there's a `catalogo.db` with proposal_json containing entities or mojibake. Let me query the DB for description fields containing entity codes or U+FFFD.

Reviso la BD para ver si hay datos reales con códigos en lugar de acentos:

**Tool: bash**

**Input:**
```json
{
  "command": "ls -la catalogo.db 2>/dev/null; venv/bin/python - <<'EOF'\nimport sqlite3, json, re\nconn = sqlite3.connect('catalogo.db')\nconn.row_factory = sqlite3.Row\n# find proposal_json with entity codes or mojibake or U+FFFD\nrows = conn.execute(\"SELECT id_prestashop, proposal_json FROM productos WHERE proposal_json IS NOT NULL\").fetchall()\nprint(\"total con proposal:\", len(rows))\nentity = re.compile(r'&[a-zA-Z#0-9]{2,8};')\nmoji = re.compile(r'Ã[€-¿]|Â|�')\nfor r in rows:\n    try: p = json.loads(r['proposal_json'])\n    except Exception: continue\n    for k, v in p.items():\n        if isinstance(v, str):\n            if entity.search(v) or moji.search(v):\n                print(r['id_prestashop'], k, repr(v[:200]))\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
-rw-r--r-- 1 icrocetti icrocetti 1404928 Aug 12 08:36 catalogo.db
total con proposal: 156
Traceback (most recent call last):
  File "<stdin>", line 8, in <module>
  File "/usr/lib/python3.14/re/__init__.py", line 289, in compile
    return _compile(pattern, flags)
  File "/usr/lib/python3.14/re/__init__.py", line 350, in _compile
    p = _compiler.compile(pattern, flags)
  File "/usr/lib/python3.14/re/_compiler.py", line 762, in compile
    p = _parser.parse(p, flags)
  File "/usr/lib/python3.14/re/_parser.py", line 973, in parse
    p = _parse_sub(source, state, flags & SRE_FLAG_VERBOSE, 0)
  File "/usr/lib/python3.14/re/_parser.py", line 460, in _parse_sub
    itemsappend(_parse(source, state, verbose, nested + 1,
                ~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                       not nested and not items))
                       ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.14/re/_parser.py", line 617, in _parse
    raise source.error(msg, len(this) + 1 + len(that))
re.PatternError: bad character range €-¿ at position 2

```

---

## Assistant (Build · Big Pickle · 3.5s)

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python - <<'EOF'\nimport sqlite3, json, re\nconn = sqlite3.connect('catalogo.db')\nconn.row_factory = sqlite3.Row\nrows = conn.execute(\"SELECT id_prestashop, proposal_json FROM productos WHERE proposal_json IS NOT NULL\").fetchall()\nentity = re.compile(r'&[a-zA-Z#0-9]{2,8};')\nmoji = re.compile(r'[\\u00c0-\\u00c3\\u2014\\uFFFD]')\nprint(\"total con proposal:\", len(rows))\nfor r in rows:\n    try: p = json.loads(r['proposal_json'])\n    except Exception: continue\n    for k, v in p.items():\n        if isinstance(v, str):\n            if entity.search(v) or moji.search(v):\n                print(r['id_prestashop'], k, repr(v[:250]))\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
total con proposal: 156
20 title 'Samsung Galaxy A16 5G: caracterÃ\xadsticas y especificaciones - smartGSM'
21 descripcion '▷ Encontr&#225; en Space tu Mouse Logitech Wir MX Master 3S Vertical &#128640; Hac&#233; click para comprar y hacerlo tuyo online. Enviamos a todo el pa&#237;s.'
12856 descripcion 'Perfil de superficie. Fabricado en aluminio extruido y anodizado. Diseñado para disipar tiras LED. \xa0 Árbitro. Color Descripción Acabado ST15-A Plata mate Perfil de superficie sin difusor Anodizado ST15-B Blanco Perfil de superficie sin difusor Pintad'
13016 descripcion '&lt;!DOCTYPE html&gt;\n&lt;html lang=&apos;es&apos;&gt;\n&lt;head&gt;\n    &lt;meta charset=&apos;UTF-8&apos;&gt;\n    &lt;meta name=&apos;viewport&apos; content=&apos;width=device-width, initial-scale=1.0&apos;&gt;\n    &lt;title&gt;CALCULADORA BOLSILLO '
82378 modelo '&gt;COMBOCORSA'
82393 imagen_url 'https://contents.mediadecathlon.com/p2310287/k$c3f4648ac2914b6e3b0e89dbea12e859/bomba-aire-manual-ciclismo-btwin-negro.jpg?format=auto&amp;quality=40&amp;f=250x250'
82409 descripcion 'Filtro de aire\n\nFiltro de aire adicional guadañadora FS 160/220/280/290 (41191410300) STIHL\n\n\n\n&amp;nbsp;'
82422 title 'Filtro de Aire B&amp;s Espuma 3 y 3.5 Hp'
82422 descripcion 'Filtro de Aire B&amp;s Espuma 3 y 3.5 Hp'
82428 title 'Rollo de cadena de motosierra CMC 3/8&#039;&#039; 1.3mm (0.50&#039;&#039;) 30 metros chisel (cuadrada)'
82428 descripcion 'Rollo de cadena de motosierra CMC 3/8&#039;&#039; 1.3mm (0.50&#039;&#039;) 30 metros. Rollo de cadena para motosierra CMC, ideal para corte de madera y armado de cadenas a medida.'
82430 descripcion 'Especificaciones técnicas&#009;&#009;Marca: Champion&#009;&#009;&#009;Número de parte: N9YC&#009;&#009;&#009;Rosca: 14 mm&#009;&#009;&#009;Largo de rosca: 19 mm (3/4&quot;)&#009;&#009;&#009;Hexágono: 20.6 mm (13/16&quot;)&#009;&#009;&#009;Electrodo: '
82436 descripcion 'Cadena de Motosierra OSLO® 0.325” 1.5mm Semi ChiselDurabilidad y rendimiento en cada corte.&amp;nbsp;La&amp;nbsp;Cadena de Motosierra OSLO®&amp;nbsp;es la herramienta perfecta para garantizar cortes precisos y eficientes, incluso en las condiciones m'
82448 descripcion 'Recuerda. El tipo de producto es una caja de 400 horquillas lisas para moño. Dimensión: 65mm. Pensada para ser utilizada en peinados de fallera o recogidos.&nbsp;La Caja de 400 Horquillas Moño Bronce 65 mm de Eurostil es un básico imprescindible para'
82453 descripcion 'El Motorola Moto G82 es un smartphone Android con una pantalla AMOLED de 6.6 pulgadas a resoluciÃ³n Full HD+ con tasa de refresco de 120Hz. Por dentro del Moto G82 encontramos un procesador Snapdragon 695 con 6GB de RAM y 128GB de almacenamiento inte'
82457 title 'Estuche &quot;Tomo del Aventurero&quot;'
82463 title 'Archivos de la estrella: dieciocho meses de bocetos, especificaciones y φ — la evolución completa del logo de USA Times | USA Times'
82472 title 'Espada apto para motosierras STIHL MS 08/076/051 .404&quot; 1.6mm 53cm punta dura'

```

---

## Assistant (Build · Big Pickle · 18.6s)

_Thinking:_

Now we have real evidence. There are multiple encoding problems visible in the DB:

1. **Mojibake (latin-1 decoded UTF-8)**: 
   - `product 20 title`: `caracterÃ\xadsticas` → should be "características" (`Ã` = mojibake of `í`... actually `í` in UTF-8 is `C3 AD`, decoded as latin-1 gives `Ã\xad`). So this is UTF-8 bytes decoded as latin-1/cp1252. This comes from scraping (Selenium or requests).
   - `product 82453 descripcion`: `resoluciÃ³n` → "resolución" mojibake.

2. **HTML entities left un-decoded**:
   - `product 21 descripcion`: `&#225;`, `&#128640;`, `&#233;`, `&#237;` — numeric entities literally stored.
   - `product 82428 title/descripcion`: `&#039;&#039;` = `''`.
   - `product 82430 descripcion`: `&#009;` (tabs), `&quot;`.
   - `product 82378 modelo`: `&gt;COMBOCORSA`.
   - `product 82393 imagen_url`: `&amp;` in URL (that's actually correct for URLs).

3. **Double-escaped HTML**:
   - `product 13016 descripcion`: `&lt;!DOCTYPE html&gt;\n&lt;html...` — an entire HTML page stored literally (garbage scrape).

4. `product 82457 title`: `&quot;Tomo del Aventurero&quot;` — literal `&quot;`.

So the two real accent-related bugs:
- **Mojibake**: UTF-8 bytes decoded as latin-1 somewhere → `Ã\xad`, `Ã³`. This is the "acentos no se escriben y aparece un codigo" (the code being `Ã` + weird char).
- **HTML entities**: literal `&#225;`, `&aacute;` stored → shows as code `&#225;` in rendering (when not interpreted).

Now where do these come from? The mojibake likely from Selenium-driven pages in `official_scraper.py` (Selenium `page_source` returns properly decoded unicode though...) OR from `ai_agent.py` via requests. Let me check ai_agent.py — the title for product 20 is "Samsung Galaxy A16 5G: características y especificaciones - smartGSM". smartGSM is a site. If ai_agent used `requests.get().text` without decode_response... but line 108 uses decode_response. Hmm, but maybe `ddgs` library returns text differently, or the result text comes from a different path.

Wait — product 20 has mojibake in title. Let me check where ai_agent fetches. Let me look at ai_agent.py around line 100-110 and how it builds the title.

Also the numeric entities `&#225;` — those come from scraping where BeautifulSoup was NOT used to decode entities, e.g. the text was extracted from an attribute or JSON string without unescaping. Or GoogleTranslator outputting entities. Let me check.

The most robust fix: normalize text at the persistence boundary (when writing proposal_json and when pushing to PrestaShop):
1. **Decode HTML entities** where appropriate (but careful: description content is intentionally HTML — decoding entities there is fine since accents should be real chars).
2. **Fix mojibake**: detect `Ã`-prefixed patterns (UTF-8 read as latin-1) and re-encode. This is the "font compatibility" issue the user mentions.

The user says "los acentos a veces no se escriben y en lugar de eso aparece un codigo". The "codigo" is most likely the `&#225;`-style entity OR the `Ã\xad` mojibake.

Let me figure out where each originates to fix at source:

**Source of numeric entities (`&#225;`, `&quot;`, `&#039;`):**
- If the scraper extracts text via BeautifulSoup `get_text()`, entities get decoded during parsing. So entities in stored text mean the text came from somewhere that didn't parse HTML — e.g., JSON-LD `content` attribute, JS state objects, or the AI agent's result where the page text contains entity-coded content. OR GoogleTranslator returning entity-encoded text.

Actually! Here's a big one: **GoogleTranslator (deep_translator)**. If you pass text containing HTML entities, deep_translator may return them as-is, or if you pass real HTML, it might return entity-encoded. More importantly — for product 82422 title "Filtro de Aire B&s Espuma 3 y 3.5 Hp" — `B&amp;s` means "B&s" (Briggs & Stratton). So an `&` became `&amp;` somewhere — that's ElementTree escaping that was NOT undone by `_wrap_language_cdata`! Because in the DB, proposal_json is the pre-push JSON, so it wasn't pushed yet... wait, product 82422 has proposal with title `Filtro de Aire B&amp;s Espuma 3 y 3.5 Hp`. This is the stored proposal JSON (pre-push). So the `&amp;` got into the JSON during enrichment storage.

Hmm wait — but the pipeline stores `translated` (the translation output) as proposal_json. So `&amp;` in title means the translation or scrape produced `&amp;`. GoogleTranslator: if you give it "B&s", it might output "B&amp;s"? Actually deep_translator's GoogleTranslator does encode the text? Let me recall... deep_translator `GoogleTranslator.translate()` sends the text in the request. If the source text contains `&`, it's fine. But actually there IS a known deep_translator behavior: it HTML-escapes? Not sure.

Alternatively, the AI agent's `_normalize_text` or the scrape extracted `&amp;` from the page (BeautifulSoup decoding: a page containing `&amp;s` would decode to `&s`). So `&amp;` in stored data means it wasn't decoded.

OK regardless of exact source, the robust fix is a **normalization function** applied to all text that flows into proposals and to PrestaShop:
- Unescape HTML entities (`html.unescape`) — converts `&amp;`, `&#225;`, `&quot;`, `&nbsp;` to real chars.
- Fix mojibake (UTF-8-as-latin1): re-encode.

But careful: 
- Description content is HTML (`<p><strong>...`). `html.unescape` on `<p>Hola &aacute;</p>` → `<p>Hola á</p>`. Good — entities get converted, tags preserved.
- `&nbsp;` → `\xa0` — that's fine.
- Mojibake detection: `Ã\xad` — pattern is a valid latin-1 decode of a UTF-8 multibyte sequence. Fix: if the string contains chars in the `Ã`-range patterns (Ã, Â, and control chars like `\xad`, `\xa0`), try `s.encode('latin-1').decode('utf-8')`. But only if it's valid latin-1 (all chars ≤ 255). If the string has a mix (e.g., real `á` alongside mojibake), a full latin-1 encode would fail on `á`. We can encode with `errors='replace'`? That would corrupt real accents. Better to do a targeted fix: replace known mojibake sequences.

Actually the cleanest targeted approach: use `ftfy` if available? Not in requirements probably. Let me check requirements.txt.

Let me not over-engineer. Let me first identify the sources precisely, then fix at source AND add a normalization guard at write time.

Let me look at:
1. ai_agent.py — how it fetches and builds title/descripcion, whether it uses decode_response and unescape.
2. official_scraper.py — the JS-object extraction and title extraction.
3. Check if there's a place where `resp.text` (latin-1 fallback) is used without decode_response.

The ai_agent title came from smartGSM. Let me read ai_agent.py around fetching and title extraction.

Hay evidencia real en la BD. Veo dos problemas: mojibake (`caracterÃ\xadsticas` = UTF-8 leído como latin-1) y entidades HTML literales (`&#225;`, `&quot;`, `&amp;`). Localizo las fuentes.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py",
  "limit": 130,
  "offset": 80
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py</path>
<type>file</type>
<content>
80:             )
81:         except Exception:
82:             html = driver.page_source
83:         time.sleep(API_SLEEP)
84:         return html
85:     except Exception as exc:
86:         logger.debug("  AI_AGENT  selenium fetch failed %s: %s", url, exc)
87:         return None
88:     finally:
89:         if driver is not None:
90:             driver.quit()
91: 
92: 
93: def _search_web(query: str, max_results: int = 5) -> list[dict]:
94:     """Search DuckDuckGo and return results with title, href."""
95:     try:
96:         from ddgs import DDGS
97:         return DDGS().text(query, max_results=max_results)
98:     except Exception as exc:
99:         logger.warning("  AI_AGENT  search failed: %s", exc)
100:         return []
101: 
102: 
103: def _fetch(url: str) -> str | None:
104:     """Fetch a URL and return the HTML text."""
105:     try:
106:         resp = _SESSION.get(url, timeout=30)
107:         resp.raise_for_status()
108:         return spec_extractors.decode_response(resp)
109:     except requests.RequestException as exc:
110:         logger.debug("  AI_AGENT  fetch failed %s: %s", url, exc)
111:         return None
112:     finally:
113:         time.sleep(API_SLEEP)
114: 
115: 
116: def _extract_image_from_tags(soup: BeautifulSoup) -> str:
117:     """Extract product image URL from <img> tags.
118: 
119:     Tries multiple strategies:
120:     1. <img> with product-related classes/ids
121:     2. <img> with product-related alt text
122:     3. Any reasonably sized <img> (last resort)
123:     """
124: 
125:     def _normalize_url(url: str) -> str:
126:         if not url or url.startswith("data:"):
127:             return url
128:         if url.startswith("//"):
129:             return "https:" + url
130:         return url
131: 
132:     # Strategy 1: <img> with product-related attributes
133:     product_selectors = [
134:         "[class*='product'] img[src]",
135:         "[class*='Product'] img[src]",
136:         "[id*='product'] img[src]",
137:         "[id*='Product'] img[src]",
138:         "[class*='gallery'] img[src]",
139:         "[class*='main-image'] img[src]",
140:         "[class*='hero'] img[src]",
141:         "[class*='detail'] img[src]",
142:     ]
143:     seen_srcs: set[str] = set()
144:     for selector in product_selectors:
145:         for img in soup.select(selector):
146:             src = str(img.get("src", "")).strip()
147:             if not src or src in seen_srcs:
148:                 continue
149:             # Skip tiny images
150:             try:
151:                 if img.get("width") and int(str(img["width"])) < 100:
152:                     continue
153:                 if img.get("height") and int(str(img["height"])) < 100:
154:                     continue
155:             except (ValueError, TypeError):
156:                 pass
157:             if src.startswith("data:") or any(
158:                 skip in src.lower()
159:                 for skip in ("icon", "logo", "avatar", "pixel", "spacer", "blank")
160:             ):
161:                 continue
162:             seen_srcs.add(src)
163:             return _normalize_url(src)
164: 
165:     # Strategy 2: <img> with product-related alt text
166:     for img in soup.find_all("img"):
167:         src = str(img.get("src", "")).strip()
168:         if not src or src.startswith("data:"):
169:             continue
170:         alt = str(img.get("alt") or "").lower()
171:         if any(kw in alt for kw in ("product", "producto", "image", "foto")):
172:             return _normalize_url(src)
173: 
174:     return ""
175: 
176: 
177: def _extract_apple_specs(soup: BeautifulSoup) -> list[dict[str, str]]:
178:     """Extract specs from Apple Support pages (gb-header + gb-list_item format).
179: 
180:     Apple support pages use a custom component system:
181:     - h3.gb-header for section names (e.g. "Chip", "Pantalla")
182:     - li.gb-list_item for spec values under each section
183:     """
184:     features = []
185:     seen = set()
186: 
187:     # Find all section headers
188:     headers = soup.select("h3.gb-header")
189:     for header in headers:
190:         section_name = header.get_text(strip=True)
191:         if not section_name:
192:             continue
193: 
194:         # Get the parent container and find list items
195:         parent = header.parent
196:         if not parent:
197:             continue
198: 
199:         items = parent.select("li.gb-list_item")
200:         for item in items:
201:             item_text = item.get_text(strip=True)
202:             if not item_text or len(item_text) < 2:
203:                 continue
204: 
205:             # For items with ":" separator, use as key-value
206:             if ":" in item_text:
207:                 name, _, value = item_text.partition(":")
208:                 name = name.strip()
209:                 value = value.strip()

(Showing lines 80-209 of 608. Use offset=210 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 5.1s)

_Thinking:_

The AI agent uses `_fetch` with `decode_response` for HTML. But the title of product 20 came from smartGSM with mojibake `caracterÃ\xadsticas`. Hmm. Let me check how the title is extracted. It could come from `_search_web` results (ddgs returns title) — ddgs results might already be mojibake if DDG serves latin-1 and the library decodes incorrectly. Product 20's title is exactly a search result title ("Samsung Galaxy A16 5G: características y especificaciones - smartGSM"). That's likely from DDGS `.text()` results, which are decoded... maybe with latin-1 fallback.

Actually wait — more likely: the AI agent uses Selenium (`_fetch_selenium`) OR the ddgs result title. The stored title in proposal_json is the scrape result title. Let me check where proposal["title"] is set in ai_agent.py — around line 262.

Let me read ai_agent.py lines 240-280 and the main enrich function to see title flow.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py",
  "limit": 180,
  "offset": 240
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py</path>
<type>file</type>
<content>
240:     if marca_lower == "tcl":
241:         # Extract model slug from product name (e.g. "L55P735-F" → "p735")
242:         model_match = re.search(r'P\d{3}', nombre, re.IGNORECASE)
243:         if model_match:
244:             model_slug = model_match.group(0).lower()
245:             # Try multiple locales
246:             for locale in ["ar/es", "us/en", "global/en", "asia/en"]:
247:                 urls.append(f"https://www.tcl.com/{locale}/tvs/{model_slug}")
248: 
249:     # Samsung, LG, Sony, etc. could be added here with their URL patterns
250: 
251:     return urls
252: 
253: 
254: def _parse_page(html: str, current_url: str = "") -> dict | None:
255:     """Try all parsers on a page and return the best result."""
256:     soup = BeautifulSoup(html, "lxml")
257: 
258:     result = spec_extractors.extract_jsonld_product(soup)
259:     if not result:
260:         # Fallback to basic OG meta
261:         og_data = spec_extractors.extract_og_product_meta(soup)
262:         if og_data.get("title"):
263:             result = {
264:                 "title": og_data.get("title", ""),
265:                 "descripcion": og_data.get("desc", ""),
266:                 "descripcion_corta": "",
267:                 "marca": og_data.get("brand", ""),
268:                 "modelo": og_data.get("retailer_id", ""),
269:                 "resumen": "",
270:                 "caracteristicas": [],
271:                 "imagen_url": og_data.get("img", ""),
272:                 "imagen_urls": [og_data["img"]] if og_data.get("img") else [],
273:                 "_source": "og_meta",
274:             }
275:     if not result:
276:         return None
277: 
278:     # Merge features from multiple sources
279:     existing = {ch["nombre"].lower() for ch in result.get("caracteristicas") or []}
280: 
281:     # Brand-specific extractors (TCL, Apple)
282:     tcl_features = spec_extractors.extract_tcl_specs(soup)
283:     for tf in tcl_features:
284:         if tf["nombre"].lower() not in existing:
285:             result["caracteristicas"].append(tf)
286:             existing.add(tf["nombre"].lower())
287: 
288:     apple_features = _extract_apple_specs(soup)
289:     for af in apple_features:
290:         if af["nombre"].lower() not in existing:
291:             result["caracteristicas"].append(af)
292:             existing.add(af["nombre"].lower())
293: 
294:     # Generic extractors (work across all sites)
295:     _generic_extractors = [
296:         ("tables", spec_extractors.extract_tables),
297:         ("dl/dt/dd", spec_extractors.extract_dl_dt_dd),
298:         ("microdata", spec_extractors.extract_microdata),
299:         ("div_spec_rows", spec_extractors.extract_div_spec_rows),
300:         ("body_text", spec_extractors.extract_body_text_specs),
301:     ]
302:     for name, extractor in _generic_extractors:
303:         try:
304:             generic_features = extractor(soup)
305:             for gf in generic_features:
306:                 if gf["nombre"].lower() not in existing:
307:                     result["caracteristicas"].append(gf)
308:                     existing.add(gf["nombre"].lower())
309:         except Exception as exc:
310:             logger.debug("  AI_AGENT  %s extractor failed: %s", name, exc)
311: 
312:     # JS state objects (Next.js, Nuxt, etc.)
313:     try:
314:         js_features = spec_extractors.extract_js_state_objects(html)
315:         for jf in js_features:
316:             if jf["nombre"].lower() not in existing:
317:                 result["caracteristicas"].append(jf)
318:                 existing.add(jf["nombre"].lower())
319:     except Exception as exc:
320:         logger.debug("  AI_AGENT  js_state extraction failed: %s", exc)
321: 
322:     # Extract image from <img> tags if not found in JSON-LD/OG
323:     if not result.get("imagen_url"):
324:         from urllib.parse import urljoin
325:         img_url = _extract_image_from_tags(soup)
326:         if img_url:
327:             # Normalize relative URLs using current page URL
328:             if img_url.startswith("/") and current_url:
329:                 img_url = urljoin(current_url, img_url)
330:             result["imagen_url"] = img_url
331:             # Also add to imagen_urls if not already there
332:             if img_url not in result.get("imagen_urls", []):
333:                 result.setdefault("imagen_urls", []).append(img_url)
334: 
335:     # Store the source URL so validation can check for junk sources
336:     if current_url:
337:         result["url"] = current_url
338: 
339:     return result
340: 
341: 
342: _MODEL_TOKEN_RE = re.compile(r'[A-Z]+\d+[A-Z]+\d+[-]?[A-Z]*')
343: _SHORT_MODEL_RE = re.compile(
344:     r'(?<![A-Za-z0-9])[A-Z]{1,3}\d{2,4}[A-Z]?(?![A-Za-z0-9])'
345: )
346: 
347: 
348: def _model_tokens(nombre: str) -> list[str]:
349:     """Extract model-number tokens from a product name.
350: 
351:     Examples: "TV TCL 55 SMART L55P735-F" → ["L55P735-F", "L55P735"],
352:     "Samsung Galaxy S21 5G" → ["S21"]. Longest-first, deduplicated.
353:     """
354:     if not nombre:
355:         return []
356:     tokens = _MODEL_TOKEN_RE.findall(nombre) + _SHORT_MODEL_RE.findall(nombre)
357:     tokens = list(dict.fromkeys(tokens))
358:     tokens.sort(key=len, reverse=True)
359:     return tokens
360: 
361: 
362: _RESELLER_PATTERNS = (
363:     "mercadolibre", "amazon", "bestbuy", "walmart", "ebay", "mediaworld",
364:     "fravega", "garbarino", "musimundo", "tiendamia", "atida",
365: )
366: 
367: 
368: def _score_candidate(data: dict, marca: str, nombre: str) -> float:
369:     """Score how coherent a scraped candidate is with the expected product.
370: 
371:     Rewards: characteristics richness, model tokens present in the title/URL,
372:     brand match, official-domain and spec-page signals.
373:     Penalizes: manual/support pages and reseller domains.
374:     """
375:     score = 0.0
376:     url = (data.get("url") or "").lower()
377:     title = (data.get("title") or data.get("titulo") or "").lower()
378: 
379:     chars = len(data.get("caracteristicas") or [])
380:     score += min(chars, 20) * 0.5
381: 
382:     tokens = _model_tokens(nombre)
383:     title_norm = title.replace("-", "").replace(" ", "")
384:     url_norm = url.replace("-", "").replace("_", "").replace("/", "")
385:     matched = sum(1 for t in tokens if t.replace("-", "") in title_norm)
386:     if matched:
387:         score += 3 + matched
388:     if any(t.replace("-", "") in url_norm for t in tokens):
389:         score += 2
390: 
391:     scraped_marca = (data.get("marca") or "").lower()
392:     if marca and scraped_marca:
393:         if marca.lower() in scraped_marca or scraped_marca in marca.lower():
394:             score += 2
395: 
396:     if marca and marca.lower() in url:
397:         score += 3
398:     if any(s in url for s in (
399:         "especificacion", "specs", "specification", "ficha-tecnica",
400:         "datasheet", "technical",
401:     )):
402:         score += 2
403:     if any(s in title for s in (
404:         "especificacion", "specs", "specification", "ficha", "datasheet",
405:         "technical",
406:     )):
407:         score += 1
408: 
409:     if any(p in url for p in (
410:         "manual", "soporte", "support", "faq", "guia", "tutorial",
411:     )):
412:         score -= 3
413:     if any(p in url for p in _RESELLER_PATTERNS):
414:         score -= 4
415: 
416:     return score
417: 
418: 
419: def _build_search_query(marca: str, nombre: str) -> str:

(Showing lines 240-419 of 608. Use offset=420 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 25.8s)

_Thinking:_

The `_parse_page` uses BeautifulSoup to parse. The mojibake in title must come from the raw HTML string. `_fetch` uses `decode_response`. But `_search_web` (DDGS) may return mojibake titles, and also `_fetch_selenium` (Selenium `driver.page_source`) returns a str that Selenium decoded... Selenium returns properly-decoded unicode usually.

Wait — for the mojibake `caracterÃ\xadsticas`, the source HTML was UTF-8. If `decode_response` got the right charset it would be fine. But the stored title came from smartGSM — was the smartGSM page fetched via Selenium (page_source) or via requests? If via Selenium, page_source is decoded using the browser's charset detection, usually fine. Hmm.

Actually — wait. Let me look more carefully at `_fetch` in ai_agent vs the `_extract_jsonld_product` in spec_extractors. The title might come from JSON-LD `name` or `og:title`. If the HTML was decoded correctly, the title would be fine.

Let me focus differently: The mojibake `Ã\xad` for `í` and `Ã³` for `ó` — a classic. Where in the pipeline could UTF-8 get decoded as latin-1?

Looking at `decode_response`: it handles most cases. But there's one path that doesn't go through decode_response: `_fetch_selenium` returns `driver.page_source` directly (line 82). And `ddgs` results. Also `official_scraper.py` may have `_fetch_page` returning `resp.text`? Let me check official_scraper's fetch. Line 262 uses decode_response. Let me check the sitemap fetch `_fetch_page`.

Actually, the more productive approach: the user asked to "fijate si hay un error de compatibilidad de fuentes" — check if there's a font/encoding compatibility error. They want me to find and fix it. Given the DB evidence, there are 3 categories of encoding corruption. Rather than chase every source (hard to know which one produced each), the robust solution is:

**Add a text-normalization step at the boundaries where text enters the DB / gets pushed:**
1. `html.unescape()` to decode literal HTML entities (`&#225;` → `á`, `&quot;` → `"`, `&amp;` → `&`, `&nbsp;` → `\xa0`).
2. Mojibake repair: re-encode UTF-8 bytes that were decoded as latin-1.

Where to apply:
- When storing proposal_json (enrich.py, check_active.py, official_scraper.py `_persist_scrape_result`).
- When pushing to PrestaShop (description building in enrich.py and app.py approve).
- Also characteristics values/names.

But we must be careful not to break intentionally-HTML description content. `html.unescape` is safe for that (it only converts entities, doesn't touch tags).

For mojibake repair, implement a helper `repair_mojibake(s)`:
```python
def repair_mojibake(s: str) -> str:
    # If the string contains the classic UTF-8-as-latin1 signature (Ã, Â, etc.)
    # AND the whole string is encodable in latin-1, re-decode as UTF-8.
    try:
        # only if there's a candidate mojibake sequence
        if any(c in s for c in "ÃÂ") and any(ord(c) < 256 for c in s):
            return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return s
```

Wait but this is risky: a legit Spanish text like "Â" or "Ã" doesn't appear. But encoding latin-1 requires all chars ≤ 255 — a string with a real `á` (0xE1 ≤ 255, fine) plus mojibake `Ã³` (Ã=0xC3, ³=0xB3, fine) would encode to latin-1 bytes = original UTF-8 bytes → decode as UTF-8 gives correct "ó" AND correct "á". Actually this works! Because mojibake happens when you have UTF-8 bytes and decode them as latin-1, producing chars all ≤ 255. If the whole string is the mojibake output, then `s.encode('latin-1')` recovers the original bytes, and `.decode('utf-8')` recovers the original text — AS LONG AS the entire string is encodable as latin-1 AND the resulting bytes are valid UTF-8.

Edge cases:
- String contains real `\xa0` (non-breaking space, from `&nbsp;`): latin-1 encode gives `0xA0` which is invalid UTF-8 → decode fails → return original. Good.
- String contains `€` (U+20AC): not latin-1 → encode fails → return original. Good.
- String contains both real unicode `á` AND mojibake — as computed, works because both are latin-1 representable and the concat of bytes is valid UTF-8.

But there's a subtle risk: a string that is ALL valid latin-1 AND the concatenated bytes form valid UTF-8 by coincidence (ASCII + some accented chars in a way that... no). For ASCII-only text, `s.encode('latin-1')` = same bytes = valid UTF-8, decode returns same string. No-op. For text with real accents like "resolución" (é=0xE9), latin-1 encode = `0xE9` which is NOT valid UTF-8 (0xE9 needs continuation bytes) → decode fails → unchanged. Good.

For mojibake "resoluciÃ³n" (Ã=0xC3 ³=0xB3) → bytes `C3 B3` = valid UTF-8 for "ó" → decode → "resolución". 

So `repair_mojibake` = try `s.encode('latin-1').decode('utf-8')` on the whole string, catch errors, return original. This is exactly the standard fix. The only real risk: text that's already correct UTF-8 but happens to contain only latin-1-representable chars AND re-encodes to valid UTF-8. E.g. "café" (é=0xE9) → latin-1 → 0xE9 invalid UTF-8 → no change. Text "¡Hola!" (¡=0xA1) → 0xA1 invalid UTF-8 → no change. Text with em-dash `—` (0x2014) not latin-1 → no change. So safe.

The `\xa0` (nbsp) case: latin-1 gives 0xA0 → invalid UTF-8 → no change, stays \xa0. Good.

Now let me find ALL the places to apply this. The cleanest: create a helper in spec_extractors.py (already has decode_response) or a new small module, and apply:

1. In `enrich.py` when storing `proposal_json` (both Path A stored reuse and Path B). Actually simplest to apply normalization:
   - At scrape result time (all scraper outputs) — in `ai_agent._parse_page`? That would be invasive.
   
Better approach: apply a sanitizer when text is STORED to DB or PUSHED:
- `enrich.py` `_store`/UPDATE proposal_json — normalize the whole `translated` dict recursively before `json.dumps`.
- `official_scraper._persist_scrape_result` — same.
- `check_active` — same.
- `admin_ui/app.py` approve — when building desc and description_short.
- `enrich._push_to_prestashop` — when building desc and description_short.

Also normalize characteristics values (they end up in descriptions and features). And title/marca/modelo.

Let me design a helper function `normalize_text(value)`:

```python
def normalize_text(value: str) -> str:
    """Fix font/encoding corruption in scraped text.

    1. HTML entities → real chars (&#225; → á, &quot; → ", &amp; → &).
    2. Mojibake: UTF-8 bytes decoded as latin-1 (Ã³ → ó, Ã± → ñ).
    """
    if not value:
        return value
    value = _html.unescape(value)
    try:
        fixed = value.encode("latin-1").decode("utf-8")
        # valid UTF-8 re-decode → real accents recovered
        value = fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return value
```

Wait, but `html.unescape("&amp;")` → `&`. Good. And `html.unescape("B&amp;s")` → "B&s". Good.

But careful: the description built by the pipeline is HTML like `<p><strong>Resolución:</strong> 4K</p>`. Applying `normalize_text` to that: unescape decodes entities (fine), mojibake repair on `<p>...` with `á` — latin-1 encode fails on... wait `á` is 0xE1, latin-1 encodable; `<p>` ASCII. Bytes: `<p><strong>Resoluci...` with é=0xE9 → invalid UTF-8 → no change. Good. But if the description is pure mojibake throughout → fixed. Good.

Where exactly to apply:

**Option A: apply at source — normalize scraped data right where proposals are built.** This covers everything downstream (proposal_json stored, descriptions pushed, features). But the push in enrich.py Path A reuses STORED data (already normalized), and approve reuses stored data.

The catch: existing already-corrupted stored data (like the 156 proposals) would stay corrupted unless re-scraped. The stored data validation (`_validate_scraped_data`) would still pass. But the user cares about future and the display. For robustness, normalize at push time too.

I'll apply `normalize_text` in these spots:
1. New helper in `spec_extractors.py` (shared by ai_agent, official_scraper) — actually better in a module that's imported by all: `spec_extractors` is imported everywhere. But semantically it's not a "spec extractor". Still, pragmatic. Alternatively create `middleware/encoding.py`. Hmm, keep it simple: add to `spec_extractors.py` since it already has `decode_response` (encoding concerns live there). 

2. Apply in `ai_agent._parse_page` — normalize title, descripcion, resumen, marca, modelo, caracteristicas, imagen... Actually normalize the whole result dict at the end of `_parse_page`. But `_parse_page` returns dict; normalize values.

3. Apply in `official_scraper` — where the result is built. There are several places. Instead, normalize in `_persist_scrape_result` (single choke point for manual URL) — normalize the result before storing.

4. Apply in `enrich.py` when storing proposal and when pushing (description building) — choke points: the UPDATE that writes proposal_json, and `_build_description`/`_push_to_prestashop`.

5. Apply in `admin_ui/app.py` approve — when building desc and description_short.

Actually, the cleanest single choke point for ALL text that leaves the system: the **put_product / description build**. But the proposal_json stored in DB also feeds the diff UI display (where the user would see `&#225;` too). The user likely sees the corrupted text in PrestaShop products AND/OR in the admin diff.

Hmm, let me think about where the user sees it. "los acentos a veces no se escriben y en lugar de eso aparece un codigo" — in PrestaShop products (published descriptions). So fix at push time is critical. Also fix at store time so re-push doesn't re-corrupt.

Let me also reconsider the mojibake source to fix at the ROOT. The smartGSM title (product 20). Let me check: smartGSM pages are probably UTF-8. `decode_response` should handle. But the title in proposal might come from `ddgs` search results title! `_search_web` returns DDGS titles, and the AI agent might use result titles as candidate titles. Let me check where the search result title is used — maybe `_search_and_enrich` stores `title` from the DDG result, not from the page. Let me read the main AI enrich function.

Let me read ai_agent.py from 419 to end.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py",
  "limit": 190,
  "offset": 419
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py</path>
<type>file</type>
<content>
419: def _build_search_query(marca: str, nombre: str) -> str:
420:     """Build a clean search query from brand and product name.
421: 
422:     Extracts the model number from the product name and constructs
423:     a cleaner query that's more likely to find official product pages.
424: 
425:     Examples:
426:         "tcl", "TV TCL 55 SMART 4K UHD HDR L55P735-F" → "TCL L55P735-F especificaciones"
427:         "apple", "iphone 15 pro max" → "apple iphone 15 pro max especificaciones"
428:         "samsung", "Galaxy S21 5G" → "Samsung Galaxy S21 5G especificaciones"
429:     """
430: 
431:     if not nombre:
432:         return f"{marca} especificaciones" if marca else "especificaciones"
433: 
434:     all_models = _model_tokens(nombre)
435: 
436:     if all_models:
437:         # Use the first (most specific) model number
438:         model = all_models[0]
439:         # Build query with brand + model, excluding manual/support pages
440:         if marca:
441:             query = f"{marca} {model} especificaciones -manual -guia -tutorial -soporte"
442:         else:
443:             query = f"{model} especificaciones -manual -guia"
444:     else:
445:         # No model found, use full name but remove noise words
446:         from .official_scraper import _NOISE_WORDS
447: 
448:         words = nombre.split()
449:         cleaned_words = [
450:             w for w in words
451:             if w.lower() not in _NOISE_WORDS and len(w) > 1
452:         ]
453:         cleaned_name = " ".join(cleaned_words[:5])  # Limit to 5 words
454:         if marca:
455:             query = f"{marca} {cleaned_name} especificaciones -manual -guia"
456:         else:
457:             query = f"{cleaned_name} especificaciones -manual -guia"
458: 
459:     return query
460: 
461: 
462: def enrich_with_ai(
463:     marca: str,
464:     nombre: str,
465:     max_results: int = 5,
466:     accept=None,
467: ) -> dict | None:
468:     """Search the web and scrape official product data (no LLM).
469: 
470:     Uses the product name (which already contains brand + model) as the
471:     primary search term.  Collects a candidate from every search result,
472:     scores each for coherence with the product name (model tokens in the
473:     title/URL, official-domain and spec-page signals, brand match), and:
474: 
475:     - if ``accept`` is given (a ``callable(data) -> bool``), returns the
476:       highest-scoring candidate that passes it — rejected candidates are
477:       skipped, so a bad first hit no longer abandons the remaining results;
478:     - otherwise returns the single highest-scoring candidate.
479: 
480:     Parameters
481:     ----------
482:     marca:
483:         Brand name (e.g. "Samsung").
484:     nombre:
485:         Product name from PrestaShop (e.g. "Galaxy S21 5G").
486:     max_results:
487:         Number of web results to consider.
488:     accept:
489:         Optional validator callback used to pick among ranked candidates.
490: 
491:     Returns
492:     -------
493:     dict | None
494:         Normalized product data on success, ``None`` if nothing found.
495:     """
496:     query = _build_search_query(marca, nombre)
497:     logger.info("  AI_AGENT  searching: %s", query)
498: 
499:     results = _search_web(query, max_results=max_results)
500:     if not results:
501:         logger.info("  AI_AGENT  no search results for: %s", query)
502:         return None
503: 
504:     candidates: list[tuple[float, dict]] = []
505: 
506:     for r in results:
507:         url = r.get("href") or r.get("link") or ""
508:         title = r.get("title", "")
509:         if not url or not url.startswith("http"):
510:             continue
511:         # Skip PDFs, manuals, and support pages
512:         if any(url.lower().endswith(ext) for ext in ('.pdf', '.doc', '.docx', '.xls')):
513:             logger.info("  AI_AGENT  skipping non-HTML: %s", url[:80])
514:             continue
515: 
516:         logger.info("  AI_AGENT  trying: %s (%s)", url, title[:60])
517: 
518:         # First try simple HTTP fetch
519:         html = _fetch(url)
520:         data = None
521:         if html and len(html) >= 500:
522:             data = _parse_page(html, url)
523: 
524:         # Fallback: try Selenium for JS-heavy pages (only when HTTP gave no
525:         # characteristics — otherwise the extra headless browser is wasted).
526:         if data is None or not data.get("caracteristicas"):
527:             logger.info("  AI_AGENT  trying Selenium for: %s", url)
528:             html_selenium = _fetch_with_selenium(url)
529:             if html_selenium and len(html_selenium) >= 500:
530:                 selenium_data = _parse_page(html_selenium, url)
531:                 if selenium_data is not None:
532:                     if data is None:
533:                         data = selenium_data
534:                     elif len(selenium_data.get("caracteristicas") or []) > len(
535:                         data.get("caracteristicas") or []
536:                     ):
537:                         data = selenium_data
538: 
539:         if data is None:
540:             continue
541:         if not data.get("marca"):
542:             data["marca"] = marca
543:         if not data.get("modelo"):
544:             data["modelo"] = ""
545:         if not (data.get("caracteristicas") or data.get("descripcion")):
546:             continue
547: 
548:         score = _score_candidate(data, marca, nombre)
549:         logger.info(
550:             "  AI_AGENT  candidate score=%.1f (%d características): %s",
551:             score, len(data.get("caracteristicas") or []), url[:80],
552:         )
553:         candidates.append((score, data))
554: 
555:     # ── Brand-specific fallback: try official website directly ────────────
556:     # For brands with predictable URL patterns, try the official site directly
557:     # if web search didn't find it.
558:     if marca:
559:         for official_url in _get_brand_official_urls(marca, nombre):
560:             logger.info("  AI_AGENT  trying official URL: %s", official_url)
561:             html_official = _fetch_with_selenium(official_url)
562:             if html_official and len(html_official) >= 500:
563:                 data_official = _parse_page(html_official, official_url)
564:                 if data_official:
565:                     if not data_official.get("marca"):
566:                         data_official["marca"] = marca
567:                     if data_official.get("caracteristicas"):
568:                         score = _score_candidate(
569:                             data_official, marca, nombre
570:                         ) + 5  # official-site boost
571:                         logger.info(
572:                             "  AI_AGENT  official candidate score=%.1f (%d características)",
573:                             score, len(data_official.get("caracteristicas") or []),
574:                         )
575:                         candidates.append((score, data_official))
576: 
577:     if not candidates:
578:         logger.info("  AI_AGENT  no product data found for %s %s", marca, nombre)
579:         return None
580: 
581:     candidates.sort(key=lambda c: c[0], reverse=True)
582: 
583:     if accept is not None:
584:         for score, data in candidates:
585:             try:
586:                 ok = bool(accept(data))
587:             except Exception as exc:  # validator must never crash the pipeline
588:                 logger.debug("  AI_AGENT  validator raised: %s", exc)
589:                 ok = False
590:             if ok:
591:                 logger.info(
592:                     "  AI_AGENT  accepted candidate (score=%.1f): %s",
593:                     score, (data.get("url") or "")[:80],
594:                 )
595:                 return data
596:             logger.info(
597:                 "  AI_AGENT  candidate rejected by validator (score=%.1f): %s",
598:                 score, (data.get("url") or "")[:80],
599:             )
600:         logger.info("  AI_AGENT  no candidate passed validation for %s %s", marca, nombre)
601:         return None
602: 
603:     best_score, best_data = candidates[0]
604:     logger.info(
605:         "  AI_AGENT  choosing best candidate (score=%.1f): %s",
606:         best_score, (best_data.get("url") or "")[:80],
607:     )
608:     return best_data

(End of file - total 608 lines)
</content>
```

---

## Assistant (Build · Big Pickle · 8.2s)

_Thinking:_

So the AI agent's `_parse_page` builds the result from scraped HTML. The mojibake `caracterÃ\xadsticas` title — where does it come from? `_parse_page` result title comes from `spec_extractors.extract_jsonld_product` or OG meta `og:title`. If the HTML string is already correctly decoded (via decode_response), the og:title would be correct. So mojibake means the HTML was NOT correctly decoded. 

But wait — the `_fetch` path uses decode_response. However, the `_fetch_with_selenium` path (line 82) returns `driver.page_source` directly. Selenium's `page_source` should be correctly decoded Unicode (the browser knows the charset). So it shouldn't be mojibake either.

Hmm — unless the mojibake got INTO the DB via `_validate_name_coherence` or via a source that re-encoded. Actually, there's a subtle one: **GoogleTranslator**. The `translate` function protects glossary with `[[GLOSS{i}]]`, translates, restores. If the source text had mojibake, it passes through as mojibake. But translate doesn't create mojibake.

Wait, actually maybe the mojibake came from `spec_extractors.extract_jsonld_product`. Let me check if it does anything with encoding... no, it just parses JSON from the soup.

Let me test empirically: check product 20's stored proposal more fully — see which fields and what _source. Let me also check products 82453, 82422, 82430, 82436, 82448 — these look like they came from different sources (82453 Moto G82 = smartGSM too probably). Let me query the full proposals to understand source and whether the whole description is mojibake or only parts.

Actually, let me step back. The user's ask is a bug report + fix request. I've identified the concrete corruption patterns in the DB. The most reliable fix is a normalization layer. But let me also try to find the actual root cause so the fix is at the source AND add the guard.

Let me check product 20 and 82453 full proposals, and specifically which extractor produced them.

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python - <<'EOF'\nimport sqlite3, json\nconn = sqlite3.connect('catalogo.db')\nconn.row_factory = sqlite3.Row\nfor pid in (20, 82453, 82422, 82430, 82436, 82378, 13016):\n    r = conn.execute(\"SELECT nombre, marca, proposal_json FROM productos WHERE id_prestashop=?\", (pid,)).fetchone()\n    if not r: continue\n    print(\"=\"*80)\n    print(\"id\", pid, \"| DB nombre:\", repr(r['nombre']))\n    try: p = json.loads(r['proposal_json'])\n    except Exception as e: print(\"no json:\", e); continue\n    print(\"keys:\", sorted(p.keys()))\n    for k in ('_source','url','title','marca','modelo','descripcion','resumen'):\n        v = p.get(k)\n        if v: print(f\"  {k}: {repr(v)[:160]}\")\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
================================================================================
id 20 | DB nombre: 'Samsung Galaxy A16'
keys: ['_ean', '_id_prestashop', '_score', '_source', 'caracteristicas', 'descripcion', 'descripcion_corta', 'imagen_url', 'imagen_urls', 'marca', 'modelo', 'resumen', 'title', 'url']
  _source: 'og_meta'
  url: 'https://www.smart-gsm.com/moviles/samsung-galaxy-a16-5g'
  title: 'Samsung Galaxy A16 5G: caracterÃ\xadsticas y especificaciones - smartGSM'
  marca: 'Samsung'
  modelo: 'A16'
  descripcion: 'Características Samsung Galaxy A16 5G: pantalla 6.7 pulgadas, Exynos 1330 2.4GHz / Dimensity 6300 2.4GHz, 4GB/8GB RAM, cámara Triple 50MP+5MP +2MP'
================================================================================
id 82453 | DB nombre: 'TORRETA MTD 82-403'
keys: ['_ean', '_id_prestashop', '_score', '_source', 'caracteristicas', 'descripcion', 'descripcion_corta', 'imagen_url', 'imagen_urls', 'marca', 'modelo', 'resumen', 'title', 'url']
  _source: 'jsonld'
  url: 'https://www.smart-gsm.com/moviles/motorola-moto-g82'
  title: 'Motorola Moto G82 5G'
  marca: 'Motorola'
  modelo: 'TORRETA'
  descripcion: 'El Motorola Moto G82 es un smartphone Android con una pantalla AMOLED de 6.6 pulgadas a resoluciÃ³n Full HD+ con tasa de refresco de 120Hz. Por dentro del Moto
================================================================================
id 82422 | DB nombre: 'FILTRO AIRE B&S 3.5'
keys: ['_ean', '_id_prestashop', '_score', '_source', 'caracteristicas', 'descripcion', 'descripcion_corta', 'imagen_url', 'imagen_urls', 'marca', 'modelo', 'resumen', 'title', 'url']
  _source: 'jsonld'
  url: 'https://homecenter.falabella.com.co/homecenter-co/product/138197429/Filtro-de-Aire-B-s-Espuma-3-y-3.5-Hp/138197430'
  title: 'Filtro de Aire B&amp;s Espuma 3 y 3.5 Hp'
  marca: 'BRIGGS'
  modelo: '138197430'
  descripcion: 'Filtro de Aire B&amp;s Espuma 3 y 3.5 Hp'
================================================================================
id 82430 | DB nombre: 'BUJIA CHAMPION N9YC'
keys: ['_ean', '_id_prestashop', '_score', '_source', 'caracteristicas', 'descripcion', 'descripcion_corta', 'imagen_url', 'imagen_urls', 'marca', 'modelo', 'resumen', 'title', 'url']
  _source: 'jsonld'
  url: 'https://www.totalimexredi.com/product-page/bujia-champion-n9yc'
  title: 'CAMPEÓN DE BUJIA N9YC'
  marca: 'CHAMPION'
  modelo: 'N9YC'
  descripcion: 'Especificaciones técnicas&#009;&#009;Marca: Champion&#009;&#009;&#009;Número de parte: N9YC&#009;&#009;&#009;Rosca: 14 mm&#009;&#009;&#009;Largo de rosca: 19 m
================================================================================
id 82436 | DB nombre: 'ROLLO CADENA 0.325 1.5 ALTERNATIVA A+'
keys: ['_ean', '_id_prestashop', '_score', '_source', 'caracteristicas', 'descripcion', 'descripcion_corta', 'imagen_url', 'imagen_urls', 'marca', 'modelo', 'resumen', 'title', 'url']
  _source: 'jsonld'
  url: 'https://oslo.jumpseller.com/rollo-cadena-motosierra-325-05015mm-oslo'
  title: 'Rollo Cadena Motosierra 0,325 1,5MM 1840 Eslabones Semi Chisel OSLO®'
  marca: 'OSLO®'
  modelo: 'IOSMA0019 + IOSAC0015'
  descripcion: 'Cadena de Motosierra OSLO® 0.325” 1.5mm Semi ChiselDurabilidad y rendimiento en cada corte.&amp;nbsp;La&amp;nbsp;Cadena de Motosierra OSLO®&amp;nbsp;es la herr
================================================================================
id 82378 | DB nombre: 'FILTRO NAFTA GRANDE T/STIHL PICO FINO'
keys: ['_ean', '_id_prestashop', '_score', '_source', 'caracteristicas', 'descripcion', 'descripcion_corta', 'imagen_url', 'imagen_urls', 'marca', 'modelo', 'resumen', 'title', 'url']
  _source: 'jsonld'
  url: 'https://spch.com.ar/productos/filtro-de-nafta-univ-picborg-doble-pico/'
  title: 'KIT DE FILTRO DE MARCO CHEV. CARRERA 1.4/1.6'
  marca: 'FRAM'
  modelo: '&gt;COMBOCORSA'
  descripcion: 'Mejorá el rendimiento de tu Chevrolet Corsa con el KIT DE FILTROS FRAM. Incluye filtros de aire, aceite y combustible. ¡Compralo y cuidá tu motor!'
================================================================================
id 13016 | DB nombre: 'CALCULADORA CASIO LC-403TV'
keys: ['_ean', '_id_prestashop', '_score', '_source', 'caracteristicas', 'descripcion', 'descripcion_corta', 'imagen_url', 'imagen_urls', 'marca', 'modelo', 'resumen', 'title', 'url']
  _source: 'jsonld'
  url: 'https://www.casaroyal.cl/casio-calculadora-bolsillo-casio-lc-403tv/p'
  title: 'CASIO CALCULADORA BOLSILLO CASIO LC-403TV'
  marca: 'CASIO'
  modelo: '106832'
  descripcion: '&lt;!DOCTYPE html&gt;\n&lt;html lang=&apos;es&apos;&gt;\n&lt;head&gt;\n    &lt;meta charset=&apos;UTF-8&apos;&gt;\n    &lt;meta name=&apos;viewport&apos; conte

```

---

## Assistant (Build · Big Pickle · 10.3s)

_Thinking:_

Excellent! This is very revealing. Now I understand:

1. **The mojibake in `descripcion`**: Product 20's `descripcion` is CORRECT ("Características Samsung Galaxy A16..."), but its `title` is mojibake. Product 82453's `descripcion` is mojibake ("resoluciÃ³n") but `title` is clean. So the mojibake is inconsistent within the same page — the same HTML produced both clean and mojibake text. That means the mojibake happened at extraction/parsing time, not at fetch.

Wait — how can the same fetched HTML produce one clean field and one mojibake field? Because they're extracted from different DOM locations. If the HTML is correctly decoded UTF-8, ALL text would be clean. Unless... the JSON-LD `<script type="application/ld+json">` content has different encoding treatment! 

`extract_jsonld_product` — when parsing JSON-LD, it probably reads `script.get_text()` or `.string`. If the HTML was decoded correctly, the JSON-LD text is correct too. Hmm.

Actually wait — maybe the two fields come from DIFFERENT fetches. The AI agent fetches via `_fetch` (requests) first; if no characteristics, fetches via Selenium. The final `data` could be a MIX? No — `_parse_page` produces one dict from one HTML. Actually, look at enrich_with_ai: it tries `_fetch`, then Selenium. The final `data` is either the requests-parsed OR selenium-parsed (whichever had more characteristics). So both title and descripcion come from the same parse.

So for product 82453: `_source: jsonld`, title clean, descripcion mojibake. For a smartGSM page with JSON-LD, both title and descripcion would come from the JSON-LD. But one clean and one not?? 

OH WAIT. I bet the mojibake happens in **`translate`** — GoogleTranslator! The `descripcion` field is translated (descripcion is in the translate fields list). GoogleTranslator receives the text. But translation doesn't create mojibake for text it receives correctly...

Actually, let me reconsider: deep_translator `GoogleTranslator.translate()` — the library POSTs `data` to translate.googleapis.com and parses the response. If the response parsing is wrong... Actually deep_translator handles encoding fine.

Hmm, but here's a thought: **the glossary protection**. `_protect_glossary` replaces terms. If the text is fine, translate returns fine.

Let me look at the ACTUAL data flow once more: `enrich.py` `_fetch_and_prepare` — it calls ai_agent, gets product_data, then translates. The `descripcion` gets translated. So the mojibake could be introduced by GoogleTranslator IF the source text sent to it was fine but the response was mis-decoded. OR — more likely — the source text ALREADY had mojibake and translation passed it through.

But wait, product 20 title mojibake but descripcion clean. `title` is NOT in the translate list (fields = ["titulo", "title", "descripcion", "description", "resumen", "summary"]). Wait, `title` IS in the list! So title gets translated too. Hmm, but product 20's title "caracterÃ\xadsticas" is mojibake while descripcion "Características" is clean.

Actually — here's a strong hypothesis: **GoogleTranslator returns the text with HTML entities encoded** when the input contains certain chars, OR deep_translator encodes input. But the mojibake pattern `Ã\xad` is specifically UTF-8-bytes-decoded-as-latin-1. deep_translator's response handling: `resp.json()['sentences']`. That's JSON, decoded as UTF-8 properly by requests. So no.

Let me look at what `_fetch_and_prepare` does and where translation happens relative to validation. And specifically check: does the AI agent or enrich store the `translated` (post-translation) result? Yes — `proposal_json` stores `translated`. So the corruption is in the translated output.

Let me look at `_fetch_and_prepare` in enrich.py.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "limit": 100,
  "offset": 380
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/enrich.py</path>
<type>file</type>
<content>
380:                 logger.warning(
381:                     "  VALIDATE  id=%d  weak generic match ratio=%.2f words=%d: scraped_title=%r",
382:                     pid, ratio, len(matched_words), scraped_title[:80],
383:                 )
384:                 return False
385: 
386:     # Check 4: la marca enriquecida debe ser coherente con el nombre original.
387:     # Un "Smart TV Samsung" no puede quedar como "Fravega" (retailer).
388:     if not _validate_name_coherence(product_data, nombre, marca, reference=reference_brand):
389:         logger.warning(
390:             "  VALIDATE  id=%d  nombre/marca incoherentes — descartando", pid,
391:         )
392:         return False
393: 
394:     return True
395: 
396: 
397: def _fetch_and_prepare(
398:     pid: int,
399:     ean: str | None,
400:     mpn: str | None,
401:     marca: str,
402:     modelo: str,
403:     nombre: str,
404:     dry_run: bool,
405: ) -> tuple[dict | None, dict | None, str]:
406:     """Fetch product data and prepare translated + scored payload.
407: 
408:     Automated pipeline tries sources in order:
409:     1. Brand site search (official site → first product result → scrape)
410:     2. AI agent (web search + extraction, last resort)
411:     3. Name-only search (infer brand from product name, search brand site)
412:     4. not_found
413: 
414:     Returns ``(product_data, translated, description)`` or
415:     ``(None, None, '')`` on failure.
416:     """
417:     product_data = None
418: 
419:     # ── 0. Brand site search (official site → product page → scrape) ──────
420:     if marca and nombre and not dry_run:
421:         from .official_scraper import _search_brand_site, scrape_from_direct_url
422: 
423:         logger.info("  BRAND_SEARCH  id=%d  buscando en sitio de %s...", pid, marca)
424:         found_url = _search_brand_site(marca, nombre, pid)
425:         if found_url:
426:             logger.info("  BRAND_SEARCH  id=%d  scraping %s", pid, found_url)
427:             pipeline_state.add_log(f"Brand site encontrado, scrapeando: {found_url}")
428:             product_data = scrape_from_direct_url(found_url, pid)
429:             if product_data is not None:
430:                 if not _validate_scraped_data(product_data, marca, nombre, pid):
431:                     logger.warning("  BRAND_SEARCH  id=%d  data rejected — wrong product", pid)
432:                     pipeline_state.add_log("Datos rechazados: no coincide con el producto esperado")
433:                     product_data = None
434:                 else:
435:                     n_chars = len(product_data.get("caracteristicas") or [])
436:                     logger.info("  BRAND_SEARCH  id=%d  succeeded (%d characteristics)", pid, n_chars)
437:                     pipeline_state.add_log(f"Brand site OK: {n_chars} características extraídas")
438: 
439:     # ── 1. AI agent (web search + extraction) ─────────────────────────────
440:     # Try AI agent if: (a) brand site search failed, or (b) brand site returned
441:     # very few characteristics (< 10) — likely a JS-heavy page with limited data.
442:     MIN_CHARS_FOR_SUCCESS = 10
443:     brand_data_low = (
444:         product_data is not None
445:         and len(product_data.get("caracteristicas") or []) < MIN_CHARS_FOR_SUCCESS
446:     )
447:     if (not product_data or brand_data_low) and nombre and not dry_run:
448:         from .ai_agent import enrich_with_ai
449: 
450:         # Use marca if available, otherwise try with just the product name
451:         ai_marca = marca or ""
452:         logger.info("  AI_AGENT  id=%d  trying web search + extraction (marca=%r)", pid, ai_marca)
453:         pipeline_state.add_log("Buscando con AI agent web search...")
454: 
455:         # When marca is empty, AI agent may return data from reseller pages with
456:         # no characteristics — require at least MIN_CHARS_WITHOUT_MARCA.  The
457:         # validator is passed in so enrich_with_ai skips rejected candidates and
458:         # keeps trying the next-ranked search result.
459:         MIN_CHARS_WITHOUT_MARCA = 5
460: 
461:         def _accept_ai(data: dict) -> bool:
462:             if marca:
463:                 return _validate_scraped_data(data, marca, nombre, pid)
464:             return (
465:                 len(data.get("caracteristicas") or []) >= MIN_CHARS_WITHOUT_MARCA
466:                 and _validate_scraped_data(data, "", nombre, pid)
467:             )
468: 
469:         ai_data = enrich_with_ai(ai_marca, nombre, accept=_accept_ai)
470:         if ai_data is not None:
471:             ai_chars = len(ai_data.get("caracteristicas") or [])
472:             logger.info("  AI_AGENT  id=%d  succeeded (%d characteristics)", pid, ai_chars)
473:             pipeline_state.add_log(f"AI agent OK: {ai_chars} características extraídas")
474:             # Keep whichever source has more characteristics
475:             if brand_data_low:
476:                 brand_chars = len((product_data or {}).get("caracteristicas") or [])
477:                 if ai_chars > brand_chars:
478:                     logger.info(
479:                         "  AI_AGENT  id=%d  replacing brand site result (%d > %d chars)",

(Showing lines 380-479 of 841. Use offset=480 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 2.7s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "limit": 120,
  "offset": 480
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/enrich.py</path>
<type>file</type>
<content>
480:                         pid, ai_chars, brand_chars,
481:                     )
482:                     product_data = ai_data
483:                 else:
484:                     logger.info(
485:                         "  AI_AGENT  id=%d  keeping brand site result (%d >= %d chars)",
486:                         pid, brand_chars, ai_chars,
487:                     )
488:             else:
489:                 product_data = ai_data
490: 
491:     # ── 2. Name-only search (no brand/MPN, but has a product name) ─────────
492:     if not product_data and nombre and not dry_run:
493:         from .official_scraper import (
494:             _infer_brand_from_name,
495:             _search_brand_site,
496:             scrape_from_direct_url,
497:         )
498: 
499:         inferred_brand = _infer_brand_from_name(nombre)
500:         if inferred_brand:
501:             logger.info(
502:                 "  NAME_SEARCH  id=%d  inferred brand=%r from name=%r",
503:                 pid, inferred_brand, nombre,
504:             )
505:             found_url = _search_brand_site(inferred_brand, nombre, pid)
506:             if found_url:
507:                 logger.info("  NAME_SEARCH  id=%d  scraping %s", pid, found_url)
508:                 product_data = scrape_from_direct_url(found_url, pid)
509:                 if product_data is not None:
510:                     if not _validate_scraped_data(product_data, inferred_brand, nombre, pid):
511:                         logger.warning("  NAME_SEARCH  id=%d  data rejected — wrong product", pid)
512:                         pipeline_state.add_log("Name search: datos rechazados, no coincide con el producto")
513:                         product_data = None
514:                     else:
515:                         n_chars = len(product_data.get("caracteristicas") or [])
516:                         logger.info(
517:                             "  NAME_SEARCH  id=%d  succeeded (%d characteristics)",
518:                             pid, n_chars,
519:                         )
520: 
521:             # Fallback: AI agent with inferred brand
522:             if not product_data:
523:                 from .ai_agent import enrich_with_ai
524: 
525:                 logger.info(
526:                     "  NAME_SEARCH  id=%d  brand site failed, trying AI agent with inferred brand=%r",
527:                     pid, inferred_brand,
528:                 )
529:                 pipeline_state.add_log("Brand site no encontrado, buscando con AI agent...")
530:                 product_data = enrich_with_ai(
531:                     inferred_brand, nombre,
532:                     accept=lambda data: _validate_scraped_data(
533:                         data, inferred_brand, nombre, pid
534:                     ),
535:                 )
536:                 if product_data is not None:
537:                     n_chars = len(product_data.get("caracteristicas") or [])
538:                     logger.info(
539:                         "  NAME_SEARCH  id=%d  AI agent succeeded (%d characteristics)",
540:                         pid, n_chars,
541:                     )
542:                     pipeline_state.add_log(f"AI agent OK: {n_chars} características extraídas")
543:         else:
544:             logger.debug(
545:                 "  NAME_SEARCH  id=%d  no brand could be inferred from %r",
546:                 pid, nombre,
547:             )
548: 
549:     if product_data is None:
550:         if not (marca or nombre):
551:             pipeline_state.add_log("Sin datos — sin marca ni nombre, marcando not_found")
552:             logger.info("  SKIP  id=%d  (no brand, no name) — marking not found", pid)
553:             if not dry_run:
554:                 mark_not_found(pid)
555:         else:
556:             pipeline_state.add_log("Reintentar después — datos insuficientes")
557:             logger.warning("  RETRY-LATER  id=%d  (brand=%s name=%s)", pid, marca, nombre)
558:         return None, None, ""
559: 
560:     # Backfill marca/modelo from product name if scraper didn't find them
561:     if not product_data.get("marca") or not product_data.get("modelo"):
562:         from .official_scraper import _extract_model_from_name, _infer_brand_from_name
563:         if not product_data.get("marca") and nombre:
564:             inferred = _infer_brand_from_name(nombre)
565:             if inferred:
566:                 product_data["marca"] = inferred.title()
567:         if not product_data.get("modelo") and nombre:
568:             model = _extract_model_from_name(nombre, product_data.get("marca") or "")
569:             if model:
570:                 product_data["modelo"] = model
571: 
572:     translated = translate_product(product_data)
573:     modelo_row = modelo or ""
574:     local_desc = f"{marca} {modelo_row}".strip()
575: 
576:     description = " ".join(
577:         filter(None, [
578:             translated.get("Title") or translated.get("title")
579:             or translated.get("Titulo") or translated.get("titulo"),
580:             translated.get("Summary") or translated.get("summary")
581:             or translated.get("Resumen") or translated.get("resumen"),
582:             translated.get("Description") or translated.get("description")
583:             or translated.get("Descripcion") or translated.get("descripcion"),
584:         ])
585:     )
586: 
587:     similarity = score_match(local_desc, description)
588:     translated["_score"] = round(similarity, 4)
589:     translated["_ean"] = ean or ""
590:     translated["_id_prestashop"] = pid
591: 
592:     return product_data, translated, description
593: 
594: 
595: def run(dry_run: bool = False, override: dict | None = None) -> int:
596:     """Enrich pending products and push to PrestaShop.
597: 
598:     Two entry paths:
599:     - Products with existing data (stuck from previous runs)

(Showing lines 480-599 of 841. Use offset=600 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 13.8s)

_Thinking:_

Now I see the full flow. `translated = translate_product(product_data)` — this translates `title`, `descripcion`, `resumen`, etc. via GoogleTranslator.

So the mojibake in the stored `descripcion` (product 82453: "resoluciÃ³n") is very likely introduced by **GoogleTranslator**. Here's why: deep_translator's GoogleTranslator sends the text and gets back a JSON response. The library's `_translate` method does:

```python
r = requests.post(...)
response = r.json()
```
and returns the text. If requests detects the charset wrong... requests uses `r.json()` which uses `r.text` decoding with `apparent_encoding` fallback → latin-1 default! 

Hmm actually — deep_translator's GoogleTranslator uses a POST to `https://translate.googleapis.com/translate_a/single`? Let me recall the deep_translator implementation. It does:
```python
payload = {...}
r = requests.post(f"{_BASE_URL}...", data=payload, params=params)
response = r.json()
```
`r.json()` calls `json.loads(r.text, encoding=...)`. `r.text` is decoded using `r.encoding` which for the translation API response without charset would default to ISO-8859-1 (requests default). But Google translate responses include `application/json; charset=utf-8`? Actually, requests' `r.json()` — if Content-Type has no charset and content is JSON, `json.loads` on the str... The classic issue: Google returns `charset=utf-8` in the header usually. But there have been reports that deep_translator produces mojibake because of this exact issue.

BUT — the important observation: product 20's `descripcion` is CLEAN ("Características") while its `title` is mojibake. And both `title` and `descripcion` are translated fields. If the source scraped text was clean and GoogleTranslator introduced mojibake on translation, BOTH would be mojibake. But descripcion is clean and title is mojibake!

So that means: the mojibake existed in the SOURCE (scraped) text for `title`, and translation passed it through unchanged (or it wasn't translated). For product 82453: title clean, descripcion mojibake. So the source itself had mojibake in different fields from different DOM locations.

Wait, but the source for 82453 is `_source: jsonld` — smartGSM JSON-LD. If the HTML was correctly decoded UTF-8, then jsonld `description` would be clean too. Unless the mojibake came from translation of the description field.

Hmm, let me reconsider: maybe the source HTML had correct UTF-8, but the text extraction path for some fields produces mojibake. How? If the html string passed to BeautifulSoup was already correctly decoded (unicode), all text is clean. So source is clean. Then mojibake must come AFTER parsing — i.e., in translation.

But then both title and descripcion (both translated) would be mojibake. Contradiction with product 20 (title mojibake, descripcion clean).

Unless... translation is skipped for some field. `translate()` returns `text` unchanged if `_TRANSLATOR_AVAILABLE` is False, or if text is empty. Both fields are non-empty. Hmm.

Wait — maybe the mojibake happened at a DIFFERENT point: when the proposal_json was re-scraped/pushed multiple times, and the mojibake got in from a previously-translated stored value, then re-translation double-corrupted? No — google translate would receive mojibake and might return... unchanged or re-corrupted.

Let me actually TEST deep_translator with a mojibake input to see behavior. And test with clean input. Actually, let me test whether GoogleTranslator introduces mojibake on clean UTF-8 input with accents.

Hago una prueba empírica del traductor para ver si introduce el mojibake:

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python - <<'EOF'\ntry:\n    from deep_translator import GoogleTranslator\n    tr = GoogleTranslator(source=\"auto\", target=\"es\")\n    for txt in [\n        \"Características y especificaciones\",\n        \"El Motorola Moto G82 es un smartphone con resolución Full HD\",\n        \"Screen resolution: Full HD+\",\n    ]:\n        out = tr.translate(txt)\n        print(repr(txt), \"->\", repr(out))\nexcept Exception as e:\n    print(\"ERR\", type(e).__name__, e)\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
'Características y especificaciones' -> 'Características y especificaciones'
'El Motorola Moto G82 es un smartphone con resolución Full HD' -> 'El Motorola Moto G82 es un smartphone con resolución Full HD'
'Screen resolution: Full HD+' -> 'Resolución de pantalla: Full HD+'

```

---

## Assistant (Build · Big Pickle · 5.4s)

_Thinking:_

GoogleTranslator works fine with clean UTF-8 input. So the mojibake is NOT from translation. It must be from the SOURCE (scraped) text.

So how can one field from a smartGSM JSON-LD be clean and another be mojibake? Let me look at `extract_jsonld_product` in spec_extractors.py — how it extracts title, description from JSON-LD.

Wait — actually, maybe the corruption comes from the translate.py `_protect_glossary`/`_restore_glossary`? No.

Let me reconsider. Actually maybe the source HTML ITSELF contained mojibake in some places. smartGSM pages might have inconsistent encoding: some parts in `<script type="application/ld+json">` escaped, OG meta escaped... Actually! HTML can contain the SAME UTF-8 content encoded differently. E.g., the JSON-LD might use `&#xed;` entities while the `<meta property="og:title">` has literal `í`. When BeautifulSoup parses, both decode to `í`. So that's not it either.

Hold on — what about **double-decoding at extraction**: if the JSON-LD string in the script tag has `&aacute;`-style or `\u00ed` escapes, and the code does `json.loads` then `html.unescape` again... that produces over-decoding (rare).

Let me look at `extract_jsonld_product` to see how title and description are read.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py",
  "limit": 75,
  "offset": 365
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py</path>
<type>file</type>
<content>
365:     - ``additionalProperty`` (PropertyValue array)
366:     - Top-level Product properties: weight, depth, width, height
367:     - ``QuantitativeValue`` objects with value + unitText
368:     """
369:     for script in soup.find_all("script", type="application/ld+json"):
370:         raw = script.string
371:         if not raw:
372:             continue
373:         try:
374:             parsed = json.loads(raw)
375:         except json.JSONDecodeError:
376:             continue
377:         items = parsed if isinstance(parsed, list) else [parsed]
378:         for item in items:
379:             if item.get("@type") not in ("Product", "product"):
380:                 continue
381:             name = item.get("name", "")
382:             desc = item.get("description", "")
383: 
384:             # Images
385:             img = ""
386:             imgs: list[str] = []
387:             raw_img = item.get("image")
388:             if isinstance(raw_img, list):
389:                 for img_item in raw_img:
390:                     if isinstance(img_item, dict):
391:                         url = img_item.get("url", "")
392:                     elif isinstance(img_item, str):
393:                         url = img_item
394:                     else:
395:                         continue
396:                     if url:
397:                         imgs.append(url)
398:                         if not img:
399:                             img = url
400:             elif isinstance(raw_img, dict):
401:                 img = raw_img.get("url", "")
402:                 if img:
403:                     imgs.append(img)
404:             elif isinstance(raw_img, str):
405:                 img = raw_img
406:                 if img:
407:                     imgs.append(img)
408: 
409:             # Brand
410:             brand = ""
411:             raw_brand = item.get("brand")
412:             if isinstance(raw_brand, dict):
413:                 brand = raw_brand.get("name", "")
414:             elif isinstance(raw_brand, str):
415:                 brand = raw_brand
416: 
417:             modelo = item.get("mpn") or item.get("sku") or ""
418: 
419:             # Characteristics from additionalProperty
420:             features: list[dict[str, str]] = []
421:             for prop in item.get("additionalProperty") or []:
422:                 n, v = clean_feature((prop.get("name") or "").strip(), (prop.get("value") or "").strip())
423:                 if n and v:
424:                     features.append({"nombre": n, "valor": v})
425: 
426:             # Top-level QuantitativeValue properties
427:             _QUANT_PROPS = ("weight", "depth", "width", "height")
428:             for prop in _QUANT_PROPS:
429:                 val = item.get(prop)
430:                 if not val or prop in {f["nombre"].lower() for f in features}:
431:                     continue
432:                 if isinstance(val, dict):
433:                     value = str(val.get("value", ""))
434:                     unit = val.get("unitText", "")
435:                     if value:
436:                         features.append({
437:                             "nombre": prop.title(),
438:                             "valor": f"{value} {unit}".strip(),
439:                         })

(Showing lines 365-439 of 836. Use offset=440 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 8.0s)

_Thinking:_

JSON-LD extraction reads `script.string` and `json.loads`. The HTML must be correctly decoded. `script.string` returns the raw text content of the script tag. If the HTML was decoded as UTF-8 correctly, this is correct. So JSON-LD fields are clean if the fetch was clean.

BUT — here's the crucial insight I keep missing. Let me re-examine: for product 82453, title is CLEAN and descripcion is MOJIBAKE. Both from JSON-LD of the same page (smartGSM). If the HTML string passed to BeautifulSoup was clean UTF-8, then json.loads gives clean strings for BOTH. So the mojibake in descripcion must have been introduced AFTER parsing — by translation.

And for product 20, title is mojibake and descripcion is clean — also both translated. 

Hmm, these two observations are contradictory under a single hypothesis. Unless... the mojibake was introduced during STORAGE or a round trip, not consistently.

Wait, actually — maybe the descriptions got translated at a different time than the title. E.g., a product was scraped, stored, then re-processed: Path A reuses stored data (`parsed`) and sets `translated = parsed` (no re-translation). Then when pushing, no translation. So the stored values persist.

The inconsistency (title mojibake, descripcion clean in the same product) suggests the corruption happened at SCRAPE time from DIFFERENT sources for each product — i.e., product 20's title came from a mojibake path while its descripcion came from a clean path. But both come from `_parse_page` of ONE page...

UNLESS — the AI agent merged `og_meta` result (product 20 `_source: og_meta`). In `_parse_page`, if JSON-LD fails, it builds result from OG meta. Product 20 `_source: og_meta` — so its title came from `og:title` meta, descripcion from `og:description`. Both from meta tags. Both from the same page.

OK here's another thought: **the OG meta extraction** — `extract_og_product_meta`. If the page's `<meta property="og:title" content="...">` contains `&#237;`-style entity or is a literal latin-1 byte sequence... The `content` attribute value in HTML: BeautifulSoup decodes entities in attribute values during parsing. So `content="...caracter&#237;sticas..."` → BeautifulSoup gives `...características...`. Clean.

I'm going in circles. Let me look at where the AI agent page fetch actually happens and whether the mojibake could come from `_fetch_with_selenium`. Actually — wait. Let me check `_fetch_with_selenium` at the top of ai_agent.py (lines 40-90) — specifically whether it returns the page with correct encoding. Let me read it.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py",
  "limit": 80,
  "offset": 1
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py</path>
<type>file</type>
<content>
1: """AI agent for official product data extraction (last resort).
2: 
3: Uses DuckDuckGo search (free) to find official product pages, fetches
4: the HTML, and extracts structured data using JSON-LD, OG meta tags,
5: and HTML table parsing.
6: 
7: This is the last resort in the enrichment cascade, tried only after
8: brand site search fails.
9: """
10: 
11: import logging
12: import re
13: import time
14: 
15: import requests
16: from bs4 import BeautifulSoup
17: from selenium import webdriver
18: from selenium.webdriver.chrome.options import Options as ChromeOptions
19: from selenium.webdriver.common.by import By
20: from selenium.webdriver.support import expected_conditions as EC
21: from selenium.webdriver.support.ui import WebDriverWait
22: 
23: from . import spec_extractors
24: from .config import API_SLEEP
25: 
26: SELENIUM_TIMEOUT = 12
27: 
28: logger = logging.getLogger(__name__)
29: 
30: _SESSION = requests.Session()
31: _SESSION.headers.update({
32:     "User-Agent": (
33:         "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
34:         "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
35:     ),
36:     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
37:     "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
38: })
39: 
40: 
41: def _create_driver() -> webdriver.Chrome:
42:     """Return a headless Chrome WebDriver configured for scraping."""
43:     opts = ChromeOptions()
44:     opts.add_argument("--headless=new")
45:     opts.add_argument("--no-sandbox")
46:     opts.add_argument("--disable-dev-shm-usage")
47:     opts.add_argument("--disable-gpu")
48:     opts.add_argument("--window-size=1920,1080")
49:     opts.add_argument(
50:         "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
51:         "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
52:     )
53:     return webdriver.Chrome(options=opts)
54: 
55: 
56: def _fetch_with_selenium(url: str) -> str | None:
57:     """Fetch a URL using headless Chrome for JS-heavy pages."""
58:     driver = None
59:     try:
60:         driver = _create_driver()
61:         driver.set_script_timeout(SELENIUM_TIMEOUT)
62:         driver.get(url)
63:         # Wait for some content to render
64:         try:
65:             WebDriverWait(driver, SELENIUM_TIMEOUT).until(
66:                 EC.presence_of_element_located(
67:                     (By.CSS_SELECTOR,
68:                      "table, .specs, .specifications, .tech-specs, "
69:                      ".pdd32-product-spec__content-item, "
70:                      "[class*='spec'], [class*='Spec'], "
71:                      "[data-testid*='spec'], [id*='spec'], "
72:                      "article, main, [role='main']")
73:                 )
74:             )
75:         except Exception:
76:             pass
77:         try:
78:             html = driver.execute_script(
79:                 "return document.documentElement.outerHTML"
80:             )

(Showing lines 1-80 of 608. Use offset=81 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 32.4s)

_Thinking:_

Selenium `page_source`/`outerHTML` returns a properly decoded str. So Selenium paths are clean.

OK. I've spent enough effort chasing the exact source per-product. Let me take stock of what's certain from the DB:

**Corruption patterns found in stored proposal data:**
1. Mojibake (`Ã\xad`, `Ã³`, `Ã\xadsticas`) — UTF-8 read as latin-1. Occurred in title (product 20, og_meta) and descripcion (product 82453, jsonld). Since translation is clean and Selenium is clean, the most likely culprit is `requests` with a latin-1 fallback... but `_fetch` uses decode_response which is robust. BUT — the **`_search_web` (ddgs) results**! The DDGS title could be mojibake. And product 20's `_source: og_meta` — the title comes from the page, not DDG. Hmm.

Actually wait — I should check whether there's a path where `resp.text` is used WITHOUT decode_response. I grep'd earlier and only saw decode_response used in middleware. But let me check `ddgs` — the library internally decodes with latin-1 default sometimes. And actually — where does product 20's og:title come from? `extract_og_product_meta` reads `<meta property="og:title">`. If that page's og:title was fine, the result would be fine...

Hmm wait, maybe I'm over-thinking the source. Let me look at this from the DUCKDBGGS angle: `_search_web` returns results whose titles might be mojibake. Where are result titles used? In `enrich_with_ai` — `title = r.get("title", "")` only for logging. Not stored. So no.

Let me actually check: maybe the mojibake got introduced by **`_validate_scraped_data` / model token matching**? No, validation doesn't modify data.

Let me try another approach — look at the git diff of the recent commits to see if there's a regression in encoding handling. The last few commits: 424b710, c62b2df, 744700b, b9c9b5c. Let me see what changed in the most recent commits related to ai_agent/spec_extractors/decode_response.

Actually, hold on. Let me reconsider the OG meta extractor. Let me look at `extract_og_product_meta` and how title is read. If the page's og:title content is literally the mojibake string in the HTML source (i.e., the site itself serves mojibake) — that's possible! Some sites genuinely serve latin-1-decoded text in their meta tags even when charset is UTF-8. E.g., smartGSM — a quick web check: smartgsm pages — if their og:title is mojibake, our tool just faithfully stores the mojibake.

Actually you know what — this is exactly why a normalization/repair layer is the right fix, REGARDLESS of exact source. The data entering the system from arbitrary third-party sites WILL sometimes be mojibake or entity-encoded, and the middleware must normalize it before storing/publishing. The DB evidence proves it happens.

So my plan:
1. Add `normalize_text()` in `spec_extractors.py` (where `decode_response` lives — encoding concerns are there) that:
   - `html.unescape()` for entities
   - repairs UTF-8-as-latin-1 mojibake
2. Apply it to scraped results at the boundaries:
   - `ai_agent._parse_page` — normalize all string values of the result (title, descripcion, resumen, marca, modelo, caracteristicas nombre/valor).
   - `official_scraper` — wherever a result dict is assembled before returning/persisting. There are multiple assembly points (scrape_from_direct_url, PDF datasheet, etc.). The simplest choke point: normalize in `_persist_scrape_result` (persist path) AND in `scrape_from_direct_url`'s return.
   - `enrich._push_to_prestashop` — normalize desc + description_short + merged characteristics values before pushing (covers re-push of already-stored corrupt data).
   - `admin_ui.app.py approve` — normalize desc/description_short (covers approval of already-corrupt stored data).
   - Also `_build_description`.

Actually, a cleaner and comprehensive approach: normalize when building the description and when storing proposal_json. But proposal_json normalization requires recursing the dict.

Let me define the normalization precisely and carefully:

```python
import html as _html

def normalize_text(value: str) -> str:
    """Fix font/encoding corruption from third-party sources.

    - HTML entities -> real characters (``&#225;`` -> ``á``, ``&quot;`` -> ``"``)
    - Mojibake: UTF-8 bytes decoded as latin-1 (``Ã³`` -> ``ó``, ``Ã±`` -> ``ñ``)

    Returns the fixed string (unchanged if nothing to fix).
    """
    if not value:
        return value
    value = _html.unescape(value)
    try:
        fixed = value.encode("latin-1").decode("utf-8")
        return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
```

Wait — there's a subtle problem with the mojibake repair when the string contains real `\xa0` (nbsp) mixed with mojibake. `&nbsp;` unescapes to `\xa0`. `\xa0` encodes to latin-1 byte 0xA0 which is invalid as a UTF-8 start byte → decode fails → whole string unchanged → mojibake NOT repaired. Hmm. That's a limitation. 

Better targeted repair: replace known mojibake byte-sequences. But a simpler robust approach: repair per-character-sequence. Actually, the standard robust approach that handles mixed content: encode latin-1, then decode utf-8 with errors that... no.

Let me think about what content mixes nbsp and mojibake. Example product 82436: `&amp;nbsp;` in description. After unescape → `&nbsp;`? No: `&amp;nbsp;` unescapes to `&nbsp;` (a literal string "&nbsp;"). Then it's not decoded further to \xa0. So after ONE unescape pass, we have literal `&nbsp;` text (7 chars). That's still a "code" visible to the user! `&amp;nbsp;` is double-escaped `&nbsp;`.

So I need **double unescape** to handle double-escaped entities: `&amp;nbsp;` → `&nbsp;` → `\xa0`. But double-unescaping blindly is risky (e.g., a legit `&amp;` in text "AT&amp;T" → first pass "AT&T", second pass "AT&T" no further entity → fine; but "Tom &amp;amp; Jerry" → "Tom &amp; Jerry" → "Tom & Jerry" — hmm that would be over-decoding something that was intentionally literal). 

For a product catalog, over-decoding is acceptable and safer than showing codes. But let me be careful with entities that are meaningful: after unescape, `&lt;` becomes `<`. If we unescape again, `<` has no entity. Fine. What about a description that legitimately wants to display `&amp;`? Edge case, ignore.

However, double-unescape could turn legit `&not;`? Only if double-escaped in source. I'll do up to 2 passes to collapse double-escaping (`&amp;` → `&`).

Actually wait — for the mojibake repair + nbsp: after unescaping `&nbsp;` to `\xa0`, if the string ALSO has mojibake `Ã³`, then `value.encode("latin-1")` succeeds (both `\xa0`=0xA0 and `Ã³`=0xC3B3 are latin-1), producing bytes: `A0 C3 B3` — then `.decode("utf-8")` fails at 0xA0. So mojibake stays unrepaired in that string. 

To handle this, do a **per-chunk repair**: repair only known mojibake sequences. Actually, the cleanest robust approach: try full repair; if it fails, fall back to replacing common mojibake pairs:

```python
_MOJIBAKE_FIXES = { "Ã¡": "á", "Ã©": "é", "Ã­": "í", "Ã³": "ó", "Ãº": "ú", "Ã±": "ñ", "Ã¤": "ä", ...}
```

But that's a big table. Alternative: repair by scanning. Actually the "encode latin-1 → decode utf-8" fails only when there's a lone high byte (like 0xA0, 0xE9, 0xE1) that isn't part of a valid UTF-8 sequence. In a mixed string with mojibake + real accents (real `é`=0xE9 in unicode → latin-1 byte 0xE9 → invalid utf-8) — wait, can a string have BOTH real accents AND mojibake? Real `é` in unicode would come from a correctly-decoded source; mojibake `Ã©` from a mis-decoded source. If a page is partially mojibake, the mojibake bytes represent the ORIGINAL utf-8, so "é" would appear as `Ã©` not as `é`. So within one text, either the whole thing is mojibake (all non-ascii chars are `ÃX`/`ÂX`/`Â` + control) or it's clean. Mixed real-accent + mojibake is rare. And nbsp (`\xa0`) IS common in clean text. So the failure mode: clean text with `\xa0` → latin-1 encode succeeds, decode fails at 0xA0 → unchanged. 

Actually that's exactly what we want for clean text! Clean text with `\xa0`: encode succeeds, decode fails → return original. Mojibake text: encode succeeds, decode succeeds → fixed. Text with `\xa0` AND mojibake → fails → unchanged (rare, acceptable).

But there's a REAL risk case: clean text that happens to encode to valid UTF-8 after latin-1 round trip. Clean text contains chars like `é` (0xE9) → decode fails → safe. ASCII → decode succeeds but is identity (same string) → safe. `\xa0` alone → fails → safe. So the only "dangerous" case: a clean text where ALL non-ascii chars are in the set that latin-1-encodes to valid UTF-8 multi-byte sequences — that requires chars 0xC2-0xDF (valid UTF-8 2-byte starts with continuation 0x80-0xBF)... a clean text with `Â` (0xC2) followed by a char 0x80-0xBF? `Â` is U+00C2 (Â circumflex), very rare in product text. So safe in practice.

OK so single-pass `normalize_text` with html.unescape + latin1→utf8 repair is good. For double-escaped entities, unescape once handles `&amp;`→`&` (e.g. `&amp;nbsp;`→`&nbsp;`). Do I need a second unescape? After first unescape, `&nbsp;` literal remains. If the user sees `&nbsp;` as a code... yes they would. So run unescape twice? Let me run it in a small loop until stable (max 2 iterations) — actually let me do a loop that keeps unescaping while the string contains entity-like patterns, up to 3 iterations, but stop if it doesn't change.

Hmm, but infinite unescape risk: `&amp;lt;` → `&lt;` → `<` (3 passes). `&amp;amp;` → `&amp;` → `&`. Converges. But there's the classic trick: `&amp;lt;` unescape 3 times gives `<` but entities like `&lt;` `&gt;` are meaningful... For product content, `<`/`>` from unescaping tags is fine (it becomes actual `<` in description which might get rendered as HTML!). Careful: if a description value contains `&lt;p&gt;` (escaped HTML that the site intended to show as literal), unescaping makes it REAL HTML. For a "descripcion" field that's going to be pushed as HTML, that's actually the desired behavior (the site had it entity-encoded, we restore). OK.

I'll limit to 2 unescape passes to avoid pathological cases, plus it handles double-escaped entities.

Now — where to apply. Let me define a function `normalize_scraped_product(data: dict) -> dict` that recursively normalizes strings, and apply it:

1. `ai_agent._parse_page` — at the end, normalize the whole result.
2. `official_scraper.scrape_from_direct_url` and its helpers — normalize at the return points / in `_persist_scrape_result`.
3. `enrich.py` — when pushing stored data (Path A) AND in `_push_to_prestashop`, normalize desc + chars before push. Also normalize the proposal before storing (Path B).
4. `admin_ui/app.py` — approve path: normalize desc/description_short.
5. `check_active.py` — same push path.

Actually, the MOST robust single-choke-point that covers ALL push paths AND stored-data re-push: normalize inside `_build_description` (enrich.py) and inside the approve route's description building + `get_description` output? The description_short comes from Excel — openpyxl returns proper unicode, but could contain nbsp/entities. Normalize it too.

And for the proposal_json stored data: normalize at STORE time so the diff UI shows clean text and re-pushes are clean. Store points: enrich.py (two UPDATE statements), check_active.py (one UPDATE), official_scraper._persist_scrape_result (one UPDATE).

Let me implement:

**In spec_extractors.py** add:
```python
def normalize_text(value: str) -> str:
def normalize_product_data(data) -> dict:
```

Actually, I realize I should keep it focused and minimal but complete. Let me:

1. Add `normalize_text` + `normalize_product` to spec_extractors.py.
2. Apply `normalize_product` to `ai_agent._parse_page` result (single choke point for AI agent).
3. Apply in `official_scraper` — find the main assembly points. There's `scrape_from_direct_url` which calls `_scrape_page_content`? Let me check where results are built in official_scraper. The simplest: normalize inside `_persist_scrape_result` AND at the end of `scrape_from_direct_url`. Actually `scrape_from_direct_url` returns the result and also persists. If I normalize in `_persist_scrape_result`, the stored data is clean, but the returned dict (used immediately for push) is not. Better to normalize the result dict itself at the point where it's about to be persisted/returned. Let me find the main return in scrape_from_direct_url.

Also there's brand-site search (`_search_brand_site` returns URL, not data) and PDF scrapers. `_scrape_pdf_datasheet` builds data. These all feed back into `scrape_from_direct_url` or `_persist_scrape_result`. Let me check the structure of official_scraper scrape_from_direct_url.

Let me look at official_scraper around the scrape flow and find where the final result dict is built (lines ~1780-2070).

El traductor es inocente — el mojibake viene de las fuentes terceras. Necesito una capa de normalización. Reviso cómo arma el resultado `official_scraper`:

**Tool: grep**

**Input:**
```json
{
  "include": "official_scraper.py",
  "path": "/home/icrocetti/dev/ProyectoDC/middleware",
  "pattern": "def scrape_from_direct_url|return result|result = \\{|_persist_scrape_result|def _scrape_pdf_datasheet|def _extract_inline|def _fetch_page"
}
```

**Output:**
```
Found 19 matches
/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py:
  Line 244: def _fetch_page(page_url: str) -> tuple["BeautifulSoup | None", list[dict[str, str]]]:

  Line 272: def _fetch_page_pdf_links(page_url: str) -> list[dict[str, str]]:

  Line 294: def _extract_inline_specs_from_soup(soup: "BeautifulSoup | None", pdf_url: str) -> list[dict[str, str]]:

  Line 810:     return result

  Line 1189:                 return result_images

  Line 1197:                 return result_images

  Line 1229:                 return result_images

  Line 1243:                 return result_images

  Line 1255:                 return result_images

  Line 1257:     return result_images

  Line 1686: def scrape_from_direct_url(url: str, product_id: int) -> dict | None:

  Line 1836:             result = {

  Line 2060:     _persist_scrape_result(product_id, result, source="manual_url", url=url)

  Line 2069:     return result

  Line 2072: def _persist_scrape_result(product_id: int, result: dict, source: str, url: str) -> None:

  Line 2124: def _scrape_pdf_datasheet(pdf_url: str, product_id: int) -> dict | None:

  Line 2166:     result = {

  Line 2220:     _persist_scrape_result(

  Line 2231:     return result

```

---

## Assistant (Build · Big Pickle · 3.3s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "limit": 80,
  "offset": 1686
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py</path>
<type>file</type>
<content>
1686: def scrape_from_direct_url(url: str, product_id: int) -> dict | None:
1687:     """Fetch a verified official URL, parse it, and persist to EAV tables.
1688: 
1689:     Uses a headless Chrome WebDriver to render JavaScript-heavy pages
1690:     (Samsung, LG, etc.) before parsing the static HTML with BeautifulSoup.
1691: 
1692:     Parameters
1693:     ----------
1694:     url:
1695:         Human-verified official manufacturer product page URL.
1696:     product_id:
1697:         PrestaShop product ID (``id_prestashop``).
1698: 
1699:     Returns
1700:     -------
1701:     dict | None
1702:         Normalized product data dict on success,
1703:         ``None`` if the fetch or parse fails.
1704: 
1705:     Side effects
1706:     -------------
1707:     - Writes characteristics into ``producto_caracteristicas`` (EAV).
1708:     - Updates ``productos.proposal_json``, ``productos.marca``,
1709:       ``productos.modelo``, ``productos.imagen_url``.
1710:     - Appends an audit log entry.
1711:     """
1712:     logger.info("  MANUAL_URL  id=%d  fetching %s", product_id, url)
1713: 
1714:     # Spec-sheet PDFs (gfast & co.): download + extract directly, no Selenium.
1715:     if (url or "").lower().split("?")[0].rstrip("/").endswith(".pdf"):
1716:         return _scrape_pdf_datasheet(url, product_id)
1717: 
1718:     driver = None
1719:     try:
1720:         driver = _create_driver()
1721:         driver.set_script_timeout(SELENIUM_TIMEOUT)
1722:         driver.get(url)
1723: 
1724:         # Wait for technical spec tables or common spec containers to render.
1725:         # Many brand sites inject specs via JS; wait up to SELENIUM_TIMEOUT.
1726:         # Samsung uses .pdd32-product-spec__content-item for spec data.
1727:         try:
1728:             WebDriverWait(driver, SELENIUM_TIMEOUT).until(
1729:                 EC.presence_of_element_located(
1730:                     (By.CSS_SELECTOR,
1731:                      "table, .specs, .specifications, .tech-specs, "
1732:                      ".pdd32-product-spec__content-item, "
1733:                      "[class*='spec'], [class*='Spec'], "
1734:                      "[data-testid*='spec'], [id*='spec']")
1735:                 )
1736:             )
1737:         except Exception:
1738:             logger.debug(
1739:                 "  MANUAL_URL  id=%d  no spec containers found within %ds, "
1740:                 "proceeding with whatever rendered",
1741:                 product_id, SELENIUM_TIMEOUT,
1742:             )
1743: 
1744:         # Hydrate: progressive scroll + expand accordions + settle
1745:         # Increase script timeout for async scroll JS on heavy pages
1746:         # Non-fatal: specs are usually rendered at page load already; the
1747:         # smooth-scroll can exceed the timeout on heavy pages (Samsung 4MB+),
1748:         # but a partial DOM is still usable.
1749:         driver.set_script_timeout(60)
1750:         try:
1751:             force_full_page_load(driver)
1752:         except Exception as exc:
1753:             logger.warning(
1754:                 "  MANUAL_URL  id=%d  force_full_page_load failed (%s), "
1755:                 "proceeding with partial DOM",
1756:                 product_id, exc,
1757:             )
1758:         driver.set_script_timeout(SELENIUM_TIMEOUT)
1759:         logger.debug(
1760:             "  MANUAL_URL  id=%d  force_full_page_load done", product_id
1761:         )
1762: 
1763:         # Use JS execution instead of driver.page_source — Samsung's
1764:         # heavy pages often cause the /source endpoint to time out.
1765:         try:

(Showing lines 1686-1765 of 2234. Use offset=1766 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.2s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "limit": 100,
  "offset": 1766
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py</path>
<type>file</type>
<content>
1766:             page_source = driver.execute_script(
1767:                 "return document.documentElement.outerHTML"
1768:             )
1769:         except Exception:
1770:             page_source = driver.page_source
1771: 
1772:         # Get the final URL after redirects (important for category detection)
1773:         final_url = driver.current_url
1774:         time.sleep(API_SLEEP)
1775:     except Exception as exc:
1776:         logger.warning("  MANUAL_URL  id=%d  selenium fetch failed: %s", product_id, exc)
1777:         return None
1778:     finally:
1779:         if driver is not None:
1780:             driver.quit()
1781: 
1782:     soup = BeautifulSoup(page_source, "lxml")
1783: 
1784:     # 0. Category page detection — if we landed on a listing/category page,
1785:     #    try to find and follow the first product link.
1786:     #    Use final_url (after redirects) instead of the original url.
1787:     if _is_category_page(soup, final_url):
1788:         product_url = _find_product_link_on_category(soup, final_url)
1789:         if product_url and product_url != url:
1790:             logger.info(
1791:                 "  MANUAL_URL  id=%d  landed on category page, following product link: %s",
1792:                 product_id, product_url,
1793:             )
1794:             driver = None
1795:             try:
1796:                 driver = _create_driver()
1797:                 driver.set_script_timeout(SELENIUM_TIMEOUT)
1798:                 driver.get(product_url)
1799:                 try:
1800:                     WebDriverWait(driver, SELENIUM_TIMEOUT).until(
1801:                         EC.presence_of_element_located(
1802:                             (By.CSS_SELECTOR,
1803:                              "table, .specs, .specifications, .tech-specs, "
1804:                              ".pdd32-product-spec__content-item, "
1805:                              "[class*='spec'], [class*='Spec'], "
1806:                              "[data-testid*='spec'], [id*='spec']")
1807:                         )
1808:                     )
1809:                 except Exception:
1810:                     pass
1811:                 driver.set_script_timeout(60)
1812:                 force_full_page_load(driver)
1813:                 driver.set_script_timeout(SELENIUM_TIMEOUT)
1814:                 try:
1815:                     page_source = driver.execute_script(
1816:                         "return document.documentElement.outerHTML"
1817:                     )
1818:                 except Exception:
1819:                     page_source = driver.page_source
1820:                 time.sleep(API_SLEEP)
1821:                 url = product_url  # Update URL for logging
1822:             except Exception as exc:
1823:                 logger.warning("  MANUAL_URL  id=%d  follow-up fetch failed: %s", product_id, exc)
1824:             finally:
1825:                 if driver is not None:
1826:                     driver.quit()
1827:             soup = BeautifulSoup(page_source, "lxml")
1828: 
1829:     # 1. Try enhanced JSON-LD (most structured, includes QuantitativeValue)
1830:     result = spec_extractors.extract_jsonld_product(soup)
1831: 
1832:     # 2. Fallback to OG / meta tags (enhanced with product: tags)
1833:     if not result:
1834:         og_data = spec_extractors.extract_og_product_meta(soup)
1835:         if og_data.get("title"):
1836:             result = {
1837:                 "title": og_data.get("title", ""),
1838:                 "descripcion": og_data.get("desc", ""),
1839:                 "descripcion_corta": "",
1840:                 "marca": og_data.get("brand", ""),
1841:                 "modelo": og_data.get("retailer_id", ""),
1842:                 "resumen": "",
1843:                 "caracteristicas": [],
1844:                 "imagen_url": og_data.get("img", ""),
1845:                 "imagen_urls": [og_data["img"]] if og_data.get("img") else [],
1846:                 "_source": "og_meta",
1847:             }
1848: 
1849:     if not result:
1850:         logger.warning("  MANUAL_URL  id=%d  no product data found at %s", product_id, url)
1851:         return None
1852: 
1853:     # 2b. Backfill marca/modelo from DB product name when scraper didn't find them
1854:     if not result.get("marca") or not result.get("modelo"):
1855:         try:
1856:             _conn = get_connection()
1857:             try:
1858:                 _row = _conn.execute(
1859:                     "SELECT nombre, marca FROM productos WHERE id_prestashop = ?",
1860:                     (product_id,),
1861:                 ).fetchone()
1862:             finally:
1863:                 _conn.close()
1864:             if _row:
1865:                 db_nombre = _row["nombre"] or ""

(Showing lines 1766-1865 of 2234. Use offset=1866 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 14.2s)

_Thinking:_

I have a good picture. The cleanest choke points for normalization:

1. **`spec_extractors.py`**: add `normalize_text()` and `normalize_product()`.
2. **`ai_agent._parse_page`**: normalize the returned dict at the end.
3. **`official_scraper`**: normalize in `scrape_from_direct_url` right before returning (line 2069) — this covers manual URL + brand site search + PDF datasheet (since `_scrape_pdf_datasheet` is called through it). Also normalize in `_scrape_pdf_datasheet`'s return (line 2231) — but that goes through scrape_from_direct_url's return, and its own persist. Let me normalize in `_persist_scrape_result` too (to be safe) — actually simplest: normalize at the top of `_persist_scrape_result` (so stored data is always clean) AND at the return of `scrape_from_direct_url`.

Actually the simplest and MOST complete: normalize inside `_persist_scrape_result` (covers stored data) — but the returned dict to enrich.py would still be dirty for the immediate push. Let me normalize the dict itself:
- In `scrape_from_direct_url` before `_persist_scrape_result`: `result = spec_extractors.normalize_product(result)`.
- In `_scrape_pdf_datasheet` before persist: same.

4. **`enrich.py`**:
   - Path A (stored reuse): normalize `parsed` before pushing. Actually, better to normalize when reading stored data in run(): `parsed = normalize_product(parsed)`.
   - Path B: normalize before storing — actually `translated` comes from ai_agent/official_scraper which are now normalized. But translate might re-introduce? No. Still normalize at store time as a guard.
   - `_push_to_prestashop`: normalize `merged_caracteristicas` and `desc` before push (guard for already-corrupt stored data).
   - `_build_description`: normalize chars before building.

5. **`admin_ui/app.py` approve**: normalize desc and description_short before pushing.

6. **`check_active.py`**: uses same `_build_description` from enrich (imported) and get_description — normalize at push (the `updates` dict building). Since check_active calls `_fetch_and_prepare` (which now normalizes) and reuses stored proposal — I'll normalize the proposal when read in check_active too.

Actually — let me reconsider scope. The most important: the description/characteristics that get PUSHED to PrestaShop. That's `_push_to_prestashop` and `app.py approve` and `check_active` updates. Plus stored proposal JSON (for re-push + display). 

Let me keep it clean:
- Add `normalize_text` and `normalize_product` to `spec_extractors.py`.
- In `ai_agent._parse_page`: normalize result before return.
- In `official_scraper`: normalize in `scrape_from_direct_url` (before persist) and in `_scrape_pdf_datasheet` (before persist). Also `_persist_scrape_result` normalize as belt-and-suspenders.
- In `enrich.py`: 
  - In `run()` Path A: normalize `parsed` when reusing.
  - In `_push_to_prestashop`: normalize merged chars + desc + description_short.
- In `admin_ui/app.py` approve: normalize desc + description_short.
- In `check_active.py`: normalize proposal when read + the description_short.

Let me also check `_build_description` — it's used by check_active and enrich. Normalize there.

Now, one important consideration about `normalize_text` and the mojibake repair when applied to the `descripcion` which is HTML. The HTML `<p><strong>...` is ASCII + accents. Real accents like `á` (0xE1) → latin-1 encode → 0xE1 → invalid UTF-8 → unchanged. Good. Mojibake inside the HTML → repaired. Good.

But wait — there's a subtlety with mojibake repair on HTML: `value.encode("latin-1").decode("utf-8")` on the WHOLE string. If the string is mostly ASCII + a few mojibake chars, the latin-1 bytes = original UTF-8 bytes → valid UTF-8 → decode → fixed. Yes.

Now let me also handle the `\xa0` (nbsp) — after unescape, `&nbsp;` → `\xa0`. When pushing to PrestaShop, `\xa0` is fine (it's a unicode nbsp). PrestaShop stores UTF-8. It renders as a space-ish char. OK. But to be safe, converting `\xa0` to a regular space in descriptions is nicer. Hmm, but `&nbsp;` in HTML descriptions is semantically meaningful (non-breaking). I'll leave it.

Now about double-unescape: `&amp;nbsp;` → unescape → `&nbsp;` (literal). If I only unescape once, the user still sees `&nbsp;`. Should I unescape twice? Let me write unescape in a loop (max 3 iterations, stop when unchanged):

```python
for _ in range(3):
    new = _html.unescape(value)
    if new == value:
        break
    value = new
```

Risk: `&lt;` → `<` → not re-unescaped. `&amp;` → `&`. Converges. Good.

But careful about mojibake repair order: unescape FIRST (entities→chars), THEN latin1→utf8 repair. Order matters: `&#195;&#179;` (ó as two numeric entities) → unescape → `Ã³` → repair → `ó`. 

Now, `normalize_product`:
```python
def normalize_product(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    for key, val in list(data.items()):
        if isinstance(val, str):
            data[key] = normalize_text(val)
        elif isinstance(val, list):
            data[key] = [normalize_product(item) if isinstance(item, dict) else (normalize_text(item) if isinstance(item, str) else item) for item in val]
    return data
```

This normalizes caracteristicas [{nombre, valor}] recursively too. Good.

Let me now write the code. First spec_extractors.py.

Let me also double-check: does `extract_og_product_meta` produce `\xa0` etc.? Not important.

Let me implement.

One more consideration: The user said "compatibilidad de fuentes" — font compatibility. They may have observed the mojibake `Ã` chars or `&#225;` codes on the front-end. My fix addresses both. Let me also verify the fix against the real DB samples by writing a quick test after implementing.

Let me write the normalize function.

Implemento la capa de normalización. Primero en `spec_extractors.py`:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py",
  "limit": 18,
  "offset": 76
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py</path>
<type>file</type>
<content>
76: 
77: 
78: def is_template_placeholder(text: str) -> bool:
79:     """Detect JS template-placeholder garbage (e.g. ``{{upgrade.yesAttr.text}}``).
80: 
81:     Samsung and other brands hide Knockout/Angular templates in the DOM that
82:     extractors pick up as fake specs.  These contain ``{{...}}``, ``[[...]]``
83:     or ``${...}`` tokens and must never be stored as characteristics.
84:     """
85:     if not text:
86:         return False
87:     return bool(
88:         re.search(r"\{\{.*\}\}", text)
89:         or re.search(r"\[\[.*\]\]", text)
90:         or re.search(r"\$\{.*\}", text)
91:     )
92: 
93: 

(Showing lines 76-93 of 836. Use offset=94 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 7.0s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py",
  "oldString": "def is_template_placeholder(text: str) -> bool:\n    \"\"\"Detect JS template-placeholder garbage (e.g. ``{{upgrade.yesAttr.text}}``).",
  "newString": "def normalize_text(value: str) -> str:\n    \"\"\"Fix font/encoding corruption that arrives from third-party sources.\n\n    Two kinds of corruption are common in scraped content:\n\n    1. **Literal HTML entities** — ``&#225;``, ``&quot;``, ``&amp;nbsp;``\n       (double-escaped) appear as visible \"codes\" instead of ``á``, ``\"``, `` ``.\n       Decoded with ``html.unescape`` up to 3 passes (``&amp;nbsp;`` → ``&nbsp;``\n       → non-breaking space), stopping as soon as the string is stable.\n    2. **Mojibake** — UTF-8 bytes decoded as latin-1 (``Ã³``, ``Ã±``, ``Ã\\\\xad``)\n       show up where accented letters should be.  Recovered by re-encoding the\n       whole string as latin-1 and decoding as UTF-8.  Clean text is untouched:\n       a real accent like ``é`` encodes to latin-1 byte ``0xE9`` which is not\n       valid UTF-8, so the re-decode fails and the original is kept.\n    \"\"\"\n    if not value:\n        return value\n    for _ in range(3):\n        unescaped = _html.unescape(value)\n        if unescaped == value:\n            break\n        value = unescaped\n    try:\n        fixed = value.encode(\"latin-1\").decode(\"utf-8\")\n        return fixed\n    except (UnicodeEncodeError, UnicodeDecodeError):\n        return value\n\n\ndef normalize_product(data) -> dict | None:\n    \"\"\"Recursively apply :func:`normalize_text` to every string in *data*.\n\n    Normalizes product dicts (title/descripcion/caracteristicas/marca/...) so\n    no entity-coded or mojibake text is stored or pushed to PrestaShop.\n    \"\"\"\n    if not isinstance(data, dict):\n        return data\n    for key, val in list(data.items()):\n        if isinstance(val, str):\n            data[key] = normalize_text(val)\n        elif isinstance(val, list):\n            data[key] = [\n                normalize_product(item) if isinstance(item, dict)\n                else normalize_text(item) if isinstance(item, str) else item\n                for item in val\n            ]\n    return data\n\n\ndef is_template_placeholder(text: str) -> bool:\n    \"\"\"Detect JS template-placeholder garbage (e.g. ``{{upgrade.yesAttr.text}}``)."
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 3.5s)

_Thinking:_

`_html` needs importing. Currently spec_extractors imports json, logging, re. Let me add `import html as _html`. Let me check the top imports.

Agrego el import de `html`:

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py",
  "oldString": "import json\nimport logging\nimport re\nfrom typing import cast\n\nfrom bs4 import BeautifulSoup, Tag",
  "newString": "import html as _html\nimport json\nimport logging\nimport re\nfrom typing import cast\n\nfrom bs4 import BeautifulSoup, Tag"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 4.3s)

Ahora aplico la normalización en `ai_agent._parse_page`:

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/ai_agent.py",
  "newString": "    # Store the source URL so validation can check for junk sources\n    if current_url:\n        result[\"url\"] = current_url\n\n    # Normalize entity-coded / mojibake text from the source page before it\n    # reaches the proposal (accents must arrive as real characters).\n    spec_extractors.normalize_product(result)\n\n    return result",
  "oldString": "    # Store the source URL so validation can check for junk sources\n    if current_url:\n        result[\"url\"] = current_url\n\n    return result"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 4.5s)

_Thinking:_

Now `official_scraper.py`. Apply normalization in `scrape_from_direct_url` before persist, and in `_scrape_pdf_datasheet`. Let me look at the area just before `_persist_scrape_result` call (line ~2057) and `_scrape_pdf_datasheet` (line 2124-2231).

Ahora `official_scraper.py` — normalizo antes de persistir en `scrape_from_direct_url`:

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "newString": "    logger.info(\n        \"  MANUAL_URL  id=%d  extracted %d characteristics from %s\",\n        product_id, len(result.get(\"caracteristicas\") or []), final_url,\n    )\n\n    # Store source URL for validation\n    result[\"url\"] = url\n\n    # Normalize entity-coded / mojibake text before it reaches the proposal.\n    spec_extractors.normalize_product(result)\n\n    # 4. Persist to DB\n    _persist_scrape_result(product_id, result, source=\"manual_url\", url=url)",
  "oldString": "    logger.info(\n        \"  MANUAL_URL  id=%d  extracted %d characteristics from %s\",\n        product_id, len(result.get(\"caracteristicas\") or []), final_url,\n    )\n\n    # Store source URL for validation\n    result[\"url\"] = url\n\n    # 4. Persist to DB\n    _persist_scrape_result(product_id, result, source=\"manual_url\", url=url)"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 5.2s)

_Thinking:_

Now check `_persist_scrape_result` — it's also called from `_scrape_pdf_datasheet` (line 2220). Let me normalize inside `_persist_scrape_result` too as a belt-and-suspenders, since it's the single persist choke point for all manual scrapes. Actually if I normalize in `_persist_scrape_result`, then both the PDF path and manual URL path are covered, and I don't need to touch `_scrape_pdf_datasheet` separately. But I already normalized in scrape_from_direct_url before persist (for the returned dict to enrich.py). For `_scrape_pdf_datasheet`, it returns result and persists via `_persist_scrape_result` — normalizing inside `_persist_scrape_result` covers the stored data, but the returned dict to enrich.py stays dirty for immediate push. Let me normalize at the top of `_persist_scrape_result` AND check `_scrape_pdf_datasheet`'s return path. Actually simplest: add normalization at the start of `_persist_scrape_result` (covers all stored data), plus in `_scrape_pdf_datasheet` right before return (covers returned dict). Let me read `_scrape_pdf_datasheet`.

Normalizo también en `_persist_scrape_result` (choke point de todo scrape) y en `_scrape_pdf_datasheet`:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "limit": 55,
  "offset": 2124
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py</path>
<type>file</type>
<content>
2124:         conn.close()
2125: 
2126: 
2127: def _scrape_pdf_datasheet(pdf_url: str, product_id: int) -> dict | None:
2128:     """Download a spec-sheet PDF and persist the extracted characteristics.
2129: 
2130:     Used for brands whose data sheets are PDFs (gfast) reached via the
2131:     ``pdf_sitemap`` strategy or pasted manually in the Admin UI.
2132: 
2133:     Some data sheets are image-based PDFs with no extractable text; those are
2134:     supplemented from the "Key: Value" spec lines rendered inline on the
2135:     category page the PDF was found on.
2136:     """
2137:     from .pdf_scraper import extract_specs_from_pdf
2138: 
2139:     logger.info("  PDF_DATASHEET  id=%d  extracting %s", product_id, pdf_url[:100])
2140: 
2141:     data = extract_specs_from_pdf(pdf_url, marca="", modelo="")
2142:     characteristics = (data.get("caracteristicas") or []) if data else []
2143: 
2144:     # Fall back to the inline spec lines of the category page the PDF came from
2145:     if len(characteristics) < 5:
2146:         seen = {c["nombre"].lower().strip() for c in characteristics}
2147:         for page_url in _pages_for_pdf(pdf_url):
2148:             soup, _links = _fetch_page(page_url)
2149:             inline = _extract_inline_specs_from_soup(soup, pdf_url)
2150:             if inline:
2151:                 logger.info(
2152:                     "  PDF_DATASHEET  id=%d  %d inline specs from %s",
2153:                     product_id, len(inline), page_url,
2154:                 )
2155:                 for ic in inline:
2156:                     if ic["nombre"].lower().strip() not in seen:
2157:                         characteristics.append(ic)
2158:                         seen.add(ic["nombre"].lower().strip())
2159:             if len(characteristics) >= 5:
2160:                 break
2161: 
2162:     if not characteristics:
2163:         logger.warning(
2164:             "  PDF_DATASHEET  id=%d  no characteristics extracted from %s",
2165:             product_id, pdf_url[:100],
2166:         )
2167:         return None
2168: 
2169:     result = {
2170:         "title": "",
2171:         "descripcion": "",
2172:         "descripcion_corta": "",
2173:         "marca": "",
2174:         "modelo": "",
2175:         "resumen": "",
2176:         "caracteristicas": characteristics,
2177:         "imagen_url": "",
2178:         "imagen_urls": [],

(Showing lines 2124-2178 of 2237. Use offset=2179 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.1s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "limit": 40,
  "offset": 2179
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py</path>
<type>file</type>
<content>
2179:         "_source": "pdf_scraper",
2180:     }
2181: 
2182:     # Backfill marca/modelo from the DB product name when the PDF has none
2183:     try:
2184:         conn = get_connection()
2185:         try:
2186:             row = conn.execute(
2187:                 "SELECT nombre FROM productos WHERE id_prestashop = ?",
2188:                 (product_id,),
2189:             ).fetchone()
2190:         finally:
2191:             conn.close()
2192:         db_nombre = (row["nombre"] or "") if row else ""
2193:         if db_nombre:
2194:             inferred = _infer_brand_from_name(db_nombre)
2195:             if inferred:
2196:                 result["marca"] = inferred.title()
2197:                 logger.info(
2198:                     "  PDF_DATASHEET  id=%d  inferred marca=%r from product name",
2199:                     product_id, inferred,
2200:                 )
2201:             # gfast models embed hyphens (T-195, N-536R) which
2202:             # _extract_model_from_name strips away, so derive the modelo from
2203:             # the digit-bearing model tokens instead of the noisy name words.
2204:             digit_tokens = [
2205:                 t for t in _extract_pdf_model_tokens(db_nombre, inferred or "")
2206:                 if any(ch.isdigit() for ch in t)
2207:             ]
2208:             if digit_tokens:
2209:                 model = max(digit_tokens, key=len).upper()
2210:                 result["modelo"] = model
2211:                 logger.info(
2212:                     "  PDF_DATASHEET  id=%d  inferred modelo=%r from product name",
2213:                     product_id, model,
2214:                 )
2215:     except Exception as exc:
2216:         logger.debug(
2217:             "  PDF_DATASHEET  id=%d  marca/modelo inference failed: %s",
2218:             product_id, exc,

(Showing lines 2179-2218 of 2237. Use offset=2219 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 2.9s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "limit": 18,
  "offset": 2219
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py</path>
<type>file</type>
<content>
2219:         )
2220: 
2221:     result["url"] = pdf_url
2222: 
2223:     _persist_scrape_result(
2224:         product_id, result, source="pdf_sitemap", url=pdf_url,
2225:     )
2226: 
2227:     logger.info(
2228:         "  PDF_DATASHEET  id=%d  saved %s %s (%d chars)",
2229:         product_id,
2230:         result["marca"],
2231:         result["modelo"],
2232:         len(result["caracteristicas"]),
2233:     )
2234:     return result
2235: 
2236: 

(Showing lines 2219-2236 of 2237. Use offset=2237 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 4.1s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/official_scraper.py",
  "newString": "    result[\"url\"] = pdf_url\n\n    # Normalize entity-coded / mojibake text before it reaches the proposal.\n    spec_extractors.normalize_product(result)\n\n    _persist_scrape_result(\n        product_id, result, source=\"pdf_sitemap\", url=pdf_url,\n    )",
  "oldString": "    result[\"url\"] = pdf_url\n\n    _persist_scrape_result(\n        product_id, result, source=\"pdf_sitemap\", url=pdf_url,\n    )"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 4.3s)

_Thinking:_

Now let me also normalize inside `_persist_scrape_result` as a belt-and-suspenders for any other path (e.g. it's only called from these two places, so it's covered). Actually, both callers now normalize before. But to be robust, add normalize at the start of `_persist_scrape_result` too. Let me check if `spec_extractors` is imported in official_scraper — yes it is (line 262 uses spec_extractors.decode_response).

Now enrich.py. The stored-data reuse path (Path A) reads `parsed` from proposal_json. I'll normalize it there. And `_push_to_prestashop` — normalize the desc/chars/description_short.

Let me look at the enrich.py imports to add the import. Let me check the top of enrich.py.

Ahora `enrich.py` — normalizo datos guardados al reutilizarlos y al hacer push:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "limit": 55,
  "offset": 1
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/enrich.py</path>
<type>file</type>
<content>
1: """Enrichment pipeline: DB cache → brand site search → AI agent → translate → embed → score → store → push.
2: 
3: Automated pipeline tries sources in order:
4: 1. Local DB (existing data from previous run)
5: 2. Brand site search (official site → first product result → scrape)
6: 3. AI agent (DuckDuckGo web search, last resort)
7: 
8: Manual URL enrichment is handled separately via the Admin UI
9: (``scrape_from_direct_url``).
10: 
11: Implements RF-06 (vector similarity scoring) and RF-07 (glossary-protected
12: translation).
13: """
14: 
15: import json
16: import logging
17: 
18: from . import pipeline_state, plan
19: from .characteristics import merge_characteristics
20: from .config import BATCH_SIZE
21: from .db import get_connection, mark_not_found, write_eav
22: from .descriptions import get_description
23: from .embedding import embedding_to_bytes, generate_embedding, score_match
24: from .spec_extractors import is_template_placeholder
25: from .translate import translate_product
26: 
27: logger = logging.getLogger(__name__)
28: 
29: 
30: def _brands_match(a: str, b: str) -> bool:
31:     """¿Dos marcas representan la misma? (sub-marcas y variantes aceptadas).
32: 
33:     Ej: "Logitech G" == Logitech, "HP Inc" == HP, "Samsung Electronics" ==
34:     Samsung.
35:     """
36:     a, b = (a or "").strip().lower(), (b or "").strip().lower()
37:     if not a or not b:
38:         return False
39:     if a == b:
40:         return True
41:     a_words = set(a.replace("-", " ").split())
42:     b_words = set(b.replace("-", " ").split())
43:     if a_words & b_words:
44:         return True
45:     return (len(a) >= 3 and a in b) or (len(b) >= 3 and b in a)
46: 
47: 
48: def _validate_name_coherence(
49:     product_data: dict | None,
50:     nombre: str,
51:     marca_db: str,
52:     reference: str | None = None,
53: ) -> bool:
54:     """Rechaza datos enriquecidos cuya marca contradiga el nombre original.
55: 

(Showing lines 1-55 of 841. Use offset=56 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.5s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "newString": "from .spec_extractors import is_template_placeholder, normalize_product, normalize_text\nfrom .translate import translate_product",
  "oldString": "from .spec_extractors import is_template_placeholder\nfrom .translate import translate_product"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 4.2s)

Ahora normalizo en el Path A (reutilizar datos guardados) y en `_push_to_prestashop`:

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "newString": "            if existing_json:\n                try:\n                    parsed = json.loads(existing_json) if isinstance(existing_json, str) else existing_json\n                except (json.JSONDecodeError, TypeError):\n                    parsed = None\n                # Los datos guardados pueden contener entidades HTML sin\n                # decodificar o mojibake (Ã³ en vez de ó) de fuentes terceras —\n                # normalizar antes de reutilizarlos o re-empujarlos.\n                if parsed:\n                    parsed = normalize_product(parsed)\n                stored_valid = False",
  "oldString": "            if existing_json:\n                try:\n                    parsed = json.loads(existing_json) if isinstance(existing_json, str) else existing_json\n                except (json.JSONDecodeError, TypeError):\n                    parsed = None\n                stored_valid = False"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 3.4s)

_Thinking:_

Now in `_push_to_prestashop`, normalize the desc and merged_caracteristicas and description_short. Let me look at `_build_description` and `_push_to_prestashop` again (lines ~85-140).

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "limit": 30,
  "offset": 85
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/enrich.py</path>
<type>file</type>
<content>
85:         title_brand = _infer_brand_from_name(scraped_title)
86:         if title_brand and not _brands_match(title_brand, reference):
87:             logger.warning(
88:                 "  COHERENCE  título %r sugiere marca %r distinta de %r",
89:                 scraped_title[:60], title_brand, reference,
90:             )
91:             return False
92: 
93:     return True
94: 
95: 
96: def _build_description(product_data: dict, caracteristicas: list | None = None) -> str:
97:     """Build full description from characteristics as ``*nombre*: valor`` lines."""
98:     chars = caracteristicas or product_data.get("caracteristicas") or []
99:     if not chars:
100:         return ""
101:     lines = "".join(
102:         f"<p><strong>{ch['nombre']}:</strong> {ch['valor']}</p>"
103:         for ch in chars if ch.get("nombre") and ch.get("valor")
104:     )
105:     return f'<div class="caracteristicas">{lines}</div>'
106: 
107: 
108: def _push_to_prestashop(
109:     conn,
110:     pid: int,
111:     product_data: dict,
112:     marca: str,
113:     modelo: str,
114:     subcat_name: str,

(Showing lines 85-114 of 846. Use offset=115 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 4.3s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "newString": "def _build_description(product_data: dict, caracteristicas: list | None = None) -> str:\n    \"\"\"Build full description from characteristics as ``*nombre*: valor`` lines.\"\"\"\n    chars = caracteristicas or product_data.get(\"caracteristicas\") or []\n    if not chars:\n        return \"\"\n    lines = \"\".join(\n        f\"<p><strong>{normalize_text(ch['nombre'])}:</strong> {normalize_text(ch['valor'])}</p>\"\n        for ch in chars if ch.get(\"nombre\") and ch.get(\"valor\")\n    )\n    return f'<div class=\"caracteristicas\">{lines}</div>'",
  "oldString": "def _build_description(product_data: dict, caracteristicas: list | None = None) -> str:\n    \"\"\"Build full description from characteristics as ``*nombre*: valor`` lines.\"\"\"\n    chars = caracteristicas or product_data.get(\"caracteristicas\") or []\n    if not chars:\n        return \"\"\n    lines = \"\".join(\n        f\"<p><strong>{ch['nombre']}:</strong> {ch['valor']}</p>\"\n        for ch in chars if ch.get(\"nombre\") and ch.get(\"valor\")\n    )\n    return f'<div class=\"caracteristicas\">{lines}</div>'"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 3.8s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "newString": "    excel_desc = get_description(subcat_name)\n    updates = {\n        \"description\": desc,\n        \"description_short\": normalize_text(excel_desc[\"descripcion_corta\"]),\n    }",
  "oldString": "    excel_desc = get_description(subcat_name)\n    updates = {\n        \"description\": desc,\n        \"description_short\": excel_desc[\"descripcion_corta\"],\n    }"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 5.2s)

_Thinking:_

Now, the `merged_caracteristicas` passed to `sync_characteristics_as_features` also should be normalized (they become PrestaShop feature values). In `_push_to_prestashop`:

```python
    merged_caracteristicas = merge_characteristics(
        product_data.get("caracteristicas") or [], subcat_name,
    )
```

The `desc` uses normalize now, but `merged_caracteristicas` goes to sync_characteristics_as_features → feature values. Let me normalize the merged list too. Also `write_eav(conn, pid, merged_caracteristicas)` stores locally.

Let me update `_push_to_prestashop` to normalize merged_caracteristicas.

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py",
  "newString": "    # Merge characteristics with default template\n    merged_caracteristicas = merge_characteristics(\n        product_data.get(\"caracteristicas\") or [], subcat_name,\n    )\n    # Normalize names/values (entities + mojibake) before they reach\n    # PrestaShop features, the local EAV and the description.\n    for ch in merged_caracteristicas:\n        ch[\"nombre\"] = normalize_text(ch.get(\"nombre\") or \"\")\n        ch[\"valor\"] = normalize_text(ch.get(\"valor\") or \"\")\n    desc = _build_description(product_data, merged_caracteristicas)",
  "oldString": "    # Merge characteristics with default template\n    merged_caracteristicas = merge_characteristics(\n        product_data.get(\"caracteristicas\") or [], subcat_name,\n    )\n    desc = _build_description(product_data, merged_caracteristicas)"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 5.3s)

_Thinking:_

Wait — `_build_description` already normalizes each ch's nombre/valor. So the loop I added for merged_caracteristicas is needed for the feature sync + write_eav. Good, both coexist.

Now the `admin_ui/app.py` approve route. Let me normalize there. The approve builds `desc` and `description_short` from merged_chars. Let me update. Also it writes EAV locally? Let me check the rest of approve (lines 477-560).

Ahora la ruta de aprobación en `admin_ui/app.py`:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/app.py",
  "limit": 115,
  "offset": 420
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/app.py</path>
<type>file</type>
<content>
420: 
421:         subcat_name = product.get("subcat_name") or ""
422: 
423:         # -- push to PrestaShop -------------------------------------------
424:         activate = request.form.get("activate", "0") == "1"
425: 
426:         # Build description from characteristics only:  *nombre*: valor
427:         chars = proposal.get("caracteristicas") or []
428:         merged_chars = merge_characteristics(chars, subcat_name)
429:         desc = ""
430:         if merged_chars:
431:             lines = "".join(
432:                 f"<p><strong>{ch['nombre']}:</strong> {ch['valor']}</p>"
433:                 for ch in merged_chars if ch.get("nombre") and ch.get("valor")
434:             )
435:             desc = f'<div class="caracteristicas">{lines}</div>'
436: 
437:         updates: dict[str, Any] = {
438:             "description": desc,
439:             "description_short": get_description(subcat_name)["descripcion_corta"],
440:         }
441:         if activate:
442:             updates["active"] = "1"
443:         try:
444:             client = AdminPrestashopClient()
445: 
446:             # sync merged characteristics as PrestaShop features
447:             feature_pairs = client.sync_characteristics_as_features(merged_chars)
448: 
449:             client.put_product(pid, updates, feature_pairs=feature_pairs or None)
450: 
451:             # upload images if available
452:             imagen_urls = proposal.get("imagen_urls") or []
453:             if imagen_urls:
454:                 uploaded_ids = client.upload_product_images(pid, imagen_urls)
455:                 if uploaded_ids:
456:                     updates["imagen_subida"] = uploaded_ids[0]
457:                 else:
458:                     updates["imagen_subida"] = False
459:             else:
460:                 imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""
461:                 if imagen_url:
462:                     img_id = client.upload_product_image(pid, imagen_url)
463:                     if img_id is not None:
464:                         updates["imagen_subida"] = img_id
465:                     else:
466:                         updates["imagen_subida"] = False
467:         except PrestashopError as exc:
468:             _audit(conn, pid, actor, "error", str(exc))
469:             conn.commit()
470:             return jsonify({"ok": False, "error": str(exc)}), 502
471: 
472:         # -- update local DB -----------------------------------------------
473:         marca_final = proposal.get("marca") or product["marca"]
474:         modelo_final = proposal.get("modelo") or product["modelo"]
475:         imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""
476: 
477:         conn.execute(
478:             """UPDATE productos
479:                SET marca = ?, modelo = ?,
480:                    estado_actualizacion = 'actualizado',
481:                    proposal_json = NULL,
482:                    imagen_url = ?,
483:                    fecha_sincronizacion = datetime('now')
484:                WHERE id_prestashop = ?""",
485:             (marca_final, modelo_final, imagen_url or None, pid),
486:         )
487: 
488:         if activate:
489:             conn.execute(
490:                 "UPDATE productos SET pendiente_activar = 0 WHERE id_prestashop = ?",
491:                 (pid,),
492:             )
493: 
494:         # write merged characteristics locally (EAV)
495:         write_eav(conn, pid, merged_chars)
496: 
497:         accion = "aprobado_y_activado" if activate else "aprobado"
498:         detalle = {
499:             "marca": marca_final,
500:             "modelo": modelo_final,
501:             "activate": activate,
502:         }
503:         img_status = updates.get("imagen_subida")
504:         if img_status is None:
505:             detalle["imagen"] = "sin_url"
506:         elif img_status is False:
507:             detalle["imagen"] = "fallo"
508:         else:
509:             detalle["imagen"] = f"ok_id_{img_status}"
510:         _audit(conn, pid, actor, accion,
511:                json.dumps(detalle, ensure_ascii=False))
512:         conn.commit()
513: 
514:         # Check completeness after activation and auto-complete if needed
515:         if activate:
516:             try:
517:                 from middleware.check_active import (
518:                     check_product_completeness,
519:                     complete_incomplete_product,
520:                 )
521:                 completeness = check_product_completeness(pid)
522:                 if not completeness["is_complete"]:
523:                     logger.info(
524:                         "Product %d is incomplete after activation (missing: %s), auto-completing...",
525:                         pid, completeness["missing"]
526:                     )
527:                     complete_incomplete_product(pid, dry_run=False)
528:             except Exception as exc:
529:                 logger.warning("Error checking completeness for product %d: %s", pid, exc)
530: 
531:     except Exception:
532:         conn.rollback()
533:         raise
534:     finally:

(Showing lines 420-534 of 1168. Use offset=535 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.6s)

_Thinking:_

Now let me check the imports in app.py to see what's available. Let me look at the imports section.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/app.py",
  "limit": 45,
  "offset": 1
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/app.py</path>
<type>file</type>
<content>
1: """Admin UI — Flask application (RF-11 … RF-14)."""
2: 
3: import json
4: import logging
5: import os
6: import secrets
7: import threading
8: from datetime import datetime, timezone
9: from typing import Any
10: 
11: from flask import (
12:     Flask,
13:     jsonify,
14:     redirect,
15:     render_template,
16:     request,
17:     session,
18:     url_for,
19: )
20: 
21: from middleware.characteristics import merge_characteristics
22: from middleware.config import DAEMON_INTERVAL
23: from middleware.db import get_connection, write_eav
24: from middleware.descriptions import get_description
25: from middleware.official_scraper import scrape_from_direct_url
26: from middleware.users import verify_user
27: 
28: from .prestashop import AdminPrestashopClient, PrestashopError
29: 
30: logger = logging.getLogger(__name__)
31: 
32: app = Flask(__name__)
33: 
34: 
35: def _load_secret_key() -> str:
36:     """Clave de sesión: env SECRET_KEY → config DB → aleatoria persistida."""
37:     from middleware.config import get_config, set_config
38: 
39:     key = os.getenv("SECRET_KEY") or get_config("SECRET_KEY")
40:     if key:
41:         return key
42:     key = secrets.token_hex(32)
43:     try:
44:         set_config("SECRET_KEY", key)
45:     except Exception:

(Showing lines 1-45 of 1168. Use offset=46 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 4.0s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/app.py",
  "newString": "from middleware.characteristics import merge_characteristics\nfrom middleware.config import DAEMON_INTERVAL\nfrom middleware.db import get_connection, write_eav\nfrom middleware.descriptions import get_description\nfrom middleware.official_scraper import scrape_from_direct_url\nfrom middleware.spec_extractors import normalize_product, normalize_text\nfrom middleware.users import verify_user",
  "oldString": "from middleware.characteristics import merge_characteristics\nfrom middleware.config import DAEMON_INTERVAL\nfrom middleware.db import get_connection, write_eav\nfrom middleware.descriptions import get_description\nfrom middleware.official_scraper import scrape_from_direct_url\nfrom middleware.users import verify_user"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 6.0s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/app.py",
  "newString": "        # -- push to PrestaShop -------------------------------------------\n        activate = request.form.get(\"activate\", \"0\") == \"1\"\n\n        # Normalize entity-coded / mojibake text before it reaches PrestaShop.\n        proposal = normalize_product(proposal)\n\n        # Build description from characteristics only:  *nombre*: valor\n        chars = proposal.get(\"caracteristicas\") or []\n        merged_chars = merge_characteristics(chars, subcat_name)\n        desc = \"\"\n        if merged_chars:\n            lines = \"\".join(\n                f\"<p><strong>{normalize_text(ch['nombre'])}:</strong> {normalize_text(ch['valor'])}</p>\"\n                for ch in merged_chars if ch.get(\"nombre\") and ch.get(\"valor\")\n            )\n            desc = f'<div class=\"caracteristicas\">{lines}</div>'\n\n        updates: dict[str, Any] = {\n            \"description\": desc,\n            \"description_short\": normalize_text(\n                get_description(subcat_name)[\"descripcion_corta\"]\n            ),\n        }",
  "oldString": "        # -- push to PrestaShop -------------------------------------------\n        activate = request.form.get(\"activate\", \"0\") == \"1\"\n\n        # Build description from characteristics only:  *nombre*: valor\n        chars = proposal.get(\"caracteristicas\") or []\n        merged_chars = merge_characteristics(chars, subcat_name)\n        desc = \"\"\n        if merged_chars:\n            lines = \"\".join(\n                f\"<p><strong>{ch['nombre']}:</strong> {ch['valor']}</p>\"\n                for ch in merged_chars if ch.get(\"nombre\") and ch.get(\"valor\")\n            )\n            desc = f'<div class=\"caracteristicas\">{lines}</div>'\n\n        updates: dict[str, Any] = {\n            \"description\": desc,\n            \"description_short\": get_description(subcat_name)[\"descripcion_corta\"],\n        }"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 3.8s)

_Thinking:_

Now `check_active.py`. It has its own `_build_description` (imported from enrich? Let me check). Let me look at check_active.py imports and where it builds desc / description_short.

Line 254-255: `desc = _build_description(proposal, merged_chars)` — where does _build_description come from? Let me check imports at top of check_active.py.

Ahora `check_active.py`:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "limit": 45,
  "offset": 1
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/check_active.py</path>
<type>file</type>
<content>
1: """Active product completeness check and auto-completion.
2: 
3: Checks active products (active=1) in PrestaShop for completeness:
4: - Image: product has at least one image
5: - Description: product has a non-empty description
6: - Characteristics: product has product_features assigned
7: 
8: Incomplete products are automatically completed using the enrichment pipeline.
9: """
10: 
11: import json
12: import logging
13: 
14: from . import pipeline_state
15: from .db import (
16:     ensure_subcategoria,
17:     get_connection,
18:     get_subcategoria_by_ps_category,
19:     insert_product,
20: )
21: 
22: logger = logging.getLogger(__name__)
23: 
24: 
25: def _ensure_product_in_db(pid: int) -> dict | None:
26:     """Ensure the product exists in the local DB with fresh data from PrestaShop.
27: 
28:     Always fetches the latest data from PrestaShop and upserts into the local DB.
29:     Returns the product row as a dict, or None if it couldn't be created.
30:     """
31:     from admin_ui.prestashop import AdminPrestashopClient
32: 
33:     conn = get_connection()
34:     try:
35:         client = AdminPrestashopClient()
36:         ps_product = client.get_product(pid)
37: 
38:         # Get manufacturer name
39:         id_mfr = ps_product.get("id_manufacturer")
40:         marca = ""
41:         if id_mfr:
42:             try:
43:                 manufacturers = client.get_manufacturers()
44:                 marca = manufacturers.get(int(id_mfr), "")
45:             except Exception:

(Showing lines 1-45 of 637. Use offset=46 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.3s)

**Tool: grep**

**Input:**
```json
{
  "include": "check_active.py",
  "path": "/home/icrocetti/dev/ProyectoDC/middleware",
  "pattern": "_build_description|from \\.enrich|import|merge_characteristics|get_description"
}
```

**Output:**
```
Found 21 matches
/home/icrocetti/dev/ProyectoDC/middleware/check_active.py:
  Line 11: import json

  Line 12: import logging

  Line 14: from . import pipeline_state

  Line 15: from .db import (

  Line 31:     from admin_ui.prestashop import AdminPrestashopClient

  Line 128:     from admin_ui.prestashop import AdminPrestashopClient, PrestashopError

  Line 148:     from admin_ui.prestashop import AdminPrestashopClient, PrestashopError

  Line 150:     from .characteristics import merge_characteristics

  Line 151:     from .db import write_eav

  Line 152:     from .descriptions import get_description

  Line 153:     from .enrich import _build_description

  Line 205:             from .enrich import _fetch_and_prepare

  Line 254:                 merged_chars = merge_characteristics(chars, subcat_name)

  Line 255:                 desc = _build_description(proposal, merged_chars)

  Line 262:                     excel_desc = get_description(subcat_name)

  Line 270:                 merged_chars = merge_characteristics(chars, subcat_name)

  Line 321:                 merged_chars = merge_characteristics(chars, subcat_name)

  Line 360:     from middleware.prestashop import PrestashopClient

  Line 483:     from . import plan

  Line 495:     from . import plan

  Line 529:     from middleware.prestashop import PrestashopClient

```

---

## Assistant (Build · Big Pickle · 3.7s)

_Thinking:_

check_active.py uses `_build_description` from enrich (which now normalizes) and `get_description` (which returns raw Excel text). Let me look at lines 148-330 of check_active.py to see the full push and the `check_inactive_pending` flow, and normalize where needed. The `proposal` parsed from JSON (line 192-200) should be normalized. And `description_short` from get_description should be normalized. And `merged_chars` values for feature sync.

Let me read lines 148-340.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "limit": 70,
  "offset": 148
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/check_active.py</path>
<type>file</type>
<content>
148:     from admin_ui.prestashop import AdminPrestashopClient, PrestashopError
149: 
150:     from .characteristics import merge_characteristics
151:     from .db import write_eav
152:     from .descriptions import get_description
153:     from .enrich import _build_description
154: 
155:     # Ensure product exists in local DB (inserts if missing)
156:     product = _ensure_product_in_db(pid)
157:     if product is None:
158:         logger.warning("Product %d could not be loaded into local DB", pid)
159:         return False
160: 
161:     # Skip if already verified as complete
162:     if product.get("active_verified"):
163:         logger.debug("Product %d already verified as complete, skipping", pid)
164:         return True
165: 
166:     # Check completeness
167:     completeness = check_product_completeness(pid)
168:     if completeness["is_complete"]:
169:         logger.info("Product %d is already complete, marking as verified", pid)
170:         if not dry_run:
171:             conn = get_connection()
172:             try:
173:                 conn.execute(
174:                     "UPDATE productos SET active_verified = 1 WHERE id_prestashop = ?",
175:                     (pid,),
176:                 )
177:                 conn.commit()
178:             finally:
179:                 conn.close()
180:         return True
181: 
182:     missing = completeness["missing"]
183:     logger.info("Product %d is incomplete, missing: %s", pid, missing)
184: 
185:     if dry_run:
186:         logger.info("  DRY RUN — would complete product %d (missing: %s)", pid, missing)
187:         return True
188: 
189:     conn = get_connection()
190:     try:
191:         subcat_name = product.get("subcat_name") or ""
192:         proposal_json = product.get("proposal_json")
193: 
194:         # Parse existing proposal if available
195:         proposal = None
196:         if proposal_json:
197:             try:
198:                 proposal = json.loads(proposal_json) if isinstance(proposal_json, str) else proposal_json
199:             except (json.JSONDecodeError, TypeError):
200:                 proposal = None
201: 
202:         # If no proposal exists, we need to fetch data first
203:         if proposal is None:
204:             logger.info("Product %d has no proposal data, running enrichment first", pid)
205:             from .enrich import _fetch_and_prepare
206: 
207:             product_data, translated, description = _fetch_and_prepare(
208:                 pid,
209:                 product.get("ean"),
210:                 product.get("mpn"),
211:                 product.get("marca") or "",
212:                 product.get("modelo") or "",
213:                 product.get("nombre") or "",
214:                 dry_run=False,
215:             )
216: 
217:             if product_data is None:

(Showing lines 148-217 of 637. Use offset=218 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.7s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "newString": "    from .characteristics import merge_characteristics\n    from .db import write_eav\n    from .descriptions import get_description\n    from .enrich import _build_description\n    from .spec_extractors import normalize_product, normalize_text",
  "oldString": "    from .characteristics import merge_characteristics\n    from .db import write_eav\n    from .descriptions import get_description\n    from .enrich import _build_description"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 3.9s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "newString": "        # Parse existing proposal if available\n        proposal = None\n        if proposal_json:\n            try:\n                proposal = json.loads(proposal_json) if isinstance(proposal_json, str) else proposal_json\n            except (json.JSONDecodeError, TypeError):\n                proposal = None\n        if proposal:\n            # Normalize entity-coded / mojibake text before reusing it.\n            proposal = normalize_product(proposal)",
  "oldString": "        # Parse existing proposal if available\n        proposal = None\n        if proposal_json:\n            try:\n                proposal = json.loads(proposal_json) if isinstance(proposal_json, str) else proposal_json\n            except (json.JSONDecodeError, TypeError):\n                proposal = None"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 4.4s)

_Thinking:_

Now the check_active push at lines ~254-272: it builds `desc = _build_description(proposal, merged_chars)` (which now normalizes). `description_short` from get_description — normalize it. And `merged_chars` used for feature_pairs — normalize the values. Let me read lines 250-285 (already saw earlier at 252-280). Let me update.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "limit": 55,
  "offset": 255
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/check_active.py</path>
<type>file</type>
<content>
255:             # Complete description if missing
256:             if "description" in missing:
257:                 chars = proposal.get("caracteristicas") or []
258:                 merged_chars = merge_characteristics(chars, subcat_name)
259:                 desc = _build_description(proposal, merged_chars)
260:                 if desc:
261:                     updates["description"] = desc
262: 
263:                 # Also set description_short if empty
264:                 desc_short = ps_product.get("description_short", "")
265:                 if not desc_short or (isinstance(desc_short, str) and not desc_short.strip()):
266:                     excel_desc = get_description(subcat_name)
267:                     if excel_desc.get("descripcion_corta"):
268:                         updates["description_short"] = excel_desc["descripcion_corta"]
269: 
270:             # Complete characteristics if missing
271:             feature_pairs = None
272:             if "characteristics" in missing:
273:                 chars = proposal.get("caracteristicas") or []
274:                 merged_chars = merge_characteristics(chars, subcat_name)
275:                 if merged_chars:
276:                     feature_pairs = client.sync_characteristics_as_features(merged_chars)
277: 
278:             # Push updates to PrestaShop
279:             if updates or feature_pairs:
280:                 client.put_product(
281:                     pid, updates,
282:                     feature_pairs=feature_pairs or None,
283:                 )
284:                 logger.info("  Updated product %d: %s", pid, list(updates.keys()))
285: 
286:             # Upload images if missing
287:             if "image" in missing:
288:                 imagen_urls = proposal.get("imagen_urls") or []
289:                 if imagen_urls:
290:                     uploaded_ids = client.upload_product_images(pid, imagen_urls)
291:                     if uploaded_ids:
292:                         logger.info("  Uploaded %d images for product %d", len(uploaded_ids), pid)
293:                     else:
294:                         logger.warning("  Failed to upload images for product %d", pid)
295:                 else:
296:                     imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""
297:                     if imagen_url:
298:                         img_id = client.upload_product_image(pid, imagen_url)
299:                         if img_id:
300:                             logger.info("  Uploaded image for product %d: %s", pid, imagen_url)
301:                         else:
302:                             logger.warning("  Failed to upload image for product %d", pid)
303: 
304:             # Update local DB
305:             marca_final = proposal.get("marca") or product.get("marca") or ""
306:             modelo_final = proposal.get("modelo") or product.get("modelo") or ""
307:             imagen_url = proposal.get("imagen_url") or product.get("imagen_url") or ""
308: 
309:             conn.execute(

(Showing lines 255-309 of 641. Use offset=310 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 5.3s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/check_active.py",
  "newString": "            # Complete description if missing\n            if \"description\" in missing:\n                chars = proposal.get(\"caracteristicas\") or []\n                merged_chars = merge_characteristics(chars, subcat_name)\n                for ch in merged_chars:\n                    ch[\"nombre\"] = normalize_text(ch.get(\"nombre\") or \"\")\n                    ch[\"valor\"] = normalize_text(ch.get(\"valor\") or \"\")\n                desc = _build_description(proposal, merged_chars)\n                if desc:\n                    updates[\"description\"] = desc\n\n                # Also set description_short if empty\n                desc_short = ps_product.get(\"description_short\", \"\")\n                if not desc_short or (isinstance(desc_short, str) and not desc_short.strip()):\n                    excel_desc = get_description(subcat_name)\n                    if excel_desc.get(\"descripcion_corta\"):\n                        updates[\"description_short\"] = normalize_text(\n                            excel_desc[\"descripcion_corta\"]\n                        )\n\n            # Complete characteristics if missing\n            feature_pairs = None\n            if \"characteristics\" in missing:\n                chars = proposal.get(\"caracteristicas\") or []\n                merged_chars = merge_characteristics(chars, subcat_name)\n                for ch in merged_chars:\n                    ch[\"nombre\"] = normalize_text(ch.get(\"nombre\") or \"\")\n                    ch[\"valor\"] = normalize_text(ch.get(\"valor\") or \"\")\n                if merged_chars:\n                    feature_pairs = client.sync_characteristics_as_features(merged_chars)",
  "oldString": "            # Complete description if missing\n            if \"description\" in missing:\n                chars = proposal.get(\"caracteristicas\") or []\n                merged_chars = merge_characteristics(chars, subcat_name)\n                desc = _build_description(proposal, merged_chars)\n                if desc:\n                    updates[\"description\"] = desc\n\n                # Also set description_short if empty\n                desc_short = ps_product.get(\"description_short\", \"\")\n                if not desc_short or (isinstance(desc_short, str) and not desc_short.strip()):\n                    excel_desc = get_description(subcat_name)\n                    if excel_desc.get(\"descripcion_corta\"):\n                        updates[\"description_short\"] = excel_desc[\"descripcion_corta\"]\n\n            # Complete characteristics if missing\n            feature_pairs = None\n            if \"characteristics\" in missing:\n                chars = proposal.get(\"caracteristicas\") or []\n                merged_chars = merge_characteristics(chars, subcat_name)\n                if merged_chars:\n                    feature_pairs = client.sync_characteristics_as_features(merged_chars)"
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 9.6s)

_Thinking:_

Now the `_fetch_and_prepare` in enrich.py — after obtaining `product_data`, it should be normalized before translating (since ai_agent and official_scraper now normalize, but the brand-site `scrape_from_direct_url` result is normalized too). But there's also the Path B store where `translated` is stored. Since sources normalize, this is covered. But belt-and-suspenders: normalize `product_data` at the start of the store/push section. Actually `_fetch_and_prepare` backfills marca/modelo AFTER getting product_data, then translates. Since sources are normalized, fine.

But wait — there's still `translate_product`. GoogleTranslator could introduce new corruption? We tested — it's clean. OK.

Now, there's one more important consideration: `get_description` reads from Excel. The Excel descriptions might contain literal `&nbsp;` or entities, but we normalize description_short now. Good.

Now, also the `_fetch_and_prepare` Path B store writes `translated` — if it's normalized at source, fine.

Let me now write a quick test to verify `normalize_text` handles the real DB samples correctly, then run the test suite.

Verifico la normalización contra los ejemplos reales de la BD:

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python - <<'EOF'\nfrom middleware.spec_extractors import normalize_text, normalize_product\n\nsamples = [\n    \"Samsung Galaxy A16 5G: caracterÃ\\xadsticas y especificaciones - smartGSM\",\n    \"El Motorola Moto G82 es un smartphone con resoluciÃ³n Full HD+\",\n    \"Encontr&#225; en Space tu Mouse Logitech. Hac&#233; click. Envi&#225;moslo a todo el pa&#237;s. &#128640;\",\n    \"Filtro de Aire B&amp;s Espuma 3 y 3.5 Hp\",\n    \"Especificaciones técnicas&#009;&#009;Marca: Champion&#009;&#009;&#009;N&#250;mero de parte: N9YC\",\n    \"Cadena de Motosierra OSLO&nbsp;es la herramienta perfecta.&amp;nbsp;La\",\n    \"Estuche &quot;Tomo del Aventurero&quot;\",\n    \"Resolución y configuración normal — texto ya correcto\",\n    \"&#195;&#179; (entidades dobles de o) -> debe ser o\",\n    \"Mejorá el rendimiento — acento agudo ya correcto\",\n    \"CADENA 3/8&#039;&#039; 1.3mm\",\n]\nfor s in samples:\n    print(repr(s[:60]))\n    print(\"  ->\", repr(normalize_text(s)[:80]))\n    print()\n\n# verify normalize_product on a real stored proposal\nimport sqlite3, json\nconn = sqlite3.connect('catalogo.db')\nr = conn.execute(\"SELECT proposal_json FROM productos WHERE id_prestashop=?\", (82430,)).fetchone()\np = json.loads(r[0])\nout = normalize_product(p)\nprint(\"producto 82430 descripcion (antes):\", repr(p[\"descripcion\"][:80]))\nprint(\"producto 82430 descripcion (despues):\", repr(out[\"descripcion\"][:80]))\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
'Samsung Galaxy A16 5G: caracterÃ\xadsticas y especificaciones -'
  -> 'Samsung Galaxy A16 5G: características y especificaciones - smartGSM'

'El Motorola Moto G82 es un smartphone con resoluciÃ³n Full H'
  -> 'El Motorola Moto G82 es un smartphone con resolución Full HD+'

'Encontr&#225; en Space tu Mouse Logitech. Hac&#233; click. E'
  -> 'Encontrá en Space tu Mouse Logitech. Hacé click. Enviámoslo a todo el país. 🚀'

'Filtro de Aire B&amp;s Espuma 3 y 3.5 Hp'
  -> 'Filtro de Aire B&s Espuma 3 y 3.5 Hp'

'Especificaciones técnicas&#009;&#009;Marca: Champion&#009;&#'
  -> 'Especificaciones técnicas\t\tMarca: Champion\t\t\tNúmero de parte: N9YC'

'Cadena de Motosierra OSLO&nbsp;es la herramienta perfecta.&a'
  -> 'Cadena de Motosierra OSLO\xa0es la herramienta perfecta.\xa0La'

'Estuche &quot;Tomo del Aventurero&quot;'
  -> 'Estuche "Tomo del Aventurero"'

'Resolución y configuración normal — texto ya correcto'
  -> 'Resolución y configuración normal — texto ya correcto'

'&#195;&#179; (entidades dobles de o) -> debe ser o'
  -> 'ó (entidades dobles de o) -> debe ser o'

'Mejorá el rendimiento — acento agudo ya correcto'
  -> 'Mejorá el rendimiento — acento agudo ya correcto'

'CADENA 3/8&#039;&#039; 1.3mm'
  -> "CADENA 3/8'' 1.3mm"

producto 82430 descripcion (antes): 'Especificaciones técnicas\t\tMarca: Champion\t\t\tNúmero de parte: N9YC\t\t\tRosca: 14 m'
producto 82430 descripcion (despues): 'Especificaciones técnicas\t\tMarca: Champion\t\t\tNúmero de parte: N9YC\t\t\tRosca: 14 m'

```

---

## Assistant (Build · Big Pickle · 25.8s)

_Thinking:_

The normalization works perfectly:
- Mojibake `caracterÃ\xadsticas` → `características` ✓
- `resoluciÃ³n` → `resolución` ✓
- `&#225;` → `á` ✓
- `B&amp;s` → `B&s` ✓
- `&#009;` → tab ✓
- `&quot;` → `"` ✓
- `&amp;nbsp;` → `\xa0` ✓
- Correct text unchanged ✓
- `&#195;&#179;` (double entity) → `ó` ✓
- Real accent unchanged ✓
- `&#039;` → `'` ✓

Note: product 82430's description was ALREADY stored with actual tabs (not `&#009;`) — interesting, the stored one shows real `\t`. Actually the earlier query showed `&#009;` in the DB. Wait, the "antes" output shows `\t`... Let me re-check. Earlier grep showed `Especificaciones técnicas&#009;&#009;Marca: Champion`. But now "antes" shows `Especificaciones técnicas\t\tMarca`. Hmm — json.loads of `&#009;`? No, json doesn't decode entities. Wait — the `repr` shows `\t` which is an actual tab char. So the DB actually has tabs, not `&#009;`. But my earlier query used `repr(v[:250])` and showed `&#009;`? Let me look again: earlier output: `'Especificaciones técnicas&#009;&#009;Marca: Champion&#009;&#009;&#009;Número de parte: N9YC&#009;...`. That was BEFORE. Now after... wait, I didn't write to the DB. The DB still has the original. The repr now shows `\t\t`. That's contradictory!

Oh wait — the difference: my earlier script did `json.loads` too and printed `v[:250]` with `repr()`. It showed `&#009;`. Now it shows `\t`. The only difference... Actually let me re-read: earlier output for 82430: `'Especificaciones técnicas&#009;&#009;Marca: Champion&#009;...'`. Hmm. But now the same read shows tabs. 

OH — maybe the difference: earlier I printed `repr(v[:250])` where v was `p.get('descripcion')`. Now `repr(p["descripcion"][:80])`. Both json.loads. Unless... the proposal_json in DB changed? No.

Actually wait, maybe I misread earlier. Let me not worry — the normalize function handles both cases anyway (the sample "Especificaciones técnicas&#009;..." test input worked and converted to \t). And the real stored one is already tabs. Either way normalize_text is idempotent and correct.

Hmm, actually the difference is interesting but not blocking. Whatever the DB stores, normalize_text handles it.

Now let me run the test suite to make sure nothing broke.

La normalización funciona en todos los casos reales. Corro los tests:

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python -m pytest tests/ -q --deselect tests/test_prestashop_helpers.py::test_read_only_fields_removed_on_put 2>&1 | tail -8",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
........................................................................ [ 58%]
...................................................                      [100%]

```

---

## Assistant (Build · Big Pickle · 14.4s)

_Thinking:_

All tests pass. Now let me also verify the syntax of the modified files and that the Flask app imports fine. Let me do a compile check on all modified files.

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python -c \"\nimport ast\nfor f in ['middleware/spec_extractors.py','middleware/ai_agent.py','middleware/official_scraper.py','middleware/enrich.py','middleware/check_active.py','admin_ui/app.py','admin_ui/prestashop.py']:\n    ast.parse(open(f).read())\nprint('OK sintaxis')\n\" && venv/bin/python -c \"\nimport sys; sys.path.insert(0, '.')\nfrom admin_ui import app\nfrom middleware import enrich, check_active, spec_extractors, ai_agent, official_scraper\nprint('OK imports')\n\"",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
OK sintaxis
OK imports

```

---

## Assistant (Build · Big Pickle · 4.1s)

_Thinking:_

Now let me also add a test for normalize_text to the existing test file, so the fix is covered. Let me check the existing test_spec_extractors.py structure to add a test in matching style. Actually the user didn't ask for tests, but there's a tests directory. Let me add a small test for normalize_text since it's the core of the fix — it aligns with the repo's existing test conventions (tests/test_spec_extractors.py exists).

Let me look at the test file structure briefly.

Agrego un test para `normalize_text` en la suite existente:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py",
  "limit": 40,
  "offset": 180
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py</path>
<type>file</type>
<content>
180:     assert "tamaño" not in by_name
181: 
182: 
183: class _FakeResp:
184:     def __init__(self, content, encoding=None, apparent_encoding=None):
185:         self.content = content
186:         self.encoding = encoding
187:         self.apparent_encoding = apparent_encoding
188: 
189: 
190: def test_decode_response_utf8_no_charset_header():
191:     body = "<html><body><p>Resolución 4K — ñandú</p></body></html>"
192:     resp = _FakeResp(body.encode("utf-8"), encoding=None)
193:     assert se.decode_response(resp) == body
194: 
195: 
196: def test_decode_response_meta_charset_beats_latin_header():
197:     body = (
198:         '<html><head><meta charset="utf-8"></head>'
199:         "<body><p>Resolución 4K — ñandú</p></body></html>"
200:     )
201:     resp = _FakeResp(body.encode("utf-8"), encoding="ISO-8859-1")
202:     assert se.decode_response(resp) == body
203: 
204: 
205: def test_decode_response_header_charset_honored():
206:     body = '<html><body><p>Größe: 55"</p></body></html>'
207:     resp = _FakeResp(body.encode("iso-8859-1"), encoding="ISO-8859-1")
208:     out = se.decode_response(resp)
209:     assert "Größe" in out
210: 
211: 
212: def test_decode_response_apparent_encoding_fallback():
213:     body = '<html><body><p>Déjà vu — 100%</p></body></html>'
214:     resp = _FakeResp(body.encode("utf-8"), encoding=None,
215:                      apparent_encoding="utf-8")
216:     assert se.decode_response(resp) == body
217: 
218: 
219: def test_decode_response_empty_body():

(Showing lines 180-219 of 223. Use offset=220 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 2.8s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py",
  "limit": 15,
  "offset": 1
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py</path>
<type>file</type>
<content>
1: """Tests for generic spec extractors (middleware/spec_extractors.py)."""
2: 
3: import json
4: 
5: from bs4 import BeautifulSoup
6: 
7: from middleware import spec_extractors as se
8: 
9: 
10: def soup(html):
11:     return BeautifulSoup(html, "lxml")
12: 
13: 
14: def test_is_template_placeholder():
15:     assert se.is_template_placeholder("{{upgrade.yesAttr.text}}")

(Showing lines 1-15 of 223. Use offset=16 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.6s)

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py",
  "limit": 10,
  "offset": 218
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py</path>
<type>file</type>
<content>
218: 
219: def test_decode_response_empty_body():
220:     resp = _FakeResp(b"")
221:     assert se.decode_response(resp) == ""
222: 
223: 

(End of file - total 223 lines)
</content>
```

---

## Assistant (Build · Big Pickle · 7.0s)

**Tool: edit**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/tests/test_spec_extractors.py",
  "newString": "def test_decode_response_empty_body():\n    resp = _FakeResp(b\"\")\n    assert se.decode_response(resp) == \"\"\n\n\ndef test_normalize_text_decodes_html_entities():\n    assert se.normalize_text(\"Encontr&#225; en Space &#128640;\") == \"Encontrá en Space 🚀\"\n    assert se.normalize_text('Estuche &quot;Tomo&quot;') == 'Estuche \"Tomo\"'\n    assert se.normalize_text(\"CADENA 3/8&#039;&#039; 1.3mm\") == \"CADENA 3/8'' 1.3mm\"\n    assert se.normalize_text(\"B&amp;s\") == \"B&s\"\n    assert se.normalize_text(\"OSLO&nbsp;es &amp;nbsp;\") == \"OSLO\\u00a0es \\u00a0\"\n\n\ndef test_normalize_text_repairs_mojibake():\n    assert se.normalize_text(\"caracterÃ\\xadsticas\") == \"características\"\n    assert se.normalize_text(\"resoluciÃ³n Full HD+\") == \"resolución Full HD+\"\n    assert se.normalize_text(\"diseÃ±ado\") == \"diseñado\"\n    # double-encoded numeric entities\n    assert se.normalize_text(\"&#195;&#179;\") == \"ó\"\n\n\ndef test_normalize_text_leaves_clean_text_untouched():\n    assert se.normalize_text(\"Resolución y configuración — correcto\") == \"Resolución y configuración — correcto\"\n    assert se.normalize_text(\"Mejorá el rendimiento\") == \"Mejorá el rendimiento\"\n    assert se.normalize_text(\"\") == \"\"\n    assert se.normalize_text(None) is None\n\n\ndef test_normalize_product_recursive():\n    data = {\n        \"title\": \"Filtro de Aire B&amp;s\",\n        \"descripcion\": \"caracterÃ\\xadsticas\",\n        \"caracteristicas\": [\n            {\"nombre\": \"Resoluci&#243;n\", \"valor\": \"4K\"},\n            {\"nombre\": \"Marca\", \"valor\": \"diseÃ±ado en ES\"},\n        ],\n        \"imagen_urls\": [\"http://x/a.png\"],\n    }\n    out = se.normalize_product(data)\n    assert out[\"title\"] == \"Filtro de Aire B&s\"\n    assert out[\"descripcion\"] == \"características\"\n    assert out[\"caracteristicas\"][0] == {\"nombre\": \"Resolución\", \"valor\": \"4K\"}\n    assert out[\"caracteristicas\"][1][\"valor\"] == \"diseñado en ES\"\n",
  "oldString": "def test_decode_response_empty_body():\n    resp = _FakeResp(b\"\")\n    assert se.decode_response(resp) == \"\""
}
```

**Output:**
```
Edit applied successfully.
```

---

## Assistant (Build · Big Pickle · 4.7s)

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python -m pytest tests/test_spec_extractors.py -q 2>&1 | tail -6",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
.....................                                                    [100%]

```

---

## Assistant (Build · Big Pickle · 19.3s)

_Thinking:_

All pass. Let me run the full suite one more time (minus the pre-existing failing test) and also verify the diff view template still compiles (unchanged this round).

Also, let me double check `official_scraper.py` uses `spec_extractors` (already confirmed — line 262). And `ai_agent.py` uses `spec_extractors.normalize_product` — spec_extractors imported as module (`from . import spec_extractors`), so `spec_extractors.normalize_product` works.

Let me run the full suite.

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python -m pytest tests/ -q --deselect tests/test_prestashop_helpers.py::test_read_only_fields_removed_on_put 2>&1 | tail -4",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
........................................................................ [ 56%]
.......................................................                  [100%]

```

---

## Assistant (Build · Big Pickle · 8.0s)

_Thinking:_

All tests pass. Let me summarize what I found and fixed.

The user reported: "los acentos a veces no se escriben y en lugar de eso aparece un codigo" (accents sometimes don't render, instead a code appears).

Diagnosis (from real DB data):
1. **Mojibake** — UTF-8 bytes decoded as latin-1 (`caracterÃ\xadsticas`, `resoluciÃ³n` → should be `características`, `resolución`).
2. **Literal HTML entities** — `&#225;`, `&quot;`, `&amp;`, `&amp;nbsp;` stored as visible "codes".
3. **Double-escaped entities** — `&amp;nbsp;`, `&#039;`.

Fix — a normalization layer (`normalize_text` + `normalize_product` in spec_extractors.py) applied at every boundary:
- `ai_agent._parse_page` (scrape result)
- `official_scraper.scrape_from_direct_url` + `_scrape_pdf_datasheet`
- `enrich.py`: stored-data reuse (Path A), `_build_description`, `_push_to_prestashop`
- `check_active.py`: proposal reuse + push
- `admin_ui/app.py` approve

Tests added. All pass.

Let me give a concise summary.

Encontré el problema y lo corregí. En la BD había datos corruptos de dos tipos:

1. **Mojibake** — texto UTF-8 leído como latin-1: `resoluciÃ³n` en vez de `resolución`, `caracterÃ\xadsticas` en vez de `características`.
2. **Entidades HTML literales** — `&#225;`, `&quot;`, `&amp;nbsp;`, `&#039;` guardadas como texto visible (los "códigos" que ves).

**Fix:** capa de normalización `normalize_text`/`normalize_product` en `middleware/spec_extractors.py:78`, aplicada en todos los puntos de entrada/salida:

- `ai_agent.py:_parse_page` — resultados de scraping
- `official_scraper.py` — `scrape_from_direct_url` y `_scrape_pdf_datasheet`
- `enrich.py` — reutilización de datos guardados, `_build_description`, `_push_to_prestashop`
- `check_active.py` — reutilización + push de auto-completado
- `admin_ui/app.py` — aprobación (descripción, descripción corta y características)

La función decodifica entidades (hasta 2 niveles: `&amp;nbsp;` → espacio) y repara mojibake re-codificando latin-1→UTF-8, dejando intacto el texto ya correcto (verificado contra ejemplos reales de la BD). Agregué tests en `tests/test_spec_extractors.py`; toda la suite pasa (el único fallo, `test_read_only_fields_removed_on_put`, ya existía).

---

## User

ERROR:admin_ui.app:Exception on /run-once [POST]
Traceback (most recent call last):
  File "/home/icrocetti/dev/ProyectoDC/venv/lib/python3.14/site-packages/flask/app.py", line 1511, in wsgi_app
    response = self.full_dispatch_request()
  File "/home/icrocetti/dev/ProyectoDC/venv/lib/python3.14/site-packages/flask/app.py", line 919, in full_dispatch_request
    rv = self.handle_user_exception(e)
  File "/home/icrocetti/dev/ProyectoDC/venv/lib/python3.14/site-packages/flask/app.py", line 917, in full_dispatch_request
    rv = self.dispatch_request()
  File "/home/icrocetti/dev/ProyectoDC/venv/lib/python3.14/site-packages/flask/app.py", line 902, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)  # type: ignore[no-any-return]
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/home/icrocetti/dev/ProyectoDC/admin_ui/app.py", line 713, in run_once
    conn.close()
    ~~~~~~~~~~^^
  File "/home/icrocetti/dev/ProyectoDC/middleware/enrich.py", line 24, in <module>
    from .spec_extractors import is_template_placeholder, normalize_product, normalize_text
ImportError: cannot import name 'normalize_product' from 'middleware.spec_extractors' (/home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py) Fijate porque me parece que tampoco selecciona bien los productos

---

## Assistant (Build · Big Pickle · 8.1s)

_Thinking:_

The error says `cannot import name 'normalize_product' from 'middleware.spec_extractors'`. But I added it. The traceback shows the import failing at enrich.py line 24. This is odd — the function exists in the file.

Wait — maybe there's a stale `.pyc` file, or the admin process is running with an old cached version. But the traceback shows the import error happening at runtime. Let me check the current state of spec_extractors.py — maybe my edit didn't actually persist, or maybe there's a duplicate/conflicting definition, or the function is defined inside something.

Actually wait — the traceback might be from a RUNNING server process (old code loaded before my edits). But the user pasted a fresh error. Let me check: `middleware/spec_extractors.py` should have `normalize_product`. Let me verify the file content. Also the user says "me parece que tampoco selecciona bien los productos" — the product selection issue: `/run-once` is a run-once override that uses `plan.matches_name` for product selection. The user thinks product selection isn't working well either.

Let me first verify the import issue.

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python -c \"import ast; t=ast.parse(open('middleware/spec_extractors.py').read()); names=[n.name for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]; print([n for n in names if 'normalize' in n])\" && venv/bin/python -c \"from middleware.spec_extractors import normalize_text, normalize_product; print('import OK')\"",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
['normalize_text', 'normalize_product']
import OK

```

---

## Assistant (Build · Big Pickle · 7.6s)

_Thinking:_

The import works fine now. The error the user got was probably from a stale running server (started before my changes, or with cached .pyc). But wait — the traceback shows `middleware/enrich.py`, line 24: `from .spec_extractors import is_template_placeholder, normalize_product, normalize_text`. That's MY edit. So the code HAS my change but the import fails at runtime. How can that be, when the current file imports fine?

Possibility: the running admin process has an old `.pyc` of spec_extractors.py (compiled before normalize_product existed) but a new `.pyc` of enrich.py? Actually Python recompiles when mtime changes. If the running process was started after enrich.py was edited but before spec_extractors was fully written... Or a bytecode cache issue where enrich.py got recompiled with new import but spec_extractors.pyc is stale. Since spec_extractors.py mtime is NEWER than enrich.py's edit (I edited spec_extractors first, then enrich), the stale .pyc scenario is weird.

Most likely: the admin server was started BEFORE my changes and had loaded old spec_extractors. When a request came in, enrich.py was re-imported fresh (Flask dev reloader?), but spec_extractors module was already imported under the old name space. Actually if spec_extractors was already imported without normalize_product, and then enrich.py gets recompiled (because its mtime changed and reloader triggers) — the reloader restarts the whole process though.

Actually the simplest explanation: the user ran the server before I made all edits, or there's a stale __pycache__. The fix for the user: restart the admin server / clear __pycache__. Let me check if there's a stale pyc.

El import funciona ahora. Probablemente el proceso del admin quedó corriendo con código viejo o hay `.pyc` obsoleto. Verifico:

**Tool: bash**

**Input:**
```json
{
  "command": "ls -la middleware/__pycache__/spec_extractors*.pyc 2>/dev/null; venv/bin/python -c \"\nimport sys; sys.path.insert(0,'.')\nimport middleware.spec_extractors as m\nprint('spec_extractors importado desde:', m.__file__)\nprint('tiene normalize_product:', hasattr(m,'normalize_product'))\n\"",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
-rw-r--r-- 1 icrocetti icrocetti 43548 Aug 12 08:48 middleware/__pycache__/spec_extractors.cpython-314.pyc
spec_extractors importado desde: /home/icrocetti/dev/ProyectoDC/middleware/spec_extractors.py
tiene normalize_product: True

```

---

## Assistant (Build · Big Pickle · 5.3s)

_Thinking:_

The pyc is from 08:48 which is after my edits (the timestamp of the pyc is after). And the import works. So the user's error is from a running server process started BEFORE my edits (it holds the old module in memory). The admin server needs a restart. But I can't restart their server. Let me tell them to restart.

Now, the second part: "me parece que tampoco selecciona bien los productos" (product selection doesn't work well). This relates to `/run-once` which uses `plan.matches_name` (name similarity based selection). Let me look at the run_once route and the plan matching to see if there's a bug.

Let me read the run_once route in admin_ui/app.py around line 713.

El import funciona — el error es del proceso del admin que quedó corriendo con código viejo en memoria (reiniciarlo lo resuelve). Ahora reviso la selección de productos en `/run-once`:

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/admin_ui/app.py",
  "limit": 80,
  "offset": 660
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/admin_ui/app.py</path>
<type>file</type>
<content>
660: # ======================================================================
661: # Run full pipeline (extract + enrich, same as pipeline.py)
662: # ======================================================================
663: 
664: @app.route("/run-pipeline", methods=["POST"])
665: def run_pipeline():
666:     """Extract inactive products then enrich them — mirrors ``python pipeline.py``."""
667:     if not _acquire_pipeline_lock():
668:         return jsonify({"ok": False, "error": "El pipeline ya está ejecutándose"}), 409
669: 
670:     from middleware import pipeline_state
671:     from middleware.enrich import run as enrich_run
672:     from middleware.extract import run as extract_run
673: 
674:     def _run():
675:         try:
676:             extract_run(dry_run=False)
677:             enrich_run(dry_run=False)
678:         except Exception as exc:
679:             logger.error("Pipeline error: %s", exc)
680:             pipeline_state.add_log(f"ERROR: {exc}")
681:         finally:
682:             pipeline_state.finish()
683:             _release_pipeline_lock()
684: 
685:     t = threading.Thread(target=_run, daemon=True)
686:     t.start()
687:     return jsonify({"ok": True, "redirect": url_for("dashboard")})
688: 
689: 
690: @app.route("/run-once", methods=["POST"])
691: def run_once():
692:     """Ejecución única: corre el pipeline UNA vez con el objetivo indicado
693:     (tipo + cantidad), sin modificar el plan configurado."""
694:     from middleware import plan
695:     from middleware.db import get_connection
696: 
697:     sub = (request.form.get("run_sub", "") or "").strip()
698:     try:
699:         cant = int(request.form.get("run_cant", "") or 0)
700:     except (TypeError, ValueError):
701:         cant = 0
702:     override = {
703:         "subcategoria": sub or None,
704:         "cantidad": cant or None,
705:     }
706:     if not override["subcategoria"] and not override["cantidad"]:
707:         return jsonify({"ok": False, "error": "Indicá tipo y/o cantidad"}), 400
708: 
709:     conn = get_connection()
710:     try:
711:         objetivo = plan.describe_target(conn, override["subcategoria"], override["cantidad"])
712:     finally:
713:         conn.close()
714: 
715:     if not _acquire_pipeline_lock():
716:         return jsonify({"ok": False, "error": "El pipeline ya está ejecutándose"}), 409
717: 
718:     from middleware import pipeline_state
719:     from middleware.enrich import run as enrich_run
720:     from middleware.extract import run as extract_run
721: 
722:     def _run():
723:         try:
724:             pipeline_state.add_log(f"Ejecución única iniciada: {objetivo}")
725:             extract_run(dry_run=False, override=override)
726:             enrich_run(dry_run=False, override=override)
727:             pipeline_state.add_log(f"Ejecución única finalizada: {objetivo}")
728:         except Exception as exc:
729:             logger.error("Run-once error: %s", exc)
730:             pipeline_state.add_log(f"ERROR: {exc}")
731:         finally:
732:             pipeline_state.finish()
733:             _release_pipeline_lock()
734: 
735:     t = threading.Thread(target=_run, daemon=True)
736:     t.start()
737:     return jsonify({"ok": True, "objetivo": objetivo, "redirect": url_for("dashboard")})
738: 
739: 

(Showing lines 660-739 of 1174. Use offset=740 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 3.8s)

_Thinking:_

The run_once route calls `extract_run(dry_run=False, override=override)` and `enrich_run(dry_run=False, override=override)`. Let me check `extract.run()` signature — does it accept `override`? Let me look at extract.py's run signature.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/extract.py",
  "limit": 75,
  "offset": 1
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/extract.py</path>
<type>file</type>
<content>
1: import logging
2: 
3: from . import pipeline_state, plan
4: from .config import BATCH_SIZE
5: from .db import (
6:     ensure_subcategoria,
7:     get_connection,
8:     get_subcategoria_by_ps_category,
9:     has_ean_in_db,
10:     has_id_in_db,
11:     has_product_not_found,
12:     insert_product,
13:     sync_producto_from_prestashop,
14: )
15: from .prestashop import PrestashopClient
16: 
17: logger = logging.getLogger(__name__)
18: 
19: 
20: def _short_circuit(id_prestashop: int, ean: str | None) -> bool:
21:     """Check whether this product can be skipped.
22: 
23:     RF-04 — EAN already exists in local DB.
24:     RF-05 — product was previously marked as not found.
25:     """
26:     if ean and has_ean_in_db(ean):
27:         return True
28:     if has_id_in_db(id_prestashop):
29:         return True
30:     if has_product_not_found(ean, id_prestashop):
31:         return True
32:     return False
33: 
34: 
35: def run(dry_run: bool = False, override: dict | None = None) -> list[dict]:
36:     """Extraer productos inactivos de PrestaShop a la BD local.
37: 
38:     ``override`` (opcional) es un dict ``{'subcategoria': str, 'cantidad': int}``
39:     para una ejecución única: se usa ESE objetivo en vez del plan configurado,
40:     sin modificarlo.
41:     """
42:     """Extraction pipeline (RF-01, RF-02, RF-04, RF-05, RF-10).
43: 
44:     Steps
45:     -----
46:     1. Fetch manufacturer name map from PrestaShop.
47:     2. Walk inactive products in pages, checking stock (RF-01 / RF-02).
48:     3. Cross-reference EAN / id_prestashop against local DB — short-circuit if
49:        already known (RF-04, RF-05).
50:     4. Insert new products into ``productos`` with
51:        ``estado_actualizacion = 'desactualizado'`` for later enrichment processing.
52:     5. Respect batch-size limit and API throttle (RF-10).
53:     """
54:     client = PrestashopClient()
55: 
56:     # -- 0. Plan de trabajo (objetivo por tipo de producto + cantidad) -------
57:     #    La ejecución única (override) gana sobre el plan sin modificarlo.
58:     #    La SELECCIÓN de productos del plan se hace por similitud del nombre
59:     #    con el tipo de producto objetivo (ver plan.matches_name).
60:     target_sub = (
61:         (override or {}).get("subcategoria")
62:         or plan.effective_subcategoria()
63:     )
64:     target_count = (
65:         (override or {}).get("cantidad")
66:         or plan.effective_cantidad(BATCH_SIZE)
67:     )
68: 
69:     target_name = target_sub if target_sub else None
70:     conn_lookup = get_connection()
71:     try:
72:         objetivo = (
73:             plan.describe_target(conn_lookup, target_sub, target_count)
74:             if override
75:             else plan.describe_plan(conn_lookup)

(Showing lines 1-75 of 214. Use offset=76 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 4.2s)

_Thinking:_

The extract.run accepts override. The enrich.run accepts override too. So the run_once route passes override correctly.

Now the user says "tampoco selecciona bien los productos" — product selection isn't working well. The selection uses `plan.matches_name(target_sub, nombre)` — name similarity, token-based. Let me look at `plan.matches_name` and `_token_similar` to find issues.

Let me read middleware/plan.py.

**Tool: read**

**Input:**
```json
{
  "filePath": "/home/icrocetti/dev/ProyectoDC/middleware/plan.py",
  "limit": 110,
  "offset": 36
}
```

**Output:**
```
<path>/home/icrocetti/dev/ProyectoDC/middleware/plan.py</path>
<type>file</type>
<content>
36: 
37: 
38: # ── similitud por nombre ────────────────────────────────────────────────
39: # Selección de productos por tipo de producto: se matchea el texto objetivo
40: # contra el NOMBRE del producto por similitud de palabras (no por subcategoría
41: # exacta).  Ej: tipo "MONITORES" alcanza a "Monitor LED 24" y tipo
42: # "MOTOSIERRAS" alcanza a "Motosierra a gasolina".
43: 
44: _STOPWORDS = {
45:     "para", "con", "los", "las", "del", "de", "el", "la", "en", "y",
46:     "o", "a", "al", "una", "un", "unas", "unos", "por", "que", "sin",
47:     "como", "se", "su", "sus", "es", "son", "le", "lo", "mas", "más",
48:     "etc", "tipo", "producto",
49: }
50: 
51: 
52: def _strip_accents(text: str) -> str:
53:     nfkd = unicodedata.normalize("NFKD", text or "")
54:     return "".join(c for c in nfkd if not unicodedata.combining(c))
55: 
56: 
57: def significant_tokens(text: str) -> list[str]:
58:     """Términos significativos de *text* (sin acentos, en mayúsculas).
59: 
60:     Se descartan palabras cortas (< 3 chars) y stopwords gramaticales.
61:     Ej: "MOTOSIERRAS A GASOLINA" → ["MOTOSIERRAS", "GASOLINA"].
62:     """
63:     norm = _strip_accents(text or "").upper()
64:     tokens = [t for t in re.split(r"[^A-Z0-9]+", norm) if len(t) >= 3]
65:     return [t for t in tokens if t not in _STOPWORDS]
66: 
67: 
68: def _token_similar(a: str, b: str) -> bool:
69:     """¿Los tokens *a* y *b* representan la misma palabra?
70: 
71:     Igualdad exacta, semejanza (singular/plural, typos, variantes) o
72:     contención con prefijo largo compartido (ej: MONITORES ↔ MONITOR).
73:     """
74:     if a == b:
75:         return True
76:     if SequenceMatcher(None, a, b).ratio() >= 0.8:
77:         return True
78:     shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
79:     return len(shorter) >= 6 and shorter in longer
80: 
81: 
82: def matches_name(target: str, product_name: str) -> bool:
83:     """¿Es *product_name* similar al texto objetivo (tipo de producto)?
84: 
85:     Regla: cada término significativo del objetivo debe aparecer (exacto o
86:     parecido) en el nombre del producto.  Si el objetivo no tiene términos
87:     significativos (todo stopwords/palabras cortas), se usa coincidencia de
88:     subcadena.
89:     """
90:     tokens = significant_tokens(target)
91:     name_norm = _strip_accents(product_name or "").upper()
92:     if not tokens:
93:         return _strip_accents(target or "").upper() in name_norm
94:     name_tokens = set(re.split(r"[^A-Z0-9]+", name_norm))
95:     return all(any(_token_similar(t, nt) for nt in name_tokens) for t in tokens)
96: 
97: 
98: def _read(key: str) -> str:
99:     try:
100:         conn = sqlite3.connect(os.getenv("DB_PATH", "catalogo.db"))
101:         try:
102:             row = conn.execute(
103:                 "SELECT valor FROM config WHERE clave = ?", (key,)
104:             ).fetchone()
105:             return row[0] if row else ""
106:         finally:
107:             conn.close()
108:     except Exception:
109:         return ""
110: 
111: 
112: def _write(key: str, value: str) -> None:
113:     try:
114:         conn = sqlite3.connect(os.getenv("DB_PATH", "catalogo.db"))
115:         try:
116:             conn.execute(
117:                 "INSERT INTO config (clave, valor) VALUES (?, ?) "
118:                 "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
119:                 (key, value),
120:             )
121:             conn.commit()
122:         finally:
123:             conn.close()
124:     except Exception:
125:         pass
126:     try:
127:         from .config import reload_db_config
128:         reload_db_config()
129:     except Exception:
130:         pass
131: 
132: 
133: def _parse_int(raw, default: int | None = None) -> int | None:
134:     try:
135:         n = int(raw)
136:     except (TypeError, ValueError):
137:         return default
138:     return n if n > 0 else default
139: 
140: 
141: # ── plan activo ────────────────────────────────────────────────────────
142: 
143: def set_active(subcategoria: str, cantidad: str) -> None:
144:     """Guardar el plan activo (``""`` limpia el valor)."""
145:     _write("plan_subcategoria", (subcategoria or "").strip())

(Showing lines 36-145 of 251. Use offset=146 to continue.)
</content>
```

---

## Assistant (Build · Big Pickle · 22.3s)

_Thinking:_

Now let me analyze `matches_name`. The rule: every significant token of the target must appear in the product name (exact or similar).

Issue candidates:
1. **`_token_similar` with `SequenceMatcher.ratio() >= 0.8`**: This is loose. E.g. target "CINTA" vs name token "CINCHA"? ratio("CINTA","CINCHA") = ... C-I-N-T-A vs C-I-N-C-H-A. Common: CIN (3). length 5,6. ratio = 2*3/(5+6)=6/11=0.545. No. What about "CINTA" vs "CINTO"? 2*4/10=0.8 → matches! So target "CINTA" (tape) would match product "CINTO" (belt). Hmm, that could be a wrong selection.

2. **`len(shorter) >= 6 and shorter in longer`**: e.g. target "CINTA" (5 chars) won't do containment. But "ESPUMA" (6) in "ESPUMAS" → match. That's fine (plural).

3. The bigger issue: **`matches_name` requires ALL target tokens to match**. But in `enrich.run`, the target filter is applied via `matches_name(plan_sub, r["nombre"])` — same function. And in `extract.run` too.

4. What about the **target being a subcategoria name** like "CINTAS ADHESIVAS" vs a product "CINTA SCOTCH 5CM"? tokens = ["CINTAS", "ADHESIVAS"]. name_tokens = {"CINTA","SCOTCH","5CM"}. "CINTAS" ~ "CINTA" (ratio 2*5/11=0.909 → similar). "ADHESIVAS" vs name tokens {CINTA,SCOTCH,5CM} — no match → product NOT selected! So a "CINTA SCOTCH 5CM" would NOT be selected for target "CINTAS ADHESIVAS" because "ADHESIVAS" isn't in the name. That's the "no selecciona bien los productos" problem — too strict (requires ALL target terms).

Wait, but actually the user said "tampoco selecciona bien los productos" — "also doesn't select products well". Given the context (the previous fix was about name changes / the scotch tape vs Redmi example), the user is worried selection picks the WRONG products (like a scotch tape picking a Redmi phone) OR doesn't pick the right ones.

Actually — re-reading the very first message: "si yo quiero una cinta scotch de 5cm de espesor no tiene sentido que me de un celular 15c redmi". So the complaint is that selection/enrichment gives wrong products. Now with the run-once error, the user says "me parece que tampoco selecciona bien los productos" — they think product selection isn't right either.

But the immediate actionable thing: the ImportError is from a stale running process. Let me address both:

1. **ImportError** — tell user to restart the admin server (the code is fine; the running process has old modules in memory). I could also add a defensive measure but the real fix is restart.

2. **Product selection** — let me investigate `matches_name` issues and the `enrich.run` filtering with `plan_limit*20`. Let me think about what "selecciona mal" means concretely.

Let me look at the settings.html run-once form to understand what the user enters. Also let me re-check how target_sub is used in extract: `target_name = target_sub` then `plan.matches_name(target_name, nombre)` filters candidates. So if the user sets the run-once target to "CINTA SCOTCH", products whose names contain "cinta" or "scotch" get selected. `matches_name` requires ALL target tokens present. "CINTA SCOTCH" → tokens CINTA, SCOTCH. A product "CINTA SCOTCH 5CM" → both present. OK.

But the enrich selection: `matches_name(plan_sub, r["nombre"] or "")`. If plan_sub is a subcategoria name like "CINTAS ADHESIVAS" and products are "CINTA SCOTCH 5CM", "CINTA TRANSPARENTE", then "ADHESIVAS" won't match and NOTHING gets selected. That's under-selection.

Conversely, over-selection: `_token_similar` with 0.8 ratio. e.g. target "CINTA" matches name "CINTO"? ratio 0.8 → yes. Or "GOMA" vs "GOMAS" → containment (len 4 <6, ratio 2*4/9=0.889 → similar) yes. That's fine.

Actually, the "selecciona mal" might refer to: the run-once picks products that are NOT of the requested type (e.g. requesting "cinta scotch 5cm" and it enriches a Redmi phone). But that's the enrichment identity validation (already handled). Or the extract selection pulling wrong products into the local DB.

Hmm. Actually let me reconsider. The most impactful bug in selection: in `extract.run`, `matches_name` uses AND logic (all target tokens must match). But the products' names in the DB might use synonyms or include extra words. E.g. target "CINTA SCOTCH" — product "CINTA ADHESIVA 5CM" — "SCOTCH" not in name → not selected, even though scotch tape == adhesive tape. So selection is strict on literal words.

But more importantly — I wonder if there's an actual BUG (crash) in selection. The user pasted a traceback that shows the ImportError. "Fijate porque me parece que tampoco selecciona bien los productos" — maybe they mean: since run-once crashes with ImportError, nothing gets selected/processed at all. "tampoco selecciona bien" could just mean "and it seems it also doesn't select products correctly" — maybe because of the crash.

Let me verify there isn't a real selection bug by examining the `enrich.run` fetch limit logic and the override handling. Let me re-read enrich.run's override + selection, lines 615-660 (already seen). It looks fine.

Let me focus: what should I actually DO? The user wants:
1. Fix the run-once error (ImportError). — Root cause: stale server process. But wait — maybe the user DID restart and still gets it? Let me double-check there's no circular import or something at admin startup. Let me test importing admin_ui.app fresh in a clean process. I already did `from admin_ui import app` successfully. So a fresh process works. The error is from a stale process.

Actually — hold on. Let me reconsider. The traceback shows `admin_ui/app.py line 713, conn.close()` then enrich.py import. The import happens inside run_once because it's deferred (line 719: `from middleware.enrich import run as enrich_run`). In the STALE process, `middleware.spec_extractors` was imported BEFORE I added normalize_product (old version, no normalize_product). enrich.py line 24 was ALSO edited in that stale process? No — the stale process loaded enrich.py before edits. But the traceback shows enrich.py line 24 HAS the new import line. So enrich.py IS the new version in that process!

That means: the process imported enrich.py (new, imports normalize_product) but spec_extractors in that process is OLD (no normalize_product). This happens if: the process started after enrich.py edit but spec_extractors.pyc was stale/cached... but the pyc now is 08:48. Actually, if the server process was started BEFORE all my edits, it would have OLD enrich.py too (without line 24 import). Unless Flask's debug reloader picked up enrich.py change but not spec_extractors change.

Actually the most plausible: the server was running with `--debug` (Flask reloader). It auto-reloaded when enrich.py changed, but the reloader imports spec_extractors from the stale in-memory module graph? No, reloader restarts fresh.

Alternatively — the user's admin.py imports `from middleware.enrich import run` at startup, and enrich imports spec_extractors at startup. If the process started when spec_extractors.py was mid-edit (I edited it first, then ai_agent, then official_scraper, then enrich), maybe the process started between my edits — spec_extractors new (has normalize_product) then... no.

Whatever — the code is now correct and a fresh process works. The answer: restart the admin server. But let me ALSO make the fix more robust: the user shouldn't hit this again. I can't control their server. But I should verify admin.py starts clean.

Let me now investigate the selection concern seriously, because the user explicitly flagged it. Let me test `matches_name` with realistic cases to find under/over-selection bugs.

Let me look at the subcategorias in the DB and test matches_name against real product names.

El ImportError es por el proceso viejo — el código actual importa bien, hay que reiniciar el admin. Ahora verifico la selección de productos con datos reales:

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python - <<'EOF'\nfrom middleware.plan import matches_name, significant_tokens\nimport sqlite3\n\nconn = sqlite3.connect('catalogo.db')\nconn.row_factory = sqlite3.Row\nsubs = [r['nombre_subcategoria'] for r in conn.execute(\"SELECT nombre_subcategoria FROM subcategorias ORDER BY nombre_subcategoria\")]\nnames = [r['nombre'] for r in conn.execute(\"SELECT DISTINCT nombre FROM productos WHERE nombre IS NOT NULL AND nombre != ''\")]\nprint(\"subcategorias:\", subs)\nprint()\n# test: for each subcategory, how many product names match\nfor sub in subs:\n    hits = [n for n in names if matches_name(sub, n)]\n    print(f\"{sub!r} -> {len(hits)} productos. ej: {hits[:4]}\")\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
subcategorias: ['ACCESORIOS TELEFONIA', 'ALL IN ONE', 'CELULARES LIBRES', 'CONSOLAS', 'FILAMENTOS Y RESINAS', 'IMPRESORAS FDM', 'IMPRESORAS RESINA', 'MONITORES', 'MOUSES CON CABLE', 'MOUSES ERGONOMICOS', 'MOUSES INALAMBRICOS', 'NOTEBOOKS', 'PERIFERICOS GAMER', 'PROYECTORES', 'SILLAS GAMER', 'SIN CLASIFICAR', 'SMART TV', 'SMARTPHONES', 'ULTRABOOKS']

'ACCESORIOS TELEFONIA' -> 0 productos. ej: []
'ALL IN ONE' -> 0 productos. ej: []
'CELULARES LIBRES' -> 0 productos. ej: []
'CONSOLAS' -> 0 productos. ej: []
'FILAMENTOS Y RESINAS' -> 0 productos. ej: []
'IMPRESORAS FDM' -> 0 productos. ej: []
'IMPRESORAS RESINA' -> 0 productos. ej: []
'MONITORES' -> 0 productos. ej: []
'MOUSES CON CABLE' -> 0 productos. ej: []
'MOUSES ERGONOMICOS' -> 0 productos. ej: []
'MOUSES INALAMBRICOS' -> 0 productos. ej: []
'NOTEBOOKS' -> 0 productos. ej: []
'PERIFERICOS GAMER' -> 0 productos. ej: []
'PROYECTORES' -> 0 productos. ej: []
'SILLAS GAMER' -> 0 productos. ej: []
'SIN CLASIFICAR' -> 0 productos. ej: []
'SMART TV' -> 2 productos. ej: ['TV 32 SAMSUNG 32T4300 HD SMART', 'TV 43 SAMSUNG 43T5300 SMART FHD']
'SMARTPHONES' -> 0 productos. ej: []
'ULTRABOOKS' -> 0 productos. ej: []

```

---

## Assistant (Build · Big Pickle · 4.6s)

_Thinking:_

Very revealing! Almost NO products match their subcategory names! Only "SMART TV" matches 2. Let me look at the product names to understand why. Let me sample the product names.

Casi ningún producto matchea su subcategoría — veamos los nombres reales:

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python - <<'EOF'\nimport sqlite3\nconn = sqlite3.connect('catalogo.db')\nconn.row_factory = sqlite3.Row\nrows = conn.execute(\"\"\"SELECT p.id_prestashop, p.nombre, s.nombre_subcategoria\n                       FROM productos p LEFT JOIN subcategorias s ON p.id_subcategoria=s.id_subcategoria\n                       ORDER BY s.nombre_subcategoria, p.nombre LIMIT 60\"\"\").fetchall()\nfor r in rows:\n    print(f\"[{r['nombre_subcategoria'] or '?'}] {r['nombre']}\")\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
[SIN CLASIFICAR] 
[SIN CLASIFICAR] 
[SIN CLASIFICAR] .
[SIN CLASIFICAR] AAA NEW PRUEBA JAJAJA
[SIN CLASIFICAR] ABRELATAS
[SIN CLASIFICAR] ACELEADOR COMPLETO
[SIN CLASIFICAR] ACOLCHADO COLORES 1 PLAZA
[SIN CLASIFICAR] ACONDICIONADOR FRUCTIS LISO COCO x350ml
[SIN CLASIFICAR] ACONDICIONADOR ISSUE SALONN x930ml -NEUTROYBETOX-
[SIN CLASIFICAR] ADMISION DESMALEZADORA 33CC
[SIN CLASIFICAR] ADMISION DESMALEZADORA 43-52CC
[SIN CLASIFICAR] AGUJA CHICA X 25 UNIDADES
[SIN CLASIFICAR] AGUJA GRANDE X 25 UNIDADES
[SIN CLASIFICAR] AGUJA MOTOR 5.5 - 6.5 HP
[SIN CLASIFICAR] AGUJA MOTOR 9 - 13 HP
[SIN CLASIFICAR] AGUJA MOTOR GX160 HONDA X 1 UNIDADE
[SIN CLASIFICAR] AMORTIGUADOR DESMALEZADORA CHINAS 33-52
[SIN CLASIFICAR] AMORTIGUADOR MOTOSIERRAS CHINAS LARGO
[SIN CLASIFICAR] ARNES DESMALEZADORAS ECONOMICO
[SIN CLASIFICAR] BOBINA ENCENDIDO 52CC DESMALEZADORA
[SIN CLASIFICAR] BOBINA ENCENDIDO MOTOSIERRA 38CC
[SIN CLASIFICAR] BOBINA MOTOGUADAÑA BLACK & DEKER
[SIN CLASIFICAR] BOBINA MOTOR 5.5HP
[SIN CLASIFICAR] BOBINA MOTOSIERRAS CHINA 45-52
[SIN CLASIFICAR] BOMBA DE ACEITE MOTOSIERRA 38CC
[SIN CLASIFICAR] BOMBA DE ACEITE MOTOSIERRAS 45-52CC
[SIN CLASIFICAR] BOMBIN B&S 3.5HP
[SIN CLASIFICAR] BOMBIN B&S 6HP
[SIN CLASIFICAR] BOMBIN C /ZOCALO
[SIN CLASIFICAR] BOMBIN C/CLIP
[SIN CLASIFICAR] BOMBIN CHICO
[SIN CLASIFICAR] BOMBIN GRANDE
[SIN CLASIFICAR] BUJIA CHAMPION CJ8
[SIN CLASIFICAR] BUJIA CHAMPION J19LM
[SIN CLASIFICAR] BUJIA CHAMPION N9YC
[SIN CLASIFICAR] BUJIA CHAMPION RC12YC
[SIN CLASIFICAR] BUJIA CHAMPION RC7YC
[SIN CLASIFICAR] BUJIA CHAMPION RCJ7Y
[SIN CLASIFICAR] BUJIA NGK B2LM
[SIN CLASIFICAR] BUJIA NGK BM6A
[SIN CLASIFICAR] CAJA ARRANQUE MOTOSIERRA 38
[SIN CLASIFICAR] CAJA ARRANQUE MOTOSIERRA 45
[SIN CLASIFICAR] CAJA ARRANQUE MOÑO
[SIN CLASIFICAR] CAJA ARRANQUE P.DOBLE MOTOSIERRA 50CC
[SIN CLASIFICAR] CAJA ENGRANAJE 9D -26MM
[SIN CLASIFICAR] CALCULADORA CASIO LC-403TV
[SIN CLASIFICAR] CARBURADOR DESMALEZADORA ECHO 4605
[SIN CLASIFICAR] CARBURADOR DESMALEZADORAS 43-52CC
[SIN CLASIFICAR] CARBURADOR MOTOSIERRA 38CC
[SIN CLASIFICAR] CARBURADOR MOTOSIERRA 45-50C
[SIN CLASIFICAR] CARCASA TORRETA POULAN
[SIN CLASIFICAR] CARDAN 9 DIENTES
[SIN CLASIFICAR] CARRETEL CORTE BAJO HUSQVARNA 12X1.75 NACIONA
[SIN CLASIFICAR] CARRETEL CORTE BAJO STIHL 12X1.50 NACIONAL
[SIN CLASIFICAR] CARRETELES CORTE BAJOS IMPORTADO
[SIN CLASIFICAR] CENTRO ESTRELLA EMBRAGUE 3 ZAPATAS MOTOSIERRA
[SIN CLASIFICAR] CILINDRO COMPLETO 33CC 36MM DESMALEZADORA
[SIN CLASIFICAR] CILINDRO COMPLETO 52CC 44MM DESMALEZADORA
[SIN CLASIFICAR] CILINDRO COMPLETO ECHO 4605
[SIN CLASIFICAR] CILINDRO COMPLETO HUSQVARNA 61

```

---

## Assistant (Build · Big Pickle · 10.8s)

_Thinking:_

The products are almost all "SIN CLASIFICAR" (unclassified). They're agricultural/garden tool parts (motosierras, desmalezadoras, bujias, etc.). These are the REAL products of this store. The subcategories in the DB (SMART TV, MOUSES, etc.) are template subcategories that don't match the actual inventory!

So the "selecciona mal" issue: the plan's target (tipo de producto) uses `matches_name`, which requires ALL significant tokens of the target to appear in the product name. If the user runs a run-once with a target like "CINTA SCOTCH" it matches products containing both words. But more relevant — the run-once form probably uses a subcategoria dropdown (from the `subcategorias` table), which has categories like "SMART TV", "NOTEBOOKS", etc., and NONE of the actual products match those. So running with a target gets 0 products. 

But wait — actually the subcategorias table might be different from what the user selects in the UI. The run-once form's `run_sub` — where does the dropdown come from? Let me check settings.html and the run_once form. The subcategorias dropdown would be populated from the DB `subcategorias` table. But the products are classified as "SIN CLASIFICAR" — meaning the extraction assigned them to SIN CLASIFICAR because their PrestaShop category didn't map to a local subcategoria.

Hmm, so there are two distinct issues:
1. The products get assigned "SIN CLASIFICAR" because `id_prestashop_categoria` mapping doesn't cover the actual PrestaShop categories.
2. The name-based selection (`matches_name`) requires ALL target tokens, so partial matches fail (e.g. "BUJIA CHAMPION" vs target "BUJIAS").

But the user's immediate message: "Fijate porque me parece que tampoco selecciona bien los productos" — in context of the run-once crash. Maybe they tested run-once, it crashed with the ImportError, so nothing was selected/processed. "tampoco selecciona bien los productos" = "it also doesn't select products properly" (referring to the enrichment queue behavior, or that after the crash the products don't get processed).

Actually let me re-read the full user message: "ERROR:admin_ui.app:Exception on /run-once [POST] ... ImportError: cannot import name 'normalize_product' ... Fijate porque me parece que tampoco selecciona bien los productos"

I think they're saying: "Check, because it seems it also doesn't select products well." The "también" (also) refers to the fact that beyond the crash, the product selection seems wrong.

The root cause of the crash: stale process. I should confirm the fix by restarting the server. But I can't restart their server. However — maybe I CAN. The admin is presumably running. Let me check if there's a running process I can restart. Actually, I should be careful about killing user processes. Let me check what's running.

Actually, let me focus on what I can concretely fix:

1. The ImportError — resolved by restarting the admin (code is correct). I'll tell the user. If there's a running server, I could offer to restart it.

2. Product selection — let me investigate whether there's a genuine bug. The concern: when the user runs a run-once with a specific type, does it select correctly?

Let me look at the real scenario. The run-once form — let me check settings.html for the run-once form and where run_sub values come from.

Los productos reales están casi todos en "SIN CLASIFICAR" y son repuestos de motosierras/desmalezadoras — muy distintos de las subcategorías de plantilla. Veo el formulario run-once:

**Tool: grep**

**Input:**
```json
{
  "include": "settings.html",
  "path": "/home/icrocetti/dev/ProyectoDC/admin_ui/templates",
  "pattern": "run_once|run_sub|run_cant|subcategoria"
}
```

**Output:**
```
Found 14 matches
/home/icrocetti/dev/ProyectoDC/admin_ui/templates/settings.html:
  Line 33:     <label for="plan_subcategoria">Tipo de producto (plan activo)</label>

  Line 34:     <input list="subcat-list" id="plan_subcategoria" name="plan_subcategoria"

  Line 37:       {% for s in subcategorias %}

  Line 57:           <input list="subcat-list" name="week_sub_{{ d.day }}" value="{{ d.subcategoria }}" placeholder="—">

  Line 74: <form method="post" action="{{ url_for('run_once') }}" class="settings-form runonce-form" id="run-once">

  Line 82:     <label for="run_sub">Tipo de producto</label>

  Line 83:     <input list="subcat-list" id="run_sub" name="run_sub" placeholder="Tipo de producto, ej: motosierras">

  Line 86:     <label for="run_cant">Cantidad</label>

  Line 87:     <input type="number" id="run_cant" name="run_cant" min="1" placeholder="10">

  Line 136:     var sub = form.run_sub.value.trim();

  Line 137:     var cant = form.run_cant.value.trim();

  Line 151:       body: 'run_sub=' + encodeURIComponent(sub) + '&run_cant=' + encodeURIComponent(cant)

  Line 159:           form.run_sub.value = '';

  Line 160:           form.run_cant.value = '';

```

---

## Assistant (Build · Big Pickle · 6.3s)

_Thinking:_

The run-once form has a free-text `run_sub` input with a datalist. The placeholder says "Tipo de producto, ej: motosierras". So the user types a free text like "motosierras". Then `matches_name("motosierras", nombre)` selects products with "motosierra" in the name.

Let me test with realistic targets the user might type:
- "motosierras" → matches "BOBINA MOTOSIERRA 38CC" etc. (singular/plural)
- "bujias" → "BUJIA CHAMPION" 
- "desmalezadoras" → "DESMALEZADORA..."

Let me test a few against the real names to see if matches_name behaves. Let me also check the earlier issue: `_token_similar` ratio >= 0.8 can produce false matches, but let's test the common scenarios.

**Tool: bash**

**Input:**
```json
{
  "command": "venv/bin/python - <<'EOF'\nfrom middleware.plan import matches_name\nnames = [\"BUJIA CHAMPION N9YC\",\"BOBINA MOTOSIERRA 38CC\",\"CARBURADOR DESMALEZADORA 43-52CC\",\"CINTA SCOTCH 5CM\",\"CINTA ADHESIVA TRANSPARENTE\",\"TORRETA MTD 82-403\",\"CALCULADORA CASIO LC-403TV\",\"TV 32 SAMSUNG 32T4300 HD SMART\"]\ntests = [\"motosierras\",\"bujias\",\"desmalezadoras\",\"cinta scotch\",\"cinta\",\"scotch\",\"torretas mtd\",\"casio calculadora\",\"smart tv\",\"bujia\",\"bombin\",\"repuestos motosierra\",\"espuma 5cm\"]\nfor t in tests:\n    hits = [n for n in names if matches_name(t, n)]\n    print(f\"{t!r:30} -> {hits}\")\nEOF",
  "workdir": "/home/icrocetti/dev/ProyectoDC"
}
```

**Output:**
```
'motosierras'                  -> ['BOBINA MOTOSIERRA 38CC']
'bujias'                       -> ['BUJIA CHAMPION N9YC']
'desmalezadoras'               -> ['CARBURADOR DESMALEZADORA 43-52CC']
'cinta scotch'                 -> ['CINTA SCOTCH 5CM']
'cinta'                        -> ['CINTA SCOTCH 5CM', 'CINTA ADHESIVA TRANSPARENTE']
'scotch'                       -> ['CINTA SCOTCH 5CM']
'torretas mtd'                 -> ['TORRETA MTD 82-403']
'casio calculadora'            -> ['CALCULADORA CASIO LC-403TV']
'smart tv'                     -> ['TV 32 SAMSUNG 32T4300 HD SMART']
'bujia'                        -> ['BUJIA CHAMPION N9YC']
'bombin'                       -> ['BOBINA MOTOSIERRA 38CC']
'repuestos motosierra'         -> []
'espuma 5cm'                   -> []

```

---

## User

---

## Assistant (Compaction · Big Pickle · 48.1s)

---

## User

dale

---

## Assistant (Compaction · Big Pickle · 18.9s)

---

## User

continua con lo que hacia

---

## Assistant (Compaction · DeepSeek V4 Flash Free · 3.3s)

---

