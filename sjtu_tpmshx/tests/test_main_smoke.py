"""GUI smoke test for B (main refactor).

Verifies that Main_Menu can be instantiated and its UI built without
exceptions. Does NOT check specific widget behavior — just 'doesn't crash'.
Runs with QT_QPA_PLATFORM=offscreen so it works headless.

Run with:
    python -m pytest sjtu_tpmshx/tests/test_main_smoke.py
"""
import sys
import os

import pytest

# Qt requires a platform plugin; offscreen works on both headless and desktop
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path, monkeypatch):
    """Main_Menu.closeEvent auto-saves the session (main.py); without this
    redirect the w.close() below writes the REAL sjtu_tpmshx/.last_session.json
    and clobbers the user's saved GUI session (bug found 2026-07-13)."""
    import sjtu_tpmshx.controllers.session_manager as sm_mod
    orig_init = sm_mod.SessionManager.__init__

    def _init(self, base_dir=None, parent=None):
        orig_init(self, base_dir=base_dir if base_dir is not None else tmp_path,
                  parent=parent)

    monkeypatch.setattr(sm_mod.SessionManager, '__init__', _init)


def test_main_menu_startup():
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    from sjtu_tpmshx.main import Main_Menu
    w = Main_Menu()
    # Key widgets that every refactor step must preserve
    assert hasattr(w, 'combo_tpms'), "combo_tpms missing after refactor"
    assert hasattr(w, 'le_L'), "le_L missing after refactor"
    assert hasattr(w, 'le_H'), "le_H missing after refactor"
    assert hasattr(w, 'canvas_temp'), "canvas_temp missing after refactor"
    assert hasattr(w, 'progress'), "progress bar missing"
    w.close()
    print("test_main_menu_startup PASS")


def test_cpu_cores_spinbox_sets_threads():
    """The 'CPU cores (energy ‖)' spinbox drives solvers.threads at runtime."""
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    from sjtu_tpmshx.main import Main_Menu
    import sjtu_tpmshx.solvers.threads as th
    w = Main_Menu()
    assert hasattr(w, 'spin_cpu_cores'), "CPU cores spinbox missing"
    mx = th.max_threads()
    assert w.spin_cpu_cores.maximum() == mx
    if mx > 1:                               # need a real change to fire the signal
        target = mx // 2
        w.spin_cpu_cores.setValue(target)
        assert th.get_solver_threads() == target, \
            "spinbox change did not apply the thread count"
        w.spin_cpu_cores.setValue(mx)
        assert th.get_solver_threads() == mx
    w.close()
    th.set_solver_threads(mx)
    print("test_cpu_cores_spinbox_sets_threads PASS")
