"""Real closure notices survive worker publication and result export."""
import csv
import json

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.models.tpms_calc import compute
from sjtu_tpmshx.models.nu_correlations import warn_sco2_nu_evidence
from sjtu_tpmshx.tests.test_worker_result_handoff import (
    _configure, _wait_for, win as win,
)


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('source', ['Nu', 'D-F'])
def test_closure_warning_worker_to_export(win, monkeypatch, tmp_path, mode, source):
    cfg = _configure(win, monkeypatch, mode)
    if mode == '3d':
        cfg.geometry.Lz_m = 0.042
    args = ('Gyroid', 7, 0.6, 0.001, 350, 101325, 16, 'air')
    compute(*args)  # Warm the real public cache outside a run; do not clear it.
    pipeline = Pipeline2D if mode == '2d' else Pipeline3D

    def build(pipe):
        if source == 'Nu':
            compute(*args)  # Actual Nu source and cache replay.
        else:
            from sjtu_tpmshx.df_surrogate.experimental_correction import apply_correction
            from sjtu_tpmshx.domain.run_warnings import range_context
            with range_context(side='B', stage='df-application'):
                apply_correction('Diamond', 'water', 7., .6, 1e-8, 200., u_mps=.02)
        if mode == '3d' and source == 'Nu':
            warn_sco2_nu_evidence(side='B', stage='3D h_v property refresh',
                                  tpms_type='Gyroid', L_mm=np.array([5., 6.]),
                                  t_mm=np.array([.3, .4]), P_in=12e6)
        return {}

    monkeypatch.setattr(pipeline, 'build_fields', build)
    monkeypatch.setattr(pipeline, 'run_solvers', lambda *a: {})
    monkeypatch.setattr(pipeline, 'finalize', lambda *a: ComputeResult(
        diagnostics={'mode': mode}, fields={'Ta': np.ones(
            (2, 2) if mode == '2d' else (2, 2, 2))}))
    monkeypatch.setattr(win, '_render_compute_result', lambda: True)
    for run in range(2):
        win.run_calculation()
        _wait_for(win.compute.is_idle)
        assert not win._test_error_dialogs
        result = win.compute.last_result()
        assert any(f'[{source} extrap]' in message for message in result.warnings)
        if source == 'D-F':
            notice = next(m for m in result.warnings if '[D-F extrap]' in m)
            assert 'side=B' in notice and 'frozen sF' in notice
            assert 'approved application' in notice and '0.02' in notice
        assert sum('[sCO2 Nu evidence]' in message for message in result.warnings) == (mode == '3d' and source == 'Nu')
        if mode == '3d' and source == 'Nu':
            assert any('zoned L=[5,6] mm, t=[0.3,0.4] mm' in message for message in result.warnings)
        assert result.extrap_reasons == []
        assert win._diag_summary['warnings'] == result.warnings
        win._compute_warnings = None  # Notification lifetime is independent.
        out = tmp_path / f'{run}.csv'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(out), ''))
        win._export_results()
        assert not win._test_error_dialogs
        with out.open(encoding='utf-8', newline='') as stream:
            rows = dict(csv.reader(stream))
        assert json.loads(rows['warnings']) == result.warnings
        assert json.loads(rows['extrap_reasons']) == []
        if mode == '3d':
            with np.load(tmp_path / f'{run}_fields.npz', allow_pickle=False) as saved:
                assert json.loads(saved['warnings'].item()) == result.warnings
                assert json.loads(saved['extrap_reasons'].item()) == []
