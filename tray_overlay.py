# tray_overlay.py
# Startet NiceGUI im Hintergrund + Tray-Icon + globaler Hotkey → Overlay-Popup

import threading
import sys
import pystray
from PIL import Image
import webview
from nicegui import ui, app
import keyboard  # oder pynput.keyboard

# === NiceGUI im Hintergrund starten ===
def run_nicegui():
    # Starte NiceGUI-Server (ohne Browser-Öffnen)
    ui.run(
        title='Echo Overlay',
        port=9876,
        show=False,          # Kein automatisches Browser-Fenster
        reload=False,
        dark=True
    )

# === Overlay-Fenster mit pywebview ===
def show_overlay():
    window = webview.create_window(
        'Echo – Neuer Gedanke',
        'http://localhost:9876',  # unsere NiceGUI-Seite
        width=600,
        height=400,
        resizable=False,
        frameless=True,           # Kein Fensterrahmen
        easy_drag=True,
        on_top=True,
        transparent=True,         # Versuch transluzent (nicht perfekt)
        background_color='#111827'  # Dunkel passend zu NiceGUI
    )
    # Zentriere Fenster
    screen_width = window.screen.width
    screen_height = window.screen.height
    window.move(screen_width // 2 - 300, screen_height // 2 - 200)

    # Optional: Schließen bei Escape
    def on_key(event):
        if event.key == 'Escape':
            window.destroy()

    window.events.closed += lambda: print("Overlay geschlossen")
    webview.start(on_key)

# === Globaler Hotkey ===
HOTKEY = 'ctrl+shift+space'   # Änderbar

def on_hotkey():
    print(f"Hotkey {HOTKEY} gedrückt → Overlay öffnen")
    # Thread-sicher aufrufen
    threading.Thread(target=show_overlay, daemon=True).start()

keyboard.add_hotkey(HOTKEY, on_hotkey)

# === System-Tray-Icon ===
def create_image():
    # Einfaches Icon (später echtes Echo-Logo)
    image = Image.new('RGB', (64, 64), color=(17, 24, 39))  # Dunkelgrau
    return image

def on_quit(icon, item):
    icon.stop()
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

# === Start ===
if __name__ == '__main__':
    # NiceGUI in separatem Thread starten
    threading.Thread(target=run_nicegui, daemon=True).start()

    # Tray-Icon starten (blockierend)
    icon.run()
