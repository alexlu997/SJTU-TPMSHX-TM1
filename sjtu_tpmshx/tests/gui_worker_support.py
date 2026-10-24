"""Function-scoped worker test window and its existing lifecycle helpers."""
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid

from sjtu_tpmshx.domain.compute_config import ComputeConfig, SolverConfig


def _wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.001)
    assert predicate(), 'Qt worker/lifecycle did not finish'


@pytest.fixture
def win(tmp_path, monkeypatch):
    from sjtu_tpmshx.controllers.session_manager import SessionManager
    from sjtu_tpmshx.main import Main_Menu

    original_init = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
                        lambda self, parent=None: original_init(
                            self, base_dir=tmp_path, parent=parent))
    monkeypatch.setenv('TPMSHX_DISABLE_3D_PANEL', '1')
    window = Main_Menu()
    monkeypatch.setattr(window, '_validate_inputs_preflight', lambda: True)
    monkeypatch.setattr(window, '_preflight_grid', lambda config: True)
    monkeypatch.setattr(window, '_preflight_3d', lambda config: (True, 8, '2×2×2'))
    monkeypatch.setattr(window, '_finalize_plots', lambda: None)
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d',
                        lambda _window: False)
    window._test_error_dialogs = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *args: window._test_error_dialogs.append(args))
    yield window
    if isValid(window):
        window.compute.cancel()
        _wait_for(window.compute.is_idle)
        # Some tests intentionally leave invalid drafts (e.g. a short Pareto
        # vector). Exercise saving, but discard those drafts during cleanup;
        # close-confirmation behavior itself is asserted inside the tests.
        with monkeypatch.context() as cleanup:
            cleanup.setattr(QMessageBox, 'warning',
                            lambda *args: QMessageBox.StandardButton.Discard)
            window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _configure(win, monkeypatch, mode):
    cfg = ComputeConfig(solver=SolverConfig(Nz=2 if mode == '3d' else 1))
    win.combo_dim.setCurrentIndex(1 if mode == '3d' else 0)
    monkeypatch.setattr('sjtu_tpmshx.ui.window_config.config_from_window',
                        lambda *args, **kwargs: cfg)
    return cfg



def _stub_stages(monkeypatch, mode, prepare):
    """Keep the real workflow and display mapping; replace numerical stages."""
    from sjtu_tpmshx.tests.test_module_result_mapping import _synthetic_results
    from sjtu_tpmshx.workflows.compute import compute
    native, performance = _synthetic_results(2 if mode == '2d' else 3)
    monkeypatch.setattr('sjtu_tpmshx.workflows.recovery.compute_run',
                        lambda config, directory, *, control, progress_cb, **kwargs:
                        compute(config, control=control, progress_cb=progress_cb))
    monkeypatch.setattr('sjtu_tpmshx.preprocess.api.prepare_case', prepare)
    monkeypatch.setattr('sjtu_tpmshx.solvers.api.run_case', lambda *a: native)
    monkeypatch.setattr('sjtu_tpmshx.postprocess.api.evaluate', lambda *a: performance)


def _stub_compute_result(monkeypatch, execute):
    """Return a display fixture through the current saved-run boundary."""
    def run(config, directory, *, control, progress_cb, **kwargs):
        return None, execute(config, control=control, progress_cb=progress_cb), None
    monkeypatch.setattr('sjtu_tpmshx.workflows.recovery.compute_run', run)
    monkeypatch.setattr('sjtu_tpmshx.controllers.module_adapter.to_compute_result',
                        lambda display, performance: display)
