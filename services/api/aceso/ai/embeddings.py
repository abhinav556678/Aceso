import hashlib
import random
from typing import List

def embed_text(text: str) -> List[float]:
    """
    Mock embedding function. In production, this would call an LLM or sentence-transformers.
    Generates a deterministic 384-dimensional vector for pgvector based on the text hash.
    """
    h = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
    random.seed(h)
    vec = [random.uniform(-1, 1) for _ in range(384)]
    # Normalize
    norm = sum(x*x for x in vec) ** 0.5
    return [x/norm for x in vec]
