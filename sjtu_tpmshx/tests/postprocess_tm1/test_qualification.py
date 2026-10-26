"""Common qualification preserves failure, missing evidence and saved state."""
from dataclasses import replace
import json
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.metrics_io import load_metrics, save_metrics
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.api import evaluate_qualification
from sjtu_tpmshx.tests.postprocess_tm1.test_applicability import result_with_evidence
from sjtu_tpmshx.tests.postprocess_tm1.test_physical_balance import sample_result


def qualified_result(dimension=3):
    result = sample_result(dimension)
    flux = mutable_data(result.boundary_fluxes)
    for phase in ('A', 'B', 'solid'):
        flux['energy']['residual'][phase][:] = 0.
        flux['energy']['source_integral'][phase] = 0.
        for key in ('advective_out', 'diffusive_out'):
            for face in flux['energy'][key][phase].values():
                face[:] = 0.
    flux['mass_A'][0][:] = 1.
    flux['mass_B'] = [face.copy() for face in flux['mass_A']]
    metadata = dict(result.metadata, thermal_mode='model_h',
        applicability_evidence=result_with_evidence().metadata['applicability_evidence'],
        execution_record=dict(version='full_execution_v1', sides={
            side: dict(fluid=fluid, solved=True) for side, fluid in (('A', 'air'), ('B', 'water'))}),
        parameters=dict(fluid_B_cfg=dict(dir=1)),
        diagnostics=dict(convergence_detail=dict(simple_ok=True, ltne_ok=True, outer_converged=True,
            fields_finite=True, envelope_ok=True), eps_A_strict=0., eps_B_strict=0.,
            eps_A_strict_cellmax=0., eps_B_strict_cellmax=0., Q_sA=0., Q_sB=0.,
            model_h_balance=dict(physical_boundary_complete=True, sides={'A': {}, 'B': {}})))
    fields = {name: np.full((2,) * dimension, value)
              for name, value in (('Ta', 350.), ('Tb', 320.), ('Ts', 335.), ('h_vB', 0.))}
    return replace(result, boundary_fluxes=flux, metadata=metadata, fields=fields,
                   field_metadata={name: dict(unit='W/(m3 K)' if name == 'h_vB' else 'K',
                       axes=tuple('xyz'[:dimension]), location='cell', state='last thermal solve')
                       for name in fields}, run_status=dict(execution='completed', converged=True))


def required_metrics(dimension=3):
    power_unit = 'W' if dimension == 3 else 'W/m'
    return {name: MetricValue(value, MetricSpec(name, unit)) for name, value, unit in (
        ('Q', 0., power_unit), ('Q_B', 0., power_unit), ('dP_A', 1., 'Pa'), ('dP_B', 1., 'Pa'),
        ('T_out_A', 330., 'K'), ('T_out_B', 330., 'K'))}


def test_complete_evidence_keeps_independent_conclusions():
    result = qualified_result()
    quality = evaluate_qualification(result, required_metrics())
    assert quality['design']['eligible'] is True
    assert quality['execution']['passed'] is quality['convergence']['passed'] is True
    assert quality['physical']['balance']['state'] == 'last thermal input'
    assert quality['physical']['balance']['energy']['units'] == 'W'
    assert quality['applicability']['passed'] is True
    assert quality['optimization']['passed'] is True
    assert quality['optimization']['deferred'] == []
    json.dumps(quality, allow_nan=False)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('name', ['Ta', 'Tb', 'Ts', 'P_report_A', 'ucA'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_actual_raw_fields_override_saved_convergence(dimension, name, value):
    result = qualified_result(dimension)
    fields = mutable_data(result.fields)
    fields[name] = np.full((2,) * dimension, 330.)
    fields[name].flat[-1] = value
    result = replace(result, fields=fields)
    quality = evaluate_qualification(result, required_metrics(dimension))
    assert result.run_status['converged'] is True
    assert quality['convergence']['gates']['fields_finite'] is True
    assert quality['convergence']['raw_fields'][name] is False
    assert quality['convergence']['passed'] is False
    assert quality['design']['eligible'] is quality['optimization']['passed'] is False


@pytest.mark.parametrize('name', ['Ta', 'Tb', 'Ts'])
def test_missing_raw_temperature_does_not_gain_qualification(name):
    result = qualified_result()
    fields = dict(result.fields)
    del fields[name]
    quality = evaluate_qualification(replace(result, fields=fields), required_metrics())
    assert quality['convergence']['raw_fields'][name] is None
    assert quality['convergence']['passed'] is None
    assert quality['design']['eligible'] is quality['optimization']['passed'] is None


@pytest.mark.parametrize('name', ['Ta', 'Tb', 'Ts'])
def test_recorded_fine_temperature_is_checked(name):
    result = qualified_result(2)
    fine = {key: np.full((4, 4), 330.) for key in ('Ta', 'Tb', 'Ts')}
    fine[name][1, 1] = np.nan
    result = replace(result, boundary_fluxes={**result.boundary_fluxes, 'fine': fine})
    quality = evaluate_qualification(result, required_metrics(2))
    assert quality['convergence']['raw_fields']['fine.' + name] is False
    assert quality['convergence']['passed'] is False
    assert quality['design']['eligible'] is quality['optimization']['passed'] is False


def test_display_and_diagnostic_nan_remain_readable_without_changing_qualification(tmp_path):
    result = qualified_result()
    metadata = mutable_data(result.metadata)
    metadata['diagnostics']['unavailable_probe'] = np.array([np.nan])
    result = replace(result, fields={**result.fields, 'Ta_display': np.full((2, 2, 2), np.nan)},
        field_metadata={**result.field_metadata, 'Ta_display': {
            **result.field_metadata['Ta'], 'state': 'display'}}, metadata=metadata)
    restored = load_result(save_result(result, tmp_path / 'diagnostics.h5'))
    assert np.isnan(restored.fields['Ta_display']).all()
    assert np.isnan(restored.metadata['diagnostics']['unavailable_probe']).all()
    quality = evaluate_qualification(restored, required_metrics())
    assert quality['convergence']['passed'] is True
    assert quality['design']['eligible'] is quality['optimization']['passed'] is True
    assert 'Ta_display' not in quality['convergence']['raw_fields']


@pytest.mark.parametrize('damage,section,expected', [
    ('range', 'applicability', False), ('missing_range', 'applicability', None),
    ('mass', 'physical', None), ('ledger', 'physical', None),
    ('boundary', 'physical', False), ('thermal_gate', 'physical', False),
    ('simple', 'convergence', False), ('unconverged', 'convergence', False),
    ('sco2', 'model_scope', None), ('missing_execution', 'model_scope', None),
    ('unknown_execution', 'model_scope', None), ('missing_side', 'model_scope', None),
    ('missing_side_state', 'model_scope', None), ('missing_fluid', 'model_scope', None),
])
@pytest.mark.parametrize('fluid', ['air', 'sco2'])
def test_no_promotion_from_a_partial_or_failed_gate(damage, section, expected, fluid):
    result = qualified_result()
    metadata, flux, status = map(mutable_data, (result.metadata, result.boundary_fluxes, result.run_status))
    metadata['execution_record']['sides']['A']['fluid'] = fluid
    if damage == 'range':
        metadata['applicability_evidence']['final'][0]['minimum'][0] = 89.
    elif damage == 'missing_range':
        del metadata['applicability_evidence']
    elif damage == 'mass':
        flux['mass_A'] = None
    elif damage == 'ledger':
        del flux['energy']
    elif damage == 'boundary':
        flux['energy']['physical_boundary_complete'] = False
    elif damage == 'thermal_gate':
        metadata['diagnostics']['eps_A_strict_cellmax'] = .01001
    elif damage == 'simple':
        metadata['diagnostics']['convergence_detail']['simple_ok'] = False
    elif damage == 'unconverged':
        status['converged'] = False
    elif damage == 'sco2':
        metadata['execution_record']['sides']['A']['fluid'] = 'sco2'
    elif damage == 'missing_execution':
        del metadata['execution_record']
    elif damage == 'unknown_execution':
        metadata['execution_record']['version'] = 'future'
    elif damage == 'missing_side':
        del metadata['execution_record']['sides']['B']
    elif damage == 'missing_side_state':
        del metadata['execution_record']['sides']['B']['solved']
    elif damage == 'missing_fluid':
        del metadata['execution_record']['sides']['A']['fluid']
    result = replace(result, metadata=metadata, boundary_fluxes=flux, run_status=status)
    quality = evaluate_qualification(result, required_metrics())
    assert quality[section]['passed'] is expected
    assert quality['design']['eligible'] is expected
    if section != 'convergence':
        assert quality['convergence']['passed'] is True
    assert quality['metrics']['passed'] is True
    assert quality['optimization']['passed'] is (True if damage == 'sco2' else expected)



@pytest.mark.parametrize('mode', ['true_h', 'conservative_energy', 'model_h'])
@pytest.mark.parametrize('fine', [None, {}])
def test_only_routes_with_refinement_require_fine_heat_evidence(mode, fine):
    result = qualified_result(2)
    metadata = mutable_data(result.metadata)
    metadata['thermal_mode'] = mode
    diagnostics = metadata['diagnostics']
    diagnostics['true_h_balance'] = dict(converged=True, enthalpy_clip_counts={'total': [0, 0]},
        effective_settings=dict(coupled_energy_tol=.001, equation_energy_tol=.001),
        coupled_energy_balance={'ratio': 0.}, equation_energy_balance={'ratio': 0.})
    diagnostics['model_h_balance'] = {name: dict(passed=True,
        A={'physical_boundary_complete': True}, B={'physical_boundary_complete': True})
        for name in ('main', 'fine')}
    diagnostics['convergence_detail']['richardson_ok'] = True
    result = replace(result, metadata=metadata, boundary_fluxes={**result.boundary_fluxes, 'fine': fine})
    quality = evaluate_qualification(result, required_metrics(2))
    assert quality['physical']['passed'] is (None if mode == 'model_h' else True)
    assert quality['design']['eligible'] is (None if mode == 'model_h' else True)


def test_missing_and_unavailable_metrics_are_distinct():
    result, metrics = qualified_result(), required_metrics()
    del metrics['dP_A']
    assert evaluate_qualification(result, metrics)['metrics']['passed'] is None
    metrics['dP_A'] = MetricValue(None, MetricSpec('dP', 'Pa'), 'invalid', 'bad pressure state')
    assert evaluate_qualification(result, metrics)['metrics']['passed'] is False


def test_historical_metrics_read_without_a_fabricated_qualification(tmp_path):
    result = qualified_result()
    performance = PerformanceResult('metrics', result.result_id, required_metrics())
    path = save_metrics(performance, tmp_path / 'old.json')
    payload = json.loads(path.read_text())
    del payload['qualification']
    path.write_text(json.dumps(payload))
    assert not load_metrics(path).qualification



@pytest.mark.parametrize('change', [dict(definition='future'), dict(source_result_id='other')])
def test_qualification_rejects_unknown_version_or_wrong_source(change):
    result, metrics = qualified_result(), required_metrics()
    quality = evaluate_qualification(result, metrics)
    quality.update(change)
    with pytest.raises(ValueError, match='qualification version or source'):
        PerformanceResult('metrics', result.result_id, metrics, quality)


@pytest.mark.parametrize('fluid', ['air', 'sco2'])
def test_saved_new_process_verdict_needs_no_solver_or_eos(tmp_path, fluid):
    result, metrics = qualified_result(), required_metrics()
    metadata = mutable_data(result.metadata)
    metadata['execution_record']['sides']['A']['fluid'] = fluid
    result = replace(result, metadata=metadata)
    quality = evaluate_qualification(result, metrics)
    performance = PerformanceResult('metrics', result.result_id, metrics, quality)
    with pytest.raises(TypeError):
        performance.qualification['design']['eligible'] = False
    result_path = save_result(result, tmp_path / 'result.h5')
    metric_path = save_metrics(performance, tmp_path / 'metrics.json')
    child = subprocess.run([sys.executable, '-c', '''
import sys
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.domain.model_refs import freeze_mapping
from sjtu_tpmshx.postprocess.api import evaluate_qualification
result, performance = load_result(sys.argv[1]), load_metrics(sys.argv[2])
assert performance.qualification == freeze_mapping(evaluate_qualification(result, performance.metrics))
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'CoolProp', 'numba', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
''', str(result_path), str(metric_path)], text=True, capture_output=True, timeout=30)
    assert child.returncode == 0, child.stderr


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('mode', ['true_h', 'conservative_energy'])
@pytest.mark.parametrize('damage', [None, 'convergence', 'clips', 'coupled', 'equation', 'nonfinite', 'missing'])
def test_true_h_common_verdict_keeps_native_energy_gates(dimension, mode, damage):
    from types import SimpleNamespace
    from sjtu_tpmshx.postprocess.qualification import _energy_gates
    balance = dict(converged=True, enthalpy_clip_counts={'total': [0, 0]},
        effective_settings={'coupled_energy_tol': .001, 'equation_energy_tol': .001},
        coupled_energy_balance={'ratio': .0002}, equation_energy_balance={'ratio': .0003})
    if damage == 'convergence':
        balance['converged'] = False
    elif damage == 'clips':
        balance['enthalpy_clip_counts']['total'][1] = 1
    elif damage in ('coupled', 'equation'):
        balance[damage + '_energy_balance']['ratio'] = .00101
    elif damage == 'nonfinite':
        balance['equation_energy_balance']['ratio'] = float('nan')
    elif damage == 'missing':
        del balance['equation_energy_balance']
    field = SimpleNamespace(metadata={'dimension': dimension, 'thermal_mode': mode,
                                     'diagnostics': {'true_h_balance': balance}})
    if damage == 'missing':
        with pytest.raises(KeyError):
            _energy_gates(field)
    else:
        gates = _energy_gates(field)
        assert len(gates) == 4 and all(type(passed) is bool for _, passed in gates)
        assert all(passed for _, passed in gates) == (damage is None)
