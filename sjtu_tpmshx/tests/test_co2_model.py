"""CO2 model identity, physical boundaries and shared preparation contracts."""
from dataclasses import replace

import CoolProp.CoolProp as CP
import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig,
)
from sjtu_tpmshx.models import co2_correlations as co2
from sjtu_tpmshx.models.co2_props import co2_prop
from sjtu_tpmshx.models.fluid_props import get
from sjtu_tpmshx.models.local_heat_transfer import local_nusselt, real_fluid_hv_local_field
from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR
from sjtu_tpmshx.preprocess.api import prepare_case


def co2_config(nz=1, side='A', other='water'):
    real = FluidConfig(type='co2', u_mps=.3, T_in_K=340., P_in_Pa=8e6)
    cold = {'water': FluidConfig(type='water', u_mps=.1, T_in_K=300., P_in_Pa=2e5),
            'air': FluidConfig(type='air', u_mps=8., T_in_K=300., P_in_Pa=2e5),
            'sco2': FluidConfig(type='sco2', u_mps=.3, T_in_K=320., P_in_Pa=8e6),
            'co2': replace(real, T_in_K=300., P_in_Pa=5e6, u_mps=.4)}[other]
    return ComputeConfig(geometry=GeometryConfig(Lz_m=.042),
        fluid_A=real if side == 'A' else cold, fluid_B=cold if side == 'A' else real,
        solver=SolverConfig(Nx=8, Ny=6, Nz=nz, max_outer_ltne=24, outer_tol_K=.001))


CO2_PAIRS = ('co2-co2', 'co2-air', 'air-co2', 'co2-water',
             'water-co2', 'co2-sco2', 'sco2-co2')


def co2_engineering_config(dimension, pair):
    """Frozen combination coverage: two topologies, gas/dense CO2 and ports."""
    index = CO2_PAIRS.index(pair)
    names = pair.split('-')
    def fluid(name, side):
        temperature = 350. if side == 0 else (320. if name == 'sco2' else 300.)
        pressure = {'air': 2e5, 'water': 2e6, 'sco2': 8e6,
                    'co2': 8e6 if side == 0 else 5e6}[name]
        return FluidConfig(type=name, u_mps={'air': 8., 'water': .1, 'sco2': .3,
                                            'co2': .7 if side else .35}[name],
                           T_in_K=temperature, P_in_Pa=pressure)
    def port(direction, partial):
        cross = .03 if direction in (0, 1) else .06
        width = cross*(.5 if partial else 1.)
        return PartialBCConfig(dir=direction, in_ctr=cross/2, in_w=width,
            out_ctr=cross/2, out_w=width, **(dict(in_z_ctr=.015, in_z_w=.015,
                out_z_ctr=.015, out_z_w=.015) if partial and dimension == 3 else {}))
    return ComputeConfig(
        geometry=GeometryConfig(tpms='Diamond' if index % 2 else 'Gyroid',
            L_dom_m=.06, H_dom_m=.03, Lz_m=.03),
        fluid_A=fluid(names[0], 0), fluid_B=fluid(names[1], 1),
        bc_A=port(4 if dimension == 3 and index == 5 else index % 2, index == 5),
        bc_B=port(3 if index % 2 else 2, index == 5),
        solver=SolverConfig(Nx=8, Ny=6, Nz=3 if dimension == 3 else 1,
                            max_outer_ltne=100, max_iter_simple=5000, outer_tol_K=.001))


@pytest.mark.parametrize('temperature,pressure', [(280., 3e6), (300., 5e6), (300., 9e6), (340., 8e6)])
def test_co2_properties_and_true_enthalpy_roundtrip(temperature, pressure):
    from sjtu_tpmshx.solvers.ltne_enthalpy_3d import _prop_field, _T_of_h_field
    t = np.array([[temperature, temperature+1.]])
    p = np.array([[pressure], [pressure+1000.]])
    for key, values in zip(('D', 'V', 'L', 'C', 'H'), co2_prop(('D', 'V', 'L', 'C', 'H'), t, p)):
        expected = np.array([[CP.PropsSI(key, 'T', ti, 'P', pi, 'HEOS::CO2')
                              for ti in t.flat] for pi in p.flat])
        assert np.allclose(values, expected, rtol=2e-13)
        assert co2_prop(key, temperature, pressure) == pytest.approx(expected[0, 0], rel=2e-13)
    broadcast_t, broadcast_p = np.broadcast_arrays(t, p)
    h = _prop_field('H', broadcast_t, broadcast_p, 'co2')
    assert np.max(np.abs(_T_of_h_field(h, broadcast_p, 'co2')-broadcast_t)) < 1e-7


@pytest.mark.parametrize('temperature,pressure', [
    (200., 1e6), (300., None), (float('nan'), 1e6), (300., 0.),
    (CP.PropsSI('Tcrit', 'CO2'), CP.PropsSI('Pcrit', 'CO2')),
    (280., CP.PropsSI('P', 'T', 280., 'Q', 0., 'CO2')),
])
def test_invalid_co2_states_are_rejected(temperature, pressure):
    with pytest.raises(ValueError):
        co2_prop('D', temperature, pressure)


def test_two_phase_inverse_does_not_become_a_valid_temperature():
    from sjtu_tpmshx.solvers.ltne_enthalpy_3d import _T_of_h_field
    h = CP.PropsSI('H', 'P', 3e6, 'Q', .5, 'CO2')
    with pytest.raises(ValueError, match='single-phase'):
        _T_of_h_field(np.array([h]), 3e6, 'co2')


@pytest.mark.parametrize('nz', [1, 3])
@pytest.mark.parametrize('mass_input', [False, True])
@pytest.mark.parametrize('temperature,pressure', [
    (CP.PropsSI('Tcrit', 'CO2'), CP.PropsSI('Pcrit', 'CO2')),
    (280., CP.PropsSI('P', 'T', 280., 'Q', 0., 'CO2')),
])
def test_preparation_rejects_co2_phase_boundary(nz, mass_input, temperature, pressure):
    cfg = co2_config(nz)
    cfg.fluid_A = replace(cfg.fluid_A, T_in_K=temperature, P_in_Pa=pressure,
                          mass_flow_kg_s=.01 if mass_input else None)
    with pytest.raises(ValueError, match='single-phase'):
        prepare_case(cfg, case_id='invalid-co2-phase')


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_geometry_nodes_and_dimensionless_interpolation(topology):
    nodes = co2.coefficients()['topologies'][topology]['geometry_nodes']
    for node in nodes:
        actual = co2.geometry(topology, node['L_mm'], node['t_mm'], 11.)
        assert actual['epsilon'] == pytest.approx(2*node['epsilon_single'], rel=1e-14)
        assert actual['D_h'] == pytest.approx(node['Dh_m'], rel=1e-14)
        assert actual['A_0'] == pytest.approx(node['A0_single_per_m'], rel=1e-14)
    corners = [n for n in nodes if n['L_mm'] in (6., 7.) and n['t_mm'] in (.4, .5)]
    actual = co2.geometry(topology, 6.5, .45)
    assert actual['D_h'] == pytest.approx(np.mean([n['Dh_m']/n['L_mm'] for n in corners])*6.5)
    assert actual['A_0'] == pytest.approx(np.mean([n['A0_single_per_m']*n['L_mm'] for n in corners])/6.5)
    with pytest.raises(ValueError, match='no extrapolation'):
        co2.geometry(topology, 8.1, .6)


def test_fixed_nu_factor_and_floor_apply_once_with_local_geometry():
    b = co2.coefficients()['topologies']['Gyroid']['Nu']['parameters']['theta']
    reynolds, pr, length, dh = 12000., 1.4, 7., 3.
    x, y, z = np.log(reynolds/1e4), np.log(pr/2.), np.log((dh/length)/.5)
    assert co2.nusselt('Gyroid', reynolds, pr, length, dh) == pytest.approx(
        1.28*np.exp(b[0]+b[1]*x+b[2]*y+b[3]*z+b[4]*x*x), rel=1e-14)
    temperatures = np.array([[325., 340.]])
    diameters = np.array([[.002, .003]])
    lengths = np.array([[5., 7.]])
    rho, mu, conductivity, cp = co2_prop(('D', 'V', 'L', 'C'), temperatures, 8e6)
    re = rho*.3*diameters/mu
    expected = 1000.*np.maximum(co2.nusselt('Gyroid', re, cp*mu/conductivity,
                                           lengths, diameters*1e3), 1.28*NU_LAM_FLOOR)*conductivity/diameters
    assert np.allclose(real_fluid_hv_local_field(temperatures, 8e6, .3, 1000., diameters,
                        'Gyroid', lengths, fluid='co2'), expected, rtol=1e-14)
    zero_nu = replace(get('co2'), nu=lambda *args: np.zeros(2))
    assert np.array_equal(local_nusselt(zero_nu, 'Gyroid', [1., 2.], .4, 7., 3., 1.4),
                          np.full(2, 1.28*NU_LAM_FLOOR))


@pytest.mark.parametrize('nz', [1, 3])
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('mode', ['cfd_smooth', 'experimental'])
def test_prepared_drag_is_side_specific_fixed_and_replayable(tmp_path, nz, side, mode):
    from sjtu_tpmshx.io.case_io import save_case, load_case
    from sjtu_tpmshx.models.catalog import resolve_model
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF, SCO2_DF_METHOD
    cfg = co2_config(nz, side)
    cfg.df_mode = mode
    case = prepare_case(cfg, case_id=f'co2-{nz}-{side}-{mode}')
    path = tmp_path/'case.yaml'
    save_case(case, path)
    restored = load_case(path)
    assert resolve_model(restored.model_refs[restored.metadata['model_roles']['fluid_'+side]]).name == 'co2'
    assert restored.metadata['model_metadata']['co2']['sides'] == (side,)
    base_k, base_f = predict_K_cF('Gyroid', 7., .6, .4, method=SCO2_DF_METHOD)
    if nz == 1:
        flow = restored.parameters['flow_inputs'][side]
        assert np.allclose(flow['K_m2'], base_k/2.5, rtol=1e-14)
        assert np.allclose(flow['cF_per_m'], base_f*2.5, rtol=1e-14)
        other = restored.parameters['flow_inputs']['B' if side == 'A' else 'A']['metadata']
    else:
        applied = restored.parameters['df_application'][side]
        assert applied['scale_K'] == .4 and applied['scale_F'] == 2.5
        assert np.allclose(restored.design_fields['K_m2'], base_k, rtol=1e-14)
        other = (restored.parameters['df_application'] or {}).get('B' if side == 'A' else 'A', {})
    assert other.get('scale_K', 1.) == 1.
    assert other.get('scale_F', 1.) != 2.5
    geometry = restored.parameters['thermal_geometry']['uniform']
    assert geometry['D_h'] == co2.geometry('Gyroid', 7., .6)['D_h']
    rerun = prepare_case(ComputeConfig.from_dict(cfg.to_dict()), case_id='repeat')
    assert rerun.metadata['model_metadata'] == case.metadata['model_metadata']
