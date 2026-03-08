# main.py – ECHO Kern + Reflexion + Export + Auto-Linking + persönlicher Name (März 2026)

from nicegui import ui, app
from datetime import datetime, timedelta
import uuid
from pathlib import Path
import zipfile
import io
import os
import shutil
import json

# Lokale Module
from database import NoteDB
from llm import generate_summary
from embedder import get_embedding

DATA_DIR = Path("data")
NOTES_DIR = DATA_DIR / "notes"
CHROMA_DIR = DATA_DIR / "chroma"
ARCHIVE_DIR = DATA_DIR / "archive"
USER_FILE = DATA_DIR / "user.json"

ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)

db = NoteDB()

# Globale Referenzen für Dialoge
reflection_dialog = None
reflection_content = None
linking_dialog = None
linking_content = None
merge_button = None

# =====================================
# Benutzername laden / abfragen
# =====================================
def load_username():
    if USER_FILE.exists():
        try:
            with open(USER_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('name', 'du')
        except:
            return 'du'
    return None


def save_username(name: str):
    USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_FILE, 'w', encoding='utf-8') as f:
        json.dump({'name': name.strip()}, f, ensure_ascii=False, indent=2)


# =====================================
# Start-Dialog für den Namen (nur beim ersten Mal)
# =====================================
async def ask_for_username():
    username = load_username()
    if username is not None:
        return username

    with ui.dialog(value=True).props('persistent') as name_dialog:
        with ui.card().classes('w-full max-w-md'):
            ui.label('Hallo! Schön dich kennenzulernen 😊').classes('text-2xl font-bold mb-4 text-center')
            ui.label('Wie darf ich dich nennen?').classes('text-lg text-center mb-6')
            name_input = ui.input(placeholder='z. B. Cdemkos oder Alex').props('outlined clearable').classes('w-full')
            ui.button('Los geht’s', on_click=lambda: name_dialog.hide()).props('unelevated color=indigo-8').classes('mt-6 w-full')

            async def save_and_close():
                name = name_input.value.strip()
                if name:
                    save_username(name)
                    ui.notify(f'Hallo {name}! Freut mich sehr.', type='positive')
                else:
                    ui.notify('Ohne Namen geht’s auch – ich nenne dich dann einfach „du“ 😄', type='info')
                    save_username('du')
                name_dialog.hide()

            ui.button('Los geht’s', on_click=save_and_close).props('unelevated color=indigo-8').classes('mt-6 w-full')

    # Warte, bis Dialog geschlossen ist
    await name_dialog
    return load_username() or 'du'


# Lade oder frage den Namen beim Start
current_user = None


@ui.page('/')
async def index():
    global reflection_dialog, reflection_content, linking_dialog, linking_content, merge_button, current_user

    if current_user is None:
        current_user = await ask_for_username()

    # Header
    with ui.column().classes('items-center w-full mb-12'):
        ui.label('ECHO').classes('text-7xl font-black text-indigo-400 tracking-widest drop-shadow-2xl')
        ui.label(f'Hallo {current_user} – dein lokaler Second Brain').classes('text-2xl text-slate-300 mt-3 font-light italic')

    # =====================================
    # Eingabe-Bereich
    # =====================================
    with ui.card().classes('w-full max-w-4xl mx-auto shadow-2xl rounded-3xl bg-gradient-to-br from-slate-950 to-slate-900 border border-slate-700/50'):
        ui.label('Neuer Gedanke').classes('text-3xl font-bold mb-5 text-white text-center')
        thought_input = ui.textarea(
            placeholder='Schreib einfach drauflos... (Enter oder Auto-Save nach 8 Sekunden Inaktivität)'
        ).props('autogrow outlined clearable bordered').classes('w-full min-h-64 bg-slate-950 text-slate-100 placeholder-slate-500 rounded-xl')

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
                    f'{current_user}, Gedanke gespeichert → {note_id[:8]}' + (' (Auto-Save)' if auto else ''),
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
            .props('unelevated color=green-600 rounded-xl').classes('mt-6 w-full md:w-1/3 mx-auto text-lg hover:scale-105 transition-transform')

    # Suche-Bereich
    with ui.card().classes('w-full max-w-4xl mx-auto mt-10 shadow-2xl rounded-3xl bg-gradient-to-br from-slate-950 to-slate-900 border border-slate-700/50'):
        ui.label('Suche in deinem ECHO').classes('text-3xl font-bold mb-5 text-white text-center')
        search_input = ui.input(
            placeholder='z. B. "Gedanken zu Japan Reise letzten 3 Monate"'
        ).props('outlined dense clearable').classes('w-full bg-slate-950 text-white placeholder-slate-500 rounded-xl')

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
                    f"Fasse ehrlich und knapp zusammen, was {current_user} zu diesem Thema gedacht hat. "
                    "Nenne wiederkehrende Muster, emotionale Tonalität und offene Fragen. "
                    "Strukturiere mit Aufzählungspunkten wenn sinnvoll.\n\n"
                    f"Suchanfrage: {query}\n\n{context}"
                )
                summary = await generate_summary(summary_prompt)

                result_area.content = (
                    f"**Zusammenfassung für {current_user}:**\n\n{summary}\n\n"
                    f"---\n\n**Gefundene Einträge:**\n\n"
                    + "\n\n".join(context_parts)
                )
            except Exception as e:
                result_area.content = f'Fehler bei der Suche: {str(e)}'
                ui.notify(f'Suchfehler: {str(e)}', type='negative')

        ui.button('Suchen', on_click=perform_search) \
            .props('unelevated color=blue-600 rounded-xl').classes('mt-6 w-full md:w-1/3 mx-auto text-lg hover:scale-105 transition-transform')

    # Schnellzugriff-Card
    with ui.card().classes('w-full max-w-4xl mx-auto mt-12 shadow-2xl rounded-3xl bg-gradient-to-r from-indigo-950/70 to-slate-950/70 border border-indigo-700/30 backdrop-blur-sm'):
        ui.label('Schnellzugriff').classes('text-2xl font-bold text-center text-indigo-300 mb-8')
        with ui.row().classes('justify-center gap-12 flex-wrap px-8 py-6'):
            ui.button(
                'Wöchentliche Reflexion jetzt',
                icon='auto_awesome',
                on_click=generate_weekly_reflection
            ).props('unelevated color=indigo-600 rounded-xl size=lg').classes('min-w-80 text-lg font-medium hover:scale-105 hover:shadow-2xl transition-all duration-300 border border-indigo-500/30')

            ui.button(
                'Alles exportieren (ZIP)',
                icon='download',
                on_click=export_all
            ).props('unelevated color=amber-600 rounded-xl size=lg').classes('min-w-80 text-lg font-medium hover:scale-105 hover:shadow-2xl transition-all duration-300 border border-amber-500/30')

    # Reflexions-Dialog
    reflection_dialog = ui.dialog(value=False).props('persistent')
    with reflection_dialog:
        with ui.card().classes('w-full max-w-4xl'):
            ui.label('Wöchentliche Reflexion').classes('text-3xl font-bold mb-6 text-indigo-300')
            reflection_content = ui.markdown().classes('prose prose-slate max-w-none dark:prose-invert')
            ui.button('Schließen', on_click=lambda: setattr(reflection_dialog, 'value', False)) \
                .props('unelevated color=grey-8 rounded-xl').classes('mt-8 w-full md:w-auto text-lg')

    # Auto-Linking Dialog
    linking_dialog = ui.dialog(value=False).props('persistent')
    with linking_dialog:
        with ui.card().classes('w-full max-w-4xl'):
            ui.label('Mögliche Verknüpfungen gefunden').classes('text-3xl font-bold mb-6 text-teal-300')
            linking_content = ui.markdown().classes('prose prose-slate max-w-none dark:prose-invert')
            with ui.row().classes('gap-6 mt-8 justify-end'):
                ui.button('Keine Verknüpfung', on_click=lambda: setattr(linking_dialog, 'value', False)) \
                    .props('unelevated color=grey-8 rounded-xl').classes('text-lg')
                merge_button = ui.button('Alle mergen', on_click=lambda: setattr(linking_dialog, 'value', False)) \
                    .props('unelevated color=teal-9 rounded-xl').classes('text-lg text-white')


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

        content = f"**Hallo {current_user}, sehr ähnliche Gedanken gefunden (Ähnlichkeit > 75 %):**\n\n"
        for entry in similar:
            content += f"- **{entry['timestamp']}** ({entry['similarity']:.2%})\n  {entry['text']}\n\n"

        content += "Möchtest du diese Einträge mergen? (Alte werden archiviert)"

        linking_content.content = content
        linking_dialog.value = True

        async def do_merge():
            merged_text = f"Hallo {current_user}, hier dein gemergter Gedanke:\n\n" + new_text + "\n\n---\n\n**Verknüpfte frühere Gedanken:**\n\n"
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

            ui.notify(f'{current_user}, Einträge erfolgreich gemergt & archiviert', type='positive')
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
            ui.notify(f'{current_user}, keine Notizen in den letzten 7 Tagen gefunden.', type='warning')
            return

        context = "\n\n".join([f"[{ts}] {text[:600]}..." for ts, text in entries])
        prompt = (
            f"Du bist ein ehrlicher, reflektierender Coach. "
            f"Analysiere die folgenden Gedanken von {current_user} der letzten Woche:\n\n"
            f"{context}\n\n"
            "- Welche Themen tauchen wiederholt auf?\n"
            "- Welche emotionale Tonalität dominiert (Frust, Neugier, Stolz, Angst, …)?\n"
            "- Welche Muster, Gewohnheiten oder offene Loops siehst du?\n"
            "- Was wurde verschoben, ignoriert oder bereut?\n"
            "- Was könnte {current_user} nächste Woche anders / besser machen?\n\n"
            "Strukturiere die Antwort klar mit Überschriften und Aufzählungspunkten. "
            "Sei direkt, aber wohlwollend – keine Schönfärberei."
        )

        reflection_text = await generate_summary(prompt)

        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_REFLEXION.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Wöchentliche Reflexion für {current_user} – {timestamp}\n\n{reflection_text}")

        embedding = get_embedding(reflection_text)
        db.add_note(note_id, timestamp, reflection_text, str(filename), embedding)

        reflection_content.content = f"**Gespeichert als:** {filename.name}\n\n{reflection_text}"
        reflection_dialog.value = True

        ui.notify(f'{current_user}, Reflexion generiert & gespeichert', type='positive')

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
        ui.notify(f'{current_user}, Export abgeschlossen – {filename}', type='positive')

    except Exception as e:
        ui.notify(f'Export fehlgeschlagen: {str(e)}', type='negative')


ui.run(
    title='ECHO – dein lokaler Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
