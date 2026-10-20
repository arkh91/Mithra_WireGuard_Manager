# File: tests/core_paths.py
# Test helper: builds a Controller that keeps its files in a temporary folder.
# Edit with: vi tests/core_paths.py
def make(tmp_path):
    """
    make(tmp_path) -> Controller
    Usage: ctl = make(tmp_path)
    """
    from mwg_core.applog import AppLog
    from mwg_core.controller import Controller
    from mwg_core.store import ServerStore, Settings
    return Controller(ServerStore(tmp_path / "s.json"), Settings(tmp_path / "set.json"), AppLog(to_file=False))
