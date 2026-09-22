"""Accepted-run inputs survive GUI edits until result publication."""
from copy import deepcopy
import threading

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D, CancelledError
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.ui.mixins.run_results import RunResultsMixin
from sjtu_tpmshx.tests.test_worker_result_handoff import win as win, _wait_for


@pytest.fixture
def run_window(win, monkeypatch, tmp_path):
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    win._apply_shanghai_defaults()
    win.le_Nx.setText('24')
    win.le_Ny.setText('18')
    win.le_Nz.setText('5')
    win.auto_fill_fluid_a()
    win.auto_fill_fluid_b()

    def render(window):
        return False  # Offscreen 3D panel; scalar publication still succeeds.

    monkeypatch.setattr(win, '_finalize_plots',
                        lambda: RunResultsMixin._finalize_plots(win))
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_2d_results.finalize_plots', render)
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d', render)
    return win


def test_running_edits_recent_restore_and_consecutive_dimensions(run_window, monkeypatch):
    win = run_window
    gui_thread = threading.get_ident()
    original_capture = win._capture_current_preset
    captures = []

    def capture(name):
        captures.append(threading.get_ident())
        return original_capture(name)

    monkeypatch.setattr(win, '_capture_current_preset', capture)
    for dim in (0, 1):
        win.combo_dim.setCurrentIndex(dim)
        win.le_Nx.setText('24')
        win.le_Ny.setText('18')
        win.le_Nz.setText('5')
        win._active_preset_name = f'start-{dim}'
        win.combo_grid.setCurrentIndex(win.combo_grid.findData(True))
        win.auto_fill_fluid_a()
        win.auto_fill_fluid_b()
        expected = original_capture('Run inputs')
        release = threading.Event()
        keys = ('dx', 'dy', 'dz') if dim else ('dx_arr', 'dy_arr')
        sizes = (40, 34, 21) if dim else (27, 20)
        result = ComputeResult(Q_W=100 + dim, diagnostics={'mode': '3d' if dim else '2d'},
                               fields={k: np.ones(n) for k, n in zip(keys, sizes)})

        def run(pipe):
            assert release.wait(10)
            return result

        monkeypatch.setattr(Pipeline3D if dim else Pipeline2D, 'run', run)
        try:
            win.run_calculation()
            # A busy click must not replace the accepted run's snapshot.
            win.combo_dim.setCurrentIndex(1 - dim)
            win.combo_fluidA.setCurrentIndex(1)
            win.le_Nx.setText('99')
            win.le_Nz.setText('13')
            win._active_preset_name = 'next draft'
            win.zone_table.setItem(0, 0, QTableWidgetItem('17'))
            win.run_calculation()
            draft = original_capture('draft')
            QApplication.processEvents()
        finally:
            release.set()
        _wait_for(win.compute.is_idle)
        assert original_capture('draft') == draft, 'completion overwrote editable inputs'
        entry = win._recent_runs[0]
        restored = deepcopy(entry['preset'])
        restored['name'] = 'Run inputs'
        assert restored == expected
        assert float(entry['Q']) == 100 + dim
        assert entry['preset_source'] == f'start-{dim}'
        assert entry['mode'] == ('3d' if dim else '2d')
        assert entry['input_grid'] == (['24', '18', '5'] if dim else ['24', '18'])
        assert entry['actual_grid'] == list(sizes)
        provenance = result.metadata['run_provenance']
        assert provenance['preset'] == expected
        tip_fields = win._sb_labels['q'].toolTip().split('  ·  ')
        assert f'preset: start-{dim}' in tip_fields
        input_grid = '24×18×5' if dim else '24×18'
        assert f'input grid {input_grid}' in tip_fields
        assert 'actual result grid ' + '×'.join(map(str, sizes)) in tip_fields
        assert win._run_provenance is None
        win._on_orch_finished(result)  # duplicate terminal delivery is ignored
        assert len(win._recent_runs) == dim + 1
        win._load_recent_run(entry)
        assert original_capture('Run inputs') == expected
        assert provenance['preset'] == expected
    assert captures and set(captures) == {gui_thread}


@pytest.mark.parametrize('outcome', ['error', 'cancel', 'reject', 'close'])
def test_failed_or_rejected_run_cannot_record_or_leak(run_window, monkeypatch, outcome):
    win = run_window
    win.combo_dim.setCurrentIndex(0)
    release = threading.Event()

    def run(pipe):
        assert release.wait(10)
        if outcome == 'error':
            raise RuntimeError('controlled failure')
        if outcome == 'cancel':
            raise CancelledError('controlled cancellation')
        return ComputeResult(Q_W=99)

    monkeypatch.setattr(Pipeline2D, 'run', run)
    original_start = win.compute.start
    if outcome == 'reject':
        monkeypatch.setattr(win.compute, 'start', lambda *args, **kwargs: False)
    try:
        win.run_calculation()
        if outcome == 'close':
            assert not win.close()
        elif outcome == 'cancel':
            win._on_cancel_compute()
        win.le_Nx.setText('66')
    finally:
        release.set()
    _wait_for(win.compute.is_idle)
    assert not getattr(win, '_recent_runs', [])
    assert getattr(win, '_run_provenance', None) is None
    if outcome == 'close':
        return
    monkeypatch.setattr(win.compute, 'start', original_start)
    monkeypatch.setattr(Pipeline2D, 'run', lambda pipe: ComputeResult(Q_W=321))
    win._active_preset_name = 'recovery'
    win.auto_fill_fluid_a()
    win.auto_fill_fluid_b()
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    assert len(win._recent_runs) == 1
    assert win._recent_runs[0]['input_grid'][0] == '66'
    assert win._recent_runs[0]['preset_source'] == 'recovery'


def test_snapshot_deepcopies_nested_preset_payload(run_window, monkeypatch):
    win = run_window
    payload = win._capture_current_preset('Run inputs')
    payload['zone_inputs']['pareto_x_decision'] = [6.0, 0.4]
    expected = deepcopy(payload)
    monkeypatch.setattr(win, '_capture_current_preset', lambda name: payload)
    release = threading.Event()

    def run(pipe):
        assert release.wait(10)
        return ComputeResult(Q_W=123)

    monkeypatch.setattr(Pipeline2D, 'run', run)
    win.combo_dim.setCurrentIndex(0)
    try:
        win.run_calculation()
        payload['zone_inputs']['pareto_x_decision'][0] = 99
        payload['line_edits']['le_Nx'] = '99'
    finally:
        release.set()
    _wait_for(win.compute.is_idle)
    assert win.compute.last_result().metadata['run_provenance']['preset'] == expected
    assert win._recent_runs[0]['preset']['zone_inputs'] == expected['zone_inputs']


def test_python_export_restores_complete_gui_inputs(run_window, monkeypatch):
    from dataclasses import asdict
    from types import SimpleNamespace
    from sjtu_tpmshx.tests.test_sco2_nu_modes import SYNTHETIC

    win = run_window
    win.combo_dim.setCurrentIndex(1)
    win.combo_fluidA.setCurrentIndex(2)
    win.combo_fluidB.setCurrentIndex(0)
    win.combo_dirA.setCurrentIndex(1)
    win.combo_df_mode.setCurrentIndex(0)
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(True))
    win._set_sco2_nu_parameters(asdict(SYNTHETIC))
    win.combo_sco2_nu_mode.setCurrentIndex(1)
    win._temp_unit = 'C'
    win.le_TinA.setText('76.85')
    win.le_TinB.setText('26.85')
    win.combo_zone_axis.setCurrentIndex(1)
    win._zone_init_1d(2)
    win.zone_table.item(0, 2).setText('6.5')
    win.chk_zones.setChecked(True)
    win._pareto_x_decision = [6.5, .45] * 18
    win._pareto_y_trans_inlet, win._pareto_y_trans_outlet = .15, .18
    expected = win._capture_current_preset('Python inputs')
    copied = []
    monkeypatch.setattr(QApplication, 'clipboard',
                        lambda: SimpleNamespace(setText=copied.append))
    win._copy_inputs_as_python()

    win._apply_shanghai_defaults()
    win._temp_unit = 'K'
    win.le_TinA.setText('422')
    namespace = {'window': win}
    exec(compile(copied[0], '<generated GUI preset>', 'exec'), namespace)
    assert namespace['cfg'] == expected
    assert win._capture_current_preset('Python inputs') == expected
    assert win._temp_unit == 'C' and win.le_TinA.text() == '76.85'


@pytest.mark.parametrize('dim', [0, 1])
def test_started_signal_edits_happen_after_config_and_snapshot(run_window, monkeypatch, dim):
    win = run_window
    win.combo_dim.setCurrentIndex(dim)
    expected = win._capture_current_preset('Run inputs')
    received = []

    def edit_on_started(mode):
        win.le_Nx.setText('88')
        win.combo_dim.setCurrentIndex(1 - dim)
        QApplication.processEvents()

    def run(pipe):
        received.append(pipe.cfg.solver.Nx)
        return ComputeResult(Q_W=42, diagnostics={'mode': '3d' if dim else '2d'})

    monkeypatch.setattr(Pipeline3D if dim else Pipeline2D, 'run', run)
    win.compute.started.connect(edit_on_started)
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    assert received == [24]
    assert win.compute.last_result().metadata['run_provenance']['preset'] == expected
    assert win.le_Nx.text() == '88'
    assert len(win._recent_runs) == 1


def test_footer_and_history_follow_each_successful_result(run_window, monkeypatch):
    win = run_window
    win.combo_dim.setCurrentIndex(0)
    for value in (100, 120, 180):
        win.auto_fill_fluid_a()
        win.auto_fill_fluid_b()
        monkeypatch.setattr(Pipeline2D, 'run', lambda pipe: ComputeResult(Q_W=value))
        win.run_calculation()
        _wait_for(win.compute.is_idle)
        assert win._sb_labels['q'].text() == f'{value:.1f} W/m'
    assert [entry['Q'] for entry in win._recent_runs] == ['180.0', '120.0', '100.0']


@pytest.mark.parametrize('dim', [0, 1])
def test_nu_run_snapshot_history_and_export(run_window, monkeypatch, tmp_path, dim):
    import csv, json
    from dataclasses import asdict, replace
    from PySide6.QtWidgets import QFileDialog
    from sjtu_tpmshx.tests.test_sco2_nu_modes import SYNTHETIC
    from sjtu_tpmshx.models.nu_correlations import sco2_nu_metadata
    win = run_window
    win._set_sco2_nu_parameters(asdict(SYNTHETIC))
    win.combo_sco2_nu_mode.setCurrentIndex(1)
    win.combo_dim.setCurrentIndex(dim)
    release = threading.Event()
    eos = {'algorithm': 'bicubic_iteration_heos_final_v1', 'sides': ['A', 'B']}
    def run(pipe):
        assert pipe.cfg.sco2_nu == SYNTHETIC
        assert release.wait(10)
        return ComputeResult(Q_W=100., diagnostics={'mode': '3d' if dim else '2d'},
            metadata={'sco2_nu': sco2_nu_metadata(pipe.cfg.sco2_nu),
                      'sco2_enthalpy_eos': eos,
                      'darcy_forchheimer': {'mode': pipe.cfg.df_mode}})
    monkeypatch.setattr(Pipeline3D if dim else Pipeline2D, 'run', run)
    try:
        win.run_calculation()
        win.combo_sco2_nu_mode.setCurrentIndex(0)
        win._set_sco2_nu_parameters(asdict(replace(SYNTHETIC, alpha_D=1.3)))
    finally:
        release.set()
    _wait_for(win.compute.is_idle)
    expected = sco2_nu_metadata(SYNTHETIC)
    assert win._recent_runs[0]['model_metadata']['sco2_nu'] == expected
    assert win._recent_runs[0]['model_metadata']['sco2_enthalpy_eos'] == eos
    timeline = json.loads((win.sm.base_dir / '.session_timeline.jsonl').read_text().splitlines()[-1])
    assert timeline['model_metadata']['sco2_nu'] == expected
    assert timeline['model_metadata']['sco2_enthalpy_eos'] == eos
    output = tmp_path / 'result.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(output), ''))
    win._export_results()
    with output.open() as stream:
        rows = dict(csv.reader(stream))
    assert json.loads(rows['metadata'])['sco2_nu'] == expected
    assert json.loads(rows['metadata'])['sco2_enthalpy_eos'] == eos
    if dim:
        with np.load(tmp_path / 'result_fields.npz', allow_pickle=False) as saved:
            assert json.loads(saved['metadata'].item())['sco2_nu'] == expected
            assert json.loads(saved['metadata'].item())['sco2_enthalpy_eos'] == eos
