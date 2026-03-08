# main.py – ECHO Second Brain (komplett & fehlerfrei – März 2026)

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


# =====================================================================
# Hilfsfunktionen – ALLE vor index() definieren!
# =====================================================================

async def generate_tags(text: str):
    try:
        prompt = (
            f"Analysiere den folgenden Text und schlage 2–4 passende Tags / Kategorien vor. "
            f"Gib nur die Tags als kommagetrennte Liste zurück, ohne Einleitung oder Erklärung.\n\n"
            f"Text: {text[:1000]}\n\n"
            f"Beispiele: Produktivität,Reise,Emotionen,Todo,Beziehung,Finanzen,Gesundheit"
        )
        tags_str = await generate_summary(prompt)
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]
        return tags[:4]
    except Exception:
        return []


async def check_and_generate_auto_reflection():
    try:
        since = (datetime.now() - timedelta(days=7)).isoformat()
        db.cursor.execute(
            "SELECT id FROM notes WHERE timestamp >= ? AND text LIKE '%Wöchentliche Reflexion%' LIMIT 1",
            (since,)
        )
        if db.cursor.fetchone():
            return

        context_entries = db.cursor.execute(
            "SELECT timestamp, text FROM notes WHERE timestamp >= ? ORDER BY timestamp",
            (since,)
        ).fetchall()

        if not context_entries:
            return

        context = "\n\n".join([f"[{ts}] {text[:600]}..." for ts, text in context_entries])
        prompt = (
            "Du bist ein ehrlicher, reflektierender Coach. "
            "Analysiere die folgenden Gedanken des Nutzers der letzten Woche:\n\n"
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

        ui.notify('Automatische wöchentliche Reflexion wurde erstellt und gespeichert.', type='positive', timeout=8)

    except Exception as e:
        print(f"Auto-Reflexion fehlgeschlagen: {e}")


async def generate_auto_daily_summary():
    try:
        since = (datetime.now() - timedelta(hours=24)).isoformat()
        db.cursor.execute("SELECT timestamp, text FROM notes WHERE timestamp >= ? ORDER BY timestamp", (since,))
        entries = db.cursor.fetchall()

        if not entries:
            return

        today = datetime.now().strftime('%Y-%m-%d')
        db.cursor.execute("SELECT id FROM notes WHERE timestamp LIKE ? AND text LIKE '%Tageszusammenfassung%'", (f"{today}%",))
        if db.cursor.fetchone():
            return

        context = "\n\n".join([f"[{ts}] {text[:400]}..." for ts, text in entries])
        prompt = (
            "Erstelle eine kurze Tageszusammenfassung für den Nutzer basierend auf den Gedanken der letzten 24 Stunden:\n\n"
            f"{context}\n\n"
            "- Welche Hauptthemen standen im Vordergrund?\n"
            "- Wie war die emotionale Tonalität (Frust, Energie, Ruhe, Druck, …)?\n"
            "- Welche offenen Punkte oder nächsten Schritte kristallisieren sich heraus?\n"
            "- Ein kurzer, motivierender oder warnender Satz für den Rest des Tages.\n\n"
            "Halte es knapp (max. 150–200 Wörter), strukturiert und direkt. "
            f"Titel: Tageszusammenfassung – {today}"
        )

        summary_text = await generate_summary(prompt)

        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_DAILY_SUMMARY.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Tageszusammenfassung – {today}\n\n{summary_text}")

        embedding = get_embedding(summary_text)
        db.add_note(note_id, timestamp, summary_text, str(filename), embedding)

        ui.notify('Deine Tageszusammenfassung wurde automatisch erstellt und gespeichert.', type='positive', timeout=8)

    except Exception as e:
        print(f"Auto-Zusammenfassung fehlgeschlagen: {e}")


async def decay_and_archive():
    try:
        archive_after_days = 90
        reference_window_days = 30

        cutoff = (datetime.now() - timedelta(days=archive_after_days)).isoformat()
        reference_cutoff = (datetime.now() - timedelta(days=reference_window_days)).isoformat()

        db.cursor.execute("""
            SELECT id, timestamp, file_path 
            FROM notes 
            WHERE timestamp < ? 
            AND (SELECT COUNT(*) FROM notes 
                 WHERE text LIKE '%' || notes.id || '%' 
                 AND timestamp > ?) = 0
        """, (cutoff, reference_cutoff))

        old_notes = db.cursor.fetchall()

        archived = 0
        for note_id, ts, file_path in old_notes:
            old_path = Path(file_path)
            if old_path.exists():
                shutil.move(str(old_path), ARCHIVE_DIR / old_path.name)
            db.collection.delete(ids=[note_id])
            db.cursor.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            archived += 1

        db.conn.commit()

        if archived > 0:
            ui.notify(f'{archived} alte Notizen wurden archiviert.', type='info', timeout=6)

    except Exception as e:
        print(f"Decay fehlgeschlagen: {e}")


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
            "Analysiere die folgenden Gedanken des Nutzers der letzten Woche:\n\n"
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
        ui.notify('Export abgeschlossen – ZIP wird heruntergeladen', type='positive')

    except Exception as e:
        ui.notify(f'Export fehlgeschlagen: {str(e)}', type='negative')


# =====================================================================
# Edit & Delete Funktionen
# =====================================================================

async def edit_note(hit):
    with ui.dialog(value=True).props('persistent') as edit_dialog:
        with ui.card().classes('w-full max-w-4xl'):
            ui.label(f'Bearbeite Eintrag vom {hit["timestamp"]}').classes('text-2xl font-bold mb-4')
            edit_input = ui.textarea(value=hit['text']).props('autogrow outlined').classes('w-full min-h-64')
            ui.button('Speichern', on_click=lambda: save_edit(hit, edit_input.value, edit_dialog)) \
                .props('unelevated color=green-8').classes('mt-6')
            ui.button('Abbrechen', on_click=edit_dialog.hide).props('unelevated color=grey-8').classes('mt-2')


async def save_edit(hit, new_text, dialog):
    try:
        # Alte Notiz archivieren
        old_path = Path(hit['file_path'])
        if old_path.exists():
            shutil.move(str(old_path), ARCHIVE_DIR / old_path.name)

        # Neue Version speichern
        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_EDIT.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Bearbeitete Version – {timestamp} (Original: {hit['timestamp']})\n\n{new_text}")

        embedding = get_embedding(new_text)
        db.add_note(note_id, timestamp, new_text, str(filename), embedding)

        # Alte aus DB und Chroma löschen
        db.collection.delete(ids=[hit['id']])
        db.cursor.execute("DELETE FROM notes WHERE id = ?", (hit['id'],))
        db.conn.commit()

        ui.notify('Eintrag erfolgreich bearbeitet & alte Version archiviert', type='positive')
        dialog.hide()

    except Exception as e:
        ui.notify(f'Bearbeitung fehlgeschlagen: {str(e)}', type='negative')


async def delete_note(hit):
    with ui.dialog(value=True).props('persistent') as delete_dialog:
        with ui.card().classes('w-full max-w-md'):
            ui.label('Eintrag wirklich löschen?').classes('text-2xl font-bold mb-4 text-red-400')
            ui.label('Diese Aktion kann nicht rückgängig gemacht werden.').classes('mb-6')
            with ui.row().classes('justify-end gap-4'):
                ui.button('Abbrechen', on_click=delete_dialog.hide).props('unelevated color=grey-8')
                ui.button('Löschen', on_click=lambda: confirm_delete(hit, delete_dialog)).props('unelevated color=red-8')


async def confirm_delete(hit, dialog):
    try:
        # Datei löschen
        old_path = Path(hit['file_path'])
        if old_path.exists():
            os.remove(old_path)

        # Aus DB und Chroma löschen
        db.collection.delete(ids=[hit['id']])
        db.cursor.execute("DELETE FROM notes WHERE id = ?", (hit['id'],))
        db.conn.commit()

        ui.notify('Eintrag erfolgreich gelöscht', type='negative')
        dialog.hide()

    except Exception as e:
        ui.notify(f'Löschen fehlgeschlagen: {str(e)}', type='negative')


# =====================================================================
# Hauptseite
# =====================================================================
@ui.page('/')
async def index():
    global reflection_dialog, reflection_content, linking_dialog, linking_content, merge_button

    # Header
    with ui.column().classes('items-center w-full mb-12'):
        ui.label('ECHO').classes('text-7xl font-black text-indigo-400 tracking-widest drop-shadow-2xl')
        ui.label('dein lokaler Stream-of-Thought Second Brain').classes('text-2xl text-slate-300 mt-3 font-light italic')

    # Automatische Funktionen beim Start
    await check_and_generate_auto_reflection()
    await generate_auto_daily_summary()
    await decay_and_archive()

    # Eingabe-Bereich
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

                # Tags generieren und speichern
                tags = await generate_tags(text)
                db.collection.update(
                    ids=[note_id],
                    metadatas=[{"timestamp": timestamp, "file_path": str(filename), "tags": ",".join(tags)}]
                )

                ui.notify(
                    f'Gedanke gespeichert → {note_id[:8]} (Tags: {", ".join(tags)})' + (' (Auto-Save)' if auto else ''),
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

    # Suche-Bereich mit Edit & Delete
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
                    "Fasse ehrlich und knapp zusammen, was der Nutzer zu diesem Thema gedacht hat. "
                    "Nenne wiederkehrende Muster, emotionale Tonalität und offene Fragen. "
                    "Strukturiere mit Aufzählungspunkten wenn sinnvoll.\n\n"
                    f"Suchanfrage: {query}\n\n{context}"
                )
                summary = await generate_summary(summary_prompt)

                html = f"**Zusammenfassung:**\n\n{summary}\n\n---\n\n**Gefundene Einträge:**\n\n"

                with ui.column() as result_column:
                    for hit in hits:
                        card = ui.card().classes('w-full mb-4')
                        with card:
                            ui.markdown(f"**{hit['timestamp']}**  \n{hit['text'][:450]}...")
                            with ui.row().classes('gap-4 mt-4'):
                                ui.button('Bearbeiten', on_click=lambda h=hit: edit_note(h)).props('unelevated color=blue-8')
                                ui.button('Löschen', on_click=lambda h=hit: delete_note(h)).props('unelevated color=red-8')

                result_area.content = html

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


ui.run(
    title='ECHO – dein lokaler Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
