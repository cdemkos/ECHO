# main.py – ECHO Second Brain
# Stand: März 2026
#
# Korrekturen gegenüber der ursprünglichen Version:
#   BUG 1: merge_button war None → AttributeError beim Auto-Linking
#           Fix: Merge-Button wird im Linking-Dialog korrekt erstellt
#   BUG 2: search() gab kein id/file_path zurück → KeyError bei Edit/Delete
#           Fix: database.py gibt vollständige Dicts zurück
#   BUG 3: decay_and_archive() löschte nicht aus ChromaDB
#           Fix: decay.run_decay(db) nutzt db.delete_note() konsistent
#   BUG 4: globale NiceGUI-Widget-Referenzen (reload-Problem)
#           Fix: Alle Widget-Referenzen leben innerhalb von @ui.page
#   BUG 5: Ollama-Status wurde nicht geprüft → kryptische Fehlermeldungen
#           Fix: Status-Check beim Start, UI-Hinweis wenn offline

from nicegui import ui
from datetime import datetime, timedelta
from pathlib import Path
import uuid
import zipfile
import io
import os
import shutil

from weasyprint import HTML

from database import NoteDB
from embedder import get_embedding
from llm import generate_summary, check_ollama_available, DEFAULT_MODEL
from decay import run_decay
from agents import check_agents

# ── Verzeichnisse ─────────────────────────────────────────────────────────────

DATA_DIR    = Path("data")
NOTES_DIR   = DATA_DIR / "notes"
CHROMA_DIR  = DATA_DIR / "chroma"
ARCHIVE_DIR = DATA_DIR / "archive"

for d in [NOTES_DIR, ARCHIVE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Globale DB-Instanz (wird einmal erstellt, bleibt für den gesamten Prozess) ─

db = NoteDB()


# ═══════════════════════════════════════════════════════════════════════════════
# Hilfsfunktionen (UI-unabhängig)
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_tags(text: str) -> list[str]:
    prompt = (
        f"Analysiere den folgenden Text und schlage 2–4 passende Tags vor.\n"
        f"Gib NUR die Tags als kommagetrennte Liste zurück, ohne Erklärung.\n\n"
        f"Text: {text[:1000]}\n\n"
        f"Beispiele: Produktivität,Reise,Emotionen,Todo,Beziehung,Finanzen,Gesundheit"
    )
    try:
        tags_str = await generate_summary(prompt)
        return [t.strip() for t in tags_str.split(",") if t.strip()][:4]
    except Exception:
        return []


def save_note_to_disk(note_id: str, timestamp: str, text: str) -> Path:
    """Schreibt Notiz als Markdown-Datei und gibt den Pfad zurück."""
    safe_ts  = timestamp.replace(":", "-")
    filename = NOTES_DIR / f"{safe_ts}_{note_id}.md"
    filename.write_text(f"# {timestamp}\n\n{text}", encoding="utf-8")
    return filename


def archive_file(file_path: str) -> None:
    """Verschiebt eine Datei ins Archiv-Verzeichnis."""
    old = Path(file_path)
    if old.exists():
        shutil.move(str(old), ARCHIVE_DIR / old.name)


# ═══════════════════════════════════════════════════════════════════════════════
# Automatische Start-Funktionen
# ═══════════════════════════════════════════════════════════════════════════════

async def auto_weekly_reflection() -> None:
    """Erstellt automatisch eine wöchentliche Reflexion wenn noch keine existiert."""
    since = (datetime.now() - timedelta(days=7)).isoformat()
    if db.note_exists_matching(datetime.now().strftime("%Y-%m-%d"), "Wöchentliche Reflexion"):
        return

    entries = db.get_notes_since(since)
    if not entries:
        return

    context = "\n\n".join(f"[{ts}] {text[:600]}" for _, ts, text, _ in entries)
    prompt  = (
        "Analysiere die folgenden Gedanken der letzten Woche:\n\n"
        f"{context}\n\n"
        "Beantworte:\n"
        "- Welche Themen tauchen wiederholt auf?\n"
        "- Welche emotionale Tonalität dominiert?\n"
        "- Welche Muster oder offene Loops erkennst du?\n"
        "- Was wurde verschoben oder bereut?\n"
        "- Was konkret nächste Woche anders machen?\n\n"
        "Strukturiere mit Überschriften und Aufzählungen. Direkt, keine Schönfärberei."
    )
    text      = await generate_summary(prompt)
    timestamp = datetime.now().isoformat()
    note_id   = str(uuid.uuid4())[:12]
    filepath  = save_note_to_disk(note_id + "_REFLEXION", timestamp, text)
    embedding = get_embedding(text)
    db.add_note(note_id, timestamp, text, str(filepath), embedding,
                tags=["Reflexion", "Wöchentlich"])
    ui.notify("Automatische Wochenreflexion erstellt.", type="positive", timeout=6)


async def auto_daily_summary() -> None:
    """Erstellt eine Tageszusammenfassung wenn heute noch keine existiert."""
    today = datetime.now().strftime("%Y-%m-%d")
    if db.note_exists_matching(today, "Tageszusammenfassung"):
        return

    since   = (datetime.now() - timedelta(hours=24)).isoformat()
    entries = db.get_notes_since(since)
    if not entries:
        return

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
    text      = await generate_summary(prompt)
    timestamp = datetime.now().isoformat()
    note_id   = str(uuid.uuid4())[:12]
    filepath  = save_note_to_disk(note_id + "_DAILY", timestamp, text)
    embedding = get_embedding(text)
    db.add_note(note_id, timestamp, text, str(filepath), embedding,
                tags=["Tageszusammenfassung"])
    ui.notify("Tageszusammenfassung erstellt.", type="positive", timeout=6)


async def auto_decay() -> None:
    """Archiviert alte unreferenzierte Notizen."""
    archived = run_decay(db)
    if archived > 0:
        ui.notify(f"{archived} alte Notizen archiviert.", type="info", timeout=5)


# ═══════════════════════════════════════════════════════════════════════════════
# Edit / Delete / Merge (als eigenständige Dialoge)
# ═══════════════════════════════════════════════════════════════════════════════

async def open_edit_dialog(hit: dict) -> None:
    """Öffnet einen Dialog zum Bearbeiten einer Notiz."""
    with ui.dialog(value=True).props("persistent") as dlg:
        with ui.card().classes("w-full max-w-4xl"):
            ui.label(f"Bearbeite Eintrag vom {hit['timestamp'][:19]}") \
                .classes("text-2xl font-bold mb-4 text-white")
            edit_input = ui.textarea(value=hit["text"]) \
                .props("autogrow outlined").classes("w-full min-h-64")
            with ui.row().classes("gap-3 mt-6"):
                ui.button("Speichern",
                          on_click=lambda: _save_edit(hit, edit_input.value, dlg)) \
                    .props("unelevated color=green-8")
                ui.button("Abbrechen", on_click=dlg.hide) \
                    .props("unelevated color=grey-8")


async def _save_edit(hit: dict, new_text: str, dialog) -> None:
    new_text = new_text.strip()
    if not new_text:
        ui.notify("Kein Text zum Speichern.", type="warning")
        return
    try:
        archive_file(hit["file_path"])
        timestamp = datetime.now().isoformat()
        note_id   = hit["id"]
        filepath  = save_note_to_disk(note_id + "_EDIT", timestamp, new_text)
        embedding = get_embedding(new_text)
        tags      = await generate_tags(new_text)
        db.update_note(note_id, timestamp, new_text, str(filepath), embedding, tags)
        ui.notify("Eintrag aktualisiert.", type="positive")
        dialog.hide()
    except Exception as e:
        ui.notify(f"Bearbeitung fehlgeschlagen: {e}", type="negative")


async def open_delete_dialog(hit: dict) -> None:
    """Öffnet einen Bestätigungs-Dialog zum Löschen einer Notiz."""
    with ui.dialog(value=True).props("persistent") as dlg:
        with ui.card().classes("w-full max-w-md"):
            ui.label("Eintrag wirklich löschen?") \
                .classes("text-2xl font-bold mb-2 text-red-400")
            ui.label(f"Erstellt: {hit['timestamp'][:19]}") \
                .classes("text-slate-400 mb-6")
            with ui.row().classes("justify-end gap-3"):
                ui.button("Abbrechen", on_click=dlg.hide) \
                    .props("unelevated color=grey-8")
                ui.button("Löschen",
                          on_click=lambda: _confirm_delete(hit, dlg)) \
                    .props("unelevated color=red-8")


async def _confirm_delete(hit: dict, dialog) -> None:
    try:
        old_path = Path(hit["file_path"])
        if old_path.exists():
            old_path.unlink()
        db.delete_note(hit["id"])
        ui.notify("Eintrag gelöscht.", type="warning")
        dialog.hide()
    except Exception as e:
        ui.notify(f"Löschen fehlgeschlagen: {e}", type="negative")


async def check_and_show_linking(note_id: str, text: str, embedding: list) -> None:
    """
    Sucht nach ähnlichen Notizen und zeigt einen Merge-Dialog.
    FIX: merge_button wird korrekt innerhalb des Dialogs erstellt.
    """
    try:
        results = db.collection.query(
            query_embeddings=[embedding],
            n_results=5,
            include=["metadatas", "documents", "distances"],
        )
        similar = []
        for i, found_id in enumerate(results["ids"][0]):
            sim = max(0.0, 1.0 - results["distances"][0][i])
            if sim > 0.75 and found_id != note_id:
                row = db.cursor.execute(
                    "SELECT timestamp, text, file_path FROM notes WHERE id = ?", (found_id,)
                ).fetchone()
                if row:
                    similar.append({
                        "id":         found_id,
                        "timestamp":  row[0],
                        "text":       row[1],
                        "file_path":  row[2],
                        "similarity": sim,
                    })

        if not similar:
            return

        with ui.dialog(value=True).props("persistent") as dlg:
            with ui.card().classes("w-full max-w-3xl"):
                ui.label("Ähnliche Gedanken gefunden") \
                    .classes("text-2xl font-bold mb-4 text-amber-300")

                for entry in similar:
                    with ui.card().classes("w-full mb-3 bg-slate-800"):
                        ui.label(f"{entry['timestamp'][:19]} "
                                 f"({entry['similarity']:.0%} ähnlich)") \
                            .classes("text-xs text-slate-400 mb-1")
                        ui.label(entry["text"][:300] + "…") \
                            .classes("text-sm text-slate-200")

                ui.label("Möchtest du diese Einträge zusammenführen? "
                         "Ältere Einträge werden archiviert.") \
                    .classes("mt-4 text-slate-300")

                with ui.row().classes("gap-3 mt-6"):
                    # FIX: merge_button wird hier direkt erstellt — kein globaler None-Verweis
                    ui.button(
                        "Zusammenführen (Merge)",
                        on_click=lambda: _do_merge(note_id, text, similar, dlg),
                    ).props("unelevated color=amber-7")
                    ui.button("Überspringen", on_click=dlg.hide) \
                        .props("unelevated color=grey-8")

    except Exception as e:
        ui.notify(f"Auto-Linking fehlgeschlagen: {e}", type="negative")


async def _do_merge(
    new_id: str, new_text: str, similar: list[dict], dialog
) -> None:
    try:
        merged = new_text + "\n\n---\n\n**Verknüpfte frühere Gedanken:**\n\n"
        for entry in similar:
            merged += f"[{entry['timestamp'][:19]}] {entry['text']}\n\n---\n\n"
            archive_file(entry["file_path"])
            db.delete_note(entry["id"])

        timestamp = datetime.now().isoformat()
        filepath  = save_note_to_disk(new_id + "_MERGED", timestamp, merged)
        embedding = get_embedding(merged)
        tags      = await generate_tags(merged)
        db.update_note(new_id, timestamp, merged, str(filepath), embedding, tags)

        ui.notify(
            f"{len(similar)} Einträge zusammengeführt & archiviert.",
            type="positive",
        )
        dialog.hide()
    except Exception as e:
        ui.notify(f"Merge fehlgeschlagen: {e}", type="negative")


# ═══════════════════════════════════════════════════════════════════════════════
# Export & Reflexion
# ═══════════════════════════════════════════════════════════════════════════════

async def export_all() -> None:
    """Erstellt ein ZIP-Backup aller Notizen, der DB und ChromaDB."""
    try:
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
        ui.notify("ZIP-Export bereit.", type="positive")
    except Exception as e:
        ui.notify(f"Export fehlgeschlagen: {e}", type="negative")


async def manual_weekly_reflection(reflection_dialog, reflection_content) -> None:
    """Manuell ausgelöste wöchentliche Reflexion mit PDF-Download."""
    since   = (datetime.now() - timedelta(days=7)).isoformat()
    entries = db.get_notes_since(since)

    if not entries:
        ui.notify("Keine Notizen in den letzten 7 Tagen.", type="warning")
        return

    context   = "\n\n".join(f"[{ts}] {text[:600]}" for _, ts, text, _ in entries)
    prompt    = (
        "Analysiere die folgenden Gedanken der letzten Woche:\n\n"
        f"{context}\n\n"
        "Beantworte:\n"
        "- Welche Themen tauchen wiederholt auf?\n"
        "- Welche emotionale Tonalität dominiert?\n"
        "- Welche Muster oder offene Loops erkennst du?\n"
        "- Was wurde verschoben oder bereut?\n"
        "- Was konkret nächste Woche anders machen?\n\n"
        "Strukturiere mit Überschriften und Aufzählungen. Direkt, keine Schönfärberei."
    )
    ref_text  = await generate_summary(prompt)
    timestamp = datetime.now().isoformat()
    note_id   = str(uuid.uuid4())[:12]
    filepath  = save_note_to_disk(note_id + "_REFLEXION", timestamp, ref_text)
    embedding = get_embedding(ref_text)
    db.add_note(note_id, timestamp, ref_text, str(filepath), embedding,
                tags=["Reflexion", "Wöchentlich"])

    # PDF generieren
    html_text = ref_text.replace("\n", "<br>")
    html_str  = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2.5cm 2cm; }}
  body {{ font-family: Helvetica, Arial, sans-serif; color: #000; background: #fff;
          line-height: 1.6; }}
  h1   {{ color: #6366f1; text-align: center; }}
  h2,h3 {{ color: #4b5563; margin-top: 1.5em; }}
  .date {{ text-align: center; color: #6b7280; margin-bottom: 2em; }}
</style></head><body>
<h1>Wöchentliche Reflexion</h1>
<div class="date">{timestamp[:19].replace("T", " ")}</div>
<div>{html_text}</div>
</body></html>"""

    try:
        pdf_bytes = HTML(string=html_str).write_pdf()
        has_pdf   = True
    except Exception:
        has_pdf   = False

    # Dialog befüllen
    reflection_content.set_content(
        f"**Gespeichert:** {filepath.name}\n\n{ref_text}"
    )
    if has_pdf:
        with reflection_dialog:
            ui.button(
                "Als PDF herunterladen",
                icon="picture_as_pdf",
                on_click=lambda: ui.download(
                    pdf_bytes,
                    filename=f"reflexion_{timestamp[:10]}.pdf",
                ),
            ).props("unelevated color=indigo-7 size=md").classes("mt-4")

    reflection_dialog.open()
    ui.notify("Reflexion generiert & gespeichert.", type="positive")


# ═══════════════════════════════════════════════════════════════════════════════
# Haupt-Seite
# ═══════════════════════════════════════════════════════════════════════════════

# ── Einmalige Start-Tasks (laufen nur beim Server-Start, nicht bei jedem Page-Load) ──

_startup_done   = False
_ollama_ok      = False
_agent_hints: list[str] = []

async def _run_startup_tasks() -> None:
    global _startup_done, _ollama_ok, _agent_hints
    if _startup_done:
        return
    _startup_done = True
    _ollama_ok    = await check_ollama_available()
    await auto_decay()
    if _ollama_ok:
        await auto_weekly_reflection()
        await auto_daily_summary()
    _agent_hints = check_agents(db)

# NiceGUI app startup hook
from nicegui import app as _nicegui_app_hook
@_nicegui_app_hook.on_startup
async def on_startup():
    await _run_startup_tasks()


@ui.page("/")
async def index():
    # Start-Tasks sind bereits beim Server-Start gelaufen
    ollama_ok   = _ollama_ok
    agent_hints = _agent_hints

    # ── Header ────────────────────────────────────────────────────────────────
    with ui.column().classes("items-center w-full mb-10"):
        ui.label("ECHO").classes(
            "text-7xl font-black text-indigo-400 tracking-widest drop-shadow-2xl"
        )
        ui.label("dein lokaler Stream-of-Thought Second Brain").classes(
            "text-2xl text-slate-300 mt-2 font-light italic"
        )

    # Ollama-Warnung
    if not ollama_ok:
        ui.notification(
            f"⚠️ Ollama nicht erreichbar — Modell '{DEFAULT_MODEL}' fehlt oder "
            f"'ollama serve' läuft nicht. LLM-Funktionen sind deaktiviert.",
            type="warning",
            timeout=0,
            close_button=True,
        )

    # Agenten-Hinweise
    if agent_hints:
        with ui.card().classes(
            "w-full max-w-4xl mx-auto mb-6 bg-indigo-950/50 border border-indigo-700/30"
        ):
            for hint in agent_hints:
                ui.markdown(hint).classes("text-slate-300 text-sm")

    # ── Eingabe ───────────────────────────────────────────────────────────────
    with ui.card().classes(
        "w-full max-w-4xl mx-auto shadow-2xl rounded-3xl "
        "bg-gradient-to-br from-slate-950 to-slate-900 border border-slate-700/50"
    ):
        ui.label("Neuer Gedanke").classes(
            "text-3xl font-bold mb-5 text-white text-center"
        )
        thought_input = ui.textarea(
            placeholder="Schreib einfach drauflos…  "
            "(Enter = speichern, Auto-Save nach 8 s Inaktivität)"
        ).props("autogrow outlined clearable").classes(
            "w-full min-h-64 bg-slate-950 text-slate-100 rounded-xl"
        )

        auto_save_timer = None

        async def save_thought(auto: bool = False) -> None:
            nonlocal auto_save_timer
            text = thought_input.value.strip()
            if not text:
                if not auto:
                    ui.notify("Kein Text zum Speichern.", type="warning")
                return

            timestamp = datetime.now().isoformat()
            note_id   = str(uuid.uuid4())[:12]

            try:
                filepath  = save_note_to_disk(note_id, timestamp, text)
                embedding = get_embedding(text)
                tags      = await generate_tags(text) if ollama_ok else []
                db.add_note(note_id, timestamp, text, str(filepath), embedding, tags)

                label = f"Gespeichert → {note_id[:8]}"
                if tags:
                    label += f"  (Tags: {', '.join(tags)})"
                if auto:
                    label += "  [Auto-Save]"
                ui.notify(label, type="positive", close_button=True)

                thought_input.set_value("")
                thought_input.run_method("focus")

                await check_and_show_linking(note_id, text, embedding)

            except Exception as e:
                ui.notify(f"Speichern fehlgeschlagen: {e}", type="negative")

        def reset_timer() -> None:
            nonlocal auto_save_timer
            if auto_save_timer:
                auto_save_timer.cancel()
            auto_save_timer = ui.timer(8.0, lambda: save_thought(auto=True), once=True)

        thought_input.on("keydown.enter", lambda: save_thought(auto=False))
        thought_input.on("input",         reset_timer)
        thought_input.on("focus",         reset_timer)

        ui.button("Manuell speichern", on_click=lambda: save_thought(auto=False)) \
            .props("unelevated color=green-600 rounded-xl") \
            .classes("mt-6 w-full md:w-1/3 mx-auto text-lg")

    # ── Suche ─────────────────────────────────────────────────────────────────
    with ui.card().classes(
        "w-full max-w-4xl mx-auto mt-10 shadow-2xl rounded-3xl "
        "bg-gradient-to-br from-slate-950 to-slate-900 border border-slate-700/50"
    ):
        ui.label("Suche in deinem ECHO").classes(
            "text-3xl font-bold mb-5 text-white text-center"
        )
        search_input = ui.input(
            placeholder='z. B. "Gedanken zu Japan Reise letzten 3 Monate"'
        ).props("outlined dense clearable").classes(
            "w-full bg-slate-950 text-white rounded-xl"
        )

        result_container = ui.column().classes("w-full mt-6 gap-4")

        async def perform_search() -> None:
            query = search_input.value.strip()
            result_container.clear()
            if not query:
                return

            with result_container:
                ui.spinner(size="lg").classes("mx-auto")

            hits = db.search(query, limit=8)
            result_container.clear()

            if not hits:
                with result_container:
                    ui.label("Keine passenden Gedanken gefunden.") \
                        .classes("text-slate-400 text-center")
                return

            # LLM-Zusammenfassung
            if ollama_ok:
                context = "\n\n".join(
                    f"[{h['timestamp'][:19]}] {h['text'][:400]}" for h in hits
                )
                prompt  = (
                    "Fasse zusammen was der Nutzer zu diesem Thema gedacht hat. "
                    "Nenne Muster, Tonalität und offene Fragen. "
                    "Aufzählungspunkte wo sinnvoll.\n\n"
                    f"Suchanfrage: {query}\n\n{context}"
                )
                summary = await generate_summary(prompt)
                with result_container:
                    with ui.card().classes(
                        "w-full bg-indigo-950/50 border border-indigo-700/30"
                    ):
                        ui.label("Zusammenfassung").classes(
                            "text-xs text-indigo-400 uppercase mb-2"
                        )
                        ui.markdown(summary).classes("text-slate-200 text-sm")

            # Ergebnis-Karten
            with result_container:
                for hit in hits:
                    with ui.card().classes(
                        "w-full bg-slate-900 border border-slate-700"
                    ):
                        with ui.row().classes(
                            "justify-between items-start w-full mb-2"
                        ):
                            ui.label(hit["timestamp"][:19]).classes(
                                "text-xs text-slate-400"
                            )
                            sim_color = (
                                "text-green-400"  if hit["similarity"] > 0.8
                                else "text-amber-400" if hit["similarity"] > 0.6
                                else "text-slate-400"
                            )
                            ui.label(f"{hit['similarity']:.0%} ähnlich").classes(
                                f"text-xs {sim_color}"
                            )

                        ui.markdown(hit["text"][:450] + ("…" if len(hit["text"]) > 450 else "")) \
                            .classes("text-slate-200 text-sm")

                        if hit.get("tags"):
                            with ui.row().classes("gap-1 mt-2 flex-wrap"):
                                for tag in hit["tags"].split(","):
                                    if tag.strip():
                                        ui.badge(tag.strip()).props("color=indigo-9 rounded")

                        with ui.row().classes("gap-2 mt-3"):
                            ui.button(
                                "Bearbeiten",
                                on_click=lambda h=hit: open_edit_dialog(h),
                            ).props("unelevated color=blue-8 size=sm")
                            ui.button(
                                "Löschen",
                                on_click=lambda h=hit: open_delete_dialog(h),
                            ).props("unelevated color=red-9 size=sm")

        search_input.on("keydown.enter", perform_search)
        ui.button("Suchen", on_click=perform_search) \
            .props("unelevated color=blue-600 rounded-xl") \
            .classes("mt-4 w-full md:w-1/3 mx-auto text-lg")

    # ── Schnellzugriff ────────────────────────────────────────────────────────

    # Reflexions-Dialog (lebt innerhalb von index() — kein globaler None-Verweis)
    with ui.dialog().props("persistent") as reflection_dialog:
        with ui.card().classes("w-full max-w-4xl"):
            ui.label("Wöchentliche Reflexion").classes(
                "text-3xl font-bold mb-4 text-indigo-300"
            )
            reflection_content = ui.markdown().classes(
                "prose prose-slate max-w-none dark:prose-invert"
            )
            ui.button(
                "Schließen",
                on_click=reflection_dialog.close,
            ).props("unelevated color=grey-8 rounded-xl").classes("mt-6")

    with ui.card().classes(
        "w-full max-w-4xl mx-auto mt-12 shadow-2xl rounded-3xl "
        "bg-gradient-to-r from-indigo-950/70 to-slate-950/70 "
        "border border-indigo-700/30"
    ):
        ui.label("Schnellzugriff").classes(
            "text-2xl font-bold text-center text-indigo-300 mb-8"
        )
        with ui.row().classes("justify-center gap-8 flex-wrap px-8 py-6"):
            ui.button(
                "Wöchentliche Reflexion",
                icon="auto_awesome",
                on_click=lambda: manual_weekly_reflection(
                    reflection_dialog, reflection_content
                ),
            ).props("unelevated color=indigo-600 rounded-xl size=lg") \
             .classes("min-w-72 text-lg hover:scale-105 transition-transform")

            ui.button(
                "Alles exportieren (ZIP)",
                icon="download",
                on_click=export_all,
            ).props("unelevated color=amber-600 rounded-xl size=lg") \
             .classes("min-w-72 text-lg hover:scale-105 transition-transform")

    # ── Statistik-Footer ──────────────────────────────────────────────────────
    total = db.count()
    ui.label(f"📝 {total} Gedanken gespeichert").classes(
        "text-center text-slate-500 text-sm mt-8 mb-4"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Start
# ═══════════════════════════════════════════════════════════════════════════════

ui.run(
    title="ECHO – dein lokaler Second Brain",
    port=9876,
    host="0.0.0.0",
    dark=True,
    reload=False,
    show=False,      # kein Browser-Fenster beim Start
    favicon="🧠",
)


# ═══════════════════════════════════════════════════════════════════════════════
# REST-API für externen Zugriff (Claude, Scripts, etc.)
# Authentifizierung via X-ECHO-Key Header (geprüft durch Apache)
# ═══════════════════════════════════════════════════════════════════════════════

from nicegui import app as nicegui_app
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

@nicegui_app.get("/api/search")
async def api_search(request: Request, q: str = "", limit: int = 6):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Parameter 'q' fehlt")
    hits = db.search(q.strip(), limit=limit)
    return JSONResponse([{
        "id":         h["id"],
        "timestamp":  h["timestamp"],
        "text":       h["text"],
        "tags":       h["tags"],
        "similarity": round(h["similarity"], 3),
    } for h in hits])


@nicegui_app.get("/api/notes/recent")
async def api_recent(limit: int = 10):
    entries = db.get_notes_since(
        (datetime.now() - timedelta(days=30)).isoformat()
    )
    return JSONResponse([{
        "id":        e[0],
        "timestamp": e[1],
        "text":      e[2][:500],
    } for e in entries[-limit:]])


@nicegui_app.post("/api/notes")
async def api_add_note(request: Request):
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="'text' fehlt")
    timestamp = datetime.now().isoformat()
    note_id   = str(uuid.uuid4())[:12]
    filepath  = save_note_to_disk(note_id, timestamp, text)
    embedding = get_embedding(text)
    tags      = body.get("tags", [])
    db.add_note(note_id, timestamp, text, str(filepath), embedding, tags)
    return JSONResponse({"id": note_id, "timestamp": timestamp, "status": "ok"})
