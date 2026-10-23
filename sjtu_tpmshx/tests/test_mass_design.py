"""Mass integration, per-condition limits, constrained proposals and saved evidence."""
from dataclasses import replace
import json

import numpy as np
import pytest

from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.optimization import mass_design as mass
from sjtu_tpmshx.optimization import multi_condition_optimizer as search
from sjtu_tpmshx.tests.test_module_result_mapping import _synthetic_results
from sjtu_tpmshx.tests.test_multi_condition_optimizer import _conditions, _fake_batches


def requirements(ids=('flow-0', 'flow-1')):
    return dict(solid_density_kg_m3=8000., conditions={name: dict(
        Q_min_W=100., dP_A_max_Pa=10., dP_B_max_Pa=20.) for name in ids})


@pytest.mark.parametrize('dimension', [2, 3])
def test_mass_and_heat_use_physical_depth_and_nonuniform_cells(tmp_path, monkeypatch, dimension):
    field, performance = _synthetic_results(dimension)
    shape = (2, 3) if dimension == 2 else (2, 3, 4)
    eps = np.linspace(.6, .9, np.prod(shape)).reshape(shape)
    metadata = mutable_data(field.metadata)
    metadata['quantity_basis'] = 'per_unit_depth' if dimension == 2 else 'total'
    metadata['design_fields']['eps_arr'] = eps
    field = replace(field, metadata=metadata)
    path = tmp_path / 'synthetic-result.h5'
    monkeypatch.setattr(mass, 'load_result', lambda _: field)
    config = _conditions(dimension)[0][1].to_dict()
    config['geometry']['Lz_m'] = .05
    limit = requirements(('one',))
    limit['conditions']['one']['Q_min_W'] = 5. if dimension == 2 else 100.
    values, checks = mass.mass_observation({'one': dict(config_snapshot=config,
        performance=performance, result_file=path)}, limit)
    expected = 0.
    for index in np.ndindex(shape):
        volume = np.prod([field.grid['d'+axis][i] for axis, i in zip('xyz', index)])
        expected += (1-eps[index])*volume*8000.*(.05 if dimension == 2 else 1.)
    assert values['core_mass_kg'] == pytest.approx(expected)
    assert checks['one']['Q_W'] == limit['conditions']['one']['Q_min_W']
    assert checks['one']['feasible']
    assert [values[key] for key in mass.CONSTRAINT_KEYS] == [0., 0., 0.]


def test_one_condition_or_side_cannot_hide_behind_an_average(tmp_path, monkeypatch):
    field, performance = _synthetic_results()
    metadata = mutable_data(field.metadata)
    metadata['design_fields']['eps_arr'] = np.full((2, 3, 4), .8)
    path = tmp_path / 'synthetic-result.h5'
    monkeypatch.setattr(mass, 'load_result', lambda _: replace(field, metadata=metadata))
    summaries = {name: dict(config_snapshot=cfg.to_dict(), performance=performance, result_file=path)
                 for name, cfg, *_ in _conditions(3)}
    metrics = dict(performance.metrics)
    metrics['Q_B'] = replace(metrics['Q_B'], value=-200.)
    metrics['dP_A'] = replace(metrics['dP_A'], value=15.)
    metrics['dP_B'] = replace(metrics['dP_B'], value=5.)
    summaries['flow-1']['performance'] = replace(performance, metrics=metrics)
    values, checks = mass.mass_observation(summaries, requirements())
    assert values['pressure_excess_A'] == .5
    assert values['pressure_excess_B'] == values['heat_shortfall'] == 0.
    assert checks['flow-0']['feasible'] and not checks['flow-1']['feasible']
    metrics['Q_B'] = replace(metrics['Q_B'], value=100.)
    summaries['flow-1']['performance'] = replace(performance, metrics=metrics)
    values, _ = mass.mass_observation(summaries, requirements())
    assert values['heat_shortfall'] == 2.


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(solid_density_kg_m3=float('nan')),
    lambda r: r.update(solid_density_kg_m3=True),
    lambda r: r.update(allow_nu_re_extrapolation=1),
    lambda r: r.update(allow_nu_re_extrapolation='yes'),
    lambda r: r['conditions'].pop('flow-1'),
    lambda r: r['conditions']['flow-0'].update(Q_min_W=0.),
    lambda r: r['conditions']['flow-0'].update(dP_B_max_Pa=float('inf')),
])
def test_invalid_limits_fail_before_native_evaluation(tmp_path, monkeypatch, mutate):
    fixed = requirements()
    mutate(fixed)
    monkeypatch.setattr(search, '_evaluate_condition_batch', lambda *a, **k: pytest.fail('invalid limits ran'))
    with pytest.raises(ValueError):
        search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / 'unused',
            method='sobol', n_init=1, n_iter=0, mass_requirements=fixed)
    assert not (tmp_path / 'unused').exists()


def _fake_mass_batches(monkeypatch):
    calls = _fake_batches(monkeypatch, fail_indices=(2,))
    evaluate = search._evaluate_condition_batch
    def batch(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        if kwargs.get('baseline') is not None:
            result['summaries'] = dict(index=int(kwargs['output_dir'].name.removeprefix('design_')))
        return result
    def observation(summaries, fixed):
        index = summaries['index']
        objectives = dict(core_mass_kg=10.-index, heat_shortfall=.1 if index == 1 else -.1,
                          pressure_excess_A=-.2, pressure_excess_B=-.3)
        return objectives, {name: dict(residuals=[objectives[key] for key in mass.CONSTRAINT_KEYS],
                                      feasible=index != 1) for name in fixed['conditions']}
    monkeypatch.setattr(search, '_evaluate_condition_batch', batch)
    monkeypatch.setattr(search, 'mass_observation', observation)
    return calls


def test_infeasible_designs_train_model_but_cannot_be_selected_and_resume(tmp_path, monkeypatch):
    calls = _fake_mass_batches(monkeypatch)
    monkeypatch.setattr(search, '_bo_versions', lambda: {})
    observed = []
    def propose(X, Y, lower, upper, reference, **kwargs):
        observed.append(Y.copy())
        assert kwargs['method'] == 'qlognei' and reference is None
        return np.asarray([lower + .4*(upper-lower)])
    monkeypatch.setattr(search, '_propose_bo', propose)
    result = search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / 'source',
        method='qlognei', n_init=3, n_iter=1, workers=1, mass_requirements=requirements())
    assert result['status'] == 'completed'
    assert result['n_usable'] == 3 and result['n_feasible'] == 2
    assert result['pareto_indices'] == [3]
    np.testing.assert_array_equal(observed[0], [[-10., -.1, -.2, -.3], [-9., .1, -.2, -.3]])
    resumed = search.resume_multi_condition_optimization(tmp_path / 'source/optimization.json',
        output_dir=tmp_path / 'resumed', workers=1)
    assert len(calls) == 5
    assert resumed['history'] == result['history']
    assert resumed['mass_requirements'] == result['mass_requirements']
    assert resumed['pareto_indices'] == [3]
    saved = tmp_path / 'source/optimization.json'
    changed = json.loads(saved.read_text())
    changed['mass_requirements']['conditions']['flow-0']['Q_min_W'] = 99.
    saved.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='mass_requirements'):
        search.resume_multi_condition_optimization(saved, output_dir=tmp_path / 'changed', workers=1)


def test_no_feasible_result_is_explicit(tmp_path, monkeypatch):
    _fake_mass_batches(monkeypatch)
    observe = search.mass_observation
    def infeasible(*args):
        objectives, checks = observe(*args)
        objectives['heat_shortfall'] = .2
        return objectives, checks
    monkeypatch.setattr(search, 'mass_observation', infeasible)
    result = search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / 'none',
        method='sobol', n_init=2, n_iter=0, workers=1, mass_requirements=requirements())
    assert result['status'] == 'completed' and result['n_usable'] == 2
    assert result['n_feasible'] == 0 and result['pareto_indices'] == []


@pytest.mark.parametrize('fixed_cell', [False, True])
def test_real_constrained_acquisition_selects_a_complete_design(tmp_path, monkeypatch, fixed_cell):
    pytest.importorskip('botorch', reason='requires the locked BO environment')
    calls = _fake_mass_batches(monkeypatch)
    result = search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / 'bo',
        method='qlognei', n_init=4, n_iter=1, workers=1, seed=7, mass_requirements=requirements(),
        field_spec={'L_bounds': [7., 7.]} if fixed_cell else None)
    assert result['status'] == 'completed' and result['n_evaluated'] == 5
    assert result['n_usable'] == 4 and len(calls) == 6
    chosen = result['history'][-1]['x_decision']
    assert result['proposals'][0]['x_decisions'] == [chosen]
    assert calls[-1][0][0][1].zones.config['x_decision'] == chosen
    assert np.isfinite(result['history'][-1]['model_y']).all()

    if fixed_cell:
        assert chosen[:len(chosen)//2] == [7.]*(len(chosen)//2)
        assert result['field_spec']['L_bounds'] == [7., 7.]


def test_search_rejects_two_fixed_fields_before_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(search, '_evaluate_condition_batch', lambda *a, **k: pytest.fail('fixed design ran'))
    with pytest.raises(ValueError, match='at least one variable field'):
        search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path / 'fixed',
            method='sobol', field_spec={'L_bounds': [7., 7.], 't_bounds': [.6, .6]})
    assert not (tmp_path / 'fixed').exists()


def test_mass_search_carries_nu_re_policy_through_batches_and_recovery(tmp_path, monkeypatch):
    _fake_mass_batches(monkeypatch)
    original = search._evaluate_condition_batch
    policies = []
    def evaluate(*args, **kwargs):
        policies.append(kwargs['allow_nu_re_extrapolation'])
        return original(*args, **kwargs)
    monkeypatch.setattr(search, '_evaluate_condition_batch', evaluate)
    fixed = dict(requirements(), allow_nu_re_extrapolation=True)
    result = search.run_multi_condition_optimization(_conditions(), output_dir=tmp_path/'source',
        method='sobol', n_init=2, n_iter=0, workers=1, mass_requirements=fixed)
    assert policies == [True, True, True]
    resumed = search.resume_multi_condition_optimization(tmp_path/'source/optimization.json',
        output_dir=tmp_path/'resumed', workers=1)
    assert resumed['mass_requirements'] == result['mass_requirements'] == fixed
    assert policies == [True] * 6
