# embedder.py – Embedding-Einstiegspunkt
#
# Einfach und ohne Zirkulärimport:
# main.py importiert get_embedding() von hier.
# Beide (embedder + NoteDB) haben ihr eigenes Modell-Exemplar.
# Das ist ~500 MB RAM extra — akzeptabel, da das Modell nur einmal geladen wird.
# Wer RAM sparen will: main.py auf db.embed() umstellen und embedder.py entfernen.

import threading
from sentence_transformers import SentenceTransformer

_model:      SentenceTransformer | None = None
_model_lock: threading.Lock             = threading.Lock()


def get_embedding(text: str) -> list:
    """
    Embedding für ein Dokument (search_document: Prefix).
    Thread-safe, lazy-loaded.
    """
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                print("Lade Embedding-Modell…")
                _model = SentenceTransformer(
                    "nomic-ai/nomic-embed-text-v1.5",
                    trust_remote_code=True,
                    device="cpu",
                )
                print("Embedding-Modell geladen.")
    return _model.encode(f"search_document: {text}").tolist()
