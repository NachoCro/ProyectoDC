"""Vector embedding generation and cosine similarity scoring (RF-06)."""

import logging
from functools import lru_cache

import numpy as np

try:
    from sentence_transformers import SentenceTransformer

    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore
    _SENTENCE_TRANSFORMERS_AVAILABLE = False

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model = None


def _get_model() -> SentenceTransformer | None:
    global _model
    if _model is None and _SENTENCE_TRANSFORMERS_AVAILABLE:
        logger.info("Loading embedding model: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def is_available() -> bool:
    return _SENTENCE_TRANSFORMERS_AVAILABLE


@lru_cache(maxsize=512)
def generate_embedding(text: str) -> np.ndarray | None:
    """Generate a 384-dim normalized embedding vector (cached by text)."""
    model = _get_model()
    if model is None:
        logger.warning("sentence-transformers not installed; skipping embedding")
        return None
    emb = model.encode(text, normalize_embeddings=True)
    return np.array(emb, dtype=np.float32)


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialize float32 vector for `productos.vector_descriptivo`."""
    return embedding.tobytes()


def embedding_from_bytes(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def score_match(local_text: str, proposed_text: str) -> float:
    """Return a similarity score (0–1) between two descriptive texts."""
    if not local_text or not proposed_text:
        return 0.0
    emb_local = generate_embedding(local_text)
    emb_proposed = generate_embedding(proposed_text)
    if emb_local is None or emb_proposed is None:
        return 0.0
    return cosine_similarity(emb_local, emb_proposed)
