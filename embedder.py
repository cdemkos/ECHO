from sentence_transformers import SentenceTransformer

_model = None

def get_embedding(text: str):
    global _model
    if _model is None:
        print("Lade Embedding-Modell (einmalig)...")
        _model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
        print("Fertig!")
    return _model.encode(f"search_query: {text}").tolist()
