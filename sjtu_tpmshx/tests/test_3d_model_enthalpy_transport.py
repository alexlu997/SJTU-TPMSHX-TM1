"""Model-h face transport: independent balances and production ownership."""

from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem
import inspect

import numpy as np
import pytest
from numba import get_num_threads, set_num_threads

from sjtu_tpmshx.solvers import _kernels_ltne_3d as kernels
from sjtu_tpmshx.solvers import ltne_energy_3d as energy
from sjtu_tpmshx.models.tpms_props import air_cp, model_h_coefficients


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('fraction', [.4, 1.])
@pytest.mark.parametrize('rb', [False, True])
def test_two_cell_model_h_balance(direction, fraction, rb):
    # Synthetic cp=2+.02*(T-300), not a replacement air correlation.
    coeff = (2., .02, 0., 300., 300.)
    constant = (2., 0., 0., 300., 300.)
    axis = direction // 2
    widths = [np.ones(2) for _ in range(3)]
    widths[axis] = np.array([2., 3.]) if direction % 2 == 0 else np.array([3., 2.])
    one = np.ones((2, 2, 2))
    def field(values):
        values = np.asarray(values)[::-1] if direction % 2 else np.asarray(values)
        shape = [1, 1, 1]; shape[axis] = 2
        return np.broadcast_to(values.reshape(shape), one.shape).copy()
    vol = field([2., 3.])
    expected_A = field([310., 305.])
    expected_S = field([310.-(1.3+5*fraction), 302.925])
    zero_faces = (np.zeros((3, 2, 2)), np.zeros((2, 3, 2)), np.zeros((2, 2, 3)))
    mass = tuple(f.copy() for f in zero_faces)
    mass[axis][:] = .1 * (1 if direction % 2 == 0 else -1)
    source_B = (300.-expected_S)/vol
    source_S = (2*expected_S-expected_A-300.)/vol
    fields = [one*308., one*300., one*304.]
    fn = kernels._gs_full_chunk_3d_stag_rb if rb else kernels._gs_full_chunk_3d_stag
    threads = get_num_threads()
    try:
        set_num_threads(2)
        fn(*fields, 2, 2, 2, *widths, one*.5, one*0, one*0,
           1/vol, 1/vol, one*.5, one*.5, one*10, one*10,
           *zero_faces, *zero_faces, direction, direction,
           np.full((2, 2), 320.), np.full((2, 2), 300.),
           np.full((2, 2), fraction), np.ones((2, 2)),
           2000, 0, .7, .7, .7, one*0, source_B, source_S, 1,
           model_mass_A=mass, model_mass_B=zero_faces,
           model_cp_A=coeff, model_cp_B=constant)
    finally:
        set_num_threads(threads)
    for actual, expected in zip(fields, (expected_A, one*300, expected_S)):
        np.testing.assert_allclose(actual, expected, rtol=0., atol=2e-7)
    budget = energy._model_h_balance(
        tuple(fields[:2]), fields[2], (mass, zero_faces), (coeff, constant),
        (direction, direction), (np.full((2, 2), 320.), np.full((2, 2), 300.)),
        (np.full((2, 2), fraction), np.ones((2, 2))),
        (one*.5, one*0), one*0, (1/vol, 1/vol), (one*.5, one*.5),
        (one*0, source_B), source_S, *widths)
    assert budget['physical_boundary_complete']
    assert budget['cell_count'] == 8
    assert budget['full_volume_m3'] == 20.
    assert abs(budget['telescoping_error_W']) < 1e-10
    assert abs(budget['full_residual_sum_W']) < 1e-7
    assert budget['physical_external_inward_W'] == pytest.approx(4*(3.375+5*fraction), abs=1e-7)


@pytest.mark.parametrize('sign', [-1., 1.])
def test_shared_sou_preserves_temperature_limiter_and_constant_cp(sign):
    T = np.broadcast_to(np.array([300., 310., 315., 330.])[:, None, None], (4, 2, 2)).copy()
    mass = (np.full((5, 2, 2), sign*.1), np.zeros((4, 3, 2)), np.zeros((4, 2, 3)))
    cp = model_h_coefficients('air')
    cap, deferred = kernels._model_h_faces(T, mass, cp, 0, np.full((2, 2), 320.), np.ones((2, 2)))
    # Face i=2: + flow has minmod(10,5)/2=2.5; - flow minmod(-15,-5)/2=-2.5.
    up = 310. if sign > 0 else 315.
    face_T = up + (2.5 if sign > 0 else -2.5)
    expected = sign*.1*kernels._model_h(face_T, cp)
    np.testing.assert_allclose(cap[0][2]*up+deferred[0][2], expected, rtol=1e-13)
    constant = (2., 0., 0., 300., 300.)
    fc, dc = kernels._model_h_faces(T, mass, constant, 0, np.full((2, 2), 320.), np.ones((2, 2)))
    np.testing.assert_allclose(fc[0], mass[0]*2.)
    np.testing.assert_allclose(fc[0][2]*up+dc[0][2], sign*.1*2*(face_T-300.))
    assert float(air_cp(350.)) == pytest.approx(cp[0]+cp[1]*(350-cp[3])+cp[2]*(350-cp[3])**2)


def test_nonzero_mass_divergence_and_unknown_external_inflow():
    one = np.ones((2, 2, 2)); T = one*310
    mass = (np.zeros((3, 2, 2)), np.zeros((2, 3, 2)), np.zeros((2, 2, 3)))
    mass[0][-1] = -.1  # Non-inlet inflow: numerical self, no physical h supplied.
    zero = tuple(np.zeros_like(f) for f in mass)
    coeff = (2., 0., 0., 300., 300.)
    r, _, _ = energy._conservation_residual_sum(
        T, T, *zero, one*.5, one*0, one*0, one*0,
        np.ones(2), np.ones(2), np.ones(2), 0, T[0], one[0], one*0,
        model_mass=mass, model_cp=coeff, return_field=True)
    # c*(T-T0)*div(m), including the often-lost -c*T0*div(m) term.
    np.testing.assert_allclose(r, 20*kernels._face_divergence(mass), atol=1e-12)
    budget = energy._model_h_balance(
        (T, T), T, (mass, zero), (coeff, coeff), (0, 0), (T[0], T[0]),
        (one[0], one[0]), (one*0, one*0), one*0, (one*0, one*0),
        (one*.5, one*.5), (one*0, one*0), one*0, np.ones(2), np.ones(2), np.ones(2))
    assert not budget['physical_boundary_complete']
    assert budget['physical_external_inward_W'] is None
    assert budget['sides']['A']['faces']['x+']['unknown_inflow_count'] == 4
    assert abs(budget['telescoping_error_W']) < 1e-12


@pytest.mark.parametrize('pair,var,nz,enabled', [
    (('air', 'air'), True, 4, True),
    (('air', 'water'), True, 4, True),
    (('water', 'air'), True, 4, True),
    (('water', 'water'), True, 4, False),
    (('air', 'sco2'), True, 4, False),
    (('air', 'air'), False, 4, False),
    (('air', 'air'), True, 1, False),
])
def test_actual_pipeline_gate_and_prebalance_mass(monkeypatch, pair, var, nz, enabled):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
    cfg = _pipeline_cfg(pair, nz)
    cfg.update(variable_rho_cp=var)
    monkeypatch.delenv('TPMSHX_VAR_RHOCP', raising=False)
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(cfg)
    hv = stages._build_hv_machinery(prob)
    for solver in (prob.sA, prob.sB):
        solver.v[:] = .02
        solver.rho_field[:] *= 1.3
    balances = []
    def balance(faces, *args):
        balances.append(True)
        for face in faces:
            face *= 9.
    monkeypatch.setattr(stages, '_balance_stream_outflow', balance)
    class Observed(Exception):
        pass
    signature = inspect.signature(energy.solve_full_domain_3d)
    def observe(*args, **kwargs):
        call = signature.bind(*args, **kwargs).arguments
        assert ('model_fluids' in call) == enabled
        if enabled:
            assert not balances
            assert call['model_fluids'] == pair
            for side, solver, eps in (('A', prob.sA, prob.eps_fA_arr), ('B', prob.sB, prob.eps_fB_arr)):
                # Both configured streams map to real y. B is reversed.
                rho = solver.rho_field if side == 'A' else solver.rho_field[:, ::-1, :]
                velocity = solver.v if side == 'A' else -solver.v[:, ::-1, :]
                re = rho*eps
                expected = np.empty_like(velocity)
                expected[:, 1:-1] = .5*(re[:, :-1]+re[:, 1:])
                expected[:, 0] = re[:, 0]; expected[:, -1] = re[:, -1]
                expected = expected * velocity * prob.dx[:, None, None] * prob.dz[None, None, :]
                np.testing.assert_array_equal(call[f'model_mass_{side}'][1], expected)
        raise Observed
    monkeypatch.setattr(stages, 'solve_full_domain_3d', observe)
    monkeypatch.setattr(stages, 'run_outer_coupling', lambda *, step, **kwargs: step(0))
    with pytest.raises(Observed):
        stages._run_outer_coupling_3d(prob, hv)


def _pipeline_cfg(pair=('air', 'air'), nz=4):
    from sjtu_tpmshx.models.tpms_props import geometry
    def port(direction):
        return dict(dir=direction, in_ctr=.015, in_w=.03, out_ctr=.015, out_w=.03,
                    in_z_ctr=.015, in_z_w=.03, out_z_ctr=.015, out_z_w=.03)
    return dict(L=.03, H=.03, Lz=.03, Nx=4, Ny=4, Nz=nz,
                u_A=.02, u_B=.02, T_inA=350., T_inB=300.,
                P_inA=200000., P_inB=12000000. if pair[1]=='sco2' else 200000.,
                T_s_init=325., tpms_type='Gyroid', Lcell=7., t_wall=.6, k_s=16.,
                eps=geometry('Gyroid', 7., .6, 16.)['epsilon'],
                fluid_type_A=pair[0], fluid_type_B=pair[1],
                fluid_A_cfg=port(2), fluid_B_cfg=port(3),
                wall_refine_3d=False, outer_anderson=False, p_in_shooting=False)


@pytest.mark.parametrize('cap', [False, True])
@pytest.mark.parametrize('invalid', [None, ('A', 'unknown'), ('B', 'nan'), ('A', 'inf')])
def test_model_h_ledger_reaches_result_before_final_post(monkeypatch, cap, invalid):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    signature = inspect.signature(energy.solve_full_domain_3d)
    seen = []
    def thermal(*args, **kwargs):
        call = signature.bind(*args, **kwargs).arguments
        shape = call['Nx'], call['Ny'], call['Nz']
        ledger = dict(physical_boundary_complete=False, physical_external_inward_W=None,
                      numerical_external_inward_W=1.25*(len(seen)+1), sides={
            side: dict(physical_boundary_complete=True,
                       convective_inward_W=value*(len(seen)+1), inlet_diffusion_inward_W=7.)
            for side, value in (('A', 156.), ('B', -228.))})
        if invalid is not None:
            side, reason = invalid
            if reason == 'unknown':
                ledger['sides'][side]['physical_boundary_complete'] = False
            else:
                ledger['sides'][side]['convective_inward_W'] = float(reason)
        seen.append(ledger)
        return (np.full(shape, 340.), np.full(shape, 310.), np.full(shape, 325.),
                dict(converged=True, iterations=250, residual=1e-8, model_h_balance=ledger))
    def outer(*, step, post, **kwargs):
        for n in range(2):
            _, carry = step(n)
            if n == 1 and not cap:
                return n, True
            post(n, carry)
        return 1, False
    monkeypatch.setattr(stages, 'solve_full_domain_3d', thermal)
    monkeypatch.setattr(stages, 'run_outer_coupling', outer)
    raw = _run_3d_stack(_pipeline_cfg())
    ledger = raw['model_h_balance']
    assert ledger['numerical_external_inward_W'] == 2.5
    assert ledger['physical_external_inward_W'] is None
    assert ledger['outer_index'] == 1
    assert ledger['post_after_last_thermal'] == cap
    assert ledger['outer_converged'] == (not cap)
    assert raw['true_h_balance'] is None
    for side, expected in (('A', 312.), ('B', 456.)):
        values = [raw['Q_enthalpy_'+side]]
        if side == 'A':
            values += [raw['Q'], raw['Q_total']]
        if invalid is not None and side == invalid[0]:
            assert all(np.isnan(value) for value in values)
        else:
            assert all(value == expected for value in values)


@pytest.mark.parametrize('cap', [False, True])
def test_native_thermal_snapshot_survives_final_post(monkeypatch, cap):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
    from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(_pipeline_cfg())
    hv = stages._build_hv_machinery(prob)
    signature = inspect.signature(energy.solve_full_domain_3d)
    consumed = {}

    def thermal(*args, **kwargs):
        call = signature.bind(*args, **kwargs).arguments
        consumed.update({name: call[name].copy() for name in ('rho_cp_fA', 'rho_cp_fB')})
        shape = prob.Nx, prob.Ny, prob.Nz
        return (np.full(shape, 340.), np.full(shape, 310.), np.full(shape, 325.),
                dict(converged=True, iterations=1, residual=0.))

    def drive(*, step, post, **kwargs):
        _, carry = step(0)
        if cap:
            post(0, carry)
        return 0, not cap

    monkeypatch.setattr(stages, 'solve_full_domain_3d', thermal)
    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    outer = stages._run_outer_coupling_3d(prob, hv, capture_native=True)
    native = outer.native_evidence
    assert native['outer_index'] == 0 and outer._outer_converged == (not cap)
    assert '_native_evidence' not in prob.cfg
    for side in ('A', 'B'):
        np.testing.assert_array_equal(native['rho_cp_' + side], consumed['rho_cp_f' + side])
        assert not np.shares_memory(native['rho_cp_' + side], getattr(outer, 'rho_cp_f' + side))
        assert not np.shares_memory(native['h_v' + side], getattr(outer, 'h_v' + side + '_field'))
    outer.Ta[:] = 350.
    prob.K_ss[:] = 0.
    np.testing.assert_array_equal(native['Ta'], 340.)
    assert np.all(native['K_ss'] > 0.)


def test_reported_model_h_two_unequal_outlets_excludes_diffusion(monkeypatch):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
    # Two CVs with unequal outlet masses. Independent h=2*theta+.01*theta**2:
    # h(340)=96, h(310)=21, h(330)=69; 4*96-(1*21+3*69)=156 W.
    # cp(340)*4*(340-325)=168 and 4*(h(340)-h(325))=159 are both wrong.
    one = np.ones((1, 1, 2)); T = np.array([[[310., 330.]]])
    mass = (np.broadcast_to([1., 3.], (2, 1, 2)).copy(),
            np.zeros((1, 2, 2)), np.zeros((1, 1, 3)))
    coeff = (2., .02, 0., 300., 300.)
    ledger = energy._model_h_balance(
        (T, T), one*320., (mass, tuple(-f for f in mass)), (coeff, coeff),
        (0, 1), (one[0]*340., one[0]*300.), (one[0], one[0]),
        (one*.0875, one*0), one*0, (one*0, one*0), (one*.5, one*.5),
        (one*0, one*0), one*0, np.ones(1), np.ones(1), np.ones(2))
    assert ledger['sides']['A']['convective_inward_W'] == pytest.approx(156.)
    assert ledger['sides']['B']['convective_inward_W'] == pytest.approx(-228.)
    assert ledger['sides']['A']['inlet_diffusion_inward_W'] == pytest.approx(7.)
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (
        T.copy(), T.copy(), one*320.,
        dict(converged=True, iterations=250, residual=0., model_h_balance=ledger)))
    def outer(*, step, **kwargs):
        step(0)
        return 0, True
    monkeypatch.setattr(stages, 'run_outer_coupling', outer)
    cfg = _pipeline_cfg(nz=2)
    cfg.update(Nx=1, Ny=1, T_inA=340.)
    cfg['fluid_A_cfg']['dir'] = 0
    cfg['fluid_B_cfg']['dir'] = 1
    raw = _run_3d_stack(cfg)
    assert raw['Q_total'] == pytest.approx(156.)
    assert raw['Q_enthalpy_B'] == pytest.approx(228.)


def test_report_without_model_h_ledger_keeps_original_cp_temperature(monkeypatch):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    def thermal(*args, **kwargs):
        return (np.full((4, 4, 4), 325.), np.full((4, 4, 4), 325.),
                np.full((4, 4, 4), 325.), dict(converged=True, iterations=250, residual=0.))
    monkeypatch.setattr(stages, 'solve_full_domain_3d', thermal)
    monkeypatch.setattr(stages, '_simple_mass_flow', lambda *a, **k: 4.)
    def outer(*, step, **kwargs):
        step(0)
        return 0, True
    monkeypatch.setattr(stages, 'run_outer_coupling', outer)
    cfg = _pipeline_cfg()
    cfg['variable_rho_cp'] = False
    monkeypatch.delenv('TPMSHX_VAR_RHOCP', raising=False)
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
    raw = _run_3d_stack(cfg)
    assert raw['Q'] == pytest.approx(4*float(air_cp(350.))*25.)
    assert raw['Q_enthalpy_B'] == pytest.approx(4*float(air_cp(300.))*25.)


def test_driver_skips_capacity_projection_and_keeps_sweep_budget(monkeypatch):
    shape = (3, 2, 2)
    one = np.ones(shape)
    faces = (np.zeros((4, 2, 2)), np.zeros((3, 3, 2)), np.zeros((3, 2, 3)))
    mass = tuple(f.copy() for f in faces)
    mass[0][:] = .01
    calls = []
    signature = inspect.signature(kernels._gs_full_chunk_3d_stag)
    def chunk(*args):
        call = signature.bind(*args).arguments
        calls.append(call['n_iters'])
        assert call['model_mass_A'] is not None
        # Returned temperatures deliberately differ from the initial fields.
        call['Ta'][:] = 315.
        call['Tb'][:] = 305.
        call['Ts'][:] = 310.
        return 1.
    def forbidden(*args, **kwargs):
        pytest.fail('qualified model h must not project capacity faces')
    monkeypatch.setattr(energy, '_gs_full_chunk_3d_stag', chunk)
    monkeypatch.setattr(energy, '_project_faces_div_free', forbidden)
    ta, tb, ts, info = energy.solve_full_domain_3d(
        3., 2., 2., *shape, 320., 300., one*.1, one*.1, one*.1,
        one, one, one*999., one*888., one,
        *([one*0]*6), dir_A=0, dir_B=0,
        ufA=faces[0], vfA=faces[1], wfA=faces[2],
        ufB=faces[0], vfB=faces[1], wfB=faces[2],
        model_mass_A=mass, model_mass_B=mass, model_fluids=('air', 'water'),
        conservative_ltne=True, max_iter=3, conv_chunk=2, return_info=True)
    assert calls == [2, 1]
    assert info['iterations'] == 3
    assert info['converged']  # Stable second chunk may qualify on the last allowed sweep.
    ledger = info['model_h_balance']
    assert ledger['sides']['A']['temperature_range_K'] == [315., 315.]
    expected = .04*(kernels._model_h(320., model_h_coefficients('air'))
                    - kernels._model_h(315., model_h_coefficients('air')))
    assert ledger['sides']['A']['convective_inward_W'] == pytest.approx(expected)
    assert ledger['sides']['B']['convective_inward_W'] == pytest.approx(.04*4182*(300.-305.))
    assert abs(ledger['telescoping_error_W']) < 1e-8


@pytest.mark.parametrize('rb', [False, True])
def test_picard_coefficients_frozen_for_entire_sweep(rb):
    one = np.ones((2, 2, 2))
    ta = np.broadcast_to(np.array([310., 305.])[:, None, None], one.shape).copy()
    tb, ts = one*300., one*300.
    expected = ta.copy()
    # Independently differentiated synthetic h at the START of the sweep.
    cp = (2.2, 2.1); intercept = (-661., -630.25)
    cells = list(np.ndindex(one.shape))
    if rb:
        cells = [p for color in range(2) for p in cells if sum(p) % 2 == color]
    for i, j, k in cells:
        incoming = 4.4 if i == 0 else .1*(cp[0]*expected[0, j, k]+intercept[0])
        new = (300.+incoming-.1*intercept[i])/(1.+.1*cp[i])
        expected[i, j, k] += .7*(new-expected[i, j, k])
    zero = (np.zeros((3, 2, 2)), np.zeros((2, 3, 2)), np.zeros((2, 2, 3)))
    mass = tuple(f.copy() for f in zero); mass[0][:] = .1
    fn = kernels._gs_full_chunk_3d_stag_rb if rb else kernels._gs_full_chunk_3d_stag
    threads = get_num_threads()
    try:
        set_num_threads(2)
        fn(ta, tb, ts, 2, 2, 2, np.ones(2), np.ones(2), np.ones(2),
           one*0, one*0, one*0, one, one*0, one*.5, one*.5, one, one,
           *zero, *zero, 0, 0, one[0]*320, one[0]*300, one[0], one[0],
           1, 0, .7, .7, .7, one*0, one*0, one*0, 1,
           model_mass_A=mass, model_mass_B=zero,
           model_cp_A=(2., .02, 0., 300., 300.), model_cp_B=(2., 0., 0., 300., 300.))
    finally:
        set_num_threads(threads)
    np.testing.assert_allclose(ta, expected, rtol=0., atol=1e-12)
