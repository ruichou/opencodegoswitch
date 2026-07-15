"""Update desktop shortcut to point to .bat"""
import os, winshell
from pathlib import Path

desktop = Path(winshell.desktop())
bat_path = Path(__file__).parent / "start_gui.bat"
shortcut_path = desktop / "OpenCode Go Switch.lnk"

if shortcut_path.exists():
    os.remove(shortcut_path)

with winshell.shortcut(str(shortcut_path)) as sc:
    sc.path = str(bat_path)
    sc.working_directory = str(bat_path.parent)
    sc.description = "OpenCode Go Switch - AI Model Proxy"
    sc.icon_location = (str(Path(__file__).parent / "icon.ico"), 0)

print(f"Done: {shortcut_path}")
