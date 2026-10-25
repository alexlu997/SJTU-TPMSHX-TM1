"""Keep old archives readable without restoring retired grid construction."""
from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig, FeatureFlags
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.tests.test_port_wall_grid_3d import _full_face_config


@pytest.mark.parametrize('dimension', [2, 3])
def test_disabled_historical_flag_keeps_inputs_without_republishing_it(tmp_path, dimension):
    config = _full_face_config(False)
    if dimension == 2:
        config.solver.Nz = 1
    payload = config.to_dict()
    payload['flags']['wall_refine_3d'] = False
    path = tmp_path / 'old.json'
    original = json.dumps(payload)
    path.write_text(original)
    restored = ComputeConfig.from_json(path)
    assert restored == config
    assert 'wall_refine_3d' not in restored.to_dict()['flags']
    assert path.read_text() == original


def test_enabled_historical_flag_requires_an_explicit_new_grid(tmp_path):
    payload = _full_face_config().to_dict()
    payload['flags']['wall_refine_3d'] = True
    path = tmp_path / 'old.json'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='wall_refine_3d is retired.*total grid counts'):
        ComputeConfig.from_json(path)
    with pytest.raises(TypeError, match='wall_refine_3d'):
        FeatureFlags(wall_refine_3d=True)


@pytest.mark.parametrize('enabled', [False, True])
def test_old_script_assignment_fails_before_grid_construction(monkeypatch, enabled):
    from sjtu_tpmshx.preprocess.three_d import preparation
    config = _full_face_config(False)
    monkeypatch.setattr(preparation, '_build_grid_3d',
                        lambda *args: pytest.fail('retired script input reached grid construction'))
    with pytest.raises(AttributeError, match='wall_refine_3d'):
        config.flags.wall_refine_3d = enabled
        prepare_case(config, case_id='old-script')


@pytest.mark.parametrize('value', [None, 'false', 'true', 0, 1, [], {}])
@pytest.mark.parametrize('prepared', [False, True])
def test_invalid_historical_flags_stay_invalid(value, prepared):
    payload = _full_face_config().to_dict()
    payload['flags']['wall_refine_3d'] = value
    with pytest.raises(ValueError, match='flags.wall_refine_3d must be boolean'):
        ComputeConfig.from_dict(payload, prepared_grid=prepared)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('enabled', [False, True])
def test_prepared_archive_keeps_its_actual_grid_and_snapshot(tmp_path, dimension, enabled):
    config = _full_face_config()
    if dimension == 2:
        config.solver.Nz = 1
    current = prepare_case(config, case_id='saved-grid')
    snapshot, parameters = mutable_data(current.config_snapshot), mutable_data(current.parameters)
    snapshot['flags']['wall_refine_3d'] = enabled
    if dimension == 2:
        parameters['run_settings']['flags']['wall_refine_3d'] = enabled
    else:
        parameters['wall_refine_3d'] = enabled
    archived = replace(current, config_snapshot=snapshot, parameters=parameters)
    path = tmp_path / 'case.h5'
    save_case(archived, path)
    original = path.read_bytes()
    restored = load_case(path)
    controls = ComputeConfig.from_dict(mutable_data(restored.config_snapshot), prepared_grid=True)
    assert controls == config
    if dimension == 2:
        from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
    else:
        from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    build_execution_inputs(restored)
    for axis in 'xyz'[:dimension]:
        np.testing.assert_array_equal(restored.grid['d' + axis], current.grid['d' + axis])
    assert restored.config_snapshot['flags']['wall_refine_3d'] is enabled
    assert path.read_bytes() == original


def test_low_level_preparation_rejects_old_constructor_before_grid_build(monkeypatch):
    from sjtu_tpmshx.preprocess.three_d import preparation
    cfg = preparation._parse_inputs_3d_cfg(_full_face_config(False))
    cfg['wall_refine_3d'] = True
    monkeypatch.setattr(preparation, '_build_grid_3d',
                        lambda *args: pytest.fail('retired input reached grid construction'))
    with pytest.raises(ValueError, match='wall_refine_3d is retired'):
        preparation._prepare_geometry_data(cfg)


@pytest.mark.parametrize('retired', [False, True])
def test_saved_condition_keeps_grid_identity_and_other_settings(retired):
    from sjtu_tpmshx.optimization.multi_condition import _check_saved_condition
    from sjtu_tpmshx.preprocess.api import prepare_fixed_mass_flow_case, prepare_inlet_mass_capacities
    config = _full_face_config(False)
    capacities = prepare_inlet_mass_capacities(config)
    flows = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    case = prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=flows[0],
                                      mass_flow_B_kg_s=flows[1], case_id='condition')
    snapshot = mutable_data(case.config_snapshot)
    snapshot['flags']['wall_refine_3d'] = retired
    old = replace(case, config_snapshot=snapshot)
    if retired:
        with pytest.raises(ValueError, match='grid setting differs'):
            _check_saved_condition(old, config, *flows, case.case_id)
    _check_saved_condition(old, config, *flows, case.case_id, saved_config=snapshot)
    snapshot['flags']['variable_rho_cp'] = not config.flags.variable_rho_cp
    with pytest.raises(ValueError, match='configuration differs'):
        _check_saved_condition(replace(case, config_snapshot=snapshot), config, *flows,
                               case.case_id, saved_config=snapshot)


def test_old_2d_baseline_keeps_other_input_and_grid_checks():
    from sjtu_tpmshx.domain.field_result import FieldResult
    from sjtu_tpmshx.optimization.multi_condition import _check_baseline_case
    from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity
    config = _full_face_config(False)
    config.solver.Nz = 1
    case = prepare_case(config, case_id='baseline-input')
    parameters = mutable_data(case.parameters)
    parameters['run_settings']['flags']['wall_refine_3d'] = False
    metadata = dict(dimension=2, quantity_basis='per_unit_depth', mode='full',
        thermal_mode='model_h', design_mode='uniform', parameters=parameters,
        design_fields=case.design_fields, df_metadata={'mode': config.df_mode})
    reference = FieldResult('baseline', case.case_id, 'synthetic', grid=case.grid,
                            model_refs=case.model_refs, metadata=metadata)
    flows = tuple(case.parameters['u_' + side] * total_inlet_mass_capacity(
        case.design_fields, case.parameters, case.grid, side) for side in 'AB')
    _check_baseline_case(reference, case, *flows)
    parameters['run_settings']['flags']['variable_rho_cp'] = not config.flags.variable_rho_cp
    with pytest.raises(ValueError, match='fixed 2D inputs differ'):
        _check_baseline_case(replace(reference, metadata={**metadata, 'parameters': parameters}), case, *flows)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('enabled', [False, True])
def test_archived_design_export_keeps_geometry_without_old_grid_construction(tmp_path, dimension, enabled):
    from sjtu_tpmshx.optimization.export_ntop_csv import export_study_design
    config = _full_face_config(False)
    if dimension == 2:
        config.solver.Nz = 1
    snapshot = config.to_dict()
    snapshot['flags']['wall_refine_3d'] = enabled
    spec = dict(n_ctrl_x=2, n_ctrl_y=2, symmetric_y=False, spline_order=1,
                L_bounds=(5., 9.), t_bounds=(.3, .9))
    if dimension == 3:
        spec['n_ctrl_z'] = 2
    decisions = [7.] * 2**dimension + [.6] * 2**dimension
    report = dict(status='completed', dimension=dimension, field_spec=spec,
        conditions=[dict(config=snapshot)], pareto_indices=[0],
        history=[dict(status='completed', x_decision=decisions, index=0, directory='design-0')])
    original = deepcopy(report)
    summary = export_study_design(report, 0, tmp_path, (3,) * dimension)
    rows = np.loadtxt(summary['csv_geometry'], delimiter=',', skiprows=1)
    assert rows.shape == (3**dimension, dimension + 2)
    np.testing.assert_allclose(rows[:, -2:], np.tile([7., .6], (len(rows), 1)), atol=1e-13)
    lengths = [config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m][:dimension]
    np.testing.assert_allclose(rows[:, :dimension].max(axis=0), np.array(lengths) * 1000.)
    assert report == original
