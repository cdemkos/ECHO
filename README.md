# Echo – dein lokaler, schneller Stream-of-Thought Second Brain

<img src="https://via.placeholder.com/1200x400/111827/ffffff?text=Echo+-+minimal+local+second+brain" alt="Echo Banner">

**Ein radikal minimalistisches, komplett lokales Notiz- & Denk-Tool**, das sich wie ein stiller Gesprächspartner anfühlt – schnell, privat, ohne Ballast.

### Philosophie in einem Satz

Du tippst oder sprichst einfach drauflos → alles wird automatisch gespeichert, indiziert und semantisch durchsuchbar → das Tool denkt mit, fasst zusammen, findet Verbindungen und erinnert dich an deine eigenen Muster – ohne dass du jemals Tags, Ordner oder komplizierte Strukturen pflegen musst.

### Was Echo anders macht (meine Prioritäten)

- **Nur ein Eingabefeld** – kein "Neue Notiz"-Button, keine Sidebar, keine Datenbank-Ansichten  
- **Sub-Second-Suche** auch bei 20.000+ Einträgen (Hybrid BM25 + Embedding)  
- **Aggressive Auto-Zusammenfassung** alter Gedankenstränge („Was habe ich eigentlich die letzten 4 Monate über X gedacht?“)  
- **Stil lernt deine Stimme** – Vorschläge klingen nach dir, nicht nach ChatGPT  
- **Mini-Agenten** in natürlicher Sprache definierbar (rudimentär im MVP)  
- **Keine Cloud, kein Telemetrie, keine API-Keys** – alles bleibt auf deinem Gerät  
- **Decay & Merge-Vorschläge** – alte, ungenutzte Gedanken verblassen sanft, Duplikate werden erkannt  
- **Wöchentliche Reflexion** (geplant): „Deine Top-Themen + emotionale Tonalität der Woche“

### Aktueller Stand (MVP – März 2026)

Funktioniert bereits:

- Stream-of-Thought-Eingabe (Text)
- Automatisches Speichern als Markdown + Chunking + Embedding
- Semantische Suche + kurze LLM-Zusammenfassung der Treffer
- Lokale Chroma-Vector-DB + SQLite-Metadaten
- NiceGUI-Web-Interface (browserbasiert, dark mode)

Noch nicht drin (Prioritäten für v0.2–v1.0):

- Globaler Hotkey + transluzentes Overlay-Fenster
- Voice-Input (faster-whisper)
- Echte Mini-Agenten mit Schedule (cron-ähnlich)
- Automatische wöchentliche Reflexion
- Decay-Logik + Merge-Vorschläge
- Auto-Linking bei neuem Eintrag
- Migration auf Tauri (native Desktop-App, < 60 MB)

### Technologie-Entscheidungen (warum genau so)

| Komponente           | Wahl                                      | Warum ich das so will                                      |
|----------------------|-------------------------------------------|-------------------------------------------------------------|
| UI                   | NiceGUI (v2.14+)                          | Sehr schnell zu prototypen, fühlt sich trotzdem app-ähnlich an |
| Vector-DB            | Chroma persistent                         | Leicht, Python-nativ, gut genug für 50k+ Einträge          |
| Embeddings           | nomic-embed-text-v1.5                     | Schnellste gute Qualität auf CPU (Sub-100 ms pro Chunk)     |
| LLM                  | Qwen2.5 3B oder Phi-4 mini (4-bit)        | Gute Balance aus Geschwindigkeit, Qualität & Größe         |
| Speicher             | SQLite + flache .md-Dateien               | Du behältst volle Kontrolle über deine Rohdaten             |
| Hotkey/Overlay       | (zukünftig) Tauri + global-shortcut       | Native App-Gefühl, echter globaler Shortcut                 |

### Installation & Start (MVP)

1. Ollama installieren & Modell ziehen
   ```bash
   ollama pull qwen2.5:3b
   # oder phi4:mini, gemma2:2b, etc.
# ECHO
