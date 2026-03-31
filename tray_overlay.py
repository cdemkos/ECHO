# tray_overlay.py – System-Tray-Icon + globaler Hotkey + Overlay-Fenster
#
# Korrekturen:
#   - NiceGUI läuft in eigenem Thread mit korrektem Event-Loop
#   - Overlay-Fenster wartet auf Server-Start bevor es öffnet
#   - Sauberes Shutdown: icon.stop() → listener.stop() → sys.exit()
#   - Hotkey-Erkennung robuster (ctrl_l + ctrl_r beide erkannt)

import sys
import threading
import time

import pystray
import webview
from PIL import Image
from pynput import keyboard as pynput_keyboard


NICEGUI_PORT = 9876
NICEGUI_URL  = f"http://localhost:{NICEGUI_PORT}"


# ── NiceGUI-Server ────────────────────────────────────────────────────────────

def run_nicegui() -> None:
    """NiceGUI im Hintergrund-Thread starten."""
    # Import erst hier damit der Haupt-Thread nicht blockiert
    from nicegui import ui

    # Overlay-Seite (kompakte Eingabe)
    @ui.page("/overlay")
    async def overlay_page():
        from datetime import datetime
        from pathlib import Path
        import uuid
        from database import NoteDB
        from embedder import get_embedding

        db = NoteDB()

        ui.label("ECHO").classes("text-3xl font-black text-indigo-400 mb-4")
        inp = ui.textarea(placeholder="Gedanke…").props("autogrow outlined").classes(
            "w-full bg-slate-900 text-white"
        )

        async def save():
            text = inp.value.strip()
            if not text:
                return
            ts      = datetime.now().isoformat()
            note_id = str(uuid.uuid4())[:12]
            safe_ts = ts.replace(":", "-")
            fp      = Path("data/notes") / f"{safe_ts}_{note_id}.md"
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(f"# {ts}\n\n{text}", encoding="utf-8")
            emb = get_embedding(text)
            db.add_note(note_id, ts, text, str(fp), emb)
            ui.notify("Gespeichert ✓", type="positive")
            inp.set_value("")

        inp.on("keydown.enter", save)
        ui.button("Speichern", on_click=save).props("unelevated color=green-7")
        ui.button("Schließen", on_click=lambda: ui.run_javascript("window.close()")) \
            .props("unelevated color=grey-8")

    ui.run(
        title="ECHO Overlay",
        port=NICEGUI_PORT,
        show=False,
        reload=False,
        dark=True,
    )


def wait_for_server(timeout: int = 15) -> bool:
    """Wartet bis NiceGUI bereit ist."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{NICEGUI_URL}/overlay", timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


# ── Overlay-Fenster ───────────────────────────────────────────────────────────

def show_overlay() -> None:
    """Öffnet ein schwebendes pywebview-Fenster über der aktuellen App."""
    if not wait_for_server():
        print("ECHO: Server nicht erreichbar, Overlay wird nicht geöffnet.")
        return

    window = webview.create_window(
        "ECHO – Neuer Gedanke",
        f"{NICEGUI_URL}/overlay",
        width=580,
        height=360,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        background_color="#111827",
    )

    # ESC schließt das Overlay
    def on_press(key):
        if key == pynput_keyboard.Key.esc:
            window.destroy()

    esc_listener = pynput_keyboard.Listener(on_press=on_press)
    esc_listener.start()
    webview.start()
    esc_listener.stop()


# ── Globaler Hotkey ───────────────────────────────────────────────────────────

# Erkennt sowohl linke als auch rechte Ctrl/Shift-Tasten
CTRL_KEYS  = {pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l, pynput_keyboard.Key.ctrl_r}
SHIFT_KEYS = {pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l, pynput_keyboard.Key.shift_r}
SPACE_KEY  = pynput_keyboard.KeyCode.from_char(" ")

pressed: set = set()
overlay_open = threading.Event()


def on_press(key) -> None:
    pressed.add(key)

    has_ctrl  = bool(pressed & CTRL_KEYS)
    has_shift = bool(pressed & SHIFT_KEYS)
    has_space = SPACE_KEY in pressed

    if has_ctrl and has_shift and has_space and not overlay_open.is_set():
        overlay_open.set()
        def _open():
            show_overlay()
            overlay_open.clear()
        threading.Thread(target=_open, daemon=True).start()


def on_release(key) -> None:
    pressed.discard(key)


hotkey_listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)


# ── Tray-Icon ─────────────────────────────────────────────────────────────────

def create_icon_image() -> Image.Image:
    """Einfaches Platzhalter-Icon (64×64, dunkelblau)."""
    img = Image.new("RGB", (64, 64), color=(67, 56, 202))  # indigo-700
    return img


def on_quit(icon, _item) -> None:
    icon.stop()
    hotkey_listener.stop()
    sys.exit(0)


tray_menu = pystray.Menu(
    pystray.MenuItem("ECHO öffnen", lambda: __import__("webbrowser").open(NICEGUI_URL)),
    pystray.MenuItem("Beenden", on_quit),
)

tray_icon = pystray.Icon(
    "ECHO",
    create_icon_image(),
    "ECHO Second Brain  (Ctrl+Shift+Space → Overlay)",
    tray_menu,
)


# ── Hauptstart ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 1. NiceGUI in eigenem Thread
    threading.Thread(target=run_nicegui, daemon=True).start()

    # 2. Globaler Hotkey-Listener
    hotkey_listener.start()

    # 3. Tray-Icon (blockiert den Haupt-Thread)
    tray_icon.run()
