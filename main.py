from nicegui import ui, app
from datetime import datetime
import uuid
from pathlib import Path
from database import NoteDB
from llm import generate_summary, answer_query
from embedder import get_embedding
from agents import check_agents

DATA_DIR = Path("data")
NOTES_DIR = DATA_DIR / "notes"
NOTES_DIR.mkdir(parents=True, exist_ok=True)

db = NoteDB()

@ui.page('/')
async def index():
    ui.label('Echo – dein lokaler Stream-of-Thought').classes('text-2xl font-bold mb-4')

    # Stream-Eingabe (großes Textarea)
    with ui.card().classes('w-full max-w-4xl mx-auto'):
        ui.label('Neuer Gedanke (Stream-of-Thought)').classes('text-lg')
        thought_input = ui.textarea(placeholder='Schreib einfach drauflos...').props('autogrow outlined clearable').classes('w-full min-h-32')
        
        async def save_thought():
            text = thought_input.value.strip()
            if not text:
                return
            timestamp = datetime.now().isoformat()
            note_id = str(uuid.uuid4())[:8]
            filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}.md"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# {timestamp}\n\n{text}")
            
            embedding = get_embedding(text)
            db.add_note(note_id, timestamp, text, str(filename), embedding)
            
            ui.notify(f'Gedanke gespeichert → {note_id}', type='positive')
            thought_input.value = ''
            check_agents()  # prüfe Agenten (rudimentär)

        ui.button('Speichern & Denken', on_click=save_thought).props('unelevated color=green-8')

    # Suche
    with ui.card().classes('w-full max-w-4xl mx-auto mt-6'):
        ui.label('Suche in deinem Echo').classes('text-lg')
        search_input = ui.input(placeholder='z. B. "Japan Reise Gedanken letzten 3 Monate"').props('outlined').classes('w-full')
        result_area = ui.markdown().classes('mt-4 prose prose-slate max-w-none')

        async def perform_search():
            query = search_input.value.strip()
            if not query:
                return
            result_area.content = 'Suche läuft...'
            ui.run_javascript('window.scrollTo(0, document.body.scrollHeight)')
            
            # Einfache semantische Suche + Synthese
            hits = db.search(query, limit=5)
            if not hits:
                result_area.content = 'Keine Treffer.'
                return
            
            context = "\n\n".join([f"[{hit['timestamp']}] {hit['text'][:400]}..." for hit in hits])
            summary = await generate_summary(f"Zusammenfassung der relevanten Gedanken zu: {query}\n\n{context}")
            result_area.content = f"**Zusammenfassung:**\n\n{summary}\n\n---\n\n**Roh-Treffer:**\n\n" + "\n\n".join([f"- {hit['timestamp']}: {hit['text'][:200]}..." for hit in hits])

        ui.button('Suchen', on_click=perform_search).props('unelevated color=blue-8')

    # Wöchentliche Reflexion Button
    ui.button('Wöchentliche Echo-Reflexion', on_click=lambda: ui.notify('Noch nicht implementiert – kommt in v0.2')).classes('mt-6')

ui.run(title='Echo – Second Brain', port=9876, dark=True)
