import chromadb
from pathlib import Path
from sentence_transformers import SentenceTransformer
import sqlite3
from datetime import datetime

class NoteDB:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(Path("data") / "chroma"))
        self.collection = self.client.get_or_create_collection(name="echo_notes")
        try:
            self.model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
        except Exception as e:
            print(f"Embedding-Modell konnte nicht geladen werden: {e}")
            raise

        db_path = Path("data/echo.db")
        db_path.parent.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                text TEXT,
                file_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()

    def add_note(self, note_id: str, timestamp: str, text: str, file_path: str, embedding: list):
        try:
            self.collection.add(
                ids=[note_id],
                embeddings=[embedding],
                metadatas=[{"timestamp": timestamp, "file_path": file_path}],
                documents=[text]
            )
            self.cursor.execute(
                "INSERT OR REPLACE INTO notes (id, timestamp, text, file_path) VALUES (?, ?, ?, ?)",
                (note_id, timestamp, text, file_path)
            )
            self.conn.commit()
        except Exception as e:
            print(f"Fehler beim Hinzufügen der Notiz {note_id}: {e}")
            raise

    def search(self, query_text: str, limit: int = 8):
        try:
            query_emb = self.model.encode(f"search_query: {query_text}").tolist()
            results = self.collection.query(
                query_embeddings=[query_emb],
                n_results=limit
            )

            hits = []
            for i, id_ in enumerate(results['ids'][0]):
                self.cursor.execute("SELECT timestamp, text FROM notes WHERE id = ?", (id_,))
                row = self.cursor.fetchone()
                if row:
                    hits.append({"timestamp": row[0], "text": row[1]})
            return hits
        except Exception as e:
            print(f"Suchfehler: {e}")
            return []
