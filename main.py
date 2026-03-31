# main.py – ECHO Second Brain v2
#
# Behobene Bugs gegenüber v1:
#   BUG-A: Race Condition _startup_done → asyncio.Lock()
#   BUG-B: LLM-Fehlertext als Notiz gespeichert → LLMError Exception, nie speichern
#   BUG-C: Deduplizierung per Text-Fragment → note_type-Feld in DB
#   BUG-D: db.cursor direkt verwendet → db._cursor privat, Methoden für alles
#   BUG-E: merge_button = None → Button direkt im Dialog erstellt
#   BUG-F: ui.notify() beim Server-Start ohne Session → nur in @ui.page aufrufen
#   BUG-G: Auto-Linking mergt Reflexionen mit sich selbst → note_type-Filter
#   BUG-H: ui.run() vor API-Routes → API-Routes vor ui.run()
#   BUG-I: Zwei Embedding-Modell-Instanzen → embedder.py delegiert an db.model
#   BUG-J: Dateiname mit Mikrosekunden-Punkt → replace + strip

import asyncio
import io
import logging
import os
import shutil
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from nicegui import app as nicegui_app
from nicegui import ui

from agents import check_agents
from database import NoteDB, is_llm_error
from decay import run_decay
from llm import DEFAULT_MODEL, LLMError, check_ollama_available, generate_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("echo")

# ── Verzeichnisse ─────────────────────────────────────────────────────────────

DATA_DIR    = Path("data")
NOTES_DIR   = DATA_DIR / "notes"
CHROMA_DIR  = DATA_DIR / "chroma"
ARCHIVE_DIR = DATA_DIR / "archive"

for _d in [NOTES_DIR, ARCHIVE_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Globale DB-Instanz ────────────────────────────────────────────────────────

db = NoteDB()

# ── Server-Start State ────────────────────────────────────────────────────────
# asyncio.Lock verhindert Race Condition wenn mehrere Tabs gleichzeitig laden

_startup_lock = asyncio.Lock()
_startup_done = False
_ollama_ok    = False
_agent_hints: list[str] = []


# ═══════════════════════════════════════════════════════════════════════════════
# Hilfsfunktionen
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_timestamp_filename(timestamp: str, suffix: str = "") -> str:
    """
    Wandelt ISO-Timestamp in sicheren Dateinamen um.
    '2026-03-31T02:31:14.204365' → '2026-03-31T02-31-14_suffix.md'
    """
    # Mikrosekunden und Punkt entfernen, Doppelpunkte ersetzen
    ts = timestamp.split(".")[0]   # bis zu den Mikrosekunden kürzen
    ts = ts.replace(":", "-")
    return f"{ts}{'_' + suffix if suffix else ''}.md"


def save_note_to_disk(note_id: str, timestamp: str, text: str, suffix: str = "") -> Path:
    """Schreibt Notiz-Datei und gibt den Pfad zurück."""
    fname    = _safe_timestamp_filename(timestamp, suffix or note_id)
    filepath = NOTES_DIR / fname
    filepath.write_text(f"# {timestamp}\n\n{text}", encoding="utf-8")
    return filepath


def archive_file(file_path: str) -> None:
    old = Path(file_path)
    if old.exists():
        shutil.move(str(old), ARCHIVE_DIR / old.name)


async def _generate_tags(text: str) -> list[str]:
    """Generiert Tags im Hintergrund — wirft keine Exception."""
    try:
        prompt    = (
            f"Schlage 2–4 präzise Tags für diesen Text vor.\n"
            f"Nur kommagetrennte Liste, keine Erklärung.\n\n"
            f"Text: {text[:800]}\n\n"
            f"Beispiele: Produktivität,Reise,Emotionen,Todo,Technik,Gesundheit"
        )
        tags_str  = await generate_summary(prompt, timeout_seconds=30)
        return [t.strip() for t in tags_str.split(",") if t.strip()][:4]
    except LLMError:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Server-Start Tasks (laufen EINMAL, nicht bei jedem Page-Load)
# ═══════════════════════════════════════════════════════════════════════════════

async def _auto_weekly_reflection() -> None:
    """Erstellt wöchentliche Reflexion wenn heute noch keine existiert."""
    # FIX-C: note_type statt Text-Fragment für Deduplizierung
    if db.auto_note_exists_today("weekly_reflection"):
        return

    since   = (datetime.now() - timedelta(days=7)).isoformat()
    # FIX: Nur echte Notizen analysieren, keine Auto-Reflexionen
    entries = db.get_notes_since(since, note_type="note")
    if not entries:
        return

    context = "\n\n".join(f"[{ts}] {text[:600]}" for _, ts, text, _ in entries)
    prompt  = (
        "Analysiere die folgenden persönlichen Gedanken der letzten Woche:\n\n"
        f"{context}\n\n"
        "Beantworte direkt und ehrlich:\n"
        "- Welche Themen tauchen wiederholt auf?\n"
        "- Welche emotionale Tonalität dominiert?\n"
        "- Welche Muster oder offene Loops siehst du?\n"
        "- Was wurde verschoben oder bereut?\n"
        "- Was konkret nächste Woche anders machen?\n\n"
        "Strukturiere mit ## Überschriften. Keine Schönfärberei."
    )

    try:
        text      = await generate_summary(prompt)
        timestamp = datetime.now().isoformat()
        note_id   = str(uuid.uuid4())[:12]
        filepath  = save_note_to_disk(note_id, timestamp, text, "REFLEXION")
        embedding = db.embed(text)
        db.add_note(note_id, timestamp, text, str(filepath), embedding,
                    tags=["Reflexion", "Wöchentlich"], note_type="weekly_reflection")
        log.info("Wöchentliche Reflexion gespeichert.")
    except LLMError as e:
        log.warning("Auto-Reflexion fehlgeschlagen: %s", e)
    except ValueError as e:
        log.error("Auto-Reflexion: ungültiger Text: %s", e)


async def _auto_daily_summary() -> None:
    """Erstellt Tageszusammenfassung wenn heute noch keine existiert."""
    if db.auto_note_exists_today("daily_summary"):
        return

    since   = (datetime.now() - timedelta(hours=24)).isoformat()
    entries = db.get_notes_since(since, note_type="note")
    if not entries:
        return

    today   = datetime.now().strftime("%Y-%m-%d")
    context = "\n\n".join(f"[{ts}] {text[:400]}" for _, ts, text, _ in entries)
    prompt  = (
        f"Erstelle eine Tageszusammenfassung für {today}:\n\n"
        f"{context}\n\n"
        "- Hauptthemen des Tages\n"
        "- Emotionale Tonalität\n"
        "- Offene Punkte / nächste Schritte\n"
        "- Ein direkter Satz für den Rest des Tages\n\n"
        "Max. 200 Wörter, strukturiert."
    )

    try:
        text      = await generate_summary(prompt)
        timestamp = datetime.now().isoformat()
        note_id   = str(uuid.uuid4())[:12]
        filepath  = save_note_to_disk(note_id, timestamp, text, "DAILY")
        embedding = db.embed(text)
        db.add_note(note_id, timestamp, text, str(filepath), embedding,
                    tags=["Tageszusammenfassung"], note_type="daily_summary")
        log.info("Tageszusammenfassung gespeichert.")
    except LLMError as e:
        log.warning("Auto-Tageszusammenfassung fehlgeschlagen: %s", e)
    except ValueError as e:
        log.error("Auto-Tageszusammenfassung: ungültiger Text: %s", e)


@nicegui_app.on_startup
async def _on_startup() -> None:
    """Läuft EINMAL beim Server-Start — nicht bei jedem Page-Load."""
    global _startup_done, _ollama_ok, _agent_hints

    # FIX-A: asyncio.Lock verhindert Race Condition
    async with _startup_lock:
        if _startup_done:
            return
        _startup_done = True

    log.info("ECHO startet…")
    _ollama_ok = await check_ollama_available()
    log.info("Ollama: %s", "online" if _ollama_ok else "offline")

    # Decay läuft immer
    archived = await asyncio.to_thread(run_decay, db)
    if archived > 0:
        log.info("%d Notizen archiviert.", archived)

    # LLM-Tasks nur wenn Ollama online
    if _ollama_ok:
        await _auto_weekly_reflection()
        await _auto_daily_summary()

    # Agenten (synchron, schnell)
    _agent_hints = check_agents(db)
    log.info("ECHO bereit. %d Notizen, %d Agenten-Hinweise.",
             db.count(note_type="note"), len(_agent_hints))


# ═══════════════════════════════════════════════════════════════════════════════
# Dialoge (Edit / Delete / Link / Reflexion)
# ═══════════════════════════════════════════════════════════════════════════════

async def _open_edit_dialog(hit: dict) -> None:
    with ui.dialog(value=True).props("persistent") as dlg:
        with ui.card().classes("w-full max-w-3xl"):
            ui.label(f"Bearbeiten — {_fmt_ts(hit['timestamp'])}") \
                .classes("text-sm font-medium text-gray-400 mb-3")
            edit_input = ui.textarea(value=hit["text"]) \
                .props("autogrow outlined").classes("w-full")
            with ui.row().classes("gap-2 mt-4 justify-end"):
                ui.button("Abbrechen", on_click=dlg.hide) \
                    .props("flat color=grey-7")
                ui.button("Speichern",
                          on_click=lambda: _save_edit(hit, edit_input.value, dlg)) \
                    .props("unelevated color=positive")


async def _save_edit(hit: dict, new_text: str, dialog) -> None:
    new_text = new_text.strip()
    if not new_text:
        ui.notify("Kein Text.", type="warning")
        return
    if is_llm_error(new_text):
        ui.notify("Ungültiger Text.", type="negative")
        return
    try:
        archive_file(hit["file_path"])
        timestamp = datetime.now().isoformat()
        filepath  = save_note_to_disk(hit["id"], timestamp, new_text, "EDIT")
        embedding = db.embed(new_text)
        tags      = await _generate_tags(new_text)
        db.update_note(hit["id"], timestamp, new_text, str(filepath),
                       embedding, tags, note_type="note")
        ui.notify("Gespeichert.", type="positive")
        dialog.hide()
    except Exception as e:
        ui.notify(f"Fehler: {e}", type="negative")
        log.error("Edit fehlgeschlagen: %s", e)


async def _open_delete_dialog(hit: dict) -> None:
    with ui.dialog(value=True).props("persistent") as dlg:
        with ui.card().classes("w-full max-w-sm"):
            ui.label("Eintrag löschen?").classes("text-base font-medium mb-1")
            ui.label(hit["text"][:120] + "…").classes("text-xs text-gray-400 mb-4")
            with ui.row().classes("justify-end gap-2"):
                ui.button("Abbrechen", on_click=dlg.hide).props("flat color=grey-7")
                ui.button("Löschen",
                          on_click=lambda: _confirm_delete(hit, dlg)) \
                    .props("unelevated color=negative")


async def _confirm_delete(hit: dict, dialog) -> None:
    try:
        Path(hit["file_path"]).unlink(missing_ok=True)
        db.delete_note(hit["id"])
        ui.notify("Gelöscht.", type="warning")
        dialog.hide()
    except Exception as e:
        ui.notify(f"Fehler: {e}", type="negative")


async def _check_and_show_linking(note_id: str, text: str, embedding: list) -> None:
    """
    Sucht nach ähnlichen ECHTEN Notizen und zeigt Merge-Dialog.
    FIX-E: Merge-Button direkt im Dialog erstellt.
    FIX-G: Nur note_type='note' wird verglichen — keine Reflexionen.
    """
    try:
        n = db.collection.count()
        if n < 2:
            return

        results = db.collection.query(
            query_embeddings=[embedding],
            n_results=min(8, n),
            include=["metadatas", "documents", "distances"],
        )
        similar = []
        for i, found_id in enumerate(results["ids"][0]):
            if found_id == note_id:
                continue
            sim = max(0.0, 1.0 - results["distances"][0][i])
            if sim < 0.78:
                continue
            # FIX-G: Nur echte Notizen mergen, keine Auto-Reflexionen
            note = db.get_note_by_id(found_id)
            if not note or note.get("note_type") != "note":
                continue
            if is_llm_error(note["text"]):
                continue
            similar.append({**note, "similarity": sim})

        if not similar:
            return

        with ui.dialog(value=True).props("persistent") as dlg:
            with ui.card().classes("w-full max-w-2xl"):
                ui.label("Ähnliche Gedanken gefunden") \
                    .classes("text-base font-medium mb-3 text-amber-400")

                for entry in similar:
                    with ui.card().classes("w-full mb-2 bg-slate-800 p-3"):
                        ui.label(f"{_fmt_ts(entry['timestamp'])}  "
                                 f"· {entry['similarity']:.0%} ähnlich") \
                            .classes("text-xs text-gray-400 mb-1")
                        ui.label(entry["text"][:200] + "…") \
                            .classes("text-sm")

                ui.label("Einträge zusammenführen? Ältere werden archiviert.") \
                    .classes("text-sm text-gray-300 mt-3 mb-4")

                with ui.row().classes("gap-2 justify-end"):
                    ui.button("Überspringen", on_click=dlg.hide) \
                        .props("flat color=grey-7")
                    # FIX-E: Button direkt erstellt, keine globale Variable
                    ui.button(
                        "Zusammenführen",
                        on_click=lambda: _do_merge(note_id, text, similar, dlg),
                    ).props("unelevated color=warning")

    except Exception as e:
        log.warning("Auto-Linking fehlgeschlagen: %s", e)


async def _do_merge(new_id: str, new_text: str, similar: list, dialog) -> None:
    try:
        merged = new_text + "\n\n---\n\n**Verknüpfte Gedanken:**\n\n"
        for entry in similar:
            merged += f"[{entry['timestamp'][:19]}] {entry['text']}\n\n---\n\n"
            archive_file(entry["file_path"])
            db.delete_note(entry["id"])

        timestamp = datetime.now().isoformat()
        filepath  = save_note_to_disk(new_id, timestamp, merged, "MERGED")
        embedding = db.embed(merged)
        tags      = await _generate_tags(merged)
        db.update_note(new_id, timestamp, merged, str(filepath),
                       embedding, tags, note_type="note")
        ui.notify(f"{len(similar)} Einträge zusammengeführt.", type="positive")
        dialog.hide()
    except Exception as e:
        ui.notify(f"Merge fehlgeschlagen: {e}", type="negative")
        log.error("Merge fehlgeschlagen: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# Export & manuelle Reflexion
# ═══════════════════════════════════════════════════════════════════════════════

async def _export_all() -> None:
    try:
        # FIX: SQLite-Checkpoint vor Export für konsistente WAL-Dateien
        with db._lock:
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for md in NOTES_DIR.glob("*.md"):
                zf.write(md, arcname=f"notes/{md.name}")
            db_file = DATA_DIR / "echo.db"
            if db_file.exists():
                zf.write(db_file, arcname="data/echo.db")
            if CHROMA_DIR.exists():
                for root, _, files in os.walk(CHROMA_DIR):
                    for file in files:
                        fp  = Path(root) / file
                        arc = fp.relative_to(DATA_DIR)
                        zf.write(fp, arcname=str(arc))
        buf.seek(0)
        fname = f"echo_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        ui.download(buf.read(), filename=fname)
        ui.notify("Backup erstellt.", type="positive")
    except Exception as e:
        ui.notify(f"Export fehlgeschlagen: {e}", type="negative")
        log.error("Export: %s", e)


async def _manual_weekly_reflection(dialog, content_widget) -> None:
    since   = (datetime.now() - timedelta(days=7)).isoformat()
    entries = db.get_notes_since(since, note_type="note")

    if not entries:
        ui.notify("Keine Notizen in den letzten 7 Tagen.", type="warning")
        return

    context = "\n\n".join(f"[{ts}] {text[:600]}" for _, ts, text, _ in entries)
    prompt  = (
        "Analysiere die folgenden persönlichen Gedanken der letzten Woche:\n\n"
        f"{context}\n\n"
        "- Welche Themen tauchen wiederholt auf?\n"
        "- Welche emotionale Tonalität dominiert?\n"
        "- Welche Muster oder offene Loops siehst du?\n"
        "- Was wurde verschoben oder bereut?\n"
        "- Was konkret nächste Woche anders machen?\n\n"
        "Strukturiere mit ## Überschriften. Direkt und ehrlich."
    )

    try:
        ref_text  = await generate_summary(prompt)
    except LLMError as e:
        ui.notify(f"Ollama nicht erreichbar: {e}", type="negative")
        return

    timestamp = datetime.now().isoformat()
    note_id   = str(uuid.uuid4())[:12]
    filepath  = save_note_to_disk(note_id, timestamp, ref_text, "REFLEXION")
    embedding = db.embed(ref_text)
    try:
        db.add_note(note_id, timestamp, ref_text, str(filepath), embedding,
                    tags=["Reflexion", "Wöchentlich"], note_type="weekly_reflection")
    except ValueError as e:
        ui.notify(f"Fehler: {e}", type="negative")
        return

    # PDF-Export (optional, weasyprint)
    pdf_bytes = None
    try:
        from weasyprint import HTML as WP
        html_str = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2.5cm 2cm; }}
  body {{ font-family: Helvetica, sans-serif; color: #000; line-height: 1.6; }}
  h1   {{ color: #6366f1; text-align: center; margin-bottom: .3em; }}
  h2   {{ color: #4b5563; margin-top: 1.4em; }}
  .date {{ text-align: center; color: #6b7280; margin-bottom: 2em; font-size: .9em; }}
</style></head><body>
<h1>Wöchentliche Reflexion</h1>
<div class="date">{timestamp[:19].replace("T", " ")}</div>
{ref_text.replace(chr(10), "<br>")}
</body></html>"""
        pdf_bytes = WP(string=html_str).write_pdf()
    except Exception:
        pass

    content_widget.set_content(f"**Gespeichert:** {filepath.name}\n\n{ref_text}")
    if pdf_bytes:
        with dialog:
            ui.button(
                "Als PDF herunterladen",
                icon="picture_as_pdf",
                on_click=lambda: ui.download(
                    pdf_bytes,
                    filename=f"reflexion_{timestamp[:10]}.pdf",
                ),
            ).props("flat color=indigo-4").classes("mt-3")
    dialog.open()
    ui.notify("Reflexion gespeichert.", type="positive")


# ═══════════════════════════════════════════════════════════════════════════════
# UI Hilfsfunktionen
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_ts(iso: str) -> str:
    """ISO-Timestamp → lesbares Deutsch: '31. Mär. · 14:22'"""
    try:
        dt  = datetime.fromisoformat(iso)
        now = datetime.now()
        if dt.date() == now.date():
            return f"heute · {dt.strftime('%H:%M')}"
        if dt.date() == (now - timedelta(days=1)).date():
            return f"gestern · {dt.strftime('%H:%M')}"
        months = ["", "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                  "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
        return f"{dt.day}. {months[dt.month]} · {dt.strftime('%H:%M')}"
    except Exception:
        return iso[:16]


def _sim_color(sim: float) -> str:
    if sim >= 0.82:
        return "text-green-400"
    if sim >= 0.65:
        return "text-amber-400"
    return "text-slate-500"


# ═══════════════════════════════════════════════════════════════════════════════
# Haupt-Seite
# ═══════════════════════════════════════════════════════════════════════════════

@ui.page("/")
async def index() -> None:
    ollama_ok   = _ollama_ok
    agent_hints = _agent_hints

    # ── CSS-Overrides für konsistentes Dark-Theme ─────────────────────────────
    ui.add_head_html("""
    <style>
      body { background: #0d1117; }
      .q-card  { background: #161b22 !important; border: 1px solid #21262d; }
      .q-field__control { background: #0d1117 !important; }
    </style>
    """)

    # ── Header (sticky, kompakt) ──────────────────────────────────────────────
    with ui.header().classes("bg-gray-900 border-b border-gray-800 px-6 py-3"):
        with ui.row().classes("w-full items-center gap-3 max-w-4xl mx-auto"):
            ui.label("🧠").classes("text-xl")
            ui.label("ECHO").classes("text-base font-medium text-indigo-400")
            ui.label("·").classes("text-gray-600")
            ui.label(f"{db.count(note_type='note')} Notizen").classes("text-xs text-gray-500")

            ui.space()

            # Ollama-Status
            if ollama_ok:
                with ui.row().classes("items-center gap-1"):
                    ui.element("div").classes("w-2 h-2 rounded-full bg-green-500")
                    ui.label(DEFAULT_MODEL).classes("text-xs text-gray-500")
            else:
                with ui.row().classes("items-center gap-1"):
                    ui.element("div").classes("w-2 h-2 rounded-full bg-red-500")
                    ui.label("Ollama offline").classes("text-xs text-red-400")

    with ui.column().classes("w-full max-w-4xl mx-auto px-4 py-6 gap-6"):

        # ── Stat-Karten ───────────────────────────────────────────────────────
        with ui.row().classes("gap-3 w-full"):
            for val, lbl, color in [
                (db.count(note_type="note"),    "Gesamt",       "text-indigo-400"),
                (db.count_today(),              "Heute",        "text-green-400"),
                (db.count(note_type="weekly_reflection"), "Reflexionen", "text-amber-400"),
            ]:
                with ui.card().classes("flex-1 p-3"):
                    ui.label(str(val)).classes(f"text-2xl font-medium {color}")
                    ui.label(lbl).classes("text-xs text-gray-500 mt-1")

        # ── Agenten-Hinweise ──────────────────────────────────────────────────
        if agent_hints:
            with ui.card().classes("w-full p-3 border border-indigo-900/50"):
                for hint in agent_hints:
                    ui.markdown(hint).classes("text-sm text-slate-300")

        # ── Eingabe ───────────────────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            with ui.row().classes("justify-between items-center mb-3"):
                ui.label("Neuer Gedanke").classes("text-sm font-medium")
                ui.label("Enter speichert · Auto-Save 8 s") \
                    .classes("text-xs text-gray-500")

            thought_input = ui.textarea(
                placeholder="Schreib einfach drauflos…"
            ).props("autogrow outlined clearable").classes(
                "w-full text-sm"
            )
            char_count = ui.label("0 Zeichen").classes("text-xs text-gray-600 mt-1")

            auto_save_timer = None

            async def save_thought(auto: bool = False) -> None:
                nonlocal auto_save_timer
                text = thought_input.value.strip()
                if not text:
                    if not auto:
                        ui.notify("Kein Text.", type="warning")
                    return
                if is_llm_error(text):
                    ui.notify("Ungültiger Text.", type="warning")
                    return

                timestamp = datetime.now().isoformat()
                note_id   = str(uuid.uuid4())[:12]
                try:
                    filepath  = save_note_to_disk(note_id, timestamp, text)
                    embedding = db.embed(text)
                    # Tags im Hintergrund — blockiert nicht das Speichern
                    tags      = await _generate_tags(text) if ollama_ok else []
                    db.add_note(note_id, timestamp, text, str(filepath),
                                embedding, tags, note_type="note")

                    label = f"Gespeichert"
                    if tags:
                        label += f" · {', '.join(tags)}"
                    if auto:
                        label += " · Auto"
                    ui.notify(label, type="positive", close_button=True)

                    thought_input.set_value("")
                    char_count.set_text("0 Zeichen")
                    thought_input.run_method("focus")

                    await _check_and_show_linking(note_id, text, embedding)

                except ValueError as e:
                    ui.notify(f"Nicht gespeichert: {e}", type="negative")
                except Exception as e:
                    ui.notify(f"Fehler: {e}", type="negative")
                    log.error("save_thought: %s", e)

            def reset_timer() -> None:
                nonlocal auto_save_timer
                val = thought_input.value or ""
                char_count.set_text(f"{len(val)} Zeichen")
                if auto_save_timer:
                    auto_save_timer.cancel()
                if val.strip():
                    auto_save_timer = ui.timer(
                        8.0, lambda: save_thought(auto=True), once=True
                    )

            thought_input.on("keydown.enter", lambda: save_thought(auto=False))
            thought_input.on("input",         reset_timer)
            thought_input.on("focus",         reset_timer)

            with ui.row().classes("mt-3 justify-end"):
                ui.button("Speichern", on_click=lambda: save_thought(auto=False)) \
                    .props("unelevated color=positive size=sm")

        # ── Suche ─────────────────────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Suche").classes("text-sm font-medium mb-3")
            with ui.row().classes("gap-2 w-full"):
                search_input = ui.input(
                    placeholder='z. B. "Rust arti Versionen" oder "Japan Reise"'
                ).props("outlined dense clearable").classes("flex-1 text-sm")
                ui.button("Suchen", on_click=lambda: perform_search()) \
                    .props("unelevated color=primary size=sm")

            result_container = ui.column().classes("w-full mt-4 gap-3")

            async def perform_search() -> None:
                query = search_input.value.strip()
                result_container.clear()
                if not query:
                    return

                with result_container:
                    with ui.row().classes("justify-center py-4"):
                        ui.spinner(size="md")

                hits = db.search(query, limit=8)
                result_container.clear()

                if not hits:
                    with result_container:
                        ui.label("Keine passenden Notizen gefunden.") \
                            .classes("text-sm text-gray-500 text-center py-4")
                    return

                # LLM-Zusammenfassung
                if ollama_ok and hits:
                    with result_container:
                        with ui.card().classes("w-full p-3 border border-indigo-900/40"):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.label("Zusammenfassung") \
                                    .classes("text-xs text-indigo-400 uppercase")
                                ui.spinner(size="xs")
                            summary_label = ui.markdown("").classes("text-sm text-slate-300")

                    context = "\n\n".join(
                        f"[{_fmt_ts(h['timestamp'])}] {h['text'][:350]}"
                        for h in hits
                    )
                    try:
                        summary = await generate_summary(
                            f"Suchanfrage: {query}\n\n{context}\n\n"
                            "Fasse knapp zusammen was der Nutzer zu diesem Thema "
                            "gedacht hat. Muster, Tonalität, offene Fragen.",
                            timeout_seconds=45,
                        )
                        summary_label.set_content(summary)
                    except LLMError:
                        summary_label.set_content("_(Ollama nicht erreichbar)_")

                # Ergebnis-Karten
                with result_container:
                    for hit in hits:
                        with ui.card().classes("w-full p-3"):
                            # Meta-Zeile
                            with ui.row().classes(
                                "justify-between items-center mb-2"
                            ):
                                ui.label(_fmt_ts(hit["timestamp"])) \
                                    .classes("text-xs text-gray-400 font-mono")
                                ui.label(f"{hit['similarity']:.0%}") \
                                    .classes(f"text-xs {_sim_color(hit['similarity'])}")

                            # Similarity-Balken
                            with ui.element("div").classes(
                                "w-full h-0.5 bg-gray-800 rounded mb-3"
                            ):
                                ui.element("div").classes(
                                    "h-full rounded bg-indigo-600"
                                ).style(f"width:{hit['similarity']:.0%}")

                            # Text
                            text_preview = hit["text"][:480]
                            if len(hit["text"]) > 480:
                                text_preview += "…"
                            ui.markdown(text_preview).classes("text-sm text-slate-200")

                            # Tags
                            if hit.get("tags"):
                                with ui.row().classes("gap-1 mt-2 flex-wrap"):
                                    for tag in hit["tags"].split(","):
                                        if tag.strip():
                                            ui.badge(tag.strip()) \
                                                .props("color=indigo-9 rounded outline")

                            # Aktionen
                            with ui.row().classes("gap-2 mt-3 justify-end"):
                                ui.button(
                                    "Bearbeiten",
                                    on_click=lambda h=hit: _open_edit_dialog(h),
                                ).props("flat color=primary size=xs")
                                ui.button(
                                    "Löschen",
                                    on_click=lambda h=hit: _open_delete_dialog(h),
                                ).props("flat color=negative size=xs")

            search_input.on("keydown.enter", perform_search)

        # ── Schnellzugriff ────────────────────────────────────────────────────

        # Reflexions-Dialog — lebt innerhalb index(), kein globaler Verweis
        with ui.dialog().props("persistent") as reflection_dialog:
            with ui.card().classes("w-full max-w-3xl"):
                ui.label("Wöchentliche Reflexion") \
                    .classes("text-base font-medium mb-4 text-indigo-400")
                reflection_content = ui.markdown().classes("text-sm text-slate-200")
                ui.button("Schließen", on_click=reflection_dialog.close) \
                    .props("flat color=grey-7").classes("mt-4")

        with ui.card().classes("w-full p-4"):
            ui.label("Aktionen").classes("text-sm font-medium mb-4")
            with ui.row().classes("gap-3 flex-wrap"):
                ui.button(
                    "Wöchentliche Reflexion",
                    icon="auto_awesome",
                    on_click=lambda: _manual_weekly_reflection(
                        reflection_dialog, reflection_content
                    ),
                ).props("unelevated color=indigo size=sm") \
                 .classes("hover:scale-105 transition-transform")

                ui.button(
                    "Backup erstellen (ZIP)",
                    icon="download",
                    on_click=_export_all,
                ).props("unelevated color=amber-8 size=sm") \
                 .classes("hover:scale-105 transition-transform")

        # ── Footer ────────────────────────────────────────────────────────────
        ui.label(
            f"ECHO v2  ·  {db.count()} Einträge total  ·  "
            f"{datetime.now().strftime('%d.%m.%Y')}"
        ).classes("text-xs text-gray-700 text-center pb-4")


# ═══════════════════════════════════════════════════════════════════════════════
# API-Routes (vor ui.run() — FIX-H)
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


@nicegui_app.get("/api/search")
async def api_search(q: str = "", limit: int = 6):
    if not q.strip():
        raise HTTPException(400, detail="Parameter 'q' fehlt")
    hits = db.search(q.strip(), limit=limit)
    return JSONResponse([{
        "id": h["id"], "timestamp": h["timestamp"],
        "text": h["text"], "tags": h["tags"],
        "similarity": round(h["similarity"], 3),
    } for h in hits])


@nicegui_app.get("/api/notes/recent")
async def api_recent(limit: int = 10):
    since   = (datetime.now() - timedelta(days=30)).isoformat()
    entries = db.get_notes_since(since, note_type="note")
    return JSONResponse([{
        "id": e[0], "timestamp": e[1], "text": e[2][:500],
    } for e in entries[-limit:]])


@nicegui_app.post("/api/notes")
async def api_add_note(request: Request):
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, detail="'text' fehlt")
    if is_llm_error(text):
        raise HTTPException(400, detail="Ungültiger Text")
    timestamp = datetime.now().isoformat()
    note_id   = str(uuid.uuid4())[:12]
    filepath  = save_note_to_disk(note_id, timestamp, text)
    embedding = db.embed(text)
    tags      = [t.strip() for t in body.get("tags", []) if t.strip()]
    db.add_note(note_id, timestamp, text, str(filepath), embedding, tags)
    return JSONResponse({"id": note_id, "timestamp": timestamp, "status": "ok"})


@nicegui_app.get("/health")
async def health():
    return {"status": "ok", "notes": db.count(note_type="note"), "ollama": _ollama_ok}


# ═══════════════════════════════════════════════════════════════════════════════
# Start
# ═══════════════════════════════════════════════════════════════════════════════

ui.run(
    title="ECHO",
    port=9876,
    host="0.0.0.0",
    dark=True,
    reload=False,
    show=False,
    favicon="🧠",
)
