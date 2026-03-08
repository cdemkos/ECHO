# Echo – dein lokaler, schneller Stream-of-Thought Second Brain

Ein radikal minimalistisches, komplett lokales Notiz- & Denk-Tool, das sich wie ein stiller Gesprächspartner anfühlt – schnell, privat, ohne Ballast.

### Philosophie in einem Satz

Du tippst oder sprichst einfach drauflos → alles wird automatisch gespeichert, indiziert und semantisch durchsuchbar → das Tool denkt mit, fasst zusammen, findet Verbindungen und erinnert dich an deine eigenen Muster – ohne dass du jemals Tags, Ordner oder komplizierte Strukturen pflegen musst.

### Was Echo anders macht

- Nur ein Eingabefeld – kein "Neue Notiz"-Button, keine Sidebar, keine Datenbank-Ansichten  
- Sub-Second-Suche auch bei 20.000+ Einträgen (Hybrid BM25 + Embedding)  
- Aggressive Auto-Zusammenfassung alter Gedankenstränge  
- Mini-Agenten in natürlicher Sprache definierbar (zukünftig)  
- Keine Cloud, kein Telemetrie, keine API-Keys  
- Decay & Merge-Vorschläge (zukünftig)  
- Wöchentliche Reflexion (zukünftig)

### Aktueller Stand (MVP – v0.1)

Funktioniert bereits:

- Stream-of-Thought-Eingabe (Text)  
- Automatisches Speichern als Markdown + Embedding  
- Semantische Suche + kurze LLM-Zusammenfassung der Treffer  
- Lokale Chroma-Vector-DB + SQLite-Metadaten  
- NiceGUI-Web-Interface (browserbasiert, dark mode)

Noch nicht implementiert (Prioritäten für v0.2–v1.0):

- Globaler Hotkey + transluzentes Overlay-Fenster  
- Voice-Input (faster-whisper)  
- Echte Mini-Agenten mit Zeitplan  
- Automatische wöchentliche Reflexion  
- Decay-Logik + Merge-Vorschläge  
- Auto-Linking bei neuem Eintrag  
- Migration auf Tauri (native Desktop-App)

### Bekannte Limitationen / Anti-Features (bewusst so gewollt)

- Keine mobile App (und wahrscheinlich nie)  
- Kein Multi-User / Sync (Cloud-Sync würde Privatsphäre brechen)  
- Kein Graph-View, Kanban, Whiteboard etc.  
- LLM-Zusammenfassungen können halluzinieren oder deinen Stil noch nicht perfekt treffen  
- Keine automatische Verschlüsselung der data/-Ordner  
- Aktuell nur Text-Eingabe (Voice & Overlay kommen später)

### Technologie-Entscheidungen

| Komponente       | Wahl                              | Grund                                      |
|------------------|-----------------------------------|--------------------------------------------|
| UI               | NiceGUI                           | Sehr schnell zu prototypen, app-ähnlich    |
| Vector-DB        | Chroma persistent                 | Leicht, Python-nativ                       |
| Embeddings       | nomic-embed-text-v1.5             | Schnell & gut auf CPU                      |
| LLM              | Qwen2.5 3B oder Phi-4 mini (4-bit)| Gute Balance Geschwindigkeit/Qualität      |
| Speicher         | SQLite + flache .md-Dateien       | Volle Kontrolle über Rohdaten              |

### Installation & Start

1. **Ollama installieren** und Modell ziehen  
   https://ollama.com

   ```bash
   ollama pull qwen2.5:3b
   # oder: ollama pull phi4:mini
   # oder: ollama pull gemma2:2b
