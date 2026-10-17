"""The GUI forwards live controls through the common compute workflow."""
import pytest

from sjtu_tpmshx.controllers.compute_orchestrator import CancelToken
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.ui.mixins.run_controller import _run_compute


def test_cancel_token_cancelled_property():
    token = CancelToken()
    assert token.cancelled is False and token.is_set() is False
    token.cancel()
    assert token.cancelled is True and token.is_set() is True


@pytest.mark.parametrize('source', ['gui', 'host'])
def test_cancelled_run_skips_preparation(monkeypatch, source):
    token = CancelToken()
    if source == 'gui':
        token.cancel()
    host = RunControl(cancel_check=lambda: source == 'host')
    monkeypatch.setattr('sjtu_tpmshx.preprocess.api.prepare_case',
                        lambda *a, **k: pytest.fail('prepared cancelled run'))
    with pytest.raises(CancelledError):
        _run_compute(ComputeConfig(), token, lambda p: None, ui_hooks={}, control=host)




@pytest.mark.parametrize('nz', [1, 3])
@pytest.mark.parametrize('host_hooks', [False, True])
def test_gui_and_host_controls_reach_solver(monkeypatch, nz, host_hooks):
    gui_progress, host_progress, residuals, labels, outer = [], [], [], [], []
    gui_labels, gui_outer = [], []
    requested = [False]
    host = RunControl(backend='cpp', native_library='/host/solver',
        native_table_directory='/host/tables',
        progress=host_progress.append if host_hooks else None,
        cancel_check=lambda: requested[0],
        iteration=labels.append if host_hooks else None,
        outer_iteration=(lambda k, n: outer.append((k, n))) if host_hooks else None,
        residual=(lambda *value: residuals.append(value)) if host_hooks else None)
    token, case = CancelToken(), object()
    config = ComputeConfig()
    config.solver.Nz, config.geometry.Lz_m = nz, .03

    def prepare(actual, *, case_id):
        assert actual is config and case_id
        return case

    def solve(actual, control):
        assert actual is case
        assert control.backend == host.backend
        assert control.native_library == host.native_library
        assert control.native_table_directory == host.native_table_directory
        assert control.residual is host.residual
        assert not control.cancel_check()
        control.report_progress(50)
        control.iteration('iter 2/10')
        control.outer_iteration(2, 10)
        if control.residual:
            control.residual('A', 2, .01)
        requested[0] = True
        with pytest.raises(CancelledError):
            control.check_cancelled()
        requested[0] = False
        token.cancel()
        with pytest.raises(CancelledError):
            control.check_cancelled()
        return object()

    monkeypatch.setattr('sjtu_tpmshx.preprocess.api.prepare_case', prepare)
    monkeypatch.setattr('sjtu_tpmshx.solvers.api.run_case', solve)
    monkeypatch.setattr('sjtu_tpmshx.postprocess.api.evaluate',
                        lambda *a: pytest.fail('evaluated cancelled result'))
    with pytest.raises(CancelledError):
        _run_compute(config, token, gui_progress.append, control=host, ui_hooks={
            'iter_label_cb': gui_labels.append,
            'iter_cb': lambda k, n: gui_outer.append((k, n))})
    assert gui_progress == [20, 55, 90]
    assert gui_labels == ['iter 2/10'] and gui_outer == [(2, 10)]
    assert host_progress == ([50] if host_hooks else [])
    assert labels == (gui_labels if host_hooks else [])
    assert outer == (gui_outer if host_hooks else [])
    assert residuals == ([('A', 2, .01)] if host_hooks else [])
