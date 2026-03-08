# tray_overlay.py – korrigiert & pynput-Version (meist ohne sudo auf Linux)

import threading
import sys
import pystray
from PIL import Image
import webview
from nicegui import ui, app
from pynput import keyboard as pynput_keyboard   # ← einheitlicher Import

# NiceGUI-Server im Hintergrund starten (ohne Browser-Fenster)
def run_nicegui():
    ui.run(
        title='Echo Overlay',
        port=9876,
        show=False,          # Kein automatisches Browser-Fenster
        reload=False,
        dark=True
    )

# Overlay-Fenster öffnen (pywebview lädt NiceGUI-Seite)
def show_overlay():
    window = webview.create_window(
        'Echo – Neuer Gedanke',
        'http://localhost:9876',
        width=600,
        height=400,
        resizable=False,
        frameless=True,           # Kein Rahmen
        easy_drag=True,
        on_top=True,
        transparent=True,         # Versuch transluzent (nicht immer perfekt)
        background_color='#111827'
    )
    # Zentriere auf Bildschirm
    screen_width = window.screen.width
    screen_height = window.screen.height
    window.move(screen_width // 2 - 300, screen_height // 2 - 200)

    # Escape zum Schließen
    def on_press(key):
        try:
            if key == pynput_keyboard.Key.esc:
                window.destroy()
        except AttributeError:
            pass

    listener = pynput_keyboard.Listener(on_press=on_press)
    listener.start()

    webview.start()

# Globaler Hotkey: Ctrl + Shift + Leertaste
HOTKEY_COMBO = {
    pynput_keyboard.Key.ctrl,
    pynput_keyboard.Key.shift,
    pynput_keyboard.KeyCode.from_char(' ')
}

current_keys = set()

def on_press(key):
    current_keys.add(key)
    if HOTKEY_COMBO.issubset(current_keys):
        print("Hotkey Ctrl+Shift+Space erkannt → Overlay öffnen")
        threading.Thread(target=show_overlay, daemon=True).start()

def on_release(key):
    if key in current_keys:
        current_keys.remove(key)

# Listener starten
listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

# System-Tray-Icon
def create_image():
    # Einfaches Platzhalter-Icon (später echtes Logo)
    return Image.new('RGB', (64, 64), color=(17, 24, 39))  # Dunkelgrau

def on_quit(icon, item):
    icon.stop()
    listener.stop()
    sys.exit(0)

menu = pystray.Menu(
    pystray.MenuItem('Beenden', on_quit)
)

icon = pystray.Icon(
    "Echo",
    create_image(),
    "Echo – Second Brain (Hotkey: Ctrl+Shift+Space)",
    menu
)

# === Hauptstart ===
if __name__ == '__main__':
    # NiceGUI in separatem Thread
    threading.Thread(target=run_nicegui, daemon=True).start()
    # Tray-Icon (blockiert)
    icon.run()
