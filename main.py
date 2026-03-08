# main.py – ECHO Second Brain mit Lade-Screen beim Start
# Stand: März 2026

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

# Globale Referenzen für Dialoge
reflection_dialog = None
reflection_content = None
linking_dialog = None
linking_content = None
merge_button = None


# =====================================
# Lade-Screen (wird als erste Seite angezeigt)
# =====================================
@ui.page('/')
async def loading_screen():
    ui.context.client.content.classes('bg-slate-950')

    with ui.column().classes('items-center justify-center min-h-screen text-white'):
        ui.label('ECHO').classes('text-8xl font-black text-indigo-400 tracking-widest drop-shadow-2xl animate-pulse')
        ui.label('Dein lokaler Second Brain lädt...').classes('text-2xl mt-6 mb-4')
        ui.spinner(size='xl', color='indigo').classes('mt-6')

        status = ui.label('Datenbank und Modelle werden initialisiert...').classes('text-lg mt-10 opacity-80')

    # Initialisierung asynchron starten
    async def initialize():
        try:
            status.text = 'Lade Embedding-Modell (einmalig, bitte warten)...'
            db = NoteDB()  # ← hier wird das Modell lazy geladen
            status.text = 'Initialisierung abgeschlossen – lade Oberfläche...'
            # Zur echten Hauptseite weiterleiten
            await ui.run_javascript('window.location.href = "/app"')
        except Exception as e:
            status.text = f'Fehler beim Laden: {str(e)}'
            status.classes('text-red-400')

    # 0.1 s verzögern, damit der Lade-Screen sichtbar ist
    ui.timer(0.1, initialize, once=True)


# =====================================
# Echte Hauptseite (wird nach Lade-Screen aufgerufen)
# =====================================
@ui.page('/app')
async def main_app():
    global reflection_dialog, reflection_content, linking_dialog, linking_content, merge_button

    # Header
    with ui.column().classes('items-center w-full mb-12'):
        ui.label('ECHO').classes('text-7xl font-black text-indigo-400 tracking-widest drop-shadow-2xl')
        ui.label('dein lokaler Stream-of-Thought Second Brain').classes('text-2xl text-slate-300 mt-3 font-light italic')

    # Automatische Funktionen beim Start
    await check_and_generate_auto_reflection()
    await generate_auto_daily_summary()
    await decay_and_archive()

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


# =====================================================================
# Hilfsfunktionen (Auszug – den Rest aus vorheriger Version übernehmen)
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


# ... (hier kommen alle anderen Funktionen wie check_auto_linking, generate_weekly_reflection,
#      export_all, edit_note, save_edit, delete_note, confirm_delete, decay_and_archive usw.
#      – kopiere sie aus deiner vorherigen Version einfach rein)

ui.run(
    title='ECHO – dein lokaler Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
