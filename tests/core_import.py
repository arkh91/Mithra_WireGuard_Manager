# File: tests/core_import.py
# Test helper: a Controller wired to the mock server of test_core.py.
# Edit with: vi tests/core_import.py
from tests.test_core import CONF, Mock, _cfg                      # noqa: F401


def ctl_for(server, tmp_path, legacy=False):
    """
    ctl_for(server, tmp_path, legacy=False) -> (controller, sid, port, fingerprint)
    Usage: ctl, sid, port, fp = ctl_for(server, tmp_path, legacy=True)
    """
    from tests.core_paths import make
    port, fp = server
    Mock.mode = "old" if legacy else "new"
    ctl = make(tmp_path)
    r = ctl.add_server(_cfg(port, fp).to_json(), "Test")
    return ctl, r["sid"], port, fp
