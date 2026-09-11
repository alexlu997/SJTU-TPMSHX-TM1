"""B2 2.1a — CancelToken.cancelled property + Pipeline ui_hooks channel.

Before this fix the pipeline layer probed ``getattr(token, 'cancelled',
False)`` while CancelToken only exposed ``.is_set()`` — cancel on the
cfg path was a silent no-op (latent bug found in the B2 pre-check).
"""
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.controllers.compute_orchestrator import CancelToken
from sjtu_tpmshx.controllers.compute_pipeline import (CancelledError, Pipeline2D,
                                          Pipeline3D, pipeline_for)


def test_cancel_token_cancelled_property():
    tok = CancelToken()
    assert tok.cancelled is False and tok.is_set() is False
    tok.cancel()
    assert tok.cancelled is True and tok.is_set() is True
    tok.reset()
    assert tok.cancelled is False


def test_cancelled_token_aborts_pipeline_before_first_phase():
    tok = CancelToken()
    tok.cancel()
    pipe = Pipeline2D(ComputeConfig(), cancel_token=tok)
    with pytest.raises(CancelledError):
        pipe.run()


def test_ui_hooks_stored_and_default_empty():
    cfg = ComputeConfig()
    assert Pipeline2D(cfg).ui_hooks == {}
    hooks = {'iter_label_cb': lambda s: None}
    assert Pipeline2D(cfg, ui_hooks=hooks).ui_hooks is hooks
    cfg3d = ComputeConfig()
    cfg3d.solver.Nz = 5
    p = pipeline_for(cfg3d, ui_hooks=hooks)
    assert isinstance(p, Pipeline3D) and p.ui_hooks is hooks


def test_backend_reports_iter_label_and_progress(monkeypatch):
    from sjtu_tpmshx.domain.module_ports import RunControl
    from sjtu_tpmshx.solvers.backends.python.two_d import coupling
    from sjtu_tpmshx.tests.test_2d_warning_callers import _prepare, _stop, ThermalBoundary
    pipe, fields = _prepare(monkeypatch, legacy=True)
    monkeypatch.setattr(coupling, 'solve_full_domain', _stop)
    labels, pcts = [], []
    with pytest.raises(ThermalBoundary):
        coupling._run_solvers(pipe._parsed, fields, RunControl(
            progress=pcts.append, iteration=labels.append))
    assert labels == ['iter 1/10']
    assert pcts == [10, 12]


def test_3d_cfg_stage_wires_iter_cb(monkeypatch):
    """_run_solvers_3d_cfg must plant iter_cb as cfg['_iter_cb'] (the key
    _run_3d_stack polls each outer iteration)."""
    import sjtu_tpmshx.pipelines.stages_3d as r3
    seen = {}
    monkeypatch.setattr(r3, '_run_3d_stack',
                        lambda cfg: seen.update(cfg) or {'ok': True})
    cb = lambda k, n: None
    out = r3._run_solvers_3d_cfg({'Nx': 4}, {}, iter_cb=cb)
    assert out == {'ok': True}
    assert seen['_iter_cb'] is cb
