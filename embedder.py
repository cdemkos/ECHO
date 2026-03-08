from sentence_transformers import SentenceTransformer

_model = None

def get_embedding(text: str):
    global _model
    if _model is None:
        ui.notify('Lade Embedding-Modell (einmalig)...', type='ongoing')
        _model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
        ui.notify('Fertig!', type='positive')
    return _model.encode(f"search_query: {text}").tolist()
