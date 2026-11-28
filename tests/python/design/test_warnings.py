"""Final design warnings retain case ownership across search and presentation."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tm1.applications.design import sizing, select, optimize, cli
from tm1.applications.design.cases import DesignCase
from tm1.applications.design.forward import ForwardResult
from tm1.run_control.run_warnings import record_warning, warning_scope


def _case(number=1):
    return DesignCase(number, 'air', 500., 2e5, .1, 'air', 300., 2e5, .1,
                      None, .1, .1, dT=50.)


def _sized_with_notices(cases, topo, l, t, arrangement='cross', **kwargs):
    # This function is serializable by loky; each worker patches only itself.
    from unittest.mock import patch
    def trial(*args, **kw):
        record_warning(('trial',), 'discarded search')
        return .1, None
    def final(c, *args, **kw):
        record_warning(('source',), f'final case {c.case}, cell {l}')
        return ForwardResult(400., 350., 10., 10., .01, .01, 1000., 1000.,
                             run_status={'converged': True})
    with patch.object(sizing, 'tpms_geometry', return_value={'epsilon': .5}), \
         patch.object(sizing, 'dP_fracs', return_value=(.01, .01)), \
         patch.object(sizing, 'solve_Lx', trial), \
         patch.object(sizing, 'forward', final):
        return sizing.size_fixed_cell(cases, topo, l, t, arrangement, **kwargs)


def test_final_cases_isolated_from_search_and_previous_runs():
    for _ in range(2):
        with warning_scope({}) as parent:
            d = _sized_with_notices([_case(1), _case(2)], 'Diamond', 5., .5)
        assert parent == {('trial',): 'discarded search'}
        assert [pc['warnings'] for pc in d.percase] == [
            ['final case 1, cell 5.0'], ['final case 2, cell 5.0']]
        assert d.validity == ''


def test_serial_loky_and_refine_keep_selected_cases(monkeypatch):
    monkeypatch.setattr(select, 'size_fixed_cell', _sized_with_notices)
    nodes = dict(topo=['Diamond'], l=[5., 6.], t=[.5])
    serial, best = select.enumerate_select([_case()], nodes=nodes)
    parallel, pbest = select.enumerate_select([_case()], nodes=nodes, n_jobs=2)
    assert [d.percase for d in parallel] == [d.percase for d in serial]
    assert pbest.percase == best.percase
    monkeypatch.setattr(optimize, 'minimize', lambda *a, **kw: SimpleNamespace(x=[4., .5]))
    monkeypatch.setattr(optimize, 'size_fixed_cell', _sized_with_notices)
    refined = optimize.warm_start_joint([_case()], best)
    assert refined is not best
    assert refined.percase[0]['warnings'] == ['final case 1, cell 4.0']
    monkeypatch.setattr(optimize, 'minimize', lambda *a, **kw: SimpleNamespace(x=[8., .5]))
    assert optimize.warm_start_joint([_case()], best) is best


@pytest.mark.parametrize('hot_fluid', ['air', 'water', 'sco2'])
def test_cli_refined_best_and_both_export_sheets(monkeypatch, tmp_path, capsys, hot_fluid):
    import openpyxl
    base = _sized_with_notices([_case()], 'Diamond', 6., .5)
    ref = _sized_with_notices([replace(_case(2), hot_fluid=hot_fluid)], 'Diamond', 4., .5)
    monkeypatch.setattr(cli, 'load_cases', lambda path: [_case()])
    monkeypatch.setattr(select, 'enumerate_select', lambda *a, **kw: ([base], base))
    monkeypatch.setattr(optimize, 'warm_start_joint', lambda *a, **kw: ref)
    path = tmp_path / 'warnings.xlsx'
    assert cli.run(['--xlsx', 'unused', '--out', str(path), '--refine']) == 0
    output = capsys.readouterr().out
    assert 'best (min-V): Diamond_l4_t0.5' in output
    assert '[算例 2] final case 2, cell 4.0' in output
    wb = openpyxl.load_workbook(path)
    for name in ('构型汇总', '算例明细'):
        rows = list(wb[name].values)
        col = rows[0].index('警告')
        assert any('final case 2, cell 4.0' in str(row[col]) for row in rows[1:])
    assert 'discarded search' not in str(list(wb['算例明细'].values))
    rows = list(wb['算例明细'].values)
    detail = dict(zip(rows[0], rows[-1]))
    assert detail['热流体'] == hot_fluid
    assert detail['热侧出口_K'] == 400.
    assert detail['热侧绝对压损_Pa'] == 2000.  # 1% of the case's 200 kPa inlet.
    assert detail['热侧相对压损_pct'] == 1.
    assert not any(column.startswith('空气') for column in rows[0])


@pytest.mark.parametrize('model,passes', [('const', 1), ('mean', 2)])
@pytest.mark.parametrize('diagnostic_state', ['available', 'unsupported', 'missing'])
def test_forward_labels_without_extra_property_or_thermal_calls(
        monkeypatch, model, passes, diagnostic_state):
    import importlib
    f = importlib.import_module('tm1.applications.design.forward')
    execution = importlib.import_module('tm1.solvers.quick_design')
    postprocess = importlib.import_module('tm1.postprocess.api')
    from tm1.run_control.run_warnings import warning_messages
    solves, diagnostics, inlets = [], [], []
    evaluate, native_run = postprocess.evaluate, execution.run_case
    record_native = execution._record_pass

    def evaluated(*args, **kwargs):
        performance = evaluate(*args, **kwargs)
        metrics = dict(performance.metrics)
        metric = metrics['energy_imbalance_rel']
        assert metric.value is not None and metric.status == 'available'
        if diagnostic_state == 'unsupported':
            metrics['energy_imbalance_rel'] = replace(
                metric, value=None, status='unsupported', reason='diagnostic unavailable')
        elif diagnostic_state == 'missing':
            del metrics['energy_imbalance_rel']
        diagnostics.append(metrics.get('energy_imbalance_rel'))
        return replace(performance, metrics=metrics)

    nu_contexts = set()

    def evidence(records):
        record_native(records)
        nu_contexts.update(key[-1][:2] for key in execution.current_warnings() if key[0] == 'nu')

    def solve(case, control):
        inlets.extend(case.metadata['applicability_inputs'])
        result = native_run(case, control)
        solves.append(result)
        return result

    monkeypatch.setattr(execution, '_record_pass', evidence)
    monkeypatch.setattr(execution, 'run_case', solve)
    monkeypatch.setattr(postprocess, 'evaluate', evaluated)
    c = replace(_case(), hot_fluid='water', cold_fluid='sco2',
                T_in_h=500., T_in_c=350., P_in_h=3e6, P_in_c=9e6,
                mdot_h=.2, mdot_c=.2)
    cold_repeat = model == 'mean' and diagnostic_state == 'available'
    if cold_repeat:
        from tm1.physical_models import sco2_props, tpms_geometry
        sco2_props._prop.cache_clear()
        tpms_geometry.compute_geometry.cache_clear()
    with warning_scope({}) as records:
        result = f.forward(c, 'Diamond', 7., .5, .1, .025, prop_model=model)
    assert len(solves) == 1
    assert len(solves[0].run_status['passes']) == passes
    assert result.Q_hot > 0. and result.Q_cold > 0.
    assert len(diagnostics) == 1 and result.energy_imbalance is diagnostics[0]
    messages = '\n'.join(warning_messages(records))
    assert [(r['source'][1], r['side'], r['stage'], r['layout']) for r in inlets] == [
        (name, 'A', 'design-dp-inlet', 'scalar')
        for name in ('water_density', 'water_viscosity', 'water_conductivity', 'water_cp')]
    assert all(r['minimum'][0] == r['maximum'][0] == 500. for r in inlets)
    assert 'side=A, stage=design-dp-inlet' in messages
    stages = ['design-inlet-pass', 'design-mean-pass'][:passes]
    assert {(side, stage) for side in ('A', 'B') for stage in stages} <= nu_contexts
    assert 'side=A, stage=design-inlet-pass' in messages
    if passes == 2:
        assert 'side=A, stage=design-mean-pass' in messages
    assert '480 K' in messages and '9 MPa' in messages
    assert 'joint qualification' in messages
    if cold_repeat:
        cold_inputs = tuple(inlets)
        with warning_scope({}) as warm_records:
            warm = f.forward(c, 'Diamond', 7., .5, .1, .025, prop_model=model)
        assert (warm.Q_hot, warm.Q_cold) == (result.Q_hot, result.Q_cold)
        assert tuple(warning_messages(warm_records)) == tuple(warning_messages(records))
        assert inlets == [*cold_inputs, *cold_inputs]


def test_source_notices_survive_global_suppression_and_repeated_scopes():
    import warnings
    from tm1.physical_models.tpms_props import air_cp
    from tm1.physical_models.nu_correlations import nu_from_Re
    from tm1.run_control.run_warnings import warning_messages
    def sources():
        air_cp(2000.)
        nu_from_Re('Diamond', 1., .25, 7., 1.)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        sources()  # Populate standalone once registries first.
        recorded = []
        for _ in range(2):
            with warning_scope({}) as records:
                sources()
            recorded.append(list(warning_messages(records)))
    assert recorded[0] == recorded[1]
    assert any('air_cp' in message for message in recorded[0])
    assert any('Re' in message for message in recorded[0])
