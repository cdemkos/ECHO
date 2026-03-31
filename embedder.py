# embedder.py – öffentlicher Embedding-Einstiegspunkt für main.py
#
# Delegiert an NoteDB.model um RAM zu sparen (eine Instanz, nicht zwei).
# main.py importiert get_embedding() von hier; NoteDB.search() nutzt db.embed_query().

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_db_instance = None


def _get_db():
    global _db_instance
    if _db_instance is None:
        from database import NoteDB
        _db_instance = NoteDB.__new__(NoteDB)
        # Nur das Modell initialisieren, keine DB-Verbindung
        import threading
        _db_instance._model      = None
        _db_instance._model_lock = threading.Lock()
    return _db_instance


def get_embedding(text: str) -> list:
    """
    Gibt den Embedding-Vektor für text als Dokument zurück.
    Nutzt das Modell aus NoteDB um doppeltes RAM-Laden zu vermeiden.
    """
    from database import NoteDB
    # Nutze das globale db-Objekt aus main wenn verfügbar,
    # sonst eigene Instanz für CLI-Nutzung (echo_to_claude.py)
    try:
        import main as _main
        db = _main.db
    except (ImportError, AttributeError):
        db = _get_db()
    return db.embed(text)
