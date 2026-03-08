<div align="center">

# ECHO  
**Dein lokaler, datenschutzfreundlicher Stream-of-Thought Second Brain**

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![NiceGUI](https://img.shields.io/badge/UI-NiceGUI-00d084?style=for-the-badge&logo=react&logoColor=white)](https://nicegui.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Repo Size](https://img.shields.io/github/repo-size/cdemkos/ECHO?style=for-the-badge&color=orange)](https://github.com/cdemkos/ECHO)

</div>

<br>

**ECHO** ist ein komplett lokales, offline-fähiges Second-Brain-Tool, das deinen Gedankengängen folgt – schnell, privat und ohne Cloud-Zwang.

- Sofortiges Stream-of-Thought-Eingabefeld mit Auto-Save  
- Semantische Suche + LLM-Zusammenfassung (Ollama lokal)  
- Automatische wöchentliche Reflexion & Tageszusammenfassung  
- Auto-Linking ähnlicher Gedanken + Merge-Funktion  
- Edit / Delete / Tags / Decay & Archivierung  
- Export als ZIP (Notizen + DB + Embeddings)  
- Tray-Icon + globaler Hotkey (zukünftig)

<br>

## Inhaltsverzeichnis

- [Features](#-features)
- [Screenshots](#-screenshots)
- [Installation](#-installation)
- [Erster Start & Tipps](#-erster-start--tipps)
- [Verwendung](#-verwendung)
- [Entwicklungsstand & Roadmap](#-entwicklungsstand--roadmap)
- [Technologie-Stack](#-technologie-stack)
- [Lizenz](#-lizenz)

## ✨ Features

| Feature                              | Status | Beschreibung                                                                                   |
|:-------------------------------------|:------:|:-----------------------------------------------------------------------------------------------|
| Stream-of-Thought Eingabe            |   ✓    | Großes Textfeld mit Auto-Save nach 8 s Inaktivität                                             |
| Semantische Suche + LLM-Zusammenfassung |   ✓    | `nomic-embed-text-v1.5` + Ollama (z. B. qwen2.5:3b)                                            |
| Manuelle & automatische Reflexion    |   ✓    | Wöchentliche Reflexion (manuell + auto beim Start prüfen)                                      |
| Automatische Tageszusammenfassung    |   ✓    | Letzte 24 h – täglich beim Start generiert, wenn nicht vorhanden                               |
| Auto-Linking & Merge                 |   ✓    | Ähnliche Gedanken (Cosine > 0.75) → Dialog → Merge (alte → archive/)                           |
| Edit & Delete in Suchergebnissen     |   ✓    | Direkt aus der Suche bearbeiten oder löschen                                                   |
| Tags per LLM                         |   ✓    | Beim Speichern 2–4 Tags automatisch generiert und gespeichert                                 |
| Decay & Archivierung                 |   ✓    | >90 Tage alte, nicht referenzierte Notizen → automatisch archivieren                          |
| ZIP-Export                           |   ✓    | Alle Notizen + DB + Chroma in einer Datei herunterladen                                        |
| Tray-Icon + globaler Hotkey          |   ⚙     | (in Vorbereitung) Ctrl+Shift+Space → Overlay-Fenster                                           |
| Voice-Input                          |   ⚙     | (geplant) Lokales Whisper → Text live einfügen                                                 |

<br>

## 📸 Screenshots

### Hauptansicht

![Hauptansicht](https://via.placeholder.com/1200x700/111827/ffffff?text=ECHO+Hauptansicht+–+dunkles+Theme)  
*(Eingabefeld, Suche, Schnellzugriff-Buttons)*

### Reflexions-Dialog

![Reflexion](https://via.placeholder.com/800x500/111827/ffffff?text=Wöchentliche+Reflexion+Dialog)  

### Auto-Linking + Merge

![Auto-Linking](https://via.placeholder.com/800x500/111827/ffffff?text=Auto-Linking+Merge+Dialog)  

*(Platzhalter – ersetze später durch echte Screenshots aus deinem Browser)*

<br>

## 🚀 Installation

1. **Voraussetzungen**

   - Python 3.11 oder 3.12 (3.10 geht auch, 3.13 noch nicht getestet)
   - Ollama installiert & läuft (`ollama serve`)
   - Empfohlenes Ollama-Modell: `ollama pull qwen2.5:3b`

2. **Repository klonen**


git clone https://github.com/cdemkos/ECHO.git

cd ECHO
python -m venv venv
source venv/bin/activate      # Linux/macOS

# Windows: venv\Scripts\activate

pip install -r requirements.txt
Embedding-Modell einmalig vorladen (wichtig – verhindert langen ersten Start)Bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)"
Starten

python main.py

Ollama läuft nicht?
ollama serve & ollama pull qwen2.5:3b

Zu wenig RAM?
→ Verwende ein kleineres Ollama-Modell, z. B. ollama pull phi4:mini
Dunkles Theme gefällt nicht?
→ Entferne dark=True in ui.run() → NiceGUI wechselt automatisch zum System-Theme



🛠 Verwendung

Gedanken festhalten → Textfeld → Enter oder 8 Sekunden warten
Suche → semantisch → Zusammenfassung durch LLM
Reflexion → Button „Wöchentliche Reflexion jetzt“
Auto-Linking → Bei ähnlichen Gedanken öffnet sich Merge-Dialog
Bearbeiten/Löschen → In Suchergebnissen pro Eintrag
Export → Button „Alles exportieren (ZIP)“



🗺 Entwicklungsstand & Roadmap
Aktuell (März 2026)

Stabile Kernfunktionen
Automatische Tages- & Wochenreflexion
Decay & Archivierung
Edit/Delete/Tags

Geplant / in Arbeit

 Tray-Icon + globaler Hotkey (Ctrl+Shift+Space → Overlay)
 Voice-Input (lokales Whisper)
 Mini-Agenten (regelbasierte Automatisierungen)
 Graph-View der Gedankenverbindungen
 Automatische tägliche Backups (lokal / Cloud)
 Mobile-freundliches Design / PWA



🛠 Technologie-Stack

Frontend → NiceGUI (Python-basiertes UI)
Embedding → nomic-embed-text-v1.5 (sentence-transformers)
LLM → Ollama (lokal, z. B. qwen2.5:3b)
Vektor-DB → Chroma (persistent)
Speicher → Markdown-Dateien + SQLite Metadaten
