# tray.py – Tray-Icon + globaler Hotkey + Overlay

import threading
import sys
import pystray
from PIL import Image
import webview
from pynput import keyboard
from nicegui import ui
import asyncio

# NiceGUI im Hintergrund starten
def run_nicegui():
    ui.run(
        title='ECHO Overlay',
        port=9876,
        show=False,
        reload=False,
        dark=True
    )

# Overlay-Fenster (pywebview)
def show_overlay():
    window = webview.create_window(
        'ECHO – Neuer Gedanke',
        'http://localhost:9876',
        width=600,
        height=400,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
        background_color='#111827'
    )
    screen_width = window.screen.width
    screen_height = window.screen.height
    window.move(screen_width // 2 - 300, screen_height // 2 - 200)

    def on_key_press(key):
        if key == keyboard.Key.esc:
            window.destroy()

    listener = keyboard.Listener(on_press=on_key_press)
    listener.start()
    webview.start()

# Globaler Hotkey: Ctrl + Shift + Space
HOTKEY_COMBO = {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.KeyCode.from_char(' ')}

current_keys = set()

def on_press(key):
    current_keys.add(key)
    if HOTKEY_COMBO.issubset(current_keys):
        threading.Thread(target=show_overlay, daemon=True).start()

def on_release(key):
    if key in current_keys:
        current_keys.remove(key)

listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

# Tray-Icon
def create_image():
    return Image.new('RGB', (64, 64), color=(17, 24, 39))

def on_quit(icon, item):
    icon.stop()
    listener.stop()
    sys.exit(0)

menu = pystray.Menu(
    pystray.MenuItem('Beenden', on_quit)
)

icon = pystray.Icon(
    "ECHO",
    create_image(),
    "ECHO – Second Brain (Ctrl+Shift+Space)",
    menu
)

if __name__ == '__main__':
    threading.Thread(target=run_nicegui, daemon=True).start()
    icon.run()
