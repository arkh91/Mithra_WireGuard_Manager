<!-- File: BUILD.md  -  Edit with: vi BUILD.md -->
# Build Mithra WireGuard Manager for Windows (1.3.5)

Same tool chain as Mithra DNS. On Windows 10/11 with Python 3.13 and Inno Setup 6:

    py -m pip install -r requirements.txt
    py main.py                         # try it (no administrator rights needed)
    py -m PyInstaller build.spec       # -> dist\MithraWireGuard\MithraWireGuard.exe
    iscc installer\installer.iss       # -> installer\Output\Mithra_WireGuard_Manager_Setup_1.3.5.exe

Version: edit the single line in `VERSION` (and `installer/version_info.txt` for the exe's file properties).

After any change to `server/install-wg-full.sh`: `python3 devtools/release.py` writes its SHA-256 into
`mwg_core/config.py`; commit that exact file to the repo's `main` (`SERVER_SCRIPT_REF`), because the install/update
commands the app shows download it from there and refuse to run it when the hash differs.

## Check a server without the window

    MithraWireGuard.exe --pull "C:\path\access.json" --out keys.json
    py main.py --pull "{\"apiUrl\":\"https://host:2053\",\"apiToken\":\"...\",\"certSha256\":\"...\"}"

Writes `{ok, route, count, verified, keys:[...]}`. Exit code 0 ok, 2 certificate mismatch, 3 other error.

## Develop and test on any OS

    python -m pytest tests                                   # parser, pinned client, old-server fallbacks, controller
    python3 devtools/test_server.py --port 9443 --keys 7     # the REAL server.js from server/install-wg-full.sh,
                                                             # behind HTTPS with a self-signed cert, fake wg/sudo/helper;
                                                             # prints both access configs (token and Outline format)
    
`test_server.py` needs node, npm and openssl. With a system proxy set, export `NO_PROXY=localhost,127.0.0.1`.

## Layout

    main.py            entry point (single instance, crash log, --pull, then the window)
    mwg_core/          access.py (config parser), wgclient.py (HTTPS client, certSha256 pinning, fallbacks),
                       controller.py (servers, keys, auto refresh, actions), store.py (settings, servers: DPAPI),
                       applog.py, config.py
    mwg_gui/           the main window, written with Qt (PySide6): window.py (sidebar, navigation, actions),
                       pages.py (server, add server, settings, logs, about), dialogs.py (key QR/config, rename, confirm),
                       widgets.py, theme.py (colours, style sheet, icons), strings.py + strings.json (English, Persian)
    assets/            logo (.ico, .png)
    server/            install-wg-full.sh (API 2.0, Outline-style routes) and wg-pull-keys.sh

The window is a normal native Windows window (no web view), so there is nothing to blink and no page that could be
replaced by another app's page. Build needs Python 3.13 and `pip install -r requirements.txt` (PySide6-Essentials).
