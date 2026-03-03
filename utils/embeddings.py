from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")  # small, fast embedding model


def embed_text(text: str) -> np.ndarray:
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
