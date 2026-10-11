"""Independent analytic checks for thermal entropy, zero load and report gates."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.validation.cases import audit_3d_conservation as audit


def test_polynomial_entropy_matches_independent_cp_over_temperature_quadrature():
    coefficients = model_h_coefficients('air')
    nodes, weights = np.polynomial.legendre.leggauss(32)
    for T in (275., 300., 350., 600.):
        a, b, c, origin, reference = coefficients
        sample = (T+reference)/2 + nodes*(T-reference)/2
        cp = a+b*(sample-origin)+c*(sample-origin)**2
        expected = (T-reference)/2*np.dot(weights, cp/sample)
        assert audit._thermal_entropy(T, coefficients) == pytest.approx(expected, abs=1e-11)


@pytest.mark.parametrize('direction', range(6))
def test_boundary_entropy_integrates_local_temperatures_before_mixing(direction):
    axis = direction//2
    T = np.moveaxis(np.array([[[400.], [400.]], [[300.], [600.]]]), 0, axis)
    if direction % 2:
        T = np.flip(T, axis=axis)
    mass = []
    for d in range(3):
        shape = list(T.shape); shape[d] += 1
        face = np.zeros(shape)
        if d == axis:
            oriented = np.moveaxis(face, d, 0)
            oriented[:] = np.array([[1.], [3.]])*(1 if direction % 2 == 0 else -1)
        mass.append(face)
    mask = np.ones(tuple(n for d, n in enumerate(T.shape) if d != axis))
    expected = 2.*(np.log(300./400.)+3*np.log(600./400.))
    actual = audit._boundary_thermal_entropy(T, mass, (2., 0., 0., 0., 300.), direction, 400., mask)
    assert actual == pytest.approx(expected, abs=1e-12)
    assert abs(actual - 8.*np.log(525./400.)) > .1
    with pytest.raises(ValueError, match='inflow face'):
        audit._boundary_thermal_entropy(T, mass, (2., 0., 0., 0., 300.), direction, 400., mask*0.)
    mass[(axis+1) % 3].flat[0] = 1.
    with pytest.raises(ValueError, match='inflow face'):
        audit._boundary_thermal_entropy(T, mass, (2., 0., 0., 0., 300.), direction, 400., mask)


def test_conductive_entropy_uses_both_half_cell_resistances_on_stretched_grid():
    T = np.array([300., 600.]).reshape(2, 1, 1)
    K = np.array([2., 4.]).reshape(2, 1, 1)
    widths = (np.array([1., 3.]), np.array([2.]), np.array([4.]))
    heat = 8./(.5/2.+1.5/4.)*(600.-300.)
    expected = heat*(1./300.-1./600.)
    actual = audit._conductive_entropy(T, K, widths)
    np.testing.assert_allclose(actual.ravel(), [expected/2, expected/2], atol=1e-12)
    assert audit._conductive_entropy(T, 0., widths).sum() == 0.


def null_case(delta=0.):
    shape = (2, 2, 2)
    fields = {key: np.full(shape, 350.+delta) for key in ('Ta', 'Tb', 'Ts')}
    fields.update({key: np.zeros(shape) for key in ('h_vA', 'h_vB', 'K_ffA', 'K_ffB', 'K_ss')})
    diag = dict(_audit_cp_A=2., _audit_cp_B=2., _audit_T_inA=350., _audit_T_inB=350.,
                _audit_m_dot_A_simple=.004, _audit_m_dot_B_simple=.004,
                T_A_out=350.+delta, T_B_out=350.+delta,
                model_h_balance={'sides': {side: {'model_cp_coefficients': (2., 0., 0., 0., 300.)}
                                           for side in ('A', 'B')}})
    params = {'fluid_A_cfg': {'dir': 0}, 'fluid_B_cfg': {'dir': 2}}
    fluxes = {}
    for side, stream in (('A', 0), ('B', 1)):
        faces = []
        for axis in range(3):
            dims = list(shape); dims[axis] += 1
            faces.append(np.full(dims, .001 if axis == stream else 0.))
        fluxes['mass_'+side] = faces
    return SimpleNamespace(fields=fields, grid={key: np.ones(2) for key in ('dx', 'dy', 'dz')},
        boundary_fluxes=fluxes,
        metadata=dict(diagnostics=diag, parameters=params, thermal_mode='model_h',
                      audit={'masks': {side: {'inlet': np.ones((2, 2))} for side in ('A', 'B')}}))


def test_zero_entropy_uses_energy_floor_but_does_not_hide_a_finite_defect():
    exact = audit.compute_phase3(null_case())
    assert exact['S_gen_global'] == exact['S_gen_volumetric'] == 0.
    assert exact['sigma_global_vs_volumetric_rel'] == 0.
    small = audit.compute_phase3(null_case(1e-7))
    assert small['entropy_normalization_W_K'] == pytest.approx(1./350.)
    assert 0. < small['sigma_global_vs_volumetric_rel'] < .05
    bad = audit.compute_phase3(null_case(50.))
    assert bad['sigma_global_vs_volumetric_rel'] > .05


def test_inlet_half_cell_heat_contributes_boundary_flux_and_entropy_production():
    r = null_case(-10.)
    r.fields['K_ffA'][:] = 2.
    result = audit.compute_phase3(r)
    # Four 1 m2 inlet faces, half a 1 m cell, K=2 W/(m K).
    heat_out = 4.*4.*(340.-350.)
    generated = heat_out*(1./350.-1./340.)
    assert result['S_boundary_conduction'] == pytest.approx(heat_out/350.)
    assert result['S_inlet_half_cell'] == pytest.approx(generated)
    assert result['S_gen_volumetric'] == pytest.approx(generated)


@pytest.mark.parametrize('key', ['Ta', 'h_vA', 'K_ffA'])
@pytest.mark.parametrize('value', [np.nan, np.inf])
def test_entropy_rejects_nonfinite_evidence(key, value):
    r = null_case(); r.fields[key][0, 0, 0] = value
    with pytest.raises(ValueError, match='finite'):
        audit.compute_phase3(r)


def test_crossover_observation_is_not_rendered_as_a_failed_gate():
    from sjtu_tpmshx.tests.test_retirement_validation_contracts import _certificate_result, _certificate_fields
    data = _certificate_result()
    certificate = audit.compute_phase2a(data)
    p3 = audit.compute_phase3(null_case())
    p3.update(C_r=.5, eps_obs=.9, cold_lt_hot=False, T_A_out=320., T_B_out=340.)
    cell = dict(net_out_total=0., net_out_abs=0., spurious_enthalpy_W=0.,
                net_out_max_cell=0., net_out_p99=0.)
    report, passed = audit.render_case('crossover', _certificate_fields(data), certificate,
                                      dict(A=cell, B=None), p3)
    assert passed and '**FAIL**' not in report
    assert 'Outlet crossover: **allowed**' in report
    # A true entropy failure must still control the report verdict.
    p3['sigma_global_vs_volumetric_rel'] = .05
    report, passed = audit.render_case('entropy failure', _certificate_fields(data), certificate,
                                      dict(A=cell, B=None), p3)
    assert not passed and '|global − volumetric| / scale < 5 %: **FAIL**' in report


@pytest.mark.parametrize('key', ['h_vA', 'K_ffA', 'K_ss'])
def test_entropy_rejects_negative_transport_coefficients(key):
    r = null_case(); r.fields[key][0, 0, 0] = -1.
    with pytest.raises(ValueError, match='nonnegative'):
        audit.compute_phase3(r)


@pytest.mark.parametrize('temperature', [0., -1.])
def test_entropy_rejects_nonpositive_absolute_temperature(temperature):
    r = null_case(); r.fields['Ta'][0, 0, 0] = temperature
    with pytest.raises(ValueError, match='positive absolute'):
        audit.compute_phase3(r)
