# main.py – Echo Kern + Reflexion + Export + Auto-Linking
# Korrigiert: Browser-Tab-Titel richtig setzen (März 2026)

from nicegui import ui, app
from datetime import datetime, timedelta
import uuid
from pathlib import Path
import zipfile
import io
import os
import shutil

# Lokale Module
from database import NoteDB
from llm import generate_summary
from embedder import get_embedding

DATA_DIR = Path("data")
NOTES_DIR = DATA_DIR / "notes"
CHROMA_DIR = DATA_DIR / "chroma"
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

NOTES_DIR.mkdir(parents=True, exist_ok=True)

db = NoteDB()

# Globale Referenzen für Dialoge
reflection_dialog = None
reflection_content = None
linking_dialog = None
linking_content = None
merge_button = None


@ui.page('/')
async def index():
    global reflection_dialog, reflection_content, linking_dialog, linking_content, merge_button

    # Header mit klarem Titel
    with ui.column().classes('items-center w-full mb-8'):
        ui.label('Echo').classes('text-5xl font-black text-indigo-400 tracking-tight')
        ui.label('dein lokaler Stream-of-Thought Second Brain').classes('text-xl text-slate-400 mt-1')

    # =====================================
    # Eingabe-Bereich
    # =====================================
    with ui.card().classes('w-full max-w-4xl mx-auto shadow-xl rounded-xl'):
        ui.label('Neuer Gedanke').classes('text-2xl font-bold mb-3 text-slate-200')
        thought_input = ui.textarea(
            placeholder='Schreib einfach drauflos... (Enter oder Auto-Save nach 8 Sekunden Inaktivität)'
        ).props('autogrow outlined clearable bordered').classes('w-full min-h-56 bg-slate-800 text-slate-100')

        auto_save_timer = None

        async def save_thought(auto: bool = False):
            nonlocal auto_save_timer
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

                await check_auto_linking(note_id, text, embedding)

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
            .props('unelevated color=green-7').classes('mt-4 w-full md:w-auto')

    # Suche-Bereich
    with ui.card().classes('w-full max-w-4xl mx-auto mt-6 shadow-xl rounded-xl'):
        ui.label('Suche in deinem Echo').classes('text-2xl font-bold mb-3 text-slate-200')
        search_input = ui.input(
            placeholder='z. B. "Gedanken zu Japan Reise letzten 3 Monate"'
        ).props('outlined dense clearable').classes('w-full')

        result_area = ui.markdown().classes('mt-6 prose prose-slate max-w-none dark:prose-invert')

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
            .props('unelevated color=blue-7').classes('mt-4 w-full md:w-auto')

    # =====================================
    # Reflexion & Export – zentral & prominent
    # =====================================
    with ui.card().classes('w-full max-w-4xl mx-auto mt-10 shadow-2xl rounded-xl bg-slate-800/50 border border-slate-700'):
        ui.label('Schnellzugriff').classes('text-xl font-semibold text-center text-slate-300 mb-6')
        with ui.row().classes('justify-center gap-8 flex-wrap'):
            ui.button(
                icon='auto_awesome',
                label='Wöchentliche Reflexion jetzt',
                on_click=generate_weekly_reflection
            ).props('unelevated color=indigo-8 size=lg').classes('min-w-64')

            ui.button(
                icon='download',
                label='Alles exportieren (ZIP)',
                on_click=export_all
            ).props('unelevated color=amber-8 size=lg').classes('min-w-64')

    # Reflexions-Dialog
    reflection_dialog = ui.dialog(value=False).props('persistent')
    with reflection_dialog:
        with ui.card().classes('w-full max-w-4xl'):
            ui.label('Wöchentliche Reflexion').classes('text-2xl font-bold mb-4')
            reflection_content = ui.markdown().classes('prose prose-slate max-w-none dark:prose-invert')
            ui.button('Schließen', on_click=lambda: setattr(reflection_dialog, 'value', False)) \
                .props('unelevated color=grey-8').classes('mt-6 w-full md:w-auto')

    # Auto-Linking Dialog
    linking_dialog = ui.dialog(value=False).props('persistent')
    with linking_dialog:
        with ui.card().classes('w-full max-w-4xl'):
            ui.label('Mögliche Verknüpfungen gefunden').classes('text-2xl font-bold mb-4')
            linking_content = ui.markdown().classes('prose prose-slate max-w-none dark:prose-invert')
            with ui.row().classes('gap-4 mt-6 justify-end'):
                ui.button('Keine Verknüpfung', on_click=lambda: setattr(linking_dialog, 'value', False)) \
                    .props('unelevated color=grey-8')
                merge_button = ui.button('Alle mergen', color='teal-9').props('unelevated') \
                    .classes('text-white')


async def check_auto_linking(new_note_id: str, new_text: str, new_embedding: list):
    try:
        query_results = db.collection.query(
            query_embeddings=[new_embedding],
            n_results=5,
            include=['metadatas', 'documents', 'distances']
        )

        similar = []
        for i in range(len(query_results['ids'][0])):
            sim = 1 - query_results['distances'][0][i]
            if sim > 0.75 and query_results['ids'][0][i] != new_note_id:
                id_ = query_results['ids'][0][i]
                db.cursor.execute("SELECT timestamp, text, file_path FROM notes WHERE id = ?", (id_,))
                row = db.cursor.fetchone()
                if row:
                    similar.append({
                        'id': id_,
                        'timestamp': row[0],
                        'text': row[1][:300] + '...',
                        'similarity': sim,
                        'file_path': row[2]
                    })

        if not similar:
            return

        content = "**Sehr ähnliche Gedanken gefunden (Ähnlichkeit > 75 %):**\n\n"
        for entry in similar:
            content += f"- **{entry['timestamp']}** ({entry['similarity']:.2%})\n  {entry['text']}\n\n"

        content += "Möchtest du diese Einträge mergen? (Alte werden archiviert)"

        linking_content.content = content
        linking_dialog.value = True

        async def do_merge():
            merged_text = new_text + "\n\n---\n\n**Verknüpfte frühere Gedanken:**\n\n"
            for entry in similar:
                merged_text += f"[{entry['timestamp']}] {entry['text']}\n\n---\n\n"
                old_path = Path(entry['file_path'])
                if old_path.exists():
                    shutil.move(str(old_path), ARCHIVE_DIR / old_path.name)
                db.collection.delete(ids=[entry['id']])
                db.cursor.execute("DELETE FROM notes WHERE id = ?", (entry['id'],))
                db.conn.commit()

            timestamp = datetime.now().isoformat()
            note_id = str(uuid.uuid4())[:12]
            filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_MERGED.md"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# Gemergter Gedanke – {timestamp}\n\n{merged_text}")

            embedding = get_embedding(merged_text)
            db.add_note(note_id, timestamp, merged_text, str(filename), embedding)

            ui.notify('Einträge erfolgreich gemergt & archiviert', type='positive')
            linking_dialog.value = False

        merge_button.on('click', do_merge)

    except Exception as e:
        ui.notify(f'Auto-Linking fehlgeschlagen: {str(e)}', type='negative')


async def generate_weekly_reflection():
    try:
        since = (datetime.now() - timedelta(days=7)).isoformat()
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

        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_REFLEXION.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Wöchentliche Reflexion – {timestamp}\n\n{reflection_text}")

        embedding = get_embedding(reflection_text)
        db.add_note(note_id, timestamp, reflection_text, str(filename), embedding)

        reflection_content.content = f"**Gespeichert als:** {filename.name}\n\n{reflection_text}"
        reflection_dialog.value = True

        ui.notify('Reflexion generiert & gespeichert', type='positive')

    except Exception as e:
        ui.notify(f'Reflexion fehlgeschlagen: {str(e)}', type='negative')


async def export_all():
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for md_file in NOTES_DIR.glob('*.md'):
                zip_file.write(md_file, arcname=f"notes/{md_file.name}")

            if Path('data/echo.db').exists():
                zip_file.write('data/echo.db', arcname='data/echo.db')

            if CHROMA_DIR.exists():
                for root, _, files in os.walk(CHROMA_DIR):
                    for file in files:
                        file_path = Path(root) / file
                        arc_path = file_path.relative_to(DATA_DIR)
                        zip_file.write(file_path, arcname=str(arc_path))

        zip_buffer.seek(0)
        filename = f"echo_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        ui.download(zip_buffer.read(), filename=filename)
        ui.notify(f'Export abgeschlossen – {filename}', type='positive')

    except Exception as e:
        ui.notify(f'Export fehlgeschlagen: {str(e)}', type='negative')


# Start mit klarem Browser-Tab-Titel
ui.run(
    title='Echo – dein lokaler Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
