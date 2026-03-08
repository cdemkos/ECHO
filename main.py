from nicegui import ui, app, notify
from datetime import datetime
import uuid
from pathlib import Path
from database import NoteDB
from llm import generate_summary
from embedder import get_embedding
import asyncio

DATA_DIR = Path("data")
NOTES_DIR = DATA_DIR / "notes"
NOTES_DIR.mkdir(parents=True, exist_ok=True)

db = NoteDB()

@ui.page('/')
async def index():
    ui.label('Echo – dein lokaler Stream-of-Thought').classes('text-2xl font-bold mb-6 text-center')

    # === Eingabe-Bereich ===
    with ui.card().classes('w-full max-w-4xl mx-auto shadow-lg'):
        ui.label('Neuer Gedanke (Stream-of-Thought)').classes('text-xl mb-2')
        thought_input = ui.textarea(
            placeholder='Schreib einfach drauflos... (Enter oder Auto-Save nach 8 Sekunden)'
        ).props('autogrow outlined clearable').classes('w-full min-h-48')

        last_change = None

        async def save_thought(auto=False):
            nonlocal last_change
            text = thought_input.value.strip()
            if not text:
                if not auto:
                    notify.warning('Kein Text zum Speichern')
                return

            timestamp = datetime.now().isoformat()
            note_id = str(uuid.uuid4())[:12]  # längere ID für Sicherheit
            filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}.md"

            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"# {timestamp}\n\n{text}")

                embedding = get_embedding(text)
                db.add_note(note_id, timestamp, text, str(filename), embedding)

                notify.success(f'Gedanke gespeichert → {note_id[:8]}' + (' (Auto-Save)' if auto else ''))
                thought_input.value = ''
                thought_input.run_method('focus')
            except Exception as e:
                notify.error(f'Speichern fehlgeschlagen: {str(e)}')

        # Enter = Speichern
        thought_input.on('keydown.enter', lambda: save_thought(auto=False))

        # Auto-Save nach 8 Sekunden Inaktivität
        async def auto_save_loop():
            while True:
                await asyncio.sleep(8)
                if thought_input.value.strip() and last_change and (datetime.now() - last_change).total_seconds() >= 8:
                    await save_thought(auto=True)

        ui.context.client.on_startup(auto_save_loop)

        # Letzte Änderung tracken
        def on_change():
            nonlocal last_change
            last_change = datetime.now()

        thought_input.on('input', on_change)

        ui.button('Manuell speichern', on_click=lambda: save_thought(auto=False)).props('unelevated color=green-9').classes('mt-4')

    # === Suche ===
    with ui.card().classes('w-full max-w-4xl mx-auto mt-8 shadow-lg'):
        ui.label('Suche in deinem Echo').classes('text-xl mb-2')
        search_input = ui.input(placeholder='z. B. "Gedanken zu Japan Reise letzten 3 Monate"').props('outlined dense').classes('w-full')

        result_area = ui.markdown().classes('mt-4 prose prose-slate max-w-none dark:prose-invert')

        async def perform_search():
            query = search_input.value.strip()
            if not query:
                result_area.content = ''
                return

            result_area.content = 'Suche läuft...'
            ui.run_javascript('window.scrollTo(0, document.body.scrollHeight)')

            try:
                hits = db.search(query, limit=8)  # etwas mehr Kontext
                if not hits:
                    result_area.content = 'Keine passenden Gedanken gefunden.'
                    return

                context_parts = []
                for hit in hits:
                    context_parts.append(f"**{hit['timestamp']}**  \n{hit['text'][:450]}...")

                context = "\n\n".join(context_parts)
                summary_prompt = (
                    "Fasse ehrlich und knapp zusammen, was der Nutzer zu diesem Thema gedacht hat. "
                    "Nenne wiederkehrende Muster, emotionale Tonalität und offene Fragen. "
                    "Strukturiere die Antwort mit Aufzählungspunkten wenn sinnvoll.\n\n"
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
                notify.error(str(e))

        ui.button('Suchen', on_click=perform_search).props('unelevated color=blue-9').classes('mt-4')

ui.run(title='Echo – Second Brain', port=9876, dark=True, reload=True)
