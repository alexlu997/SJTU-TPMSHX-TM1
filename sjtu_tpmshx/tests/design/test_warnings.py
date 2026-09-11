"""Final design warnings retain case ownership across search and presentation."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.design import sizing, select, optimize, cli
from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import ForwardResult
from sjtu_tpmshx.domain.run_warnings import record_warning, warning_scope


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
        return ForwardResult(400., 350., 10., 10., .01, .01, 1000., 1000.)
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


def test_cli_refined_best_and_both_export_sheets(monkeypatch, tmp_path, capsys):
    import openpyxl
    base = _sized_with_notices([_case()], 'Diamond', 6., .5)
    ref = _sized_with_notices([_case(2)], 'Diamond', 4., .5)
    monkeypatch.setattr(cli, 'load_cases', lambda path: [_case()])
    monkeypatch.setattr(cli, 'enumerate_select', lambda *a, **kw: ([base], base))
    monkeypatch.setattr(optimize, 'warm_start_joint', lambda *a, **kw: ref)
    path = tmp_path / 'warnings.xlsx'
    assert cli.run(['--xlsx', 'unused', '--out', str(path), '--refine']) == 0
    output = capsys.readouterr().out
    assert 'best (min-V): Diamond_l4_t0.5' in output
    assert '[工况 2] final case 2, cell 4.0' in output
    wb = openpyxl.load_workbook(path)
    for name in ('构型汇总', '工况明细'):
        rows = list(wb[name].values)
        col = rows[0].index('警告')
        assert any('final case 2, cell 4.0' in str(row[col]) for row in rows[1:])
    assert 'discarded search' not in str(list(wb['工况明细'].values))


@pytest.mark.parametrize('model,passes', [('const', 1), ('mean', 2)])
def test_forward_labels_without_extra_property_or_thermal_calls(monkeypatch, model, passes):
    import importlib
    import numpy as np
    f = importlib.import_module('sjtu_tpmshx.design.forward')
    model_source = importlib.import_module('sjtu_tpmshx.models.quick_design')
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    execution = importlib.import_module('sjtu_tpmshx.solvers.backends.python.quick_design.execution')
    from sjtu_tpmshx.models import design_fluids as fluids
    from sjtu_tpmshx.domain.run_warnings import record_range, warning_messages
    calls, solves = [], []
    def props(fluid, T, P):
        calls.append((fluid, T, P))
        record_range(('property', fluid), T, (0., 1.), label=fluid, quantity='T', unit='K')
        return fluids.Props(10., 1e-5, .1, 1000., .1)
    def thermal(*args, **kwargs):
        solves.append((args, kwargs))
        shape = (args[3], args[4], args[5])
        return (*tuple(np.full(shape, t) for t in (400., 350., 375.)), {'converged': True})
    monkeypatch.setattr(model_source, 'fluid_props', props)
    monkeypatch.setattr(fluids, 'fluid_props', props)
    monkeypatch.setattr(preparation, 'tpms_geometry', lambda *a, **kw: dict(
        epsilon=.5, epsilon_A=.25, A_0=100., D_h=.001))
    monkeypatch.setattr(execution, 'solve_full_domain_3d', thermal)
    monkeypatch.setattr(model_source, '_dp_one', lambda *a, **kw: 100.)
    c = replace(_case(), hot_fluid='water', cold_fluid='sco2')
    with warning_scope({}) as records:
        result = f.forward(c, 'Diamond', 7., .5, .1, .1, prop_model=model)
    expected = [('water', 500., 2e5), ('sco2', 300., 2e5),
                ('water', 500., 2e5), ('water', 320., 2e5),
                ('sco2', 300., 2e5), ('sco2', 480., 9e6)]
    if passes == 2:
        expected += [('water', 450., 2e5), ('water', 320., 2e5),
                     ('sco2', 325., 2e5), ('sco2', 480., 9e6)]
    assert calls == expected and len(solves) == passes
    assert result.Q_hot == 10000. and result.Q_cold == 5000.
    messages = '\n'.join(warning_messages(records))
    for side in ('A', 'B'):
        assert f'side={side}, stage=design-inlet-pass' in messages
        assert f'side={side}, stage=design-dp-inlet' in messages
        assert f'side={side}, stage=design-nu-representative-pr' in messages
        if passes == 2:
            assert f'side={side}, stage=design-mean-pass' in messages
    assert '480 K' in messages and '9 MPa' in messages
    assert 'joint qualification' in messages


def test_source_notices_survive_global_suppression_and_repeated_scopes():
    import warnings
    from sjtu_tpmshx.models.tpms_props import air_cp
    from sjtu_tpmshx.models.nu_correlations import nu_from_Re
    from sjtu_tpmshx.domain.run_warnings import warning_messages
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
