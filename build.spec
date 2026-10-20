# File: build.spec
# PyInstaller recipe. Usage: pyinstaller build.spec   (on Windows) -> dist\MithraWireGuard\MithraWireGuard.exe
# Edit with: vi build.spec
from pathlib import Path

ROOT = Path(SPECPATH)
datas = [(str(ROOT / "assets"), "assets"), (str(ROOT / "mwg_gui" / "strings.json"), "mwg_gui"), (str(ROOT / "VERSION"), ".")]

# Qt plugins (the "windows" platform plugin is required to open any window). PyInstaller normally finds them by itself;
# adding them explicitly keeps the build correct on every machine.
import importlib.util
_pyside = Path(importlib.util.find_spec("PySide6").submodule_search_locations[0])
for _sub in ("platforms", "styles", "imageformats", "iconengines"):
    if (_pyside / "plugins" / _sub).is_dir():
        datas.append((str(_pyside / "plugins" / _sub), "PySide6/plugins/" + _sub))

a = Analysis([str(ROOT / "main.py")], pathex=[str(ROOT)], datas=datas,
             hiddenimports=["mwg_core._vendor.segno", "PySide6.QtSvg"],
             excludes=["tkinter", "devtools", "tests", "numpy", "PIL", "webview", "PySide6.QtQuick", "PySide6.QtQml",
                       "PySide6.QtPdf", "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtDBus"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MithraWireGuard", console=False,
          icon=str(ROOT / "assets" / "mithracorp_logo.ico"), version=str(ROOT / "installer" / "version_info.txt"))
coll = COLLECT(exe, a.binaries, a.datas, name="MithraWireGuard")
