import chromadb
from pathlib import Path
from sentence_transformers import SentenceTransformer
import sqlite3

class NoteDB:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(Path("data") / "chroma"))
        self.collection = self.client.get_or_create_collection(name="echo_notes")
        self.model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
        
        self.conn = sqlite3.connect('data/echo.db')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                text TEXT,
                file_path TEXT
            )
        ''')
        self.conn.commit()

    def add_note(self, note_id: str, timestamp: str, text: str, file_path: str, embedding: list):
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

    def search(self, query_text: str, limit: int = 6):
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
