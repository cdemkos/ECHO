# decay.py – Automatische Archivierung alter, unreferenzierter Notizen

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR    = Path("data")
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def run_decay(db, archive_after_days: int = 90, reference_window_days: int = 30) -> int:
    cutoff     = (datetime.now() - timedelta(days=archive_after_days)).isoformat()
    ref_cutoff = (datetime.now() - timedelta(days=reference_window_days)).isoformat()
    old_notes  = db.get_old_unreferenced(cutoff, ref_cutoff)
    archived   = 0
    for note_id, _ts, file_path in old_notes:
        old_path = Path(file_path)
        if old_path.exists():
            shutil.move(str(old_path), ARCHIVE_DIR / old_path.name)
        db.delete_note(note_id)
        archived += 1
    if archived > 0:
        log.info("Decay: %d Notiz(en) archiviert.", archived)
    return archived


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database import NoteDB
    log.info("Starte Decay…")
    count = run_decay(NoteDB())
    log.info("Fertig: %d archiviert.", count)
