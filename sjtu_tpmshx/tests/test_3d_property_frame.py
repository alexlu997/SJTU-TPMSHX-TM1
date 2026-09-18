"""Exercise the wired outer property refresh without running numerical sweeps."""

from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem
import inspect

import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
from sjtu_tpmshx.models.tpms_props import geometry


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2'])
@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('variable_rho_cp', [False, True])
@pytest.mark.parametrize('thermal_start', ['post', 'warm', 'cold'])
def test_outer_temperature_properties_share_simple_frame(
        monkeypatch, fluid, direction, variable_rho_cp, thermal_start):
    # Unequal dimensions and a gradient on every axis expose wrong permutations
    # as well as missing reflections. Both A and B visit all six directions.
    shape = (4, 5, 6)
    lengths = (.04, .05, .06)
    directions = (direction, (direction + 2) % 6)
    pressure = 12e6 if fluid == 'sco2' else 2e6

    def port(d):
        cross1 = 1 if d < 2 else 0
        cross2 = 1 if d >= 4 else 2
        w, wz = lengths[cross1], lengths[cross2]
        return dict(dir=d, in_ctr=w/2, in_w=w, out_ctr=w/2, out_w=w,
                    in_z_ctr=wz/2, in_z_w=wz, out_z_ctr=wz/2, out_z_w=wz)

    cfg = dict(L=lengths[0], H=lengths[1], Lz=lengths[2],
               Nx=shape[0], Ny=shape[1], Nz=shape[2],
               u_A=.02, u_B=.02, T_inA=350., T_inB=300.,
               P_inA=pressure, P_inB=pressure, T_s_init=325.,
               tpms_type='Gyroid', Lcell=7., t_wall=.6, k_s=16.,
               eps=geometry('Gyroid', 7., .6, 16.)['epsilon'],
               fluid_type_A=fluid, fluid_type_B=fluid,
               fluid_A_cfg=port(directions[0]), fluid_B_cfg=port(directions[1]),
               wall_refine_3d=False, outer_anderson=False, p_in_shooting=False)
    cfg['variable_rho_cp'] = variable_rho_cp
    if thermal_start == 'cold':
        cfg.pop('T_s_init')
    monkeypatch.delenv('TPMSHX_SCO2_COMPRESSIBLE', raising=False)
    monkeypatch.delenv('TPMSHX_VAR_RHOCP', raising=False)
    observations = {}

    def solve(solver, **kwargs):
        # The real update_T_field and all post-refresh code execute; only the
        # expensive SIMPLE sweeps are replaced by an observation at entry.
        if id(solver) in observations:
            observations[id(solver)].append(tuple(
                getattr(solver, name).copy()
                for name in ('T_field', 'rho_field', 'mu_field', '_mu_eff_field')))
        return True, 0

    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', solve)
    prob = _build_3d_problem(cfg)
    hv = stages._build_hv_machinery(prob)
    model = stages.fluid_props.get(fluid)

    class InletObserved(Exception):
        pass

    signature = inspect.signature(stages.solve_full_domain_3d)
    expected_inlets = {}
    expected_capacity = {}

    def observe_inlet(*args, **kwargs):
        call = signature.bind(*args, **kwargs).arguments
        for side in ('A', 'B'):
            np.testing.assert_allclose(call[f'inlet_flux_{side}'], expected_inlets[side],
                                       rtol=2e-15, atol=0.)
            np.testing.assert_allclose(call[f'rho_cp_f{side}'], expected_capacity[side],
                                       rtol=2e-15, atol=0.)
        raise InletObserved

    monkeypatch.setattr(stages, 'solve_full_domain_3d', observe_inlet)

    def drive(*, step, post, **kwargs):
        state = vars(inspect.getclosurevars(post).nonlocals["state"])
        solvers = (prob.sA, prob.sB)
        for solver in solvers:
            observations[id(solver)] = []
            solver.P[:] = np.arange(solver.P.size).reshape(solver.P.shape) * 10.
            x, _, z = np.indices(solver.v.shape)
            # Face-averaged openings are already represented in actual v.
            solver.v[:] = .02 * np.array([0., .4, 1.])[(x+z) % 3]
        i, j, k = np.indices(shape)
        marker = i + 2*j + .5*k
        def check_thermal(outer):
            for side, solver, d, tin, eps in zip(
                    ('A', 'B'), solvers, directions, (350., 300.),
                    (prob.eps_fA_arr, prob.eps_fB_arr)):
                # Deliberately stale internal capacity must be replaced only
                # on the approved air/variable-rho route.
                state[f'rho_cp_f{side}'][:] *= 1.7
                expected_capacity[side] = state[f'rho_cp_f{side}'].copy()
                if fluid == 'air' and variable_rho_cp:
                    mapped_rho = np.empty(shape)
                    for x, y, z in np.ndindex(solver.rho_field.shape):
                        real = [y, x, z] if d < 2 else ([x, y, z] if d < 4 else [x, z, y])
                        if d % 2:
                            real[d//2] = shape[d//2]-1-real[d//2]
                        mapped_rho[tuple(real)] = solver.rho_field[x, y, z]
                    temperature = state['Ta' if side == 'A' else 'Tb']
                    expected_capacity[side] = mapped_rho * stages.air_cp(
                        tin if temperature is None else temperature)
                cross = [axis for axis in range(3) if axis != d//2]
                wanted = np.empty(tuple(shape[axis] for axis in cross))
                for a, b in np.ndindex(wanted.shape):
                    real = [0, 0, 0]
                    real[d//2] = shape[d//2]-1 if d % 2 else 0
                    real[cross[0]], real[cross[1]] = a, b
                    area = (prob.dx, prob.dy, prob.dz)[cross[0]][a] * (
                        prob.dx, prob.dy, prob.dz)[cross[1]][b]
                    wanted[a, b] = (solver.rho_field[a, 0, b] * solver.v[a, 0, b]
                                    * eps[tuple(real)] * area * model.cp(tin, pressure))
                expected_inlets[side] = wanted
            with pytest.raises(InletObserved):
                step(outer)

        if thermal_start != 'post':
            for solver in solvers:
                solver.rho_field[:] *= 1.2
            if thermal_start == 'warm':
                state['Ta'][:] = 340.-marker
                state['Tb'][:] = 310.+marker
            check_thermal(0)
            # Stop before final-report consumers of absent cold-start fields.
            raise InletObserved
        # Use existing mutable thermal warm-start fields to feed the actual
        # callback; no copied source or stand-alone mapping helper is tested.
        for outer in (0, 1):
            state['Ta'][:] = 340. - marker - outer
            state['Tb'][:] = 310. + marker + 2*outer
            expected = []
            for solver, d, temperature in zip(solvers, directions,
                                               (state['Ta'], state['Tb'])):
                mapped = np.empty_like(solver.T_field)
                # Independent index oracle: SIMPLE j is the stream coordinate.
                for x, y, z in np.ndindex(mapped.shape):
                    real = [y, x, z] if d < 2 else ([x, y, z] if d < 4 else [x, z, y])
                    if d % 2:
                        real[d//2] = shape[d//2] - 1 - real[d//2]
                    mapped[x, y, z] = temperature[tuple(real)]
                rho = ((solver.P_ref_abs + solver.P) / (stages.R_AIR * mapped)
                       if model.compressible else model.rho(mapped, pressure))
                mu = model.mu(mapped, pressure)
                if outer:
                    rho = stages._ALPHA_T*rho + (1-stages._ALPHA_T)*solver.rho_field
                    # update_T_field refreshes air mu before A's blend and
                    # after B's blend. Preserve that existing ordering.
                    if not model.compressible:
                        mu = stages._ALPHA_T*mu + (1-stages._ALPHA_T)*solver.mu_field
                expected.append((mapped, rho, mu, mu/solver.eps_field))
            previous_capacity = [state[f'rho_cp_f{side}'].copy() for side in ('A', 'B')]
            post(outer, None)
            for side, solver, temperature, previous in zip(
                    ('A', 'B'), solvers, (state['Ta'], state['Tb']), previous_capacity):
                if fluid == 'air' and variable_rho_cp:
                    # This route refreshes only at the next thermal call.
                    np.testing.assert_array_equal(state[f'rho_cp_f{side}'], previous)
                elif not variable_rho_cp or side == 'B':
                    np.testing.assert_allclose(
                        state[f'rho_cp_f{side}'], model.rho(temperature, pressure)
                        * model.cp(temperature, pressure), rtol=2e-15, atol=0.)
            for solver, fields in zip(solvers, expected):
                assert len(observations[id(solver)]) == outer + 1
                for actual, wanted in zip(observations[id(solver)][-1], fields):
                    np.testing.assert_allclose(actual, wanted, rtol=2e-15, atol=0.)
                    assert actual.flags.c_contiguous
            # Exercise the real next thermal call with deliberately distinct
            # internal rho-cp. The oracle uses original SIMPLE inlet faces,
            # independent index mapping, and the registry's declared Tin/Pin.
            check_thermal(outer)
        return 1, False

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    if thermal_start == 'post':
        stages._run_outer_coupling_3d(prob, hv)
    else:
        with pytest.raises(InletObserved):
            stages._run_outer_coupling_3d(prob, hv)
