"""Fixed geometry and roughness cross the Case boundary as validated data."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.backends.python.three_d import runtime, flux
from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg


@pytest.mark.parametrize('mode', ['asymmetric', 'experimental'])
def test_prepared_geometry_and_roughness_are_consumed(monkeypatch, mode):
    cfg = _small_air_cfg()
    cfg = replace(cfg, geometry=replace(cfg.geometry, delta_levelset=.05 if mode == 'asymmetric' else 0.),
                  df_mode='experimental' if mode == 'experimental' else 'cfd_smooth')
    if mode == 'experimental':
        from sjtu_tpmshx.domain.compute_config import PartialBCConfig
        cfg = replace(cfg, geometry=replace(cfg.geometry, L_dom_m=.182, H_dom_m=.042, Lz_m=.042),
                      fluid_A=replace(cfg.fluid_A, u_mps=4., P_in_Pa=2e5),
                      fluid_B=replace(cfg.fluid_B, u_mps=4., P_in_Pa=2e5),
                      bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=3))
    case = prepare_case(cfg, case_id=mode + '-geometry')
    parameters, prepared = build_execution_inputs(case)
    def forbidden(*args, **kwargs):
        raise AssertionError('execution queried fixed geometry or receiver roughness')
    from sjtu_tpmshx.models import tpms_props, tpms_geometry
    monkeypatch.setattr(tpms_props, 'geometry', forbidden)
    monkeypatch.setattr(tpms_geometry, '_phi_grid', forbidden)
    monkeypatch.setattr(flux, '_resolve_ui_roughness', forbidden)
    from sjtu_tpmshx.df_surrogate import experimental_correction
    monkeypatch.setattr(experimental_correction, 'correction_scale', forbidden)
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *a, **k: None)
    problem = runtime.build_problem(parameters, prepared)
    hv = runtime._build_hv_machinery(problem)
    local_hv = hv._build_hv_local_3d(
        None, np.full((problem.Nx, problem.Ny, problem.Nz), problem.u_A),
        problem.T_inA, problem.P_inA, problem.fluid_type_A)
    assert np.all(np.isfinite(local_hv))
    if mode == 'asymmetric':
        assert hv._hv_ratio_A != 1.
        expected_split = case.parameters['thermal_geometry']['split_A']
        assert runtime._prepared_eps_overrides(parameters, problem.eps) == (
            problem.eps * expected_split, problem.eps * (1. - expected_split))
    else:
        assert runtime._prepared_eps_overrides(parameters, problem.eps) == (None, None)
    # Physical K fields remain effective inputs after freezing calibration.
    changed = replace(case, design_fields={**case.design_fields, 'K_m2': case.design_fields['K_m2'] * 2.})
    changed_cfg, changed_prepared = build_execution_inputs(changed)
    changed_problem = runtime.build_problem(changed_cfg, changed_prepared)
    np.testing.assert_array_equal(changed_problem.sA.K_arr, problem.sA.K_arr * 2.)
    bad_geometry = {**case.parameters['thermal_geometry'], 'split_A': 1.1}
    bad = replace(case, parameters={**case.parameters, 'thermal_geometry':bad_geometry})
    with pytest.raises(ValueError, match='side split'):
        build_execution_inputs(bad)


def test_archived_bulk_hv_loads_but_does_not_set_local_heat_transfer(tmp_path, monkeypatch):
    from sjtu_tpmshx.io.case_io import save_case, load_case

    case = prepare_case(_small_air_cfg(), case_id='archived-bulk-hv')
    assert 'air_bulk_hv' not in case.parameters['thermal_geometry']
    shape = tuple(len(case.grid['d' + axis]) for axis in 'xyz')
    geometry = {**case.parameters['thermal_geometry'],
                'air_bulk_hv': {side: np.full(shape, value)
                                for side, value in (('A', 123.), ('B', 456.))}}
    archived = replace(case, parameters={**case.parameters, 'thermal_geometry': geometry})
    save_case(archived, tmp_path / 'case.h5')
    loaded = load_case(tmp_path / 'case.h5')
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *a, **k: None)
    fields = []
    for prepared_case in (case, loaded):
        parameters, prepared = build_execution_inputs(prepared_case)
        problem = runtime.build_problem(parameters, prepared)
        hv = runtime._build_hv_machinery(problem)
        fields.append(hv._build_hv_local_3d(
            None, np.full(shape, problem.u_A), problem.T_inA, problem.P_inA, 'air'))
    np.testing.assert_array_equal(fields[0], fields[1])
    assert np.any(fields[1] != 123.)
    invalid = {**geometry, 'air_bulk_hv': {'A': np.full(shape, np.nan)}}
    with pytest.raises(ValueError, match='bulk heat transfer'):
        save_case(replace(case, parameters={**case.parameters, 'thermal_geometry': invalid}),
                  tmp_path / 'invalid.h5')


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('end', ['inlet', 'outlet'])
def test_prepared_openings_match_actual_solver_geometry_before_solving(side, end, tmp_path, monkeypatch):
    from sjtu_tpmshx.domain.portable_data import mutable_data
    from sjtu_tpmshx.io.case_io import save_case, load_case
    from sjtu_tpmshx.solvers.api import run_case

    config = _small_air_cfg()
    config.solver = replace(config.solver, Nx=4, Ny=4, Nz=4)
    full = prepare_case(config, case_id='full-opening')
    port = getattr(config, 'bc_' + side)
    width = 'in_w' if end == 'inlet' else 'out_w'
    partial = prepare_case(replace(config, **{'bc_' + side: replace(
        port, **{width: getattr(port, width) / 2.})}), case_id='partial-opening')
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *a, **k: None)
    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve',
                        lambda *a, **k: pytest.fail('construction control ran a PDE'))
    # Both coherent full and partial cases remain supported, without replacing
    # the supplied masks. The constructor supplies independent geometry evidence.
    for case in (full, partial):
        problem = runtime.build_problem(*build_execution_inputs(case))
        for name, solver in (('A', problem.sA), ('B', problem.sB)):
            for boundary in ('inlet', 'outlet'):
                np.testing.assert_allclose(
                    case.parameters['prepared']['openings'][name][boundary],
                    getattr(solver, boundary + '_frac'), rtol=1e-12, atol=1e-15)
    parameters = mutable_data(full.parameters)
    parameters['prepared']['openings'][side][end] = partial.parameters['prepared']['openings'][side][end]
    save_case(replace(full, parameters=parameters), tmp_path / 'case.h5')
    restored = load_case(tmp_path / 'case.h5')
    monkeypatch.setattr(runtime, '_run_two_simple',
                        lambda *a, **k: pytest.fail('conflicting opening reached a PDE'))
    with pytest.raises(ValueError, match=f'fluid {side} {end} opening'):
        run_case(restored)
