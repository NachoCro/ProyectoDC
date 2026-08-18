# Middleware PrestaShop ↔ Icecat

Python middleware: extracts inactive products (active=0, qty>1) from PrestaShop, enriches via web scraping, and provides a Flask admin UI for approval + push-back.

## Entrypoints

| Cmd                                                     | What                                                                         |
| ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `python daemon.py [-v] [--interval S] [--dry-run] [--check-inactive] [--no-initial-pipeline]` | **Main script** — extract + enrich on startup (omit with `--no-initial-pipeline`), then continuous active-product verification loop. With `--check-inactive` also validates inactive products with stock and marks them "pendientes para activar" when complete. |
| `python pipeline.py [-v] [--dry-run]`                   | One-shot extract → enrich.                                                   |
| `python admin.py [-v] [--host HOST] [--port PORT] [--debug]` | Flask admin UI — dashboard, diff, approve/reject/re-sync, audit log, settings, brands, daemon control |
| `python scripts/sync_categories.py`                     | Create PrestaShop categories from local categorias/subcategorias             |

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
sqlite3 catalogo.db < schema.sql          # base tables + seed data
```

`db.py:_ensure_schema()` auto-migrates on first `get_connection()` call — adds columns via ALTER TABLE and creates `audit_log`. No manual migration step needed.

- **Config:** `.env` via `python-dotenv` — never commit. Loaded by `middleware/config.py`. Also has a **DB-backed config** layer (`config` table) that overrides `.env` values — editable via Admin UI Settings page.
- **Real PrestaShop:** `docker compose up -d`, then `scripts/setup_prestashop.sh` prints the API key. Backoffice at `http://localhost:8080/admin` (admin@prestashop.com / admin123).
- **PrestaShop 1.6 test instance:** `docker compose -f docker-compose.ps16.yml up -d` → `http://localhost:8081` (backoffice `http://localhost:8081/admin16`, admin@prestashop.com / admin123). The auto-install fails to download the Spanish language pack (translation server is dead), so it installs with `PS_LANGUAGE=en` and — because of that failed step — never creates the `PS_WEBSERVICE` config row; insert it manually (`INSERT INTO ps_configuration (name, value, date_add, date_upd) VALUES ('PS_WEBSERVICE','1',NOW(),NOW());`) then create an API key via `ps_webservice_account` + `ps_webservice_account_shop` (shop 1) + `ps_webservice_permission` (minimal: products GET+PUT, stock_availables/manufacturers/product_features/product_feature_values GET, images POST).
- **Optional deps:** `sentence-transformers` and `deep-translator` — both wrapped in try/except ImportError.
- **Vector index:** `vector_index.sql` requires sqlite-vec — **not wired into app code yet**.
- **No linter, formatter, or test framework** configured.

## Architecture

```
middleware/              ← extraction + enrichment engine
  config.py             — env loader (BATCH_SIZE=10, API_SLEEP=2, DB_PATH=catalogo.db) + DB-backed config
  db.py                 — SQLite helpers (WAL, foreign keys), auto-migration on first connect, shared helpers (write_eav, ensure_subcategoria)
  prestashop.py         — PrestashopClient (REST XML, read-only, HTTPBasicAuth)
  extract.py            — fetch inactive → stock filter → short-circuit → insert (stores nombre, modelo inferred from name)
  ai_agent.py           — DuckDuckGo web search + HTML scraping (JSON-LD/OG/tables), last resort
  enrich.py             — pipeline: existing data → brand site search → AI agent → name-only search → translate → embed → score → store → push
  official_scraper.py   — Selenium-based scraping: direct URL + brand site search + sitemap search + PDF sitemap search + PDF fallback
  spec_extractors.py    — shared generic spec extractors (tables, dl/dt/dd, microdata, div rows, JSON-LD, JS state objects, OG meta, body text, TCL API); filters JS template placeholders ({{...}})
  pdf_scraper.py        — PDF spec-sheet extraction via pdfplumber (tables → text regex); used as last-resort fallback in scrape_from_direct_url and as the primary extractor in the pdf_sitemap strategy
  embedding.py          — sentence-transformers (all-MiniLM-L6-v2, 384-dim, LRU cached)
  translate.py          — GoogleTranslator with protected glossary (~60 tech terms)
  characteristics.py    — merge_characteristics(): template + scraped data merge logic
  descriptions.py       — load product descriptions from 003 DESCRIPCIONES.xlsx
  check_active.py       — active product completeness verification + auto-completion + inactive "pendiente_activar" marking
  daemon_state.py       — daemon state tracker (SQLite-backed, shared between daemon + admin UI)
  pipeline_state.py     — pipeline state (in-memory) + progress mirrored to daemon_state (SQLite) for the dashboard progress bar
admin_ui/               ← Flask approval UI
  app.py                — routes: dashboard, diff, approve/reject/re-sync, scrape-url, audit, settings, brands, daemon control, check-active, run-pipeline
  prestashop.py         — AdminPrestashopClient (adds GET/PUT as JSON/XML, CDATA wrapping)
admin_ui/templates/     — 7 Jinja2 templates (base, dashboard, diff, products, audit, settings, brands)
scripts/
  setup_prestashop.sh   — docker compose up + enable webservice + generate API key
  sync_categories.py    — create PrestaShop categories from local categorias/subcategorias
migrations/             — SQL migration files (001_admin_ui.sql, 002_imagen_url.sql) — historical reference; db.py:_ensure_schema() is the source of truth
default_characteristics.json   — 79 templates with default values per subcategory
subcategory_mapping.json       — maps DB subcategoria name → template key (19 entries)
descripcion_mapping.json       — maps DB subcategoria name → Excel description key
brands_mapping.json            — maps brand name → search strategy ({mpn} placeholder in search_url, or strategy:"sitemap" + sitemap_url + url_pattern, or strategy:"pdf_sitemap" + sitemap_url; optional direct_url_pattern ({model_slug}) and has_pdf:true)
```

## Ingestion rules

- Filter: `active=0` + `quantity >= 1` (code uses `qty < 1` skip) + EAN/id not in `productos` + not previously `product_not_found`
- Batch: max 10 per run (`BATCH_SIZE`), 2s sleep between all external API calls (`API_SLEEP`)
- Products without subcategoría → assigned to `SIN CLASIFICAR` (auto-created, category 1)
- Products resolved to subcategory via PrestaShop's `id_category_default` → `subcategorias.id_prestashop_categoria` mapping

## Key flows

- **Extraction** (`middleware/extract.py`): walks inactive products page-by-page, fetches stock map for each page, keeps only qty>1, short-circuits if EAN/id already in DB or marked `product_not_found`, syncs local fields with PrestaShop data (PrestaShop is source of truth), resolves subcategory from product's `id_category_default` (matching `subcategorias.id_prestashop_categoria`), falls back to `SIN CLASIFICAR` if no match, inserts with `estado_actualizacion='desactualizado'`. `modelo` is inferred from the product name during extraction via `_extract_model_from_name`. **Known-product short-circuit happens DURING the walk** (`_load_known` preloads local ids/EANs once): already-known products are synced (up to `target_count` of them) but do **not** consume the `target_count` quota, so a run asking for N actually inserts N *new* products instead of stopping after N seen (repeated runs used to keep walking the same known products and process far fewer than requested). A defensive `max_walked = max(target_count*10, BATCH_SIZE*5)` cap bounds the scan when the catalog lacks enough new products. **Scope:** the run-once "Opciones avanzadas" can target `inactive` (default), `active`, or `both` catalogs via the `scope` key in the `override` dict — `extract` then walks `get_inactive_products`/`get_active_products` (per-scope offsets) until `target_count` candidates are found. The run-once form also supports `run_dry_run` (simulate, no PrestaShop writes) and `run_skip_extract` (enrich-only).
- **Enrichment** (`middleware/enrich.py`): selects `product_not_found = 0 AND estado_actualizacion = 'desactualizado'`. For each product, tries sources in cascade: (1) existing `icecat_json` data (historical column name, now stores generic proposal JSON), (2) brand site search via `official_scraper._search_brand_site` (Selenium), (3) AI agent web search via `ai_agent.enrich_with_ai`, (4) name-only search (infer brand from product name). Translates (glossary-protected), generates embedding + cosine score, stores proposal JSON + `vector_descriptivo`. Marks `product_not_found = 1` only when there is no brand AND no name; otherwise it stays in the queue (`RETRY-LATER`). Merges characteristics with default template, builds description, pushes to PrestaShop.
- **Active product verification** (`middleware/check_active.py`): daemon periodically checks active products (active=1) for completeness (image, description, characteristics). Incomplete products are auto-completed using the enrichment pipeline. Products verified as complete get `active_verified = 1` to skip future checks.
- **Inactive product validation** (`middleware/check_active.py:check_inactive_pending`): run when the daemon starts with `--check-inactive` (or the dashboard checkbox). Walks inactive products with stock (qty ≥ 1), checks completeness; complete ones are marked `pendiente_activar = 1` ("para activar"), incomplete ones are auto-completed first. Products already marked are skipped. The "Para activar" tab + badge in the admin shows them; "Aprobar y activar" clears the flag.
- **Approval:** two approve modes — "Aprobar y activar" (PUTs descriptions + `active=1`) and "Aprobar (sin activar)" (only descriptions). Both merge characteristics with default template, build description as HTML `<p><strong>{nombre}:</strong> {valor}</p>` lines from merged characteristics, push to PrestaShop (descriptions + features). EAV written locally, marked `actualizado`. Audit distinguishes `aprobado` vs `aprobado_y_activado`. Reject clears proposal data. Re-sync resets flags for retry.
- **Excel-cell description style** (`middleware/characteristics.py:format_excel_value` + `build_description_html`): description lines follow the `003 DESCRIPCIONES.xlsx` cell style — option lists normalized to ` / ` separators (unit expressions like `MB/S` are left untouched), short technical values uppercased (`si`→`SI`, `cable`→`CABLE`; measurements like `1.4 GHz` and prose like `Samsung Exynos W920` keep their case), duplicate lines dropped, and characteristic names > 60 chars truncated. Used by `enrich._build_description`, the admin approve route and `check_active`. Feature sync to PrestaShop still uses the raw names/values.
- **Translation** (`middleware/translate.py`): glossary protects ~60 technical terms (OLED, USB-C, DDR5, RTX, etc.) via `[[GLOSS{i}]]` placeholder substitution (bracketed markers survive GoogleTranslator; the old NUL-based `\x00G{i}\x00` was rewritten to U+FFFD by the translator, leaking `G{i}` into the output). Does **not** translate `descripcion_corta`.
- **Embedding** (`middleware/embedding.py`): `all-MiniLM-L6-v2`, 384-dim float32, normalized. LRU cache (512 entries). Stored as raw bytes in `productos.vector_descriptivo`.
- **Descriptions from Excel** (`middleware/descriptions.py`): reads `003 DESCRIPCIONES.xlsx` (DESCRIPCIONES sheet) and maps DB subcategory names to Excel entries via `descripcion_mapping.json`. Used for `description_short` in both pipeline push and admin approval.

## Gotchas

- **Plan matching by name similarity:** the plan's "tipo de producto" (active plan, weekly agenda, or run-once override) selects products by **name similarity** (`plan.matches_name` — token-based, accent/case-insensitive, singular/plural aware), not by exact subcategory match. Applied consistently in `extract.py`, `enrich.py`, and `check_active.py` (`_matches_target`). `enrich.run()` fetches up to `max(plan_limit*20, 200)` candidates and refines in Python (SQLite can't do SequenceMatcher). In run-once mode (`override` set) the queue query is ordered `p.rowid DESC` so the freshly extracted products are enriched first instead of mixing with old retries. Matching rules (`middleware/plan.py`): generic catalog words ("repuestos", "accesorios", "piezas", "kit", …) are dropped from the target (stopwords are compared case-insensitively — tokens are uppercased), so "repuestos motosierra" selects motosierra parts even though no product name contains "repuestos". `_token_similar` requires a shared prefix in addition to `SequenceMatcher.ratio() >= 0.8` — a bare ratio lets "BOMBIN" match "BOBINA" (different parts). Morphological variants (CABLE→CABLEADO, MONITOR→MONITORES) match when the shorter word is a prefix with a short suffix.
- **Port conflict:** `.env` defaults to `localhost:8080/api` (real PrestaShop). Change `.env` if you run PrestaShop elsewhere.
- **Enrichment on start:** `instalar.sh` asks whether to run extraction+enrichment when the daemon starts (persisted as `ENRICH_ON_START` in `.env`, default 0 = skip). Skipping adds `--no-initial-pipeline` to the daemon. The dashboard's daemon form has the same toggle ("Iniciar sin extracción/enriquecimiento").
- **modelo extracted at ingestion:** extraction infers `modelo` from the product name (`_extract_model_from_name`); enrichment/approval only backfill it if still empty.
- **Approve modes:** two buttons in diff — "Aprobar y activar" pushes `active=1` + descriptions; "Aprobar (sin activar)" pushes only descriptions.
- **`icecat_json` column name is historical** — the column now stores generic proposal JSON from brand site search or AI agent scraping. No Icecat integration exists.
- **`product_not_found` vs `active_verified`:** `product_not_found` flags products excluded from processing. `active_verified` tracks if active products were verified as complete. `pendiente_activar` (migration 007) marks inactive products verified as complete and ready for activation.
- **Diff action forms are AJAX:** `approve`/`reject`/`re-sync` routes return JSON (`{"ok", "redirect"}`); `diff.html` submits them via `fetch` and follows `redirect` (which points back to `url_for('diff', pid=pid)`). Submitting them as a plain HTML POST shows raw JSON.
- **AdminPrestashopClient.\_set_field** (`admin_ui/prestashop.py:491`) handles `<language>` creation for multi-language fields — but only for keys in its hardcoded list (`description`, `description_short`, `name`, `link_rewrite`, `meta_title`, `meta_description`, `meta_keywords`, `delivery_in_stock`, `delivery_out_stock`, `available_now`, `available_later`).
- **CDATA wrapping:** `put_product` post-processes the XML to wrap `<language>` content in CDATA sections (`admin_ui/prestashop.py:_wrap_language_cdata`). Otherwise ElementTree escapes HTML entities and PrestaShop renders them literally.
- **PUT sanitization:** `put_product` also strips all XML attributes (`_strip_prestashop_attrs`) and drops every `<associations>` child except `product_features` + `categories` — PrestaShop 8.1 returns 500 on GET-attrs (xlink:href, nodeType) and on image/combination associations in the PUT body. It always forces `visibility=both`, `indexed=1`, `state=1`.
- **DB:** SQLite, WAL mode, foreign keys ON. `catalogo.db` is gitignored. Config table stores runtime settings that override `.env`.
- **Selenium required:** both brand site search (`official_scraper.py`) and AI agent (`ai_agent.py`) use headless Chrome via Selenium.
- **Scraped data validation** (`enrich.py:_validate_scraped_data`): rejects manual/support/FAQ pages, checks brand match, verifies model tokens appear in scraped title. Also enforces TV/monitor size disambiguation (wanted size in product name vs scraped title/specs). `_validate_name_coherence` rejects data whose enriched brand contradicts the original product name (a "Smart TV Samsung" can't end up as "Fravega") — the reference brand is inferred from the name or taken from the DB; applied to fresh scrapes, AI-agent results, and re-pushing stored proposal JSON. **Token check (check 3):** if the name has a letter+digit model token (e.g. `GND307`) it is decisive — at least one must appear in the scraped title (`(?<![a-z0-9\-])` lookbehind prevents `st15` fragmenting out of `nm-st15`). Generic names (no model token, no reference brand) must additionally pass a word-overlap + `SequenceMatcher` similarity gate (≥2 words & ratio ≥ 0.40, or ratio ≥ 0.50) so a loose word overlap like "tapa"/"combustible" can't pull in an unrelated product (truck fuel-tank lid, bike pump, GPU page). The brand-less AI path (`_accept_ai`) runs this **full** validation (previously only a character count + name coherence, which let "KIT DIAFRAGMA GND307" get enriched as a "GeForce RTX 3070"). `soporte` is deliberately NOT a junk pattern (it also means "mount/stand", e.g. TV mounts); English `support` is kept.
- **Feature value length limit:** PrestaShop rejects feature values longer than 255 chars. `sync_characteristics_as_features` truncates to 255 before POSTing.
- **Product category assignment:** `put_product` accepts `category_ids` to assign the product to corresponding PrestaShop categories. The pipeline passes the subcategory's PS category (from `subcategorias.id_prestashop_categoria`).
- **Default characteristics** (`middleware/characteristics.py`): `merge_characteristics()` merges scraped characteristics with a default template per subcategory. Rules: (1) every template entry is included, (2) if scraped data has a characteristic with the same name (case-insensitive), its value overwrites the default, (3) extra scraped characteristics are appended at the end.
- **Official scraper** (`middleware/official_scraper.py`): `scrape_from_direct_url(url, product_id)` accepts a human-verified official URL, uses headless Selenium (Chrome) to render JS-heavy pages, then parses with BeautifulSoup (JSON-LD/OG meta/HTML tables), and persists to EAV tables. Used by the Admin UI for manual URL enrichment. Also handles redirects to category/listing pages (follows first product link), Logitech JS-object extraction, and a PDF spec-sheet fallback when < 5 characteristics are found.
- **Brand site search** (`official_scraper.py:_search_brand_site`): if the brand has a `search_url` + `result_selector` in `brands_mapping.json`, uses Selenium to navigate to the brand's internal search page, waits for product card elements, scores every result card by title/URL vs the cleaned model slug (accessory keywords penalized), and returns the best URL. Also supports sitemap-based search (`strategy:"sitemap"` + `sitemap_url` + `url_pattern` — Samsung, TCL, Acer) with fuzzy slug matching, and a `direct_url_pattern` (`{model_slug}`) fallback when search yields nothing.
- **PDF sitemap search** (`official_scraper.py:_search_brand_pdf_sitemap`): for brands with `strategy:"pdf_sitemap"` + `sitemap_url` (e.g. gfast) — sites that have no per-product pages and expose each spec sheet only as a PDF linked from category/listing pages. `_fetch_page` downloads each sitemap page once (24h in-memory soup cache, `API_SLEEP` throttle on real fetch), collects all `.pdf` links, and `_score_pdf_url` ranks them against the product name/model (bonus for model tokens in the filename + SequenceMatcher overlap, acceptance threshold 9.0). The winning PDF is scraped by `_scrape_pdf_datasheet`, which runs pdfplumber (`extract_specs_from_pdf`) and — when < 5 characteristics are extracted (image-based PDFs) — falls back to `_extract_inline_specs_from_soup`, which parses the "Key: Value" text specs that Elementor pages render inline next to the PDF link. Persists with `source="pdf_sitemap"`.
- **PDF-sitemap auto-discovery** (`official_scraper.py:_discover_brand_pdf_sitemap`): when a brand has **no** entry in `brands_mapping.json`, `_search_brand_site` no longer gives up — it tries to discover a gfast-style source automatically. It probes candidate official domains (`.com.ar`, `.com`, `www.`, `.net`, `.com.uy`) × common sitemap paths (`/wp-sitemap-posts-page-1.xml`, `/wp-sitemap.xml`, `/sitemap_index.xml`, `/sitemap.xml`, `/sitemap-1.xml`, `/page-sitemap.xml`) and accepts the first sitemap whose pages show the PDF-spec pattern (`_detect_pdf_spec_site`: ≥ 3 spec-PDF links across a sample of ≤ 8 pages and ≥ 1 page listing several). The outcome is cached per brand key (`_PDF_SITEMAP_DISCOVERY`) so the probe cost is paid once per brand, not per product; a failed probe (all domains/paths empty) is cached as `None` and never retried this process. So new gfast-like brands are handled with zero config.
- **Generic spec extractors** (`middleware/spec_extractors.py`): shared by `official_scraper` and `ai_agent`. Samsung-style Knockout/Angular pages embed JS template placeholders (e.g. `{{upgrade.yesAttr.text}}`) in the DOM that get picked up as fake specs — extractors drop any name/value matching `{{...}}`, `[[...]]`, or `${...}`. The body-text extractor is only run when structured extractors produce < 10 characteristics (too noisy otherwise).
- **PDF fallback** (`middleware/pdf_scraper.py`): `scrape_from_direct_url` scans the page for spec-sheet PDF links (`ficha`/`specs`/`datasheet` keywords, `.pdf` suffix) and extracts tables/text via pdfplumber when structured extraction found < 5 characteristics. `brands_mapping.json` flags brands known to publish PDFs (`has_pdf: true` — Xerox, Canon, HP, Epson, Ricoh). A `.pdf` URL passed directly to `scrape_from_direct_url` (or found by `_search_brand_pdf_sitemap`) skips Selenium entirely and goes straight to `_scrape_pdf_datasheet`.
- **Name-only search** (`enrich.py`): infers brand from product name using `_infer_brand_from_name`, then tries brand site search + AI agent with the inferred brand.
- **Manual URL enrichment:** `POST /products/<pid>/scrape-url` accepts a URL, calls `scrape_from_direct_url()`, which fetches the page, extracts JSON-LD/OG/HTML tables, writes to EAV, updates proposal JSON, and sets `estado_actualizacion='desactualizado'`. It does **not** clear `product_not_found` — use the re-sync button for that.
- **Product state field:** PrestaShop 8.1 requires `ps_product.state = 1` for products to appear in Catálogo > Productos. Products created via the webservice default to `state=0` (draft). `put_product` forces `state=1` alongside `visibility` and `indexed` to prevent invisible products.
- **PrestaShop 1.6 compat:** two config keys to flip when pointing at the 1.6 instance: `PS_COMPAT_81=0` (1.6 has no product `state` field — the 8.1 workaround forces it and breaks PUT) and `PS_MPN_FIELD=reference` (the `mpn` field doesn't exist in 1.6; the extract client would get a 400 on `display=[...,mpn,...]`). `PS_CREATE_FEATURES=0` already skips features/values that don't exist. `product_features` + `product_feature_values` GETs are required for the no-create sync.
- **PrestaShop client split:** `middleware/prestashop.py` is read-only (GET). `admin_ui/prestashopop.py` extends it with PUT, image upload, and feature sync. Enrichment imports from `admin_ui.prestashop` for write operations.
- **Pipeline lock:** Admin UI uses a `pipeline_lock` config key to prevent concurrent pipeline runs. Lock is acquired before extraction/full-pipeline and released in `finally`.
- **Daemon state:** shared between daemon process and admin UI via SQLite `config` table (`daemon_state.py`). Dashboard polls `/api/daemon-status` for real-time updates. **Pipeline progress:** `pipeline_state` mirrors `{running, phase, current, total, pid, product_name, started_at, finished_at}` to `daemon_state.pipeline_progress` on every start/update/finish so the dashboard's "Ejecución en curso" card + progress bar work cross-process (run-once thread or daemon subprocess). Extraction phase shows an indeterminate bar (total unknown); enrichment shows `current/total`.

## Guardrails

- **Throttle:** 2s sleep on every external API call (PrestaShop)
- **Short-circuit:** local DB checks run before any scraping call
- **Immutable audit:** `audit_log` table append-only
- **Pipeline lock:** prevents concurrent extraction/pipeline runs from admin UI

## Enrichment cascade (DB → brand site search → AI agent → name-only → not-found / retry-later)

The enrichment pipeline (`middleware/enrich.py`) tries sources in order:

1. **Local DB** (existing proposal JSON): if a previous run stored data but push failed, re-push without re-fetching — but only when the stored `caracteristicas` are non-empty and free of JS template placeholders (`{{...}}`); otherwise re-scrape.
2. **Brand site search** (`middleware/official_scraper.py:_search_brand_site`): if the brand has a `search_url` + `result_selector` in `brands_mapping.json`, uses Selenium to navigate to the brand's internal search page, scores result cards by title/URL match, and scrapes the best URL. Brands with `strategy:"sitemap"` use sitemap matching instead; `direct_url_pattern` is a fallback. Brands with `strategy:"pdf_sitemap"` use PDF-sitemap matching. Brands without a mapping trigger **PDF-sitemap auto-discovery** (see above) before falling through to the AI agent.
3. **AI agent** (`middleware/ai_agent.py:enrich_with_ai`): DuckDuckGo web search → fetch pages → extract JSON-LD/OG meta/HTML tables. Requires a product name (brand+model); every candidate is validated via `_validate_scraped_data` before acceptance (without a brand it also needs ≥ 5 characteristics — reseller-page noise guard). Uses `ddgs` package. No API credits. Skipped in dry-run mode. Brand-site results with < 10 characteristics also trigger this source to try to beat them.
4. **Name-only search** (`enrich.py`): if brand/MPN search failed, infers brand from product name via `_infer_brand_from_name`, then retries brand site search + AI agent with inferred brand.
5. **Not found / retry-later**: `product_not_found = 1` is set **only** when there is no brand AND no name. If a brand or name exists but all sources fail, the product stays in the queue (`RETRY-LATER`) and is retried next run.
6. **Manual URL enrichment** (`middleware/official_scraper.py:scrape_from_direct_url`): human pastes a verified official manufacturer URL in the Admin UI, the scraper fetches/parses the page (JSON-LD → OG meta → HTML tables → brand+generic extractors → PDF fallback), persists characteristics to EAV tables, and sets `estado_actualizacion='desactualizado'` (does **not** clear `product_not_found` — use re-sync).

## Legal / compliance

**Leer `LEGAL.md` antes de vender o desplegar.** Resumen: el scrapeo de terceros y la republicación de contenido (imágenes/fichas con copyright) son la mayor exposición legal. Respetar ToS/robots.txt de las fuentes en `brands_mapping.json`, el cliente es responsable de los derechos de publicación y de validar el contenido, y no subir `.env`/claves al repo. Guía operativa + cláusulas contractuales recomendadas en `LEGAL.md`.
