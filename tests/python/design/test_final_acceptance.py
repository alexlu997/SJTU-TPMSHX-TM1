"""Final sizing evidence, not the search's candidate, controls recommendation."""
from dataclasses import replace
import math
import pickle

import pytest

from tm1.applications.design import sizing
from tm1.applications.design.cases import DesignCase
from tm1.applications.design.forward import ForwardResult
from tm1.applications.design.report import detail_rows, summary_rows
from tm1.applications.design.select import pareto_tags
from tm1.data_types.metric_spec import MetricSpec
from tm1.data_types.performance_result import MetricValue


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
    if d.feasible:
        light = sizing.size_fixed_cell([condition], 'Diamond', 6., .4, rho_s=2700.)
        assert light.feasible and light.V == d.V
        assert d.weight == pytest.approx(.3 * d.V * 7900.)
        assert light.weight == pytest.approx(.3 * d.V * 2700.)
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
    from tm1.applications.design.report import write_xlsx

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
        cells = list(workbook['算例明细'].values)
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


def test_final_water_failure_retains_failed_case_and_continues_cases(monkeypatch):
    from tm1.physical_models.fluid_props import QuickDesignWaterFieldError
    from tm1.run_control.run_warnings import record_warning
    cases = [DesignCase(i, 'air', 400., 2e5, .01, 'water', 300., 2e5, .01,
                        100., .05, .05) for i in (1, 2)]
    good = ForwardResult(340., 330., 600., 600., .01, .01, 1000., 1000.,
                         run_status={'converged': True})
    calls = []
    def final(case, *args, **kwargs):
        calls.append(case.case)
        if case.case == 1:
            record_warning(('test', 'water notice'), 'water notice')
            raise QuickDesignWaterFieldError('design-inlet-pass B water index=(0, 0, 0), T=500 K')
        return good
    monkeypatch.setattr(sizing, 'solve_Lx', lambda *a, **kw: (.1, good))
    monkeypatch.setattr(sizing, 'forward', final)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .7})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.01, .01))
    design = sizing.size_fixed_cell(cases, 'Diamond', 6., .4)
    # The workbook summary reads the warnings before the details sheet reads them again.
    assert summary_rows([design], {})[0]['警告'] == '[算例 1] water notice'
    assert detail_rows([design])[0]['警告'] == 'water notice'
    # A parallel search returns each design from a loky worker process.
    design = pickle.loads(pickle.dumps(design))
    assert not design.feasible and calls == [1, 2]
    assert 'case 1: water-state-invalid@final' in design.reason
    failed, good_row = detail_rows([design])
    assert math.isnan(failed['热侧换热量_W'])
    assert failed['数值收敛'] is False
    assert 'index=(0, 0, 0)' in failed['终验'] and failed['警告'] == 'water notice'
    assert good_row['热侧换热量_W'] == 600.
    assert math.isnan(design.dP_hot_max)
    assert not pareto_tags([design])


def test_unresolved_water_candidate_keeps_identity_without_aborting_selection(monkeypatch):
    from tm1.physical_models.fluid_props import QuickDesignWaterFieldError
    case = DesignCase(1, 'air', 400., 2e5, .01, 'water', 300., 2e5, .01,
                      100., .05, .05)
    widths = []
    def unresolved(*args, **kwargs):
        widths.append(args[4])
        raise QuickDesignWaterFieldError('water-state-search-exhausted: controlled field failure')
    monkeypatch.setattr(sizing, 'solve_Lx', unresolved)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .7})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.01, .01))
    design = sizing.size_fixed_cell([case], 'Diamond', 6., .4)
    assert not design.feasible and len(widths) > 1
    assert design.topo == 'Diamond' and design.l == 6. and design.t == .4
    assert 'water-state-search-exhausted' in design.reason
    assert 'cooling-unreachable' not in design.reason
