-- ---------------------------------------------------------------------------
-- Índice vectorial HNSW (sqlite-vec)
-- Ejecutar SOLO después de cargar la extensión vec0 desde la aplicación:
--   db.load_extension("vec0")   # o la ruta completa a la .so / .dll
-- ---------------------------------------------------------------------------

CREATE VIRTUAL TABLE IF NOT EXISTS productos_vector_idx USING vec0(
    id_prestashop       INTEGER PRIMARY KEY,
    vector_descriptivo  FLOAT[384] distance_metric=cosine
);
