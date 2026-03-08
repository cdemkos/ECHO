from sentence_transformers import SentenceTransformer
from functools import lru_cache

_model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)

@lru_cache(maxsize=1000)  # Cache für häufige Queries
def get_embedding(text: str):
    try:
        return _model.encode(f"search_query: {text}").tolist()
    except Exception as e:
        print(f"Embedding-Fehler: {e}")
        return [0.0] * 768  # Fallback-Vektor (Dimension von nomic)
