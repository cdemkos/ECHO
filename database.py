# database.py – NoteDB
#
# Einzige Quelle der Wahrheit für alle Datenbankoperationen.
# Alle Methoden sind thread-sicher via explizitem Lock.
# db.cursor ist privat (_cursor) — externer Zugriff ist verboten.

import logging
import os
import sqlite3
import threading
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

os.environ["ANONYMIZED_TELEMETRY"] = "False"

log = logging.getLogger(__name__)

DATA_DIR   = Path("data")
DB_PATH    = DATA_DIR / "echo.db"
CHROMA_DIR = DATA_DIR / "chroma"

# Erkennungs-Präfix für LLM-Fehler — diese Strings NIEMALS als Notiz speichern
LLM_ERROR_PREFIXES = ("[Timeout", "[LLM-Fehler", "[llm-fehler")


def is_llm_error(text: str) -> bool:
    """Gibt True zurück wenn text eine LLM-Fehlermeldung ist, keine echte Notiz."""
    t = text.strip()
    return any(t.startswith(p) for p in LLM_ERROR_PREFIXES)


class NoteDB:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)

        # ChromaDB
        self.client     = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.collection = self.client.get_or_create_collection(name="echo_notes")

        # SQLite — check_same_thread=False weil NiceGUI async verwendet
        self.conn    = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._lock   = threading.Lock()
        self._cursor = self.conn.cursor()
        self._migrate()

        # Embedding-Modell — lazy loaded, ein einziges Exemplar
        self._model      = None
        self._model_lock = threading.Lock()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _migrate(self) -> None:
        with self._lock:
            self._cursor.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    id         TEXT PRIMARY KEY,
                    timestamp  TEXT NOT NULL,
                    text       TEXT NOT NULL,
                    file_path  TEXT NOT NULL,
                    tags       TEXT NOT NULL DEFAULT '',
                    note_type  TEXT NOT NULL DEFAULT 'note',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_notes_ts   ON notes(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(note_type);
            """)
            self.conn.commit()

    # ── Embedding ─────────────────────────────────────────────────────────────

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    log.info("Lade Embedding-Modell…")
                    self._model = SentenceTransformer(
                        "nomic-ai/nomic-embed-text-v1.5",
                        trust_remote_code=True,
                        device="cpu",
                    )
                    log.info("Embedding-Modell geladen.")
        return self._model

    def embed(self, text: str) -> list:
        return self.model.encode(f"search_document: {text}").tolist()

    def embed_query(self, text: str) -> list:
        return self.model.encode(f"search_query: {text}").tolist()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_note(
        self,
        note_id:   str,
        timestamp: str,
        text:      str,
        file_path: str,
        embedding: list,
        tags:      list | None = None,
        note_type: str = "note",
    ) -> None:
        """
        Speichert eine neue Notiz in ChromaDB und SQLite.
        Gibt eine Exception wenn text eine LLM-Fehlermeldung ist.
        """
        if is_llm_error(text):
            raise ValueError(f"LLM-Fehlertext darf nicht gespeichert werden: {text[:60]}")

        tags_str = ",".join(t.strip() for t in (tags or []) if t.strip())

        self.collection.add(
            ids=[note_id],
            embeddings=[embedding],
            metadatas=[{
                "timestamp": timestamp,
                "file_path": file_path,
                "tags":      tags_str,
                "note_type": note_type,
            }],
            documents=[text],
        )
        with self._lock:
            self._cursor.execute(
                "INSERT OR REPLACE INTO notes"
                "(id, timestamp, text, file_path, tags, note_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (note_id, timestamp, text, file_path, tags_str, note_type),
            )
            self.conn.commit()

    def delete_note(self, note_id: str) -> None:
        """Löscht Notiz aus ChromaDB UND SQLite — einziger Lösch-Ort."""
        try:
            self.collection.delete(ids=[note_id])
        except Exception as e:
            log.warning("ChromaDB delete warning (%s): %s", note_id, e)
        with self._lock:
            self._cursor.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self.conn.commit()

    def update_note(
        self,
        note_id:   str,
        timestamp: str,
        text:      str,
        file_path: str,
        embedding: list,
        tags:      list | None = None,
        note_type: str = "note",
    ) -> None:
        if is_llm_error(text):
            raise ValueError(f"LLM-Fehlertext darf nicht gespeichert werden: {text[:60]}")

        tags_str = ",".join(t.strip() for t in (tags or []) if t.strip())
        meta     = {"timestamp": timestamp, "file_path": file_path,
                    "tags": tags_str, "note_type": note_type}
        try:
            self.collection.update(
                ids=[note_id], embeddings=[embedding],
                metadatas=[meta], documents=[text],
            )
        except Exception:
            self.collection.add(
                ids=[note_id], embeddings=[embedding],
                metadatas=[meta], documents=[text],
            )
        with self._lock:
            self._cursor.execute(
                "UPDATE notes SET timestamp=?, text=?, file_path=?, tags=?, note_type=? "
                "WHERE id=?",
                (timestamp, text, file_path, tags_str, note_type, note_id),
            )
            self.conn.commit()

    # ── Lesen ─────────────────────────────────────────────────────────────────

    def search(self, query_text: str, limit: int = 8) -> list[dict]:
        """
        Semantische Suche. Gibt Dicts mit id, timestamp, text, file_path, tags, similarity.
        Filtert automatisch Fehler-Notizen und Auto-Reflexionen aus.
        """
        n = self.collection.count()
        if n == 0:
            return []

        query_emb = self.embed_query(query_text)
        # Mehr abfragen als nötig, dann filtern
        fetch     = min(limit * 3, n)
        results   = self.collection.query(
            query_embeddings=[query_emb],
            n_results=fetch,
            include=["metadatas", "documents", "distances"],
        )

        hits = []
        for i, note_id in enumerate(results["ids"][0]):
            with self._lock:
                self._cursor.execute(
                    "SELECT timestamp, text, file_path, tags, note_type "
                    "FROM notes WHERE id = ?",
                    (note_id,),
                )
                row = self._cursor.fetchone()
            if not row:
                continue
            # LLM-Fehler und reine Auto-Reflexionen nicht in Suchergebnissen zeigen
            if is_llm_error(row[1]):
                continue
            similarity = max(0.0, 1.0 - results["distances"][0][i])
            hits.append({
                "id":         note_id,
                "timestamp":  row[0],
                "text":       row[1],
                "file_path":  row[2],
                "tags":       row[3],
                "note_type":  row[4],
                "similarity": similarity,
            })
            if len(hits) >= limit:
                break
        return hits

    def get_note_by_id(self, note_id: str) -> dict | None:
        """Gibt eine einzelne Notiz zurück, oder None."""
        with self._lock:
            row = self._cursor.execute(
                "SELECT id, timestamp, text, file_path, tags, note_type "
                "FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "timestamp": row[1], "text": row[2],
                "file_path": row[3], "tags": row[4], "note_type": row[5]}

    def get_notes_since(self, since_iso: str, note_type: str | None = None) -> list[tuple]:
        """
        Gibt (id, timestamp, text, file_path) zurück.
        note_type=None → alle; note_type='note' → nur echte Notizen.
        Filtert LLM-Fehler automatisch aus.
        """
        with self._lock:
            if note_type:
                rows = self._cursor.execute(
                    "SELECT id, timestamp, text, file_path FROM notes "
                    "WHERE timestamp >= ? AND note_type = ? ORDER BY timestamp",
                    (since_iso, note_type),
                ).fetchall()
            else:
                rows = self._cursor.execute(
                    "SELECT id, timestamp, text, file_path FROM notes "
                    "WHERE timestamp >= ? ORDER BY timestamp",
                    (since_iso,),
                ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows if not is_llm_error(r[2])]

    def get_old_unreferenced(self, cutoff_iso: str, ref_cutoff_iso: str) -> list[tuple]:
        """(id, timestamp, file_path) für Notizen die archiviert werden sollen."""
        with self._lock:
            return self._cursor.execute("""
                SELECT id, timestamp, file_path FROM notes
                WHERE timestamp < ?
                AND (
                    SELECT COUNT(*) FROM notes AS n2
                    WHERE n2.text LIKE '%' || notes.id || '%'
                    AND n2.timestamp > ?
                ) = 0
            """, (cutoff_iso, ref_cutoff_iso)).fetchall()

    def auto_note_exists_today(self, note_type: str) -> bool:
        """
        Prüft ob heute bereits eine Auto-Notiz des gegebenen Typs existiert.
        Ersetzt note_exists_matching() — sucht nach note_type statt Text-Fragment.
        """
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            row = self._cursor.execute(
                "SELECT id FROM notes WHERE timestamp LIKE ? AND note_type = ? LIMIT 1",
                (f"{today}%", note_type),
            ).fetchone()
        return row is not None

    def count(self, note_type: str | None = None) -> int:
        with self._lock:
            if note_type:
                return self._cursor.execute(
                    "SELECT COUNT(*) FROM notes WHERE note_type = ?", (note_type,)
                ).fetchone()[0]
            return self._cursor.execute("SELECT COUNT(*) FROM notes").fetchone()[0]

    def count_today(self) -> int:
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            return self._cursor.execute(
                "SELECT COUNT(*) FROM notes WHERE timestamp LIKE ? AND note_type = 'note'",
                (f"{today}%",),
            ).fetchone()[0]
