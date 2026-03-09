# main.py – ECHO Second Brain (komplett mit Graph-View & druckfreundlichem PDF-Export)
# Stand: März 2026

from nicegui import ui, app
from datetime import datetime, timedelta
import uuid
from pathlib import Path
import zipfile
import io
import os
import shutil
import json  # für Graph-Daten

# Für PDF-Export (weißes Layout, schwarzer Text, blauer Titel)
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

    # Schnellzugriff-Card (mit Link zum Graph-View)
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

    # Reflexions-Dialog (mit PDF-Download)
    reflection_dialog = ui.dialog(value=False).props('persistent')
    with reflection_dialog:
        with ui.card().classes('w-full max-w-4xl'):
            ui.label('Wöchentliche Reflexion').classes('text-3xl font-bold mb-6 text-indigo-300')
            reflection_content = ui.markdown().classes('prose prose-slate max-w-none dark:prose-invert')
            ui.button('Schließen', on_click=lambda: setattr(reflection_dialog, 'value', False)) \
                .props('unelevated color=grey-8 rounded-xl').classes('mt-8 w-full md:w-auto text-lg')


# =====================================================================
# Graph-View Seite
# =====================================================================

@ui.page('/graph')
async def graph_view():
    ui.label('Graph-View: Gedankenverbindungen').classes('text-4xl font-bold mb-8 text-center text-indigo-300')

    # Filter-Controls
    with ui.row().classes('justify-center gap-6 mb-8 flex-wrap'):
        limit_input = ui.number(
            label='Max. Notizen laden',
            value=150,
            min=50,
            max=800
        ).classes('w-48')
        threshold_input = ui.number(
            label='Mindest-Ähnlichkeit',
            value=0.70,
            min=0.50,
            max=0.95,
            step=0.05
        ).classes('w-48')
        refresh_btn = ui.button(
            'Graph neu laden',
            icon='refresh',
            color='indigo'
        ).props('unelevated flat size=lg')

    # Status & Graph-Container
    status = ui.label('Lade Graph... (bei vielen Notizen etwas Geduld)').classes('text-center text-lg mb-4 opacity-80')
    graph_container = ui.html('').classes('w-full h-[75vh] border border-slate-700 rounded-xl overflow-hidden bg-slate-900')

    async def build_and_render_graph():
        try:
            status.text = 'Lade Notizen und berechne Verbindungen...'
            await ui.context.client.request  # Kontext erzwingen

            limit = int(limit_input.value)
            min_sim = float(threshold_input.value)

            # Notizen laden (neueste zuerst, begrenzt)
            db.cursor.execute(
                "SELECT id, timestamp, text FROM notes ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            notes = db.cursor.fetchall()

            if not notes:
                status.text = 'Keine Notizen vorhanden.'
                return

            nodes = []
            edges = set()  # vermeidet Duplikate

            for note_id, ts, text in notes:
                short_label = (text.split('\n')[0][:40] or ts[:19]).replace('"', "'")
                nodes.append({
                    "id": note_id,
                    "label": short_label,
                    "title": f"{ts}\n{text[:300]}...",
                    "value": 8 + len(text) // 300,  # Knotengröße ~ Textlänge
                    "group": ts[:10]  # Farbcluster nach Tag
                })

                # Ähnlichste Notizen holen
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

            # Kanten formatieren
            edge_list = [
                {"from": fr, "to": to, "value": sim * 4, "title": f"{sim:.1%} Ähnlichkeit"}
                for (fr, to), sim in edges
            ]

            graph_data = {"nodes": nodes, "edges": edge_list}

            status.text = f'Graph geladen: {len(nodes)} Knoten, {len(edge_list)} Verbindungen'

            # vis-network Script (CDN)
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

    # Initial laden
    await build_and_render_graph()

    # Refresh-Button
    async def on_refresh():
        graph_container.content = ''
        status.text = 'Graph wird neu geladen...'
        await build_and_render_graph()

    refresh_btn.on('click', on_refresh)


# =====================================================================
# Hilfsfunktionen (Rest wie zuvor – gekürzt dargestellt)
# =====================================================================

# ... (generate_tags, check_and_generate_auto_reflection, generate_auto_daily_summary,
#      decay_and_archive, check_auto_linking, generate_weekly_reflection, export_all,
#      edit_note, save_edit, delete_note, confirm_delete bleiben unverändert)

ui.run(
    title='ECHO – dein lokaler Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
