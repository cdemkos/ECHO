import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer
import sqlite3
from pathlib import Path

class NoteDB:
    def __init__(self):
        self.client = chromadb.PersistentClient(path="data/chroma")
        self.collection = self.client.get_or_create_collection("echo_notes")
        self.model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
        self.conn = sqlite3.connect('data/echo.db')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                text TEXT,
                file_path TEXT,
                embedding_id TEXT
            )
        ''')
        self.conn.commit()

    def add_note(self, note_id, timestamp, text, file_path, embedding):
        self.collection.add(
            ids=[note_id],
            embeddings=[embedding.tolist()],
            metadatas=[{"timestamp": timestamp, "file_path": str(file_path)}],
            documents=[text]
        )
        self.cursor.execute(
            "INSERT OR REPLACE INTO notes VALUES (?, ?, ?, ?, ?)",
            (note_id, timestamp, text, file_path, note_id)
        )
        self.conn.commit()

    def search(self, query_text, limit=5):
        query_emb = self.model.encode(query_text).tolist()
        results = self.collection.query(query_embeddings=[query_emb], n_results=limit)
        
        hits = []
        for i in range(len(results['ids'][0])):
            id_ = results['ids'][0][i]
            self.cursor.execute("SELECT timestamp, text FROM notes WHERE id = ?", (id_,))
            row = self.cursor.fetchone()
            if row:
                hits.append({"timestamp": row[0], "text": row[1]})
        return hits
