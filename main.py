# main.py – ECHO Second Brain (stabilisiert – alle LLM-Aufrufe abgefangen)
# Stand: März 2026

from nicegui import ui, app
from datetime import datetime, timedelta
import uuid
from pathlib import Path
import zipfile
import io
import os
import shutil
import json

# Für PDF-Export (weiß, schwarz, blauer Titel)
from weasyprint import HTML

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

    # Header
    with ui.column().classes('items-center w-full mb-12'):
        ui.label('ECHO').classes('text-7xl font-black text-indigo-400 tracking-widest drop-shadow-2xl')
        ui.label('dein lokaler Stream-of-Thought Second Brain').classes('text-2xl text-slate-300 mt-3 font-light italic')

    # Automatische Funktionen beim Start – mit Fehlerbehandlung
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

                tags = await generate_tags(text)  # mit try/except in generate_tags
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

                try:
                    summary = await generate_summary(summary_prompt)
                except Exception as llm_err:
                    summary = f"[Zusammenfassung konnte nicht generiert werden: {str(llm_err)}]"

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
                'Graph-View öffnen',
                icon='hub',
                on_click=lambda: ui.navigate.to('/graph')
            ).props('unelevated color=purple-600 rounded-xl size=lg').classes('min-w-80 text-lg font-medium hover:scale-105 hover:shadow-2xl transition-all duration-300 border border-purple-500/30')

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


# =====================================================================
# Graph-View Seite (bereinigt – await-Problem entfernt)
# =====================================================================

@ui.page('/graph')
async def graph_view():
    ui.label('Graph-View: Gedankenverbindungen').classes('text-4xl font-bold mb-8 text-center text-indigo-300')

    # Filter-Controls
    with ui.row().classes('justify-center gap-6 mb-8 flex-wrap'):
        limit_input = ui.number(label='Max. Notizen laden', value=150, min=50, max=800).classes('w-48')
        threshold_input = ui.number(label='Mindest-Ähnlichkeit', value=0.70, min=0.50, max=0.95, step=0.05).classes('w-48')
        refresh_btn = ui.button('Graph neu laden', icon='refresh', color='indigo').props('unelevated flat size=lg')

    status = ui.label('Lade Graph...').classes('text-center text-lg mb-4 opacity-80')
    graph_container = ui.html('').classes('w-full h-[75vh] border border-slate-700 rounded-xl overflow-hidden bg-slate-900')

    async def build_and_render_graph():
        try:
            status.text = 'Lade Notizen und berechne Verbindungen...'

            limit = int(limit_input.value)
            min_sim = float(threshold_input.value)

            db.cursor.execute("SELECT id, timestamp, text FROM notes ORDER BY timestamp DESC LIMIT ?", (limit,))
            notes = db.cursor.fetchall()

            if not notes:
                status.text = 'Keine Notizen vorhanden.'
                return

            nodes = []
            edges = set()

            for note_id, ts, text in notes:
                short_label = (text.split('\n')[0][:40] or ts[:19]).replace('"', "'")
                nodes.append({
                    "id": note_id,
                    "label": short_label,
                    "title": f"{ts}\n{text[:300]}...",
                    "value": 8 + len(text) // 300,
                    "group": ts[:10]
                })

                embedding = get_embedding(text)
                results = db.collection.query(
                    query_embeddings=[embedding],
                    n_results=10,
                    include=['metadatas', 'distances']
                )

                for j in range(len(results['ids'][0])):
                    other_id = results['ids'][0][j]
                    if other_id == note_id:
                        continue
                    sim = 1 - results['distances'][0][j]
                    if sim >= min_sim:
                        edge_key = tuple(sorted([note_id, other_id]))
                        edges.add((edge_key, sim))

            edge_list = [
                {"from": fr, "to": to, "value": sim * 4, "title": f"{sim:.1%} Ähnlichkeit"}
                for (fr, to), sim in edges
            ]

            graph_data = {"nodes": nodes, "edges": edge_list}

            status.text = f'Graph geladen: {len(nodes)} Knoten, {len(edge_list)} Verbindungen'

            vis_script = f"""
            <div id="mynetwork" style="width:100%; height:100%;"></div>
            <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
            <script>
                var container = document.getElementById('mynetwork');
                var data = {json.dumps(graph_data)};
                var options = {{
                    nodes: {{
                        shape: 'dot',
                        font: {{ size: 14, color: '#e2e8f0' }},
                        scaling: {{ min: 10, max: 40 }},
                        borderWidth: 2,
                        borderWidthSelected: 4
                    }},
                    edges: {{
                        arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }},
                        smooth: {{ type: 'continuous' }},
                        color: {{ color: '#64748b', highlight: '#a5b4fc' }}
                    }},
                    physics: {{
                        enabled: true,
                        barnesHut: {{ gravitationalConstant: -6000, springLength: 120 }}
                    }},
                    interaction: {{
                        hover: true,
                        navigationButtons: true,
                        keyboard: true,
                        zoomView: true,
                        dragView: true
                    }},
                    groups: {{ useDefaultGroups: true }}
                }};
                new vis.Network(container, data, options);
            </script>
            """

            graph_container.content = vis_script

        except Exception as e:
            status.text = f'Fehler beim Erstellen des Graphs: {str(e)}'
            status.classes('text-red-400')

    await build_and_render_graph()

    async def on_refresh():
        graph_container.content = ''
        status.text = 'Graph wird neu geladen...'
        await build_and_render_graph()

    refresh_btn.on('click', on_refresh)


# =====================================================================
# Hilfsfunktionen mit Fehlerbehandlung
# =====================================================================

async def generate_tags(text: str):
    try:
        prompt = f"Analysiere den Text und schlage 2–4 Tags vor (kommagetrennt, keine Erklärung):\n\n{text[:1000]}\n\nBeispiele: Produktivität,Reise,Emotionen"
        tags_str = await generate_summary(prompt)
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]
        return tags[:4]
    except Exception as e:
        print(f"Tag-Generierung fehlgeschlagen: {e}")
        return []


async def check_and_generate_auto_reflection():
    try:
        since = (datetime.now() - timedelta(days=7)).isoformat()
        db.cursor.execute("SELECT id FROM notes WHERE timestamp >= ? AND text LIKE '%Wöchentliche Reflexion%' LIMIT 1", (since,))
        if db.cursor.fetchone():
            return

        context_entries = db.cursor.execute("SELECT timestamp, text FROM notes WHERE timestamp >= ? ORDER BY timestamp", (since,)).fetchall()
        if not context_entries:
            return

        context = "\n\n".join([f"[{ts}] {text[:600]}..." for ts, text in context_entries])
        prompt = (
            "Du bist ein reflektierender Coach. Analysiere die Gedanken der letzten Woche:\n\n"
            f"{context}\n\n"
            "- Wiederkehrende Themen?\n"
            "- Emotionale Tonalität?\n"
            "- Muster / Loops?\n"
            "- Was wurde ignoriert / bereut?\n"
            "- Nächste Woche besser machen?\n\n"
            "Strukturiert mit Überschriften und Punkten. Direkt, wohlwollend."
        )

        reflection_text = await generate_summary(prompt)

        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_AUTO_REFLEXION.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Automatische Reflexion – {timestamp}\n\n{reflection_text}")

        embedding = get_embedding(reflection_text)
        db.add_note(note_id, timestamp, reflection_text, str(filename), embedding)

        ui.notify('Automatische Reflexion erstellt.', type='positive', timeout=6)

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
            "Kurze Tageszusammenfassung basierend auf den letzten 24h:\n\n"
            f"{context}\n\n"
            "- Hauptthemen?\n"
            "- Emotionale Tonalität?\n"
            "- Offene Punkte / nächste Schritte?\n"
            "- Kurzer motivierender Satz.\n\n"
            "Knapp, strukturiert, direkt."
        )

        summary_text = await generate_summary(prompt)

        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_DAILY_SUMMARY.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Tageszusammenfassung – {today}\n\n{summary_text}")

        embedding = get_embedding(summary_text)
        db.add_note(note_id, timestamp, summary_text, str(filename), embedding)

        ui.notify('Tageszusammenfassung automatisch erstellt.', type='positive', timeout=6)

    except Exception as e:
        print(f"Auto-Tageszusammenfassung fehlgeschlagen: {e}")


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
            "Analysiere die Gedanken der letzten Woche:\n\n"
            f"{context}\n\n"
            "- Wiederkehrende Themen?\n"
            "- Emotionale Tonalität?\n"
            "- Muster / Loops?\n"
            "- Verschoben / ignoriert / bereut?\n"
            "- Nächste Woche besser machen?\n\n"
            "Klar strukturiert, direkt, wohlwollend."
        )

        try:
            reflection_text = await generate_summary(prompt)
        except Exception as llm_err:
            reflection_text = f"[LLM-Fehler: {str(llm_err)}]\n\nBitte prüfe Ollama (Server läuft? Modell gezogen?)."
            print(f"LLM-Fehler in Reflexion: {llm_err}")

        timestamp = datetime.now().isoformat()
        note_id = str(uuid.uuid4())[:12]
        filename = NOTES_DIR / f"{timestamp.replace(':', '-')}_{note_id}_REFLEXION.md"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Wöchentliche Reflexion – {timestamp}\n\n{reflection_text}")

        embedding = get_embedding(reflection_text)
        db.add_note(note_id, timestamp, reflection_text, str(filename), embedding)

        # PDF (weiß, schwarz, blauer Titel)
        html_safe_text = reflection_text.replace('\n', '<br>')

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Wöchentliche Reflexion – {timestamp[:10]}</title>
            <style>
                @page {{ size: A4; margin: 2.5cm 2cm; }}
                body {{ font-family: 'Helvetica', 'Arial', sans-serif; line-height: 1.6; color: #000000; background: #ffffff; margin: 0; padding: 0; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 1cm; }}
                h1 {{ color: #6366f1; text-align: center; font-size: 2.2em; margin-bottom: 0.4em; }}
                .date {{ text-align: center; color: #4b5563; font-size: 1.1em; margin-bottom: 2em; }}
                .content {{ font-size: 1.05em; color: #000000; }}
                h2, h3 {{ color: #4b5563; margin-top: 1.5em; }}
                ul, ol {{ margin-left: 1.5em; }}
                hr {{ border: none; border-top: 1px solid #d1d5db; margin: 2em 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Wöchentliche Reflexion</h1>
                <div class="date">{timestamp[:19].replace('T', ' ')}</div>
                <div class="content">{html_safe_text}</div>
            </div>
        </body>
        </html>
        """

        pdf_bytes = HTML(string=html_content).write_pdf()

        reflection_content.clear()
        reflection_content.content = f"**Gespeichert als:** {filename.name}\n\n{reflection_text}"

        ui.button(
            'Als PDF herunterladen',
            icon='picture_as_pdf',
            on_click=lambda: ui.download(pdf_bytes, filename=f"reflexion_{timestamp[:10]}.pdf")
        ).props('unelevated color=indigo-7 size=lg').classes('mt-6 w-full md:w-auto')

        reflection_dialog.value = True

        ui.notify('Reflexion generiert & PDF bereit', type='positive')

    except Exception as e:
        ui.notify(f'Reflexion fehlgeschlagen: {str(e)}', type='negative')


# ... (decay_and_archive, check_auto_linking, export_all, edit_note, save_edit, delete_note, confirm_delete bleiben unverändert – wie in vorheriger Version)

ui.run(
    title='ECHO – dein lokaler Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
