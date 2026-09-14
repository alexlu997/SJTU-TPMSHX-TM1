"""Vectorised T(h,P) inverse for the Option B enthalpy-form 3D LTNE rewrite.

The conservative enthalpy kernel keeps h as the primary fluid unknown; the
3D Python backend must invert T = T(h,P) each outer iteration to feed the
diffusion/inter-phase coupling. sco2_temperature_field is the field counterpart
of the scalar sco2_temperature (the per-cell array form the kernel refresh needs).
"""
import numpy as np
import pytest

from sjtu_tpmshx.models import sco2_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")

@pytest.mark.parametrize('pressure', [7.9e6, 8e6, 16e6])
def test_temperature_field_round_trips_enthalpy_field(pressure):
    """T(h(T)) == T over a field spanning the pseudocritical line."""
    T = np.array([[290.0, 307.0], [312.0, 360.0]])
    h = sco2_props.sco2_enthalpy_field(T, pressure)
    T_back = sco2_props.sco2_temperature_field(h, pressure)
    assert T_back.shape == T.shape
    assert np.allclose(T_back, T, atol=1e-3)


@pytest.mark.parametrize('pressure', [7.9e6, 8e6, 16e6])
def test_temperature_field_matches_scalar(pressure):
    """Field query agrees with the scalar sco2_temperature element-wise."""
    h = np.array([sco2_props.sco2_enthalpy(300.0, pressure),
                  sco2_props.sco2_enthalpy(330.0, pressure)])
    Tf = sco2_props.sco2_temperature_field(h, pressure)
    assert Tf[0] == pytest.approx(sco2_props.sco2_temperature(float(h[0]), pressure), rel=1e-9)
    assert Tf[1] == pytest.approx(sco2_props.sco2_temperature(float(h[1]), pressure), rel=1e-9)


@pytest.mark.parametrize('pressure', [np.nextafter(7.9e6, -np.inf),
                                    np.nextafter(16e6, np.inf)])
def test_property_and_inverse_reject_pressure_before_eos(monkeypatch, pressure):
    def unexpected_eos(*args):
        pytest.fail('out-of-range pressure reached EOS')
    monkeypatch.setattr(sco2_props, '_PropsSI', unexpected_eos)
    for temperature, enthalpy in ((330., 4e5), (np.array([330.]), np.array([4e5]))):
        with pytest.raises(ValueError, match=r'pressure must be within 7.9..16 MPa'):
            sco2_props.sco2_prop('H', temperature, pressure)
        with pytest.raises(ValueError, match=r'pressure must be within 7.9..16 MPa'):
            sco2_props.sco2_temperature_from_enthalpy(enthalpy, pressure)


@pytest.mark.parametrize('temperature, message', [(np.nan, 'must be finite'),
                                                (279., 'temperature must be')])
def test_state_error_order_precedes_pressure(temperature, message):
    with pytest.raises(ValueError, match=message + r'.*index=\(1,\)'):
        sco2_props._validate_state([330., temperature], [8e6, 7.9e6 - 1.],
                                   where='paired state')


@pytest.mark.parametrize('temperature,pressure', [(279., 12e6), (701., 12e6),
                                                 (330., 7.9e6 - 1.), (330., 16.1e6)])
def test_true_h_rejects_normal_eos_outside_model(temperature, pressure):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    # A normal EOS value is not proof that the production model supports it.
    h = ent._h_scalar(temperature, pressure, 'sco2')
    with pytest.raises(ValueError, match='enthalpy EOS return B.*index='):
        ent._T_of_h_field(np.array([h]), pressure, 'sco2',
                          where='enthalpy EOS return B')


@pytest.mark.parametrize('temperature,pressure', [(np.nan, 12e6), (330., np.inf),
                                                 (701., 12e6), (330., 7.9e6 - 1.)])
def test_true_h_property_field_checks_paired_states_before_eos(monkeypatch, temperature, pressure):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    def unexpected_eos(*args):
        pytest.fail('invalid actual state reached EOS')
    monkeypatch.setattr(ent, '_PropsSI', unexpected_eos)
    with pytest.raises(ValueError, match=r'index=\(1,\).*T=.* K, P=.* Pa'):
        ent._prop_field('H', np.array([320., temperature]),
                        np.array([8e6, pressure]), 'sco2')


def _guard_pipeline(**kwargs):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    cell = np.ones((1, 1, 1))
    values = dict(Nx=1, Ny=1, Nz=1, dx=[.01], dy=[.01], dz=[.01],
                  eps_arr=cell*.7, K_ss=cell*5., h_vA_field=cell*100.,
                  h_vB_field=cell*100., m_dot_A=.01, m_dot_B=.01,
                  T_inA=330., T_inB=320., P_A=12e6, P_B=12e6,
                  dir_A=0, dir_B=1, n_outer=1)
    values.update(kwargs)
    return ent.solve_ltne_enthalpy_3d_pipeline(**values)


@pytest.mark.parametrize('side', ['A', 'B'])
def test_true_h_inlet_rejects_before_eos(monkeypatch, side):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    def unexpected_eos(*args):
        pytest.fail('invalid inlet reached EOS')
    monkeypatch.setattr(ent, '_PropsSI', unexpected_eos)
    with pytest.raises(ValueError, match='inlet ' + side):
        _guard_pipeline(**{'T_in' + side: 701.})


@pytest.mark.parametrize('warm_start', [False, True])
@pytest.mark.parametrize('side', ['A', 'B'])
def test_true_h_initial_state_checks_local_pressure(side, warm_start):
    fields = {'pressure_' + side + '_field': np.full((1, 1, 1), 7.9e6 - 1.)}
    if warm_start:
        fields['T' + side.lower() + '_init'] = np.full((1, 1, 1), 330.)
    with pytest.raises(ValueError, match='warm start ' + side + r'.*P=7899999.0 Pa'):
        _guard_pipeline(**fields)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('fluids', [('sco2', 'sco2'), ('sco2', 'air'),
                                  ('sco2', 'water'), ('air', 'sco2'),
                                  ('water', 'sco2')])
def test_true_h_local_pressure_floor_routes_without_sweeps(monkeypatch, dimension, fluids):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d

    # Exercise inlet, warm start, property refresh and EOS return, without a PDE solve.
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', lambda *args: None)
    p_in = [8e6 if fluid == 'sco2' else 2e5 for fluid in fluids]
    p_local = [7.9e6 if fluid == 'sco2' else 2e5 for fluid in fluids]
    if dimension == 3:
        cell = np.full((1, 1, 1), 330.)
        Ta, Tb, _, info = _guard_pipeline(
            fluid_A=fluids[0], fluid_B=fluids[1], P_A=p_in[0], P_B=p_in[1],
            T_inA=330., T_inB=330., Ta_init=cell, Tb_init=cell,
            pressure_A_field=np.full(cell.shape, p_local[0]),
            pressure_B_field=np.full(cell.shape, p_local[1]))
    else:
        cell = np.full((1, 1), 330.)
        flux = (np.full((2, 1), .01), np.zeros((1, 2)))
        Ta, Tb, _, info = solve_enthalpy_2d(
            330., 330., p_local[0], p_local[1], flux, flux,
            100., 100., 5., .35, .35, [.01], [.01],
            fluid_A=fluids[0], fluid_B=fluids[1],
            P_inA=p_in[0], P_inB=p_in[1], Ta_init=cell, Tb_init=cell, max_iter=1)
    np.testing.assert_allclose(Ta, 330., atol=1e-6)
    np.testing.assert_allclose(Tb, 330., atol=1e-6)
    native = info['_native_state']
    assert native['sco2_enthalpy_eos']['sides'] == [
        side for side, fluid in zip(('A', 'B'), fluids) if fluid == 'sco2']
    for side, T, fluid, pressure in zip(('A', 'B'), (Ta, Tb), fluids, p_local):
        exact = ent._T_of_h_field(native['h_' + side], pressure, fluid)
        np.testing.assert_array_equal(T, exact.reshape(T.shape))


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('iterations', [1, 2])
def test_true_h_refresh_and_final_return_reject(monkeypatch, dimension, side, iterations):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d
    h_bad = ent._h_scalar(701., 12e6, 'sco2')
    def invalid_after_sweep(hA, hB, *args):
        (hA if side == 'A' else hB)[:] = h_bad
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', invalid_after_sweep)
    stage = 'final' if iterations == 1 else 'iteration'
    with pytest.raises(ValueError, match=f'enthalpy {stage} EOS return {side}'):
        if dimension == 3:
            _guard_pipeline(n_outer=iterations)
        else:
            flux = (np.full((2, 1), .01), np.zeros((1, 2)))
            solve_enthalpy_2d(330., 320., 12e6, 12e6, flux, flux,
                100., 100., 5., .35, .35, [.01], [.01],
                P_inA=12e6, P_inB=12e6, max_iter=iterations)


@pytest.mark.parametrize('temperature', [280., 700.])
def test_true_h_boundary_allows_mathematical_bracket_outside_model(monkeypatch, temperature):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    original = ent._PropsSI
    bracket_queries = []

    def eos(key, input_key, value, *args):
        if key == 'T':
            return np.full(np.shape(value), temperature)
        if key == 'H' and input_key == 'T' and np.ndim(value) == 0:
            bracket_queries.append(float(value))
        return original(key, input_key, value, *args)

    monkeypatch.setattr(ent, '_PropsSI', eos)
    Ta, Tb, _, _ = _guard_pipeline(T_inA=temperature, T_inB=temperature)
    assert max(temperature - 60., 230.) in bracket_queries
    assert temperature + 60. in bracket_queries
    np.testing.assert_array_equal(Ta, temperature)
    np.testing.assert_array_equal(Tb, temperature)


@pytest.mark.parametrize('temperature', [280., 700.])
def test_true_h_real_boundary_roundtrip_obeys_strict_return_domain(temperature):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    h = np.array([ent._h_scalar(temperature, 12e6, 'sco2')])
    raw = np.asarray(ent._PropsSI('T', 'H', h, 'P', np.array([12e6]), 'CO2')).reshape(1)
    # Exact-boundary inputs can round-trip outside the domain on some platforms.
    if raw[0] < 280. or raw[0] > 700.:
        with pytest.raises(ValueError, match='temperature must be within 280..700 K'):
            ent._T_of_h_field(h, 12e6, 'sco2')
    else:
        np.testing.assert_array_equal(ent._T_of_h_field(h, 12e6, 'sco2'), raw)


@pytest.mark.parametrize('boundary,direction', [(280., -np.inf), (700., np.inf)])
def test_true_h_one_ulp_outside_boundary_is_rejected(monkeypatch, boundary, direction):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    raw = np.array([np.nextafter(boundary, direction)])
    monkeypatch.setattr(ent, '_PropsSI', lambda *args: raw)
    with pytest.raises(ValueError, match='temperature must be within 280..700 K'):
        ent._T_of_h_field(np.ones(1), 12e6, 'sco2')
    assert raw[0] == np.nextafter(boundary, direction)


@pytest.mark.parametrize('returned', [np.nan, np.inf])
def test_true_h_nonfinite_eos_return_is_rejected(monkeypatch, returned):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    monkeypatch.setattr(ent, '_PropsSI', lambda *args: [330., returned])
    with pytest.raises(ValueError, match=r'must be finite.*index=\(1,\)'):
        ent._T_of_h_field(np.ones(2), np.array([8e6, 16e6]), 'sco2')


@pytest.mark.parametrize('temperature', [279., 280., 700., 701.])
def test_iteration_table_cannot_mask_heos_domain_boundaries(temperature):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    pressure = np.array([12e6])
    # A non-state sentinel makes any accidental table evaluation fail.
    lookup = ent._sco2_iteration_lookup(pressure, object())
    h = np.array([ent._h_scalar(temperature, 12e6, 'sco2')])
    try:
        exact = ent._T_of_h_field(h, pressure, 'sco2')
    except ValueError:
        with pytest.raises(ValueError, match='temperature must be within'):
            ent._T_of_h_field(h, pressure, 'sco2', lookup=lookup)
    else:
        np.testing.assert_array_equal(
            ent._T_of_h_field(h, pressure, 'sco2', lookup=lookup), exact)
    assert not lookup['used']


def test_iteration_state_is_owned_by_solve_and_discarded_after_failure(monkeypatch):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    original_state, original_eos = ent.AbstractState, ent._T_of_h_field
    states, calls = [], []

    def state(*args):
        states.append(original_state(*args))
        return states[-1]

    def eos(*args, **kwargs):
        calls.append((kwargs['where'], kwargs.get('lookup')))
        return original_eos(*args, **kwargs)

    monkeypatch.setattr(ent, 'AbstractState', state)
    monkeypatch.setattr(ent, '_T_of_h_field', eos)
    with monkeypatch.context() as failing:
        def fail(*args):
            raise ValueError('injected sweep failure')
        failing.setattr(ent, '_gs_enthalpy_sweeps_3d', fail)
        with pytest.raises(ValueError, match='injected sweep failure'):
            _guard_pipeline()
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', lambda *args: None)
    _, _, _, info = _guard_pipeline(coupled_energy_tol=.05)
    assert len(states) == 2 and states[0] is not states[1]
    iterations = [lookup for where, lookup in calls if 'iteration' in where]
    assert len(iterations) == 4
    assert all(lookup['state'] is states[i // 2] for i, lookup in enumerate(iterations))
    assert all(lookup is None for where, lookup in calls if 'final' in where)
    assert info['_native_state']['sco2_enthalpy_eos']['final_backend'] == 'HEOS'
    _guard_pipeline(fluid_A='air', fluid_B='water', P_A=2e5, P_B=2e5)
    assert len(states) == 2


def test_pending_cancel_precedes_table_initialization(monkeypatch):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    from sjtu_tpmshx.domain.cancellation import CancelledError
    def forbidden(*args):
        pytest.fail('cancelled solve initialized a table')
    monkeypatch.setattr(ent, 'AbstractState', forbidden)
    with pytest.raises(CancelledError):
        _guard_pipeline(cancel_check=lambda: True)
