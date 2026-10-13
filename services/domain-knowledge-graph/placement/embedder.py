"""Static embedding model shared by the index builder, the search tool and the baseline."""
from functools import lru_cache

import numpy as np

from .config import EMBED_MODEL


def concept_text(name: str, description: str | None) -> str:
    return name + (": " + description if description else "")


@lru_cache(maxsize=1)
def _model():
    from model2vec import StaticModel
    return StaticModel.from_pretrained(EMBED_MODEL)


def embed(texts: list[str]) -> np.ndarray:
    v = np.asarray(_model().encode(texts), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
    return v
