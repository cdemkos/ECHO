# decay.py – Automatische Archivierung alter Notizen

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sqlite3

DATA_DIR = Path("data")
NOTES_DIR = DATA_DIR / "notes"
ARCHIVE_DIR = DATA_DIR / "archive"
DB_PATH = DATA_DIR / "echo.db"

ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

def run_decay():
    try:
        # Parameter (anpassbar)
        archive_after_days = 90
        reference_window_days = 30

        cutoff = (datetime.now() - timedelta(days=archive_after_days)).isoformat()
        reference_cutoff = (datetime.now() - timedelta(days=reference_window_days)).isoformat()

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Alte Notizen finden, die lange nicht referenziert wurden
        cursor.execute("""
            SELECT id, timestamp, file_path 
            FROM notes 
            WHERE timestamp < ? 
            AND (SELECT COUNT(*) FROM notes 
                 WHERE text LIKE '%' || notes.id || '%' 
                 AND timestamp > ?) = 0
        """, (cutoff, reference_cutoff))

        old_notes = cursor.fetchall()

        archived_count = 0
        for note_id, ts, file_path in old_notes:
            old_path = Path(file_path)
            if old_path.exists():
                shutil.move(str(old_path), ARCHIVE_DIR / old_path.name)
                archived_count += 1

            # Aus Chroma und SQLite entfernen
            # (Achtung: Chroma-Collection muss manuell gelöscht werden, da keine Python-ID bekannt)
            cursor.execute("DELETE FROM notes WHERE id = ?", (note_id,))

        conn.commit()
        conn.close()

        if archived_count > 0:
            print(f"Decay: {archived_count} alte Notizen wurden archiviert.")
        else:
            print("Decay: Keine Notizen zum Archivieren gefunden.")

    except Exception as e:
        print(f"Decay fehlgeschlagen: {e}")


if __name__ == "__main__":
    print("Starte Decay-Prozess...")
    run_decay()
    print("Decay abgeschlossen.")
