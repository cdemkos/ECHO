from nicegui import ui, app
from datetime import datetime
import uuid
from pathlib import Path
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

    # === Eingabe-Bereich ===
    with ui.card().classes('w-full max-w-4xl mx-auto shadow-lg'):
        ui.label('Neuer Gedanke').classes('text-xl mb-2')
        thought_input = ui.textarea(
            placeholder='Schreib einfach drauflos... (Enter zum Speichern)'
        ).props('autogrow outlined clearable autogrow').classes('w-full min-h-40')

        async def save_thought():
            text = thought_input.value.strip()
            if not text:
                ui.notify('Kein Text zum Speichern', type='warning')
                return

            timestamp = datetime.now().isoformat()
            note_id = str(uuid.uuid4())[:8]
            filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}.md"

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# {timestamp}\n\n{text}")

            try:
                embedding = get_embedding(text)
                db.add_note(note_id, timestamp, text, str(filename), embedding)
                ui.notify(f'Gedanke gespeichert → {note_id[:8]}', type='positive')
            except Exception as e:
                ui.notify(f'Fehler beim Speichern/Indizieren: {str(e)}', type='negative')

            thought_input.value = ''
            thought_input.run_method('focus')

        ui.button('Speichern (Enter)', on_click=save_thought).props('unelevated color=green-9').classes('mt-4')

        # Enter-Taste → Speichern
        thought_input.on('keydown.enter', save_thought, throttle=0.3)

    # === Suche ===
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
                hits = db.search(query, limit=6)
                if not hits:
                    result_area.content = 'Keine passenden Gedanken gefunden.'
                    return

                context = "\n\n".join([f"[{hit['timestamp']}] {hit['text'][:350]}..." for hit in hits])
                summary_prompt = f"Fasse knapp und ehrlich zusammen, was der Nutzer zu diesem Thema gedacht hat:\n\n{context}"
                summary = await generate_summary(summary_prompt)

                result_area.content = (
                    f"**Zusammenfassung:**\n\n{summary}\n\n"
                    f"---\n\n**Gefundene Einträge:**\n\n"
                    + "\n\n".join([f"- **{hit['timestamp']}**  \n  {hit['text'][:220]}..." for hit in hits])
                )
            except Exception as e:
                result_area.content = f'Fehler bei der Suche: {str(e)}'

        ui.button('Suchen', on_click=perform_search).props('unelevated color=blue-9').classes('mt-4')

ui.run(
    title='Echo – Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
