# main.py – Echo Kern + Reflexion + Export (Stand März 2026)

from nicegui import ui, app
from datetime import datetime, timedelta
import uuid
from pathlib import Path
import zipfile
import io
import shutil
import os

from database import NoteDB
from llm import generate_summary
from embedder import get_embedding

DATA_DIR = Path("data")
NOTES_DIR = DATA_DIR / "notes"
CHROMA_DIR = DATA_DIR / "chroma"
NOTES_DIR.mkdir(parents=True, exist_ok=True)

db = NoteDB()


@ui.page('/')
async def index():
    ui.label('Echo – dein lokaler Stream-of-Thought').classes('text-2xl font-bold mb-6 text-center')

    # =====================================
    # Eingabe-Bereich (unverändert)
    # =====================================
    with ui.card().classes('w-full max-w-4xl mx-auto shadow-lg'):
        ui.label('Neuer Gedanke (Stream-of-Thought)').classes('text-xl mb-2')
        thought_input = ui.textarea(
            placeholder='Schreib einfach drauflos... (Enter oder Auto-Save nach 8 Sekunden)'
        ).props('autogrow outlined clearable').classes('w-full min-h-48')

        last_change = None
        auto_save_timer = None

        async def save_thought(auto: bool = False):
            nonlocal last_change, auto_save_timer
            text = thought_input.value.strip()
            if not text:
                if not auto:
                    ui.notify('Kein Text zum Speichern', type='warning')
                return

            timestamp = datetime.now().isoformat()
            note_id = str(uuid.uuid4())[:12]
            filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}.md"

            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"# {timestamp}\n\n{text}")

                embedding = get_embedding(text)
                db.add_note(note_id, timestamp, text, str(filename), embedding)

                ui.notify(
                    f'Gedanke gespeichert → {note_id[:8]}' + (' (Auto-Save)' if auto else ''),
                    type='positive',
                    close_button=True
                )
                thought_input.value = ''
                thought_input.run_method('focus')
            except Exception as e:
                ui.notify(f'Speichern fehlgeschlagen: {str(e)}', type='negative')

        thought_input.on('keydown.enter', lambda: save_thought(auto=False))

        def reset_auto_save_timer():
            nonlocal auto_save_timer
            if auto_save_timer:
                auto_save_timer.cancel()
            auto_save_timer = ui.timer(8.0, lambda: save_thought(auto=True), once=True)

        thought_input.on('input', reset_auto_save_timer)
        thought_input.on('focus', reset_auto_save_timer)

        ui.button('Manuell speichern', on_click=lambda: save_thought(auto=False)) \
            .props('unelevated color=green-9').classes('mt-4')

    # =====================================
    # Suche-Bereich (unverändert)
    # =====================================
    with ui.card().classes('w-full max-w-4xl mx-auto mt-4 shadow-lg'):
        ui.label('Suche in deinem Echo').classes('text-xl mb-2')
        search_input = ui.input(placeholder='z. B. "Gedanken zu Japan Reise letzten 3 Monate"') \
            .props('outlined dense').classes('w-full')

        result_area = ui.markdown().classes('mt-4 prose prose-slate max-w-none dark:prose-invert')

        async def perform_search():
            query = search_input.value.strip()
            if not query:
                result_area.content = ''
                return

            result_area.content = 'Suche läuft...'
            ui.run_javascript('window.scrollTo(0, document.body.scrollHeight)')

            try:
                hits = db.search(query, limit=8)
                if not hits:
                    result_area.content = 'Keine passenden Gedanken gefunden.'
                    return

                context_parts = [f"**{hit['timestamp']}**  \n{hit['text'][:450]}..." for hit in hits]
                context = "\n\n".join(context_parts)
                summary_prompt = (
                    "Fasse ehrlich und knapp zusammen, was der Nutzer zu diesem Thema gedacht hat. "
                    "Nenne wiederkehrende Muster, emotionale Tonalität und offene Fragen. "
                    "Strukturiere mit Aufzählungspunkten wenn sinnvoll.\n\n"
                    f"Suchanfrage: {query}\n\n{context}"
                )
                summary = await generate_summary(summary_prompt)

                result_area.content = (
                    f"**Zusammenfassung:**\n\n{summary}\n\n"
                    f"---\n\n**Gefundene Einträge:**\n\n"
                    + "\n\n".join(context_parts)
                )
            except Exception as e:
                result_area.content = f'Fehler bei der Suche: {str(e)}'
                ui.notify(f'Suchfehler: {str(e)}', type='negative')

        ui.button('Suchen', on_click=perform_search) \
            .props('unelevated color=blue-9').classes('mt-4')

    # =====================================
    # Neue Buttons: Reflexion & Export
    # =====================================
    with ui.row().classes('justify-center gap-6 mt-8'):
        ui.button('Wöchentliche Reflexion jetzt', on_click=generate_weekly_reflection) \
            .props('unelevated color=indigo-9 outline').classes('text-lg px-8 py-4')

        ui.button('Alles exportieren (ZIP)', on_click=export_all) \
            .props('unelevated color=amber-9 outline').classes('text-lg px-8 py-4')

    # Dialog für Reflexions-Anzeige
    with ui.dialog(value=False).props('persistent') as reflection_dialog:
        with ui.card().classes('w-full max-w-4xl'):
            ui.label('Wöchentliche Reflexion').classes('text-2xl font-bold mb-4')
            reflection_content = ui.markdown().classes('prose prose-slate max-w-none dark:prose-invert')
            ui.button('Schließen', on_click=reflection_dialog.hide) \
                .props('unelevated color=grey-8').classes('mt-6')


async def generate_weekly_reflection():
    try:
        since = (datetime.now() - timedelta(days=7)).isoformat()
        # Alle Notizen der letzten 7 Tage holen
        db.cursor.execute("SELECT timestamp, text FROM notes WHERE timestamp >= ? ORDER BY timestamp", (since,))
        entries = db.cursor.fetchall()

        if not entries:
            ui.notify('Keine Notizen in den letzten 7 Tagen gefunden.', type='warning')
            return

        context = "\n\n".join([f"[{ts}] {text[:600]}..." for ts, text in entries])
        prompt = (
            "Du bist ein ehrlicher, reflektierender Coach. "
            "Analysiere die folgenden Gedanken der letzten Woche:\n\n"
            f"{context}\n\n"
            "- Welche Themen tauchen wiederholt auf?\n"
            "- Welche emotionale Tonalität dominiert (Frust, Neugier, Stolz, Angst, …)?\n"
            "- Welche Muster, Gewohnheiten oder offene Loops siehst du?\n"
            "- Was wurde verschoben, ignoriert oder bereut?\n"
            "- Was könnte der Nutzer nächste Woche anders / besser machen?\n\n"
            "Strukturiere die Antwort klar mit Überschriften und Aufzählungspunkten. "
            "Sei direkt, aber wohlwollend – keine Schönfärberei."
        )

        reflection_text = await generate_summary(prompt)

        # Als neue Notiz speichern
        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_REFLEXION.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Wöchentliche Reflexion – {timestamp}\n\n{reflection_text}")

        embedding = get_embedding(reflection_text)
        db.add_note(note_id, timestamp, reflection_text, str(filename), embedding)

        # Im Dialog anzeigen
        reflection_content.content = f"**Gespeichert als:** {filename.name}\n\n{reflection_text}"
        reflection_dialog.open()

        ui.notify('Reflexion generiert & gespeichert', type='positive')

    except Exception as e:
        ui.notify(f'Reflexion fehlgeschlagen: {str(e)}', type='negative')


async def export_all():
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Alle Markdown-Notizen
            for md_file in NOTES_DIR.glob('*.md'):
                zip_file.write(md_file, arcname=f"notes/{md_file.name}")

            # SQLite-Datenbank
            zip_file.write('data/echo.db', arcname='data/echo.db')

            # Chroma-Ordner (komplett)
            for root, _, files in os.walk(CHROMA_DIR):
                for file in files:
                    file_path = Path(root) / file
                    arc_path = file_path.relative_to(DATA_DIR)
                    zip_file.write(file_path, arcname=str(arc_path))

        zip_buffer.seek(0)
        ui.download(zip_buffer.read(), filename=f"echo_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        ui.notify('Export abgeschlossen – ZIP wird heruntergeladen', type='positive')

    except Exception as e:
        ui.notify(f'Export fehlgeschlagen: {str(e)}', type='negative')


ui.run(title='Echo – Second Brain', port=9876, dark=True, reload=True, show=True)
