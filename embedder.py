# embedder.py – globales, lazy-loaded Embedding-Modell

from sentence_transformers import SentenceTransformer
import threading

_model = None
_model_lock = threading.Lock()

def get_embedding(text: str):
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # Double-Check-Locking
                print("Lade Embedding-Modell (einmalig, bitte warten...)")
                _model = SentenceTransformer(
                    'nomic-ai/nomic-embed-text-v1.5',
                    trust_remote_code=True,
                    device='cpu'  # oder 'cuda' wenn du eine GPU hast
                )
                print("Embedding-Modell geladen!")
    return _model.encode(f"search_query: {text}").tolist()
