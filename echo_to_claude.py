"""
echo_to_claude.py – ECHO Kontext-Bridge für Claude

Zweck:
    Vor einem neuen Claude-Chat relevantes Wissen aus ECHO abrufen
    und als formatierten Kontext-Block ausgeben, den du in den Chat kopierst.

Verwendung:
    python echo_to_claude.py
    python echo_to_claude.py --thema "arti rust crate versionen"
    python echo_to_claude.py --thema "arti" --limit 8 --kein-llm

Workflow:
    1. Dieses Script ausführen
    2. Den ausgegebenen Kontext-Block kopieren
    3. Am Anfang des Claude-Chats einfügen
    4. Claude hat sofort dein gespeichertes Wissen
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Gleiche Imports wie der Rest von ECHO
from database import NoteDB
from llm import generate_summary


# ── Konfiguration ──────────────────────────────────────────────────────────────

DEFAULT_LIMIT      = 6      # Anzahl semantisch ähnlicher Notizen
SCORE_THRESHOLD    = 0.45   # Notizen unter diesem Cosine-Score weglassen
MAX_NOTE_CHARS     = 400    # Einzelne Notiz auf diese Länge kürzen
CLAUDE_CONTEXT_TAG = "ECHO_KONTEXT"  # Erkennungs-Tag im Ausgabe-Block


# ── Hauptlogik ─────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="ECHO → Claude Kontext-Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--thema", "-t",
        type=str,
        default=None,
        help="Suchthema (z.B. 'arti rust versionen'). Ohne Angabe: interaktiv abfragen.",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximale Anzahl Notizen (Standard: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--kein-llm",
        action="store_true",
        help="Nur Notizen ausgeben, keine LLM-Zusammenfassung",
    )
    parser.add_argument(
        "--kopierbereit",
        action="store_true",
        help="Nur den Kontext-Block ausgeben (kein Fortschritts-Text)",
    )
    args = parser.parse_args()

    # Thema abfragen wenn nicht übergeben
    thema = args.thema
    if not thema:
        if args.kopierbereit:
            print("Fehler: --kopierbereit benötigt --thema", file=sys.stderr)
            sys.exit(1)
        thema = input("Thema für diesen Claude-Chat: ").strip()
        if not thema:
            print("Kein Thema angegeben.", file=sys.stderr)
            sys.exit(1)

    if not args.kopierbereit:
        print(f"\n🔍 Suche in ECHO nach: '{thema}'")

    # ── ECHO Datenbank abfragen ────────────────────────────────────────────────
    try:
        db = NoteDB()
    except Exception as e:
        print(f"❌ ECHO-Datenbank konnte nicht geöffnet werden: {e}", file=sys.stderr)
        print("   Stelle sicher dass du das Script aus dem ECHO-Verzeichnis startest.", file=sys.stderr)
        sys.exit(1)

    hits = db.search(thema, limit=args.limit)

    if not hits:
        if not args.kopierbereit:
            print("ℹ️  Keine relevanten Notizen gefunden.")
            print("   Tipp: Trag Wissen nach einem Chat in ECHO ein:")
            print(f"   → '{thema}: <was du gelernt hast>'")
        sys.exit(0)

    if not args.kopierbereit:
        print(f"✅ {len(hits)} Notiz(en) gefunden\n")

    # ── Notizen aufbereiten ────────────────────────────────────────────────────
    notizen_text = ""
    for i, hit in enumerate(hits, 1):
        ts   = hit.get("timestamp", "unbekannt")
        text = hit.get("text", "").strip()

        # Zu lange Notizen kürzen
        if len(text) > MAX_NOTE_CHARS:
            text = text[:MAX_NOTE_CHARS].rsplit(" ", 1)[0] + " …"

        notizen_text += f"[{i}] {ts}\n{text}\n\n"

    # ── LLM-Zusammenfassung (optional) ────────────────────────────────────────
    zusammenfassung = ""
    if not args.kein_llm:
        if not args.kopierbereit:
            print("🤖 Erstelle LLM-Zusammenfassung (Ollama)…")

        prompt = f"""Du bist ein Assistent der einem Entwickler hilft, Kontext für eine neue KI-Chat-Session vorzubereiten.

Thema des nächsten Chats: "{thema}"

Folgende Notizen wurden aus dem persönlichen Second-Brain des Entwicklers abgerufen:
---
{notizen_text}
---

Fasse das relevante Wissen in 3-6 präzisen Stichpunkten zusammen.
Fokus auf: Fallstricke, korrekte Versionen, gelernte Lösungen, offene Punkte.
Antworte auf Deutsch. Kein Fließtext, nur Stichpunkte mit • als Zeichen.
Wenn kein relevantes Wissen vorhanden ist, schreib nur: "Keine relevanten Vorkenntnisse gefunden."
"""
        zusammenfassung = await generate_summary(prompt)

    # ── Kontext-Block formatieren ──────────────────────────────────────────────
    now    = datetime.now().strftime("%Y-%m-%d %H:%M")
    block  = format_kontext_block(
        thema=thema,
        notizen_text=notizen_text,
        zusammenfassung=zusammenfassung,
        timestamp=now,
        mit_llm=not args.kein_llm,
    )

    # ── Ausgabe ────────────────────────────────────────────────────────────────
    if not args.kopierbereit:
        print("─" * 60)
        print("📋 KONTEXT-BLOCK (kopieren und in Claude einfügen):")
        print("─" * 60)

    print(block)

    if not args.kopierbereit:
        print("─" * 60)
        print("✅ Fertig. Kopiere den Block oben in deinen Claude-Chat.")


def format_kontext_block(
    thema: str,
    notizen_text: str,
    zusammenfassung: str,
    timestamp: str,
    mit_llm: bool,
) -> str:
    """
    Formatiert den Kontext-Block den Claude am Anfang des Chats liest.
    Das Format ist so gewählt dass Claude es sofort versteht und
    als verlässliche Vorinformation behandelt.
    """
    lines = [
        f"<{CLAUDE_CONTEXT_TAG}>",
        f"Datum: {timestamp}",
        f"Thema: {thema}",
        f"Quelle: ECHO (lokales Second-Brain, semantische Suche)",
        "",
    ]

    if mit_llm and zusammenfassung and "Keine relevanten" not in zusammenfassung:
        lines += [
            "## Zusammenfassung des gespeicherten Wissens",
            zusammenfassung,
            "",
        ]

    lines += [
        "## Gespeicherte Notizen (nach Relevanz sortiert)",
        notizen_text.strip(),
        "",
        "## Hinweis an Claude",
        "Diese Notizen stammen aus meinem persönlichen Wissens-Archiv.",
        "Behandle sie als verlässlichen Kontext — sie beschreiben Erfahrungen",
        "und Lösungen aus früheren Arbeitssessions.",
        "Wenn eine Notiz eine Versionsnummer oder einen Fallstrick nennt,",
        "übernimm diese Information ohne sie in Frage zu stellen.",
        f"</{CLAUDE_CONTEXT_TAG}>",
    ]

    return "\n".join(lines)


# ── Einstieg ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(main())
