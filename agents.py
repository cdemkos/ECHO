# agents.py – Regelbasierte Mini-Agenten
#
# Laufen einmal beim Server-Start, geben Hinweise für die UI zurück.
# Synchron aber schnell (nur SQLite-Abfragen, kein LLM).
# Filtert Auto-Notizen (Reflexionen, Tageszusammenfassungen) automatisch aus.

import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


def check_agents(db) -> list[str]:
    hints = []
    try:
        hints += _agent_no_notes_today(db)
        hints += _agent_recurring_topic(db)
        hints += _agent_open_todos(db)
    except Exception as e:
        log.warning("Agent-Check fehlgeschlagen: %s", e)
    return hints


def _agent_no_notes_today(db) -> list[str]:
    """Warnt wenn heute noch keine echte Notiz (note_type='note') geschrieben wurde."""
    today = datetime.now().strftime("%Y-%m-%d")
    notes = db.get_notes_since(today + "T00:00:00", note_type="note")
    if not notes:
        return ["💡 Du hast heute noch keinen Gedanken festgehalten."]
    return []


def _agent_recurring_topic(db) -> list[str]:
    """Erkennt häufige Begriffe der letzten 7 Tage (nur echte Notizen)."""
    since = (datetime.now() - timedelta(days=7)).isoformat()
    notes = db.get_notes_since(since, note_type="note")
    if len(notes) < 5:
        return []

    stopwords = {
        "und", "der", "die", "das", "ist", "ich", "du", "es", "ein", "eine",
        "nicht", "mit", "für", "in", "an", "auf", "zu", "von", "sie", "wir",
        "aber", "auch", "noch", "schon", "dann", "wenn", "wie", "was", "dass",
        "have", "been", "that", "this", "with", "from", "they",
    }
    word_count: dict[str, int] = {}
    for _, _, text, _ in notes:
        for word in text.lower().split():
            word = word.strip(".,!?;:\"'()[]{}#*_")
            if len(word) > 4 and word not in stopwords:
                word_count[word] = word_count.get(word, 0) + 1

    recurring = [w for w, c in word_count.items() if c >= 4]
    if recurring:
        top = sorted(recurring, key=lambda w: -word_count[w])[:3]
        return [f"🔁 Wiederkehrende Themen diese Woche: **{', '.join(top)}**"]
    return []


def _agent_open_todos(db) -> list[str]:
    """Zählt echte Notizen mit TODO-Markierung."""
    since = (datetime.now() - timedelta(days=30)).isoformat()
    notes = db.get_notes_since(since, note_type="note")
    count = sum(1 for _, _, text, _ in notes if "todo" in text.lower())
    if count >= 3:
        return [f"📋 {count} offene TODOs in den letzten 30 Tagen — Zeit zum Aufräumen?"]
    return []
