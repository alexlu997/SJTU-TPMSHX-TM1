"""Real closure notices survive worker publication and result export."""
import csv
import json

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog

from sjtu_tpmshx.applications.gui.ui.plot_2d_results import finalize_plots as _real_finalize_plots
from sjtu_tpmshx.applications.gui.ui.plot_3d_results import (
    _render_2d_slices_from_3d as _real_render_2d_slices_from_3d,
    finalize_plots_3d as _real_finalize_plots_3d,
)
from sjtu_tpmshx.physical_models.tpms_calc import compute
from sjtu_tpmshx.physical_models.nu_correlations import warn_sco2_nu_evidence
from tests.python.gui_worker_support import (
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
            from sjtu_tpmshx.physical_models.df_surrogate.experimental_correction import apply_correction
            from sjtu_tpmshx.run_control.run_warnings import range_context
            with range_context(side='B', stage='df-application'):
                apply_correction('Diamond', 'water', 7., .6, 1e-8, 200., u_mps=.02)
        if mode == '3d' and source == 'Nu':
            warn_sco2_nu_evidence(side='B', stage='3D h_v property refresh',
                                  tpms_type='Gyroid', L_mm=np.array([5., 6.]),
                                  t_mm=np.array([.3, .4]), P_in=12e6)
        return {}

    _stub_stages(monkeypatch, mode, build)
    monkeypatch.setattr(win.results, 'render', lambda mode: True)
    for run in range(2):
        win.single_run.submit()
        _wait_for(win.single_run.is_idle)
        assert not win._test_error_dialogs
        result = win.single_run.compute.last_result()
        assert any(f'[{source} extrap]' in message for message in result.warnings)
        if source == 'D-F':
            notice = next(m for m in result.warnings if '[D-F extrap]' in m)
            assert 'side=B' in notice and 'frozen sF' in notice
            assert 'approved application' in notice and '0.02' in notice
        assert sum('[sCO2 Nu evidence]' in message for message in result.warnings) == (mode == '3d' and source == 'Nu')
        if mode == '3d' and source == 'Nu':
            assert any('zoned L=[5,6] mm, t=[0.3,0.4] mm' in message for message in result.warnings)
        assert result.extrap_reasons == []
        assert win.results.summary()['warnings'] == result.warnings
        out = tmp_path / f'{run}.csv'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(out), ''))
        win.result_export.export_results()
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
    from sjtu_tpmshx.applications.result_adapter import to_compute_result
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from sjtu_tpmshx.postprocess.api import evaluate_qualification
    from tests.python.test_module_result_mapping import _synthetic_results
    from tests.python.postprocess_tm1.test_applicability import result_with_evidence
    native, performance = _synthetic_results()
    evidence = mutable_data(result_with_evidence().metadata['applicability_evidence'])
    evidence['final'][0]['minimum'][0] = 89.
    native = replace(native, metadata=dict(native.metadata, applicability_evidence=evidence),
        fields={**native.fields, **{name: np.full_like(native.fields[name], 330.)
                                   for name in ('Ta', 'Tb', 'Ts')}})
    quality = evaluate_qualification(native, performance.metrics)
    performance = replace(performance, qualification=quality)
    result = to_compute_result(native, performance)
    assert result.converged and result.metadata['qualification']['design']['eligible'] is False
    win.results.publish(result)
    win.results.refresh_summary()
    assert win._sb_labels['design'].text() == '未通过 ⚠'
    assert win._sb_labels['design_reason'].text()
    assert '超范围' in win._sb_labels['design'].toolTip()
    assert '允许' in win.results.diagnostic_text()
    assert win._sb_labels['extrap'].text() == '未通过 ⚠'
    assert '设计资格：不合格' in win.results.diagnostic_text()
    path = tmp_path / 'range-rejected.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), 'CSV'))
    win.result_export.export_results()
    with path.open(encoding='utf-8', newline='') as stream:
        rows = dict(csv.reader(stream))
    archived = json.loads(rows['metadata'])['qualification']
    assert archived['convergence']['passed'] is True
    assert archived['applicability']['passed'] is False
    assert archived['design']['eligible'] is False
    assert not win._test_error_dialogs


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_extrapolation_watermarks_name_recorded_model_without_constdf(win, mode):
    from sjtu_tpmshx.postprocess.result_display import (
        extrapolation_model_label, extrapolation_watermark,
    )
    from types import SimpleNamespace
    from tests.python.gui_workbench_support import _result

    with pytest.raises(ValueError, match='darcy_forchheimer'):
        extrapolation_model_label({})
    with pytest.raises(ValueError, match='darcy_forchheimer'):
        extrapolation_model_label({'darcy_forchheimer': {'mode': 'experimental', 'A': {'campaign': 'c'}}})
    with pytest.raises(ValueError, match='darcy_forchheimer'):
        extrapolation_watermark({}, ['V2 wall thickness must be inside the 0.3..0.5 mm CFD grid.'])
    assert extrapolation_watermark({}, []) == ''

    result = _result(mode)
    result.extrap_reasons = ['V2 wall thickness must be inside the 0.3..0.5 mm CFD grid.']
    result.metadata = {
        **result.metadata,
        'darcy_forchheimer': {'mode': 'experimental'},
        'model_refs': [{'name': 'darcy_forchheimer', 'version': 'cfd_full_core_3cell_fixed_v2'}],
    }
    win.results.publish(result)
    if mode == '2d':
        _real_finalize_plots(win, field='temp')
        texts = [item.get_text() for item in win.canvas_temp.fig.texts]
        assert len(texts) == 1
        assert 'cfd_full_core_3cell_fixed_v2（实验标定）' in texts[0]
        assert '外推' in texts[0]
        assert 'ConstDF-v1' not in texts[0]
    else:
        seen = {}
        win.canvas_3d = SimpleNamespace(
            cleanup=lambda: None, color_range_state=lambda: {},
            set_scale_sharing=lambda **kw: None,
            set_fields=lambda **kw: seen.update(kw),
            set_lattice_geometry=lambda *args: None,
            set_watermark=lambda text: seen.__setitem__('watermark', text),
        )
        assert _real_finalize_plots_3d(win)
        assert 'cfd_full_core_3cell_fixed_v2（实验标定）' in seen['watermark']
        assert '外推' in seen['watermark']
        assert 'ConstDF-v1' not in seen['watermark']
        _real_render_2d_slices_from_3d(win, result, field='temp')
        texts = [item.get_text() for item in win.canvas_temp.fig.texts]
        assert len(texts) == 1
        assert 'cfd_full_core_3cell_fixed_v2（实验标定）' in texts[0]
        assert '外推' in texts[0]
        assert 'ConstDF-v1' not in texts[0]
