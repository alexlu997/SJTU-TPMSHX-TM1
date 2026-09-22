"""3D publication keeps valid solver data when rendering fails.

The view-readiness flag must be separate from the ResultCache presence
bridge: clearing _has_results_3d would destroy the exportable ComputeResult.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from sjtu_tpmshx.controllers.result_cache import ResultCache
from sjtu_tpmshx.ui.mixins.run_controller import RunControllerMixin
from sjtu_tpmshx.ui.mixins.run_results import RunResultsMixin


# ── ultra-lite Main_Menu stub ───────────────────────────────────────


class _ComputeStub:
    """Tiny ``self.compute`` stub for the orchestrator-finished slot."""

    def __init__(self, mode='3d'):
        self._mode = mode

    def current_mode(self):
        return self._mode

    def last_log(self):
        return ''

    def last_elapsed(self):
        return 0.


class _StatusBarStub:
    def showMessage(self, *_a, **_kw):
        pass


class _DummyWindow(RunControllerMixin, RunResultsMixin):
    """Lite ``Main_Menu`` stand-in carrying just the attrs the 3D branch
    of ``_on_orch_finished`` touches."""

    def __init__(self):
        self.compute = _ComputeStub()
        self.btn_compute = MagicMock()
        self.btn_export = MagicMock()
        from sjtu_tpmshx.domain.compute_result import ComputeResult
        self.cache = ResultCache()
        self.cache.set_result('3d', ComputeResult(Q_W=100.0, dP_A_Pa=50.0,
                                                diagnostics={'mode': '3d'}))
        self._rendered_3d_slices = False
        self._compute_running = True
        self._last_solve_log = ''
        self._compute_3d_watchdog = None

    def _end_compute_ui(self, *, success):
        self._end_compute_ui_success = success
        self._compute_running = False

    def _push_recent_run(self):
        pass

    def _update_tab_visibility(self):
        pass

    def _switch_tab(self, _name):
        pass

    def _refresh_status_bar(self):
        pass

    def _stamp_result_provenance(self, _elapsed):
        pass

    def statusBar(self):
        return _StatusBarStub()


# ── tests ───────────────────────────────────────────────────────────


def _run_finished(win, finalize_behavior):
    """Drive Main_Menu._on_orch_finished with finalize_plots_3d patched."""
    import sjtu_tpmshx.main as main
    if isinstance(finalize_behavior, BaseException):
        def _fb(_w):
            raise finalize_behavior
        patch_fin = patch('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d', _fb)
    else:
        patch_fin = patch('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d',
                          return_value=finalize_behavior)
    with patch_fin:
        main.Main_Menu._on_orch_finished(win, win.cache.get_result('3d'))
    assert not win._compute_running


def test_3d_finalize_crash_gates_tab_off_but_keeps_result():
    """When ``finalize_plots_3d`` raises, the 3D View tab must be gated off
    (``_3d_view_ready`` False) — but the valid solver result must SURVIVE so it
    stays exportable (U1: was destroyed via the result-nulling bridge)."""
    win = _DummyWindow()
    assert win.cache.get_result('3d') is not None and win.cache.has_results('3d') is True

    _run_finished(win, RuntimeError("PyVista context lost"))

    # Tab gated off (panel never populated) — the H5 invariant, now carried by
    # the dedicated flag instead of the result-nulling _has_results_3d.
    assert getattr(win, '_3d_view_ready', False) is False
    # U1: result preserved — Export / status read _result_3d.
    assert win.cache.get_result('3d') is not None, "finalize crash destroyed the 3D result"


def test_3d_finalize_success_marks_view_ready_and_keeps_result():
    """Happy path: finalize returns True → tab ready + result present."""
    win = _DummyWindow()

    _run_finished(win, True)

    assert getattr(win, '_3d_view_ready', False) is True
    assert win.cache.get_result('3d') is not None


def test_3d_soft_vis_fail_preserves_result_for_export():
    """U1 (audit 2026-06-28): on the REAL ResultCache bridge a soft viz failure
    (finalize returns False — offscreen/headless/GL/TPMSHX_DISABLE_3D_PANEL)
    must NOT destroy the freshly-computed 3D result. The valid Q/dP must survive
    so the 'visualisation failed' status branch + Export work; tab-readiness is
    carried by ``_3d_view_ready`` instead of the result-nulling flag."""
    win = _DummyWindow()
    assert win.cache.get_result('3d') is not None

    _run_finished(win, False)

    # The bug: line 566 wrote _has_results_3d=False -> bridge nulled _result_3d.
    assert win.cache.get_result('3d') is not None, "soft viz-fail destroyed the 3D result"
    # Tab gated off so the user is not routed to a blank canvas.
    assert getattr(win, '_3d_view_ready', False) is False
