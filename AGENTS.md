# Middleware PrestaShop ↔ Icecat

Python middleware: extracts inactive products (active=0, qty>1) from PrestaShop, enriches via Icecat, and provides a Flask admin UI for approval + push-back.

## Entrypoints

| Cmd                                                     | What                                                                         |
| ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `python main.py [-v] [--dry-run]`                       | Extract → enrich (Icecat, translate, embed, score). Always runs both phases. |
| `python admin.py [-v] [--host HOST] [--port PORT] [--debug]` | Flask admin UI — dashboard, diff, approve/reject/re-sync, audit log          |
| `python mock_prestashop.py [--host HOST] [--port PORT]` | Mock PrestaShop REST API (default port 8000)                                 |
| `python scripts/sync_categories.py`                     | Create PrestaShop categories from local categorias/subcategorias             |

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
sqlite3 catalogo.db < schema.sql          # base tables + seed data
```

`db.py:_ensure_schema()` auto-migrates on first `get_connection()` call — adds columns via ALTER TABLE and creates `audit_log`. No manual migration step needed.

- **Config:** `.env` via `python-dotenv` — never commit. Loaded by `middleware/config.py`.
- **Mock workflow:** start mock (`python mock_prestashop.py` on :8000), then set `PRESTASHOP_API_URL=http://localhost:8000/api` in `.env`.
- **Real PrestaShop:** `docker compose up -d`, then `scripts/setup_prestashop.sh` prints the API key. Backoffice at `http://localhost:8080/admin` (admin@prestashop.com / admin123).
- **Optional deps:** `sentence-transformers` and `deep-translator` — both wrapped in try/except ImportError.
- **Vector index:** `vector_index.sql` requires sqlite-vec — **not wired into app code yet**.
- **No linter, formatter, or test framework** configured.

## Architecture

```
middleware/              ← extraction + enrichment engine
  config.py             — env loader (BATCH_SIZE=10, API_SLEEP=2, DB_PATH=catalogo.db)
  db.py                 — SQLite helpers (WAL, foreign keys), auto-migration on first connect
  prestashop.py         — PrestashopClient (REST XML, read-only, HTTPBasicAuth)
  extract.py            — fetch inactive → stock filter → short-circuit → insert (stores nombre)
  icecat.py             — IcecatClient (Live JSON API, api-token header, normalizer)
  embedding.py          — sentence-transformers (all-MiniLM-L6-v2, 384-dim, LRU cached)
  translate.py          — GoogleTranslator with protected glossary (~60 tech terms)
  enrich.py             — pipeline: DB cache → URL template → Icecat → translate → embed → score → store → push
  characteristics.py    — merge_characteristics(): template + Icecat merge logic
  descriptions.py       — load product descriptions from 003 DESCRIPCIONES.xlsx
  official_scraper.py   — manual URL scraping (scrape_from_direct_url)
admin_ui/               ← Flask approval UI
  app.py                — routes: dashboard, diff, approve/reject/re-sync, scrape-url, audit
  prestashop.py         — AdminPrestashopClient (adds GET/PUT as JSON/XML, CDATA wrapping)
admin_ui/templates/     — 5 Jinja2 templates (base, dashboard, diff, products, audit)
scripts/
  setup_prestashop.sh   — docker compose up + enable webservice + generate API key
  sync_categories.py    — create PrestaShop categories from local categorias/subcategorias
migrations/             — SQL migration files (001_admin_ui.sql, 002_imagen_url.sql) — historical reference; db.py:_ensure_schema() is the source of truth
default_characteristics.json   — 79 templates with default values per subcategory
subcategory_mapping.json       — maps DB subcategoria name → template key (19 entries)
descripcion_mapping.json       — maps DB subcategoria name → Excel description key
brands_mapping.json            — maps brand name → direct URL template ({mpn} placeholder)
```

## Ingestion rules

- Filter: `active=0` + `quantity >= 1` (code uses `qty < 1` skip) + EAN/id not in `productos` + not previously `product_not_found`
- Batch: max 10 per run (`BATCH_SIZE`), 2s sleep between all external API calls (`API_SLEEP`)
- Products without subcategoría → assigned to `SIN CLASIFICAR` (auto-created, category 1)
- Products resolved to subcategory via PrestaShop's `id_category_default` → `subcategorias.id_prestashop_categoria` mapping

## Key flows

- **Extraction** (`middleware/extract.py`): walks inactive products page-by-page, fetches stock map for each page, keeps only qty>1, short-circuits if EAN/id already in DB or marked `product_not_found`, syncs local fields with PrestaShop data (PrestaShop is source of truth), resolves subcategory from product's `id_category_default` (matching `subcategorias.id_prestashop_categoria`), falls back to `SIN CLASIFICAR` if no match, inserts with `estado_actualizacion='desactualizado'`.
- **Enrichment** (`middleware/enrich.py`): selects `icecat_json IS NULL AND product_not_found = 0 AND icecat_not_found = 0`. For each product: (1) if brand has a URL template in `brands_mapping.json` and product has MPN, builds the URL and calls `scrape_from_direct_url` — if that succeeds, uses the scraped data directly; (2) otherwise falls back to Icecat (by EAN → Brand+MPN). Translates (glossary-protected), generates embedding + cosine score, stores `icecat_json` + `vector_descriptivo`. If all sources return 404, flags `icecat_not_found = 1` for manual URL enrichment via Admin UI. Merges characteristics with default template, builds description, pushes to PrestaShop.
- **Approval:** two approve modes — "Aprobar y activar" (PUTs descriptions + `active=1`) and "Aprobar (sin activar)" (only descriptions). Both merge Icecat characteristics with default template, build description as `*nombre*: valor` lines from merged characteristics, push to PrestaShop (descriptions + features). EAV written locally, marked `actualizado`. Audit distinguishes `aprobado` vs `aprobado_y_activado`. Reject clears `icecat_json`. Re-sync resets flags for retry.
- **Translation** (`middleware/translate.py`): glossary protects ~60 technical terms (OLED, USB-C, DDR5, RTX, etc.) via `\x00G{i}\x00` placeholder substitution. Does **not** translate `descripcion_corta`.
- **Embedding** (`middleware/embedding.py`): `all-MiniLM-L6-v2`, 384-dim float32, normalized. LRU cache (512 entries). Stored as raw bytes in `productos.vector_descriptivo`.

## Gotchas

- **Port conflict:** `.env` defaults to `localhost:8080/api` (real PrestaShop). Mock runs on **8000**. Change `.env` when switching.
- **modelo empty after extraction:** set to `""` during extraction. Populated during enrichment (from Icecat) or approval.
- **Approve modes:** two buttons in diff — "Aprobar y activar" pushes `active=1` + descriptions; "Aprobar (sin activar)" pushes only descriptions.
- **AdminPrestashopClient.\_set_field** (`admin_ui/prestashop.py:382`) handles `<language>` creation for multi-language fields — but only for keys in its hardcoded list (`description`, `description_short`, `name`, `link_rewrite`, `meta_title`, `meta_description`, `meta_keywords`, `delivery_in_stock`, `delivery_out_stock`, `available_now`, `available_later`).
- **CDATA wrapping:** `put_product` post-processes the XML to wrap `<language>` content in CDATA sections (`admin_ui/prestashop.py:_wrap_language_cdata`). Otherwise ElementTree escapes HTML entities and PrestaShop renders them literally.
- **Mock limitations:** `filter[active]` only supports `[0]`/`[1]`. Product list endpoint only returns manufacturer_name when `display=full` or `display=[...,manufacturer_name]`. Single product detail supports `?output_format=JSON`. Mock does not handle `active=1` writes — PUT handler only matches simple tags and a single `<language>` for description. Mock supports `POST /api/images/products/<pid>` for image upload testing.
- **Mock seed data:** products 101, 102, 105 (inactive, qty≥2), 103 (inactive, qty=1 → filtered by qty>1 rule), 104 (inactive, qty=0 → filtered), 201 (active → filtered). Product 103 has no EAN. Product 105 has `id_category_default=28` (SMART TV) to test category-based subcategory resolution. Stock: synthetic `stock_available` IDs = pid + 1000.
- **DB:** SQLite, WAL mode, foreign keys ON. `catalogo.db` is gitignored.
- **Icecat auth:** `api-token` header + `shopname` query param (not old `UserName`/`APIKey`). Credentials in `.env` — never log.
- **Icecat search order:** EAN first; if no EAN or not found, Brand+MPN fallback. All failed → marks `icecat_not_found = 1` (product stays in queue for manual URL enrichment via Admin UI).
- **Icecat normalizer** (`icecat.py:_normalize`): flattens raw `GeneralInfo`/`FeaturesGroups` to `{title, descripcion, descripcion_corta, marca, modelo, resumen, caracteristicas, imagen_url}`. Image URL extracted from `Image.HighPic` → `Pic500x500` → `LowPic`.
- **Product image upload** (`admin_ui/prestashop.py`): `upload_product_image` downloads from Icecat URL and POSTs to `POST /api/images/products/{id}`. Called during approval/pipeline. Failure is non-blocking (log warning, approval proceeds).
- **Characteristics as Features:** `sync_characteristics_as_features` creates each Icecat characteristic as a Feature + Feature Value in PrestaShop (`POST /api/features`, `POST /api/feature_values`), then passes `(id_feature, id_feature_value)` pairs to `put_product` for `<product_features>`. Fetches all existing features/values in 2 GETs (`_fetch_all_features`, `_fetch_all_feature_values`) and only POSTs new ones.
- **Feature value length limit:** PrestaShop rejects feature values longer than 255 chars. `sync_characteristics_as_features` truncates to 255 before POSTing.
- **Product category assignment:** `put_product` accepts `category_ids` to assign the product to corresponding PrestaShop categories. The pipeline passes the subcategory's PS category (from `subcategorias.id_prestashop_categoria`).
- **Default characteristics** (`middleware/characteristics.py`): `merge_characteristics()` merges Icecat characteristics with a default template per subcategory. Rules: (1) every template entry is included, (2) if Icecat has a characteristic with the same name (case-insensitive), its value overwrites the default, (3) extra Icecat characteristics are appended at the end.
- **Descriptions from Excel** (`middleware/descriptions.py`): reads `003 DESCRIPCIONES.xlsx` (DESCRIPCIONES sheet) and maps DB subcategory names to Excel entries via `descripcion_mapping.json`. **Not wired into the pipeline/approval yet** — currently the description is built entirely from merged characteristics as `*nombre*: valor` lines.
- **Official scraper** (`middleware/official_scraper.py`): `scrape_from_direct_url(url, product_id)` accepts a human-verified official URL, fetches the page, extracts JSON-LD/OG meta/HTML tables, and persists to EAV tables. Used by the Admin UI for manual URL enrichment.
- **icecat_not_found vs product_not_found:** `icecat_not_found` flags products where Icecat specifically returned 404 (eligible for manual URL enrichment). `product_not_found` flags products with no EAN/MPN or completely missing from all sources (excluded from all processing).
- **Manual URL enrichment:** `POST /products/<pid>/scrape-url` accepts a URL, calls `scrape_from_direct_url()`, which fetches the page, extracts JSON-LD/OG/HTML tables, writes to EAV, updates `icecat_json`, and clears `icecat_not_found`.
- **Product state field:** PrestaShop 8.1 requires `ps_product.state = 1` for products to appear in Catálogo > Productos. Products created via the webservice default to `state=0` (draft). `put_product` forces `state=1` alongside `visibility` and `indexed` to prevent invisible products.
- **PrestaShop client split:** `middleware/prestashop.py` is read-only (GET). `admin_ui/prestashop.py` extends it with PUT, image upload, and feature sync. Enrichment imports from `admin_ui.prestashop` for write operations.

## Guardrails

- **Throttle:** 2s sleep on every external API call (PrestaShop + Icecat)
- **Short-circuit:** local DB checks run before any Icecat call
- **Immutable audit:** `audit_log` table append-only

## Enrichment cascade (DB → URL template → Icecat → not-found → manual URL)

The enrichment pipeline (`middleware/enrich.py`) tries sources in order:

1. **Local DB** (existing `icecat_json`): if a previous run stored data but push failed, re-push without re-fetching.
2. **URL template** (`middleware/enrich.py:_build_url_template`): if the brand has a template in `brands_mapping.json` and the product has an MPN, builds the direct URL and calls `scrape_from_direct_url`. Deterministic, no search engines, no API credits.
3. **Icecat** (by EAN → Brand+MPN fallback): broader coverage, uses API credits.
4. **Not found**: if all automated sources fail, sets `icecat_not_found = 1` — product stays in queue for manual URL enrichment via the Admin UI.
5. **Manual URL enrichment** (`middleware/official_scraper.py:scrape_from_direct_url`): human pastes a verified official manufacturer URL in the Admin UI, the scraper fetches/parses the page (JSON-LD → OG meta → HTML tables), persists characteristics to EAV tables, and clears `icecat_not_found`.
