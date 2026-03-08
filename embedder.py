from sentence_transformers import SentenceTransformer

_model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)

def get_embedding(text: str):
    # nomic-embed-text-v1.5 erwartet diesen Prefix für beste Ergebnisse
    return _model.encode(f"search_query: {text}")
