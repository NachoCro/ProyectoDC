-- =============================================================================
-- Schema: Middleware PrestaShop ↔ Icecat
-- Motor:  SQLite 3.x + sqlite-vec (extensión vectorial)
-- Fuente: ProyectoDC/AGENTS.md — Requerimientos de Base de Datos (RBD)
-- =============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. TABLAS PRINCIPALES (3FN + EAV)
-- ---------------------------------------------------------------------------

--- 1.1  Categorías (clasificación global de nivel superior)
CREATE TABLE IF NOT EXISTS categorias (
    id_categoria    INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_categoria TEXT    NOT NULL UNIQUE
);

--- 1.2  Subcategorías (clasificación de contexto, FK a categorías)
CREATE TABLE IF NOT EXISTS subcategorias (
    id_subcategoria     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_categoria        INTEGER NOT NULL REFERENCES categorias(id_categoria)
                            ON DELETE CASCADE ON UPDATE CASCADE,
    nombre_subcategoria TEXT    NOT NULL UNIQUE
);

--- 1.3  Diccionario de propiedades técnicas (EAV — atributos)
CREATE TABLE IF NOT EXISTS caracteristicas (
    id_caracteristica      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_caracteristica  TEXT    NOT NULL UNIQUE
);

--- 1.4  Productos (entidades de inventario fijo)
CREATE TABLE IF NOT EXISTS productos (
    id_prestashop          INTEGER PRIMARY KEY,          -- ID de PrestaShop (no autoincrement)
    id_subcategoria        INTEGER NOT NULL REFERENCES subcategorias(id_subcategoria)
                               ON UPDATE CASCADE,
    ean                    TEXT    NULL,                  -- Código de barras (hasta 14 dígitos)
    mpn                    TEXT    NULL,                  -- Número de parte del fabricante
    marca                  TEXT    NOT NULL,
    modelo                 TEXT    NOT NULL,
    vector_descriptivo     BLOB    NULL,                  -- Embedding float32[384] serializado
    fecha_sincronizacion   TEXT    NULL,                  -- ISO-8601
    estado_actualizacion   TEXT    NOT NULL DEFAULT 'desactualizado'
                               CHECK (estado_actualizacion IN ('actualizado', 'desactualizado')),
    product_not_found      INTEGER NOT NULL DEFAULT 0
                               CHECK (product_not_found IN (0, 1))
);

--- 1.5  Valores EAV (tabla intermedia polimórfica)
CREATE TABLE IF NOT EXISTS producto_caracteristicas (
    id_prestashop      INTEGER NOT NULL REFERENCES productos(id_prestashop)
                          ON DELETE CASCADE ON UPDATE CASCADE,
    id_caracteristica  INTEGER NOT NULL REFERENCES caracteristicas(id_caracteristica)
                          ON DELETE CASCADE ON UPDATE CASCADE,
    valor              TEXT    NOT NULL,
    PRIMARY KEY (id_prestashop, id_caracteristica)
);

-- ---------------------------------------------------------------------------
-- 2. ÍNDICES B-TREE
-- ---------------------------------------------------------------------------

--- Búsqueda por identificadores comerciales
CREATE INDEX IF NOT EXISTS idx_productos_ean      ON productos(ean);
CREATE INDEX IF NOT EXISTS idx_productos_mpn      ON productos(mpn);

--- Filtro por contexto y estado
CREATE INDEX IF NOT EXISTS idx_productos_subcategoria        ON productos(id_subcategoria);
CREATE INDEX IF NOT EXISTS idx_productos_estado_actualizacion ON productos(estado_actualizacion);

--- Compuesto EAV (ya cubierto por la PK compuesta, pero se explicita por claridad)
-- La PK (id_prestashop, id_caracteristica) en producto_caracteristicas
-- genera automáticamente un índice B-Tree único compuesto.

-- ---------------------------------------------------------------------------
-- 3. ÍNDICE VECTORIAL (HNSW via sqlite-vec)
-- ---------------------------------------------------------------------------
-- Requiere: .load ./vec0  o  la extensión cargada desde la aplicación.
-- La virtual table vec0 almacena el embedding y provee búsqueda por
-- similitud coseno. Debe mantenerse sincronizada con productos.vector_descriptivo
-- desde la lógica de aplicación.

-- Nota: el índice vectorial HNSW se crea desde la aplicación Python
-- después de cargar la extensión sqlite-vec. Ver vector_index.sql.

-- ---------------------------------------------------------------------------
-- 4. DATOS INICIALES
-- ---------------------------------------------------------------------------

--- 4.1  Categorías
INSERT OR IGNORE INTO categorias (id_categoria, nombre_categoria) VALUES
    (1, 'TELEFONIA'),
    (2, 'INFORMATICA'),
    (3, 'IMPRESION 3D'),
    (4, 'MOUSES'),
    (5, 'TV Y MONITORES'),
    (6, 'GAMERS');

--- 4.2  Subcategorías
INSERT OR IGNORE INTO subcategorias (id_subcategoria, id_categoria, nombre_subcategoria) VALUES
    -- TELEFONIA
    (1,  1, 'CELULARES LIBRES'),
    (2,  1, 'SMARTPHONES'),
    (3,  1, 'ACCESORIOS TELEFONIA'),
    -- INFORMATICA (antes PORTATILES)
    (4,  2, 'NOTEBOOKS'),
    (5,  2, 'ULTRABOOKS'),
    (6,  2, 'ALL IN ONE'),
    -- IMPRESION 3D
    (7,  3, 'IMPRESORAS FDM'),
    (8,  3, 'IMPRESORAS RESINA'),
    (9,  3, 'FILAMENTOS Y RESINAS'),
    -- MOUSES
    (10, 4, 'MOUSES INALAMBRICOS'),
    (11, 4, 'MOUSES CON CABLE'),
    (12, 4, 'MOUSES ERGONOMICOS'),
    -- TV Y MONITORES
    (13, 5, 'SMART TV'),
    (14, 5, 'MONITORES'),
    (15, 5, 'PROYECTORES'),
    -- GAMERS
    (16, 6, 'SILLAS GAMER'),
    (17, 6, 'PERIFERICOS GAMER'),
    (18, 6, 'CONSOLAS');

--- 4.3  Características técnicas (diccionario EAV)
INSERT OR IGNORE INTO caracteristicas (id_caracteristica, nombre_caracteristica) VALUES
    -- Generales / transversales
    (1,  'Marca'),
    (2,  'Modelo'),
    (3,  'Color'),
    (4,  'Peso'),
    (5,  'Dimensiones'),
    -- Impresión 3D
    (6,  'Tecnologia de impresion'),
    (7,  'Volumen de impresion'),
    (8,  'Resolucion de capa'),
    (9,  'Diametro de filamento'),
    (10, 'Materiales compatibles'),
    (11, 'Velocidad de impresion'),
    (12, 'Numero de extrusores'),
    (13, 'Cama caliente'),
    (14, 'Conectividad'),
    (15, 'Pantalla tactil'),
    -- Notebooks / Informática
    (16, 'Procesador'),
    (17, 'RAM'),
    (18, 'Almacenamiento'),
    (19, 'Tipo de pantalla'),
    (20, 'Tamaño de pantalla'),
    (21, 'Resolucion de pantalla'),
    (22, 'Tarjeta grafica'),
    (23, 'Sistema operativo'),
    (24, 'Duracion de bateria'),
    (25, 'Puertos'),
    -- Mouses
    (26, 'Tipo de conexion'),
    (27, 'Sensor'),
    (28, 'DPI'),
    (29, 'Numero de botones'),
    (30, 'Tipo de bateria'),
    (31, 'Iluminacion RGB'),
    (32, 'Ergonomico'),
    -- Telefonía
    (33, 'Camara principal'),
    (34, 'Camara frontal'),
    (35, 'Capacidad de bateria'),
    (36, 'Conectividad movil'),
    (37, 'Resistencia al agua'),
    -- TV / Monitores
    (38, 'Frecuencia de actualizacion'),
    (39, 'Brillo'),
    (40, 'Relacion de aspecto'),
    (41, 'HDR'),
    (42, 'Tiempo de respuesta'),
    -- Gamers / general
    (43, 'Factor de forma'),
    (44, 'Iluminacion'),
    (45, 'Material del chasis');
