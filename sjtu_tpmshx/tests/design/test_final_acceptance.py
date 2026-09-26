"""Final sizing evidence, not the search's candidate, controls recommendation."""
from dataclasses import replace
import math

import pytest

from sjtu_tpmshx.design import sizing
from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import ForwardResult
from sjtu_tpmshx.design.report import detail_rows, summary_rows
from sjtu_tpmshx.design.select import pareto_tags
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue


@pytest.mark.parametrize('change,reason', [
    ({}, ''),
    ({'T_out_hot': 370.}, 'T_out>target'),
    ({'run_status': {'converged': False}}, 'not-converged'),
    ({'run_status': {}}, 'not-converged'),
    ({'dP_hot_frac': .06}, 'dP>lim'),
    ({'Re_hot': float('nan')}, 'nonfinite'),
])
def test_final_case_controls_feasibility_and_report(monkeypatch, change, reason):
    condition = DesignCase(1, 'air', 400., 101325., .01, 'air', 300., 101325., .01,
                           None, .05, .05, dT=50.)
    good = ForwardResult(340., 330., 600., 600., .01, .01, 1000., 1000.,
                         run_status={'converged': True},
                         energy_imbalance=MetricValue(0., MetricSpec('energy_imbalance_rel', '1')))
    def forward(*args, tol=sizing.LTNE_TOL, **kwargs):
        return replace(good, **change) if tol == sizing.LTNE_TOL else good
    monkeypatch.setattr(sizing, 'forward', forward)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .7})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.01, .01))
    d = sizing.size_fixed_cell([condition], 'Diamond', 6., .4)
    assert d.feasible is (not reason)
    assert reason in d.reason
    tags = pareto_tags([d])
    assert bool(tags) is (not reason)
    assert summary_rows([d], tags)[0]['可行'] == ('否' if reason else '是')
    details = detail_rows([d])
    assert len(details) == 1  # Failed final evidence is still exported.
    assert reason in details[0]['终验']
    assert details[0]['冷侧换热量_W'] == 600.
    assert details[0]['能量不平衡_rel'] == 0.
    assert details[0]['能量诊断状态'] == 'available'
    if reason == 'nonfinite':
        assert math.isnan(details[0]['Re热'])


def test_duty_target_is_checked_against_final_duty(monkeypatch):
    condition = DesignCase(1, 'air', 400., 101325., .01, 'air', 300., 101325., .01,
                           100., .05, .05)
    result = ForwardResult(300., 330., 90., 90., .01, .01, 1000., 1000.,
                           run_status={'converged': True})
    monkeypatch.setattr(sizing, 'solve_Lx', lambda *a, **kw: (.1, result))
    monkeypatch.setattr(sizing, 'forward', lambda *a, **kw: result)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .7})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.01, .01))
    d = sizing.size_fixed_cell([condition], 'Diamond', 6., .4)
    assert not d.feasible and 'Q<target@final' in d.reason


@pytest.mark.parametrize('diagnostic_state', ['available', 'unsupported', 'missing'])
def test_energy_diagnostic_is_reported_without_a_new_feasibility_gate(
        monkeypatch, tmp_path, diagnostic_state):
    from openpyxl import load_workbook
    from sjtu_tpmshx.design.report import write_xlsx

    condition = DesignCase(1, 'air', 400., 101325., .01, 'air', 300., 101325., .01,
                           None, .05, .05, dT=50.)
    hot, cold = 600.123456, 60.234567
    imbalance = abs(hot - cold) / max(abs(hot), abs(cold))
    metric = MetricValue(imbalance, MetricSpec('energy_imbalance_rel', '1'))
    if diagnostic_state == 'unsupported':
        metric = replace(metric, value=None, status='unsupported', reason='diagnostic unavailable')
    elif diagnostic_state == 'missing':
        metric = None
    result = ForwardResult(340., 330., hot, cold, .01, .01, 1000., 1000.,
                           run_status={'converged': True}, energy_imbalance=metric)
    calls = []
    def final(*args, **kwargs):
        calls.append(args[0].case)
        return result
    monkeypatch.setattr(sizing, 'solve_Lx', lambda *a, **kw: (.1, result))
    monkeypatch.setattr(sizing, 'forward', final)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .7})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.01, .01))
    design = sizing.size_fixed_cell([condition], 'Diamond', 6., .4)
    assert design.feasible and design.reason == '' and calls == [1]
    case, = design.percase
    expected_value = metric.value if metric is not None else None
    expected_status = metric.status if metric is not None else 'insufficient_data'
    expected_reason = metric.reason if metric is not None else '未提供能量不平衡诊断'
    assert case['Q_W'] == hot and case['Q_cold_W'] == cold
    assert case['energy_imbalance_rel'] == expected_value
    assert case['energy_imbalance_status'] == expected_status
    assert case['energy_imbalance_reason'] == expected_reason
    assert case['run_status']['converged'] and case['acceptance_reasons'] == []
    assert imbalance > .8  # Deliberately imbalanced, still governed by the existing gates.

    path = tmp_path / 'energy.xlsx'
    assert write_xlsx(path, [design]) == (1, 1, 1)
    workbook = load_workbook(path)
    try:
        cells = list(workbook['工况明细'].values)
        row = dict(zip(cells[0], cells[1]))
        assert row['热侧换热量_W'] == hot and row['冷侧换热量_W'] == cold
        assert row['换热量_kW'] == round(hot / 1e3, 3)
        if expected_value is None:
            assert row['能量不平衡_rel'] is None
        else:
            assert row['能量不平衡_rel'] == pytest.approx(expected_value, rel=0., abs=1e-15)
        assert row['能量诊断状态'] == expected_status
        assert row['能量诊断原因'] == (expected_reason or None)
        assert row['数值收敛'] is True and row['终验'] is None
    finally:
        workbook.close()
