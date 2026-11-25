"""Fixed geometry and roughness cross the Case boundary as validated data."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.run_control.module_ports import resolve_control
from tests.python.cases_3d import small_air_config
from tests.python.native.stage_interception import run_stage


def _first_state(case):
    """Run ``case`` and return its first native snapshot with the result capture."""
    states = []
    stage = run_stage(case, resolve_control(RunControl()),
                      checkpoint=lambda state: states or states.append(state))
    return states[0], stage


@pytest.mark.parametrize('mode', ['asymmetric', 'experimental'])
def test_prepared_geometry_and_roughness_are_consumed(monkeypatch, mode):
    cfg = small_air_config()
    cfg.solver = replace(cfg.solver, max_outer_ltne=2, max_iter_simple=500)
    cfg = replace(cfg, geometry=replace(cfg.geometry, delta_levelset=.05 if mode == 'asymmetric' else 0.),
                  df_mode='experimental' if mode == 'experimental' else 'cfd_smooth')
    if mode == 'experimental':
        from sjtu_tpmshx.data_types.compute_config import PartialBCConfig
        cfg = replace(cfg, geometry=replace(cfg.geometry, L_dom_m=.182, H_dom_m=.042, Lz_m=.042),
                      fluid_A=replace(cfg.fluid_A, u_mps=4., P_in_Pa=2e5),
                      fluid_B=replace(cfg.fluid_B, u_mps=4., P_in_Pa=2e5),
                      bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=3))
    case = prepare_case(cfg, case_id=mode + '-geometry')
    prepared = case.parameters['prepared']
    def forbidden(*args, **kwargs):
        raise AssertionError('execution queried fixed geometry or receiver roughness')
    from sjtu_tpmshx.physical_models import tpms_props, tpms_geometry
    from sjtu_tpmshx.cpp_interface import _native_geometry
    geometry_call = _native_geometry._call
    def prepared_call(function, *args):
        # Port validation shares the status helper, not fixed TPMS geometry.
        if not getattr(function, '__name__', '').startswith('tpmshx_geometry_grid_'):
            forbidden()
        return geometry_call(function, *args)
    monkeypatch.setattr(_native_geometry, '_call', prepared_call)
    with pytest.raises(AssertionError, match='execution queried fixed geometry'):
        _native_geometry.threshold('Gyroid', .1)
    monkeypatch.setattr(tpms_props, 'geometry', forbidden)
    monkeypatch.setattr(tpms_geometry, '_phi_grid', forbidden)
    from sjtu_tpmshx.physical_models.df_surrogate import experimental_correction
    monkeypatch.setattr(experimental_correction, 'correction_scale', forbidden)
    # The audit option detaches the returned solver-axis flow fields.
    audited = replace(case, parameters={**case.parameters, '_emit_audit': True})
    state, stage = _first_state(audited)
    assert all(np.all(np.isfinite(field)) for field in stage.arrays['hv'])
    for side, flow in zip('AB', stage.native['flow']):
        axes = prepared['axes'][side]
        epsilon = flow['epsilon'].transpose(axes['solver_to_real_perm'])
        if axes['is_reverse']:
            epsilon = np.flip(epsilon, axis=axes['stream_real_axis'])
        np.testing.assert_array_equal(epsilon, case.design_fields['eps_arr'])
    changed = replace(audited, design_fields={**case.design_fields, 'K_m2': case.design_fields['K_m2']*2.})
    changed_state, _ = _first_state(changed)
    for index in range(2):
        key = f'state.result.flow.{index}.permeability'
        np.testing.assert_array_equal(changed_state[key], state[key]*2.)
    bad_geometry = {**case.parameters['thermal_geometry'], 'split_A': 1.1}
    bad = replace(case, parameters={**case.parameters, 'thermal_geometry':bad_geometry})
    from sjtu_tpmshx.solvers.full_3d import validate_saved_case
    with pytest.raises(ValueError, match='side split'):
        validate_saved_case(bad)


def test_archived_bulk_hv_loads_but_does_not_set_local_heat_transfer(tmp_path, monkeypatch):
    from sjtu_tpmshx.file_io.case_io import save_case, load_case

    case = prepare_case(small_air_config(), case_id='archived-bulk-hv')
    assert 'air_bulk_hv' not in case.parameters['thermal_geometry']
    shape = tuple(len(case.grid['d' + axis]) for axis in 'xyz')
    geometry = {**case.parameters['thermal_geometry'],
                'air_bulk_hv': {side: np.full(shape, value)
                                for side, value in (('A', 123.), ('B', 456.))}}
    archived = replace(case, parameters={**case.parameters, 'thermal_geometry': geometry})
    save_case(archived, tmp_path / 'case.h5')
    loaded = load_case(tmp_path / 'case.h5')
    fields = []
    for prepared_case in (case, loaded):
        stage = run_stage(prepared_case, resolve_control(RunControl()))
        fields.append(stage.arrays['hv'][0])
    np.testing.assert_array_equal(fields[0], fields[1])
    assert np.any(fields[1] != 123.)
    invalid = {**geometry, 'air_bulk_hv': {'A': np.full(shape, np.nan)}}
    with pytest.raises(ValueError, match='bulk heat transfer'):
        save_case(replace(case, parameters={**case.parameters, 'thermal_geometry': invalid}),
                  tmp_path / 'invalid.h5')


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('end', ['inlet', 'outlet'])
def test_prepared_openings_match_actual_solver_geometry_before_solving(side, end, tmp_path, monkeypatch):
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from sjtu_tpmshx.file_io.case_io import save_case, load_case
    from sjtu_tpmshx.solvers.api import run_case

    config = small_air_config()
    config.solver = replace(config.solver, Nx=4, Ny=4, Nz=4, max_outer_ltne=2, max_iter_simple=500)
    full = prepare_case(config, case_id='full-opening')
    port = getattr(config, 'bc_' + side)
    width = 'in_w' if end == 'inlet' else 'out_w'
    partial = prepare_case(replace(config, **{'bc_' + side: replace(
        port, **{width: getattr(port, width) / 2.})}), case_id='partial-opening')
    for case in (full, partial):
        raw = run_stage(case, resolve_control(RunControl())).native
        for name, flow in zip('AB', raw['flow']):
            for boundary in ('inlet', 'outlet'):
                np.testing.assert_allclose(
                    case.parameters['prepared']['openings'][name][boundary],
                    flow[boundary+'_opening'], rtol=1e-12, atol=1e-15)
    parameters = mutable_data(full.parameters)
    parameters['prepared']['openings'][side][end] = partial.parameters['prepared']['openings'][side][end]
    save_case(replace(full, parameters=parameters), tmp_path / 'case.h5')
    restored = load_case(tmp_path / 'case.h5')
    entered = []
    with pytest.raises(ValueError, match='prepared full 3D openings disagree with rectangles'):
        run_case(restored, RunControl(progress=entered.append, outer_iteration=lambda *args: entered.append(args)))
    assert not entered, 'conflicting opening reached a PDE'
