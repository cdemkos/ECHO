from nicegui import ui, app
from datetime import datetime
import uuid
from pathlib import Path
import asyncio

from database import NoteDB
from llm import generate_summary
from embedder import get_embedding

DATA_DIR = Path("data")
NOTES_DIR = DATA_DIR / "notes"
NOTES_DIR.mkdir(parents=True, exist_ok=True)

db = NoteDB()

@ui.page('/')
async def index():
    ui.label('Echo – dein lokaler Stream-of-Thought').classes('text-2xl font-bold mb-6 text-center')

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

        # Enter = manuelles Speichern
        thought_input.on('keydown.enter', lambda: save_thought(auto=False))

        # Timer-basierter Auto-Save
        def reset_auto_save_timer():
            nonlocal auto_save_timer
            if auto_save_timer:
                auto_save_timer.cancel()
            auto_save_timer = ui.timer(8.0, lambda: save_thought(auto=True), once=True)

        thought_input.on('input', reset_auto_save_timer)
        thought_input.on('focus', reset_auto_save_timer)

        ui.button('Manuell speichern', on_click=lambda: save_thought(auto=False)) \
            .props('unelevated color=green-9').classes('mt-4')

    # Suche-Bereich (unverändert, aber mit ui.notify-Fehlerbehandlung)
    with ui.card().classes('w-full max-w-4xl mx-auto mt-8 shadow-lg'):
        ui.label('Suche in deinem Echo').classes('text-xl mb-2')
        search_input = ui.input(
            placeholder='z. B. "Gedanken zu Japan Reise letzten 3 Monate"'
        ).props('outlined dense').classes('w-full')

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

ui.run(title='Echo – Second Brain', port=9876, dark=True, reload=True, show=True)
