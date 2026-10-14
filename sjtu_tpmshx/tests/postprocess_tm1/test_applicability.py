"""Original parameter limits use actual final samples, not cell fractions."""
import json
from math import inf, nextafter
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.range_policy import assess_range, parameter_bounds
from sjtu_tpmshx.domain.run_warnings import (
    RangeRecord, range_context, range_observations, record_range, warning_messages, warning_scope,
)
from sjtu_tpmshx.postprocess.api import evaluate_applicability


def sample(minimum, maximum, bounds=(100., 200.), *, size=2, **changes):
    return dict(source=('nu_raw', 'water', 'Gyroid'), side='A', stage='main', layout='cell',
                shape=(size,), quantity='Re', unit='-', bounds=bounds, captured=True,
                minimum=(minimum, (0,)), maximum=(maximum, (size-1,)), low=int(minimum < bounds[0]),
                high=int(maximum > bounds[1]), size=size, nonfinite=0, **changes)


@pytest.mark.parametrize('minimum,maximum,status', [
    (100., 200., 'within_original'), (90., 220., 'within_margin'),
    (89.99, 200., 'outside_limit'), (100., 220.01, 'outside_limit'),
])
def test_parameter_boundaries(minimum, maximum, status):
    row = assess_range(sample(minimum, maximum))
    assert row['status'] == status
    assert row['allowed_bounds'] == pytest.approx((90., 220.))


def test_decimal_calibration_endpoint_and_one_bad_cell():
    assert assess_range(sample(.09, .10, (.10, .25)))['within_limit'] is True
    row = assess_range(sample(.08999, .10, (.10, .25), size=1000))
    assert row['low'] == 1 and row['within_limit'] is False
    assert row['relative_extrapolation'] > .1


@pytest.mark.parametrize('bounds', [(0., 1.), (-1., 1.)])
def test_nonpositive_bounds_require_a_domain_rule_for_extrapolation(bounds):
    assert assess_range(sample(.2, .3, bounds))['status'] == 'within_original'
    assert assess_range(sample(bounds[0]-.01, .3, bounds))['status'] == 'domain_rule_required'
    with pytest.raises(ValueError, match='positive ordered'):
        parameter_bounds(bounds)


def test_hard_bounds_are_not_expanded():
    assert assess_range(sample(95., 200., constraint='hard_bounds'))['within_limit'] is False
    assert assess_range(sample(nextafter(100., 0.), 200., constraint='hard_bounds'))['within_limit'] is False


def test_nonfinite_samples_are_not_inside_the_range():
    row = sample(100., 200.)
    row.update(nonfinite=1, maximum=None)
    assert assess_range(row)['within_limit'] is False
    row = sample(100., inf)
    with pytest.raises(ValueError, match='finite ordered extrema'):
        assess_range(row)


def test_last_actual_call_does_not_inherit_earlier_extrema():
    with warning_scope({}) as records, range_context(side='A', stage='main', layout='cell'):
        for values in ([10., 500.], [110., 150.]):
            record_range(('nu_raw', 'water', 'Gyroid'), values, (100., 200.),
                         label='water Nu', quantity='Re', unit='-')
    history, = range_observations(records)
    final, = range_observations(records, last=True)
    assert history['minimum'][0] == 10. and history['maximum'][0] == 500.
    assert final['minimum'][0] == 110. and final['maximum'][0] == 150.
    assert assess_range(history)['within_limit'] is False
    assert assess_range(final)['within_limit'] is True
    assert len(list(warning_messages(records))) == 1
    record, = records.values()
    old = RangeRecord(*(getattr(record, name) for name in (
        'label', 'quantity', 'unit', 'bounds', 'minimum', 'maximum', 'low', 'high', 'size', 'nonfinite')))
    unknown, = range_observations({next(iter(records)): old}, last=True)
    assert assess_range(unknown)['within_limit'] is None


def test_original_hx_calibration_overrides_broader_application_history():
    from sjtu_tpmshx.df_surrogate.experimental_correction import apply_correction
    with warning_scope({}) as records, range_context(side='A', stage='prepared-df', layout='scalar'):
        _, _, metadata = apply_correction('Diamond', 'water', 7., .6, 1e-8, 40., .014)
    assert metadata['velocity_window_mps']['min'] < .014
    row, = range_observations(records)
    assert row['bounds'][0] == .10
    assert assess_range(row)['within_limit'] is False


def result_with_evidence(*, final=True):
    row = sample(100., 200.)
    evidence = dict(version='applicability_evidence_v1', inlet_recorded=True,
        inlet=[row], final=[row] if final else [], scope_notes=['range membership is not experimental validation'],
        required=[dict(group='final', side='A', source=row['source'])])
    grid = dict(dimension=2, length_unit='m', axis_order=('x', 'y'),
                dx=np.ones(2), dy=np.ones(2), x_edges=np.arange(3.), y_edges=np.arange(3.))
    return FieldResult('range', 'case', 'fixture', grid=grid, run_status=dict(execution='completed', converged=False),
                       metadata=dict(dimension=2, quantity_basis='per_unit_depth', applicability_evidence=evidence))


def test_missing_final_evidence_is_not_a_pass():
    summary = evaluate_applicability(result_with_evidence(final=False))
    assert summary['status'] == 'unverified' and summary['within_limits'] is None
    assert summary['missing'][0]['group'] == 'final'
    old = FieldResult('old', 'case', 'fixture')
    assert evaluate_applicability(old)['status'] == 'unavailable'
    assert 'design_eligible' not in evaluate_applicability(result_with_evidence())


def test_new_process_reads_the_same_verdict_without_eos_or_solver(tmp_path):
    from sjtu_tpmshx.io.result_io import save_result
    result = result_with_evidence()
    path = save_result(result, tmp_path / 'ranges.h5')
    process = subprocess.run([sys.executable, '-c', r'''
import json, sys
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate_applicability
print(json.dumps(evaluate_applicability(load_result(sys.argv[1])), allow_nan=False))
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'CoolProp', 'numba', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
''', str(path)], text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == json.loads(json.dumps(evaluate_applicability(result)))


@pytest.mark.parametrize('field,value', [('captured', 'yes'), ('constraint', 'unknown'), ('size', 0)])
def test_invalid_policy_evidence_is_rejected(field, value):
    row = sample(100., 200.)
    row[field] = value
    with pytest.raises(ValueError):
        assess_range(row)


def test_runtime_joint_scope_notice_is_preserved():
    from sjtu_tpmshx.domain.case_data import CaseData
    from sjtu_tpmshx.solvers.applicability_evidence import capture_applicability
    note = 'Joint sCO2 coverage remains unverified.'
    evidence = capture_applicability(CaseData('case'), result_with_evidence(),
                                     {('nu-evidence', 'sco2', 'A', 'main'): note})
    assert evidence['scope_notes'] == (note,)


@pytest.mark.parametrize('mode', ['cfd_smooth', 'experimental'])
def test_preparation_selects_calibration_limits_only_for_the_active_resource(mode):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig, SolverConfig, ExtrapPolicy
    from sjtu_tpmshx.preprocess.api import prepare_case
    config = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=8.1, T_in_K=350., P_in_Pa=2e5),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=2e6),
        solver=SolverConfig(Nx=4, Ny=4), df_mode=mode, extrap=ExtrapPolicy(allow=True))
    case = prepare_case(config, case_id='selected-range-' + mode)
    rows = [row for row in case.metadata['applicability_inputs']
            if row['source'] == ('df-experimental', 'water', 'Gyroid')]
    if mode == 'experimental':
        assert rows and all(row['bounds'][0] == .10 for row in rows)
        assert all(assess_range(row)['within_limit'] is False for row in rows)
    else:
        assert rows == []
