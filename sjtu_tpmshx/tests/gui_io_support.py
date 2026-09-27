"""Module-scoped IO test window with isolated session persistence."""
import pytest


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(
        ['pytest', '-platform', 'offscreen'])
    # Redirect SessionManager's default base_dir before Main_Menu is built:
    # closeEvent auto-saves the session, and without this the teardown
    # w.close() writes the REAL sjtu_tpmshx/.last_session.json (bug found
    # 2026-07-13). Module-scoped fixture, so patch manually (monkeypatch
    # fixture is function-scoped) and undo after close.
    from _pytest.monkeypatch import MonkeyPatch
    import sjtu_tpmshx.controllers.session_manager as sm_mod
    mp = MonkeyPatch()
    session_dir = tmp_path_factory.mktemp('session')
    orig_init = sm_mod.SessionManager.__init__

    def _init(self, base_dir=None, parent=None):
        orig_init(self, base_dir=base_dir if base_dir is not None else session_dir,
                  parent=parent)

    mp.setattr(sm_mod.SessionManager, '__init__', _init)
    import sjtu_tpmshx.main as main_mod
    w = main_mod.Main_Menu()
    yield w
    w.close()
    w.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    mp.undo()
