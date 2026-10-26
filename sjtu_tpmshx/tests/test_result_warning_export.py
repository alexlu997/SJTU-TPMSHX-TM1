"""Real closure notices survive worker publication and result export."""
import csv
import json

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog

from sjtu_tpmshx.models.tpms_calc import compute
from sjtu_tpmshx.models.nu_correlations import warn_sco2_nu_evidence
from sjtu_tpmshx.tests.gui_worker_support import (
    _configure, _stub_stages, _wait_for, win as win,
)


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('source', ['Nu', 'D-F'])
def test_closure_warning_worker_to_export(win, monkeypatch, tmp_path, mode, source):
    cfg = _configure(win, monkeypatch, mode)
    if mode == '3d':
        cfg.geometry.Lz_m = 0.042
    args = ('Gyroid', 7, 0.6, 0.001, 350, 101325, 16, 'air')
    compute(*args)  # Warm the real public cache outside a run; do not clear it.

    def build(config, *, case_id):
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

    _stub_stages(monkeypatch, mode, build)
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
        assert win._result_summary()['warnings'] == result.warnings
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


def test_converged_outside_range_result_keeps_design_rejection_in_gui_and_export(win, monkeypatch, tmp_path):
    from dataclasses import replace
    from sjtu_tpmshx.controllers.module_adapter import to_compute_result
    from sjtu_tpmshx.domain.portable_data import mutable_data
    from sjtu_tpmshx.postprocess.api import evaluate_qualification
    from sjtu_tpmshx.tests.test_module_result_mapping import _synthetic_results
    from sjtu_tpmshx.tests.postprocess_tm1.test_applicability import result_with_evidence
    native, performance = _synthetic_results()
    evidence = mutable_data(result_with_evidence().metadata['applicability_evidence'])
    evidence['final'][0]['minimum'][0] = 89.
    native = replace(native, metadata=dict(native.metadata, applicability_evidence=evidence),
        fields={**native.fields, **{name: np.full_like(native.fields[name + '_display'], 330.)
                                   for name in ('Ta', 'Tb', 'Ts')}})
    quality = evaluate_qualification(native, performance.metrics)
    performance = replace(performance, qualification=quality)
    result = to_compute_result(native, performance)
    assert result.converged and result.metadata['qualification']['design']['eligible'] is False
    win.write_result(result)
    win._update_result_summary()
    assert win._sb_labels['design'].text().startswith('未通过 ⚠：')
    assert '超范围' in win._sb_labels['design'].toolTip()
    assert '允许' in win._diag_summary_text()
    assert win._sb_labels['extrap'].text() == '未通过 ⚠'
    assert '设计资格：不合格' in win._diag_summary_text()
    path = tmp_path / 'range-rejected.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), 'CSV'))
    win._export_results()
    with path.open(encoding='utf-8', newline='') as stream:
        rows = dict(csv.reader(stream))
    archived = json.loads(rows['metadata'])['qualification']
    assert archived['convergence']['passed'] is True
    assert archived['applicability']['passed'] is False
    assert archived['design']['eligible'] is False
    assert not win._test_error_dialogs
