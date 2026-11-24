"""Gera o PhoneMouse.exe (PyInstaller) e o instalador PhoneMouse-Setup (Inno Setup).

Uso (no Windows, na pasta do projeto):  py build\\build.py
Requisitos: py -m pip install -r requirements.txt pyinstaller  +  Inno Setup 6 (winget install JRSoftware.InnoSetup)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "out"
sys.path.insert(0, str(ROOT))

import server  # noqa: E402  (gera os ícones)

server.ensure_icons()

print("== PyInstaller ==")
subprocess.run([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noconsole", "--onedir",
    "--name", "PhoneMouse", "--icon", str(server.ICON_ICO),
    "--add-data", f"{ROOT / 'static' / 'index.html'}{os.pathsep}static",
    "--hidden-import", "pystray._win32",
    "--distpath", str(OUT / "dist"), "--workpath", str(OUT / "work"), "--specpath", str(OUT),
    str(ROOT / "server.py"),
], check=True)

print("== Inno Setup ==")
cands = [shutil.which("ISCC"),
         Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
         Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
         Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"]
iscc = next((str(c) for c in cands if c and Path(c).exists()), None)
if not iscc:
    sys.exit("Inno Setup não encontrado (winget install JRSoftware.InnoSetup). O .exe está em build\\out\\dist.")
subprocess.run([iscc, str(ROOT / "build" / "installer.iss")], check=True)
print("Instalador em:", OUT)
