"""Prepared 2D inputs and independent returned-state physical audits."""
import ctypes as ct
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig, ZoneInputConfig,
)
from sjtu_tpmshx.models.grid import _port_overlap_1d, _port_fractions_1d
from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.result_math import pressure_face_values
from sjtu_tpmshx.solvers.backends import prepared_2d as execution
from sjtu_tpmshx.tests.native.pressure_audit import inlet_pressure_state
from sjtu_tpmshx.tests.native.simple_inputs import f2_settings
from sjtu_tpmshx.tests.native.simple_audit import mass_balance, raw_faces
from sjtu_tpmshx.tests.native.test_simple_2d import audit_momentum
from sjtu_tpmshx.tests.native.model_h_audit_2d import _model_h_balance

ROOT = Path(__file__).resolve().parents[3]
D = ct.POINTER(ct.c_double)
S = ct.c_size_t


def prepared_record(case, *, pressure_shooting=True):
    cfg, prepared = execution.build_execution_inputs(case)
    cfg['p_in_shooting'] = pressure_shooting
    return dict(cfg=cfg, prepared=prepared)


def configuration(*, directions=(0, 3), outer=4, partial=True, warm=False,
                  mode='model_h', simple_max=3000, pressure_shooting=True):
    lengths = (.06, .03)

    def port(direction, clipped):
        width = lengths[1 if direction < 2 else 0]
        center, opening = (width * .476, width * .457) if clipped else (width/2, width)
        return PartialBCConfig(dir=direction, in_ctr=center, in_w=opening,
                               out_ctr=center, out_w=opening)

    fluids = ('water', 'sco2') if mode == 'true_h' else ('air', 'water')
    pressure = 8e6 if mode == 'true_h' else 2e5
    return ComputeConfig(
        fluid_A=FluidConfig(type=fluids[0], u_mps=.05 if mode == 'true_h' else 3., T_in_K=350., P_in_Pa=pressure),
        fluid_B=FluidConfig(type=fluids[1], u_mps=.015 if mode == 'true_h' else .2,
                            T_in_K=320. if mode == 'true_h' else 300., P_in_Pa=pressure),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.6, k_s_W_mK=16.,
            L_dom_m=lengths[0], H_dom_m=lengths[1], delta_levelset=.1 if mode == 'temperature' else 0.),
        solver=SolverConfig(Nx=8, Ny=6, Nz=1, max_outer_ltne=outer, max_iter_simple=simple_max,
                            T_s_init_K=327. if warm else None),
        bc_A=port(directions[0], partial), bc_B=port(directions[1], False),
        extrap=ExtrapPolicy(allow=True))


def inputs(record):
    cfg, prepared = record['cfg'], record['prepared']
    shape = (len(prepared['energy_dx']), len(prepared['energy_dy']))

    def cell(value):
        return np.ascontiguousarray(np.broadcast_to(np.asarray(value, dtype=np.float64), shape))

    geometry = cfg['thermal_geometry']['fields'] or cfg['thermal_geometry']['uniform']
    z = cfg['za']
    properties = cfg['static_properties']
    arrays = [prepared['energy_dx'], prepared['energy_dy'], np.ones(1),
        cell(properties['A']['K_ff'] if z is None else z['K_ffA_arr']),
        cell(properties['B']['K_ff'] if z is None else z['K_ffB_arr']),
        cell(properties['geometry']['K_ss'] if z is None else z['K_ss_arr']),
        cell(cfg['eps'] if z is None else z['eps_arr']), cell(geometry['A_0']), cell(geometry['D_h']),
        cell(cfg['Lcell'] * 1e-3 if z is None else z['L_field'] * 1e-3)]
    mode = ('true_h' if 'sco2' in (cfg['fluid_A'], cfg['fluid_B']) and cfg['zone_config'] is None else
            'model_h' if cfg['compute_cfg'].geometry.delta_levelset == 0 and
            (cfg['zone_config'] is None or cfg['z_axis'] == 'continuous') else 'temperature')
    multiplier = 1.
    if mode == 'true_h' and cfg['compute_cfg'].sco2_nu.mode != 'cfd_smooth':
        multiplier = getattr(cfg['compute_cfg'].sco2_nu, 'alpha_G' if cfg['tpms_type'] == 'Gyroid' else 'alpha_D')
    scalars = [cfg['Lcell'] * 1e-3, cfg['eps'], cfg['thermal_geometry']['split_A'], multiplier,
               cfg.get('T_s_init') or 0.]
    for side in ('A', 'B'):
        flow, opening, port = cfg['flow_inputs'][side], cfg['boundary_openings'][side], cfg['cfg'+side]
        arrays.extend([flow['K_m2'], flow['cF_per_m'], flow.get('K_field_m2', np.empty(0)),
            flow.get('cF_field_per_m', np.empty(0)), opening['in_geom_frac'], opening['out_geom_frac'],
            opening['in_profile_frac'], opening['out_profile_frac'],
            _port_overlap_1d(flow['dx'], port['out_ctr']-port['out_w']/2,
                             port['out_ctr']+port['out_w']/2, staggered=True)])
        physical = getattr(cfg['compute_cfg'], 'fluid_'+side)
        side_geometry = (cfg['thermal_geometry']['side_geometry'] or {}).get(side, (0., 0., 0., 0.))
        scalars.extend([cfg['T_in'+side], physical.P_in_Pa, cfg['u_'+side], properties[side]['mu'],
            flow['seed_K_m2'], flow['seed_cF_per_m'], port['in_ctr']-port['in_w']/2, port['in_ctr']+port['in_w']/2,
            port['out_ctr']-port['out_w']/2, port['out_ctr']+port['out_w']/2, *side_geometry])
    solver = cfg['compute_cfg'].solver
    monitor = f2_settings(SimpleNamespace(**{key: value for key, value in vars(solver).items() if value is not None}))
    has_water = 'water' in (cfg['fluid_A'], cfg['fluid_B'])
    thermal_tolerance = .1 if mode == 'true_h' else 1. if has_water else .5
    flags = [int(cfg['tpms_type'] == 'Gyroid'), ('temperature', 'model_h', 'true_h').index(mode),
        ('air', 'water', 'sco2').index(cfg['fluid_A']), ('air', 'water', 'sco2').index(cfg['fluid_B']),
        cfg['dir_A'], cfg['dir_B'], int(cfg['compute_cfg'].geometry.delta_levelset != 0), int(cfg.get('T_s_init') is not None),
        int(cfg['cfgA'].get('uniform_inlet_2d', False)), int(cfg['cfgB'].get('uniform_inlet_2d', False)),
        int(cfg['p_in_shooting']), 0,
        1, 1, cfg['compute_cfg'].solver.max_iter_simple or 10000,
        2, cfg['compute_cfg'].solver.max_outer_ltne or 10, 12000 if has_water else 5000,
        500 if mode != 'true_h' else 3,
        monitor.n_confirm, monitor.mom_every, monitor.stall_window, 0, int(z is not None)]
    scalars.extend([.7, .3, .3, 287.05, 0.,
        monitor.mom_tol, monitor.mass_local_tol, monitor.mass_global_tol, monitor.backflow_max,
        monitor.vtol, monitor.stall_ratio, cfg['compute_cfg'].solver.outer_tol_K or 1., .01, .7,
        min(thermal_tolerance * 2e-3, 1e-3), max(thermal_tolerance, 1e-8) / 100.])
    arrays.append(cell(geometry['D_h']*1000. / (cfg['Lcell'] if z is None else z['L_field'])))
    assert len(arrays) == 29 and len(flags) == 24 and len(scalars) == 49
    arrays = [np.ascontiguousarray(x, dtype=np.float64) for x in arrays]
    return dict(shape=shape, arrays=arrays, flags=flags, scalars=scalars, mode=mode,
                envelope=cfg.get('envelope_mode', 'raise'))


@pytest.fixture(scope='module')
def native():
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    suffix = '.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'
    library = ROOT / '.cache/native-deps/build' / ('pilot-'+host) / (('' if os.name == 'nt' else 'lib')+'full_2d_test'+suffix)
    library = Path(os.environ.get('TPMSHX_FULL_2D_TEST_LIBRARY', library))
    if not library.is_file():
        message = f'full2D coarse qualification library not built: {library}'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    lib = ct.CDLL(str(library))
    lib.test_full_2d_run.argtypes = [ct.POINTER(S), ct.POINTER(D), ct.POINTER(S), ct.POINTER(S), D,
        ct.c_char_p, ct.c_char_p, ct.c_int, ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_char), S]
    lib.test_full_2d_run.restype = ct.c_int
    lib.test_full_2d_json.argtypes, lib.test_full_2d_json.restype = [ct.c_void_p], ct.c_char_p
    lib.test_full_2d_destroy.argtypes, lib.test_full_2d_destroy.restype = [ct.c_void_p], None

    def run(request):
        arrays = request['arrays']
        handle, error = ct.c_void_p(), ct.create_string_buffer(2048)
        code = lib.test_full_2d_run((S * 2)(*request['shape']), (D * len(arrays))(*(a.ctypes.data_as(D) for a in arrays)),
            (S * len(arrays))(*(a.size for a in arrays)), (S * len(request['flags']))(*request['flags']),
            (ct.c_double * len(request['scalars']))(*request['scalars']),
            str(ROOT / '.cache/native-deps/tables/full2d-tests').encode(), request['envelope'].encode(), request.get('full', False),
            ct.byref(handle), error, len(error))
        if code:
            assert not handle.value
            return code, error.value.decode(), None
        try:
            return code, '', json.loads(lib.test_full_2d_json(handle))
        finally:
            lib.test_full_2d_destroy(handle)

    return run


def compare_array(actual, expected, kind='other'):
    if expected is None:
        assert np.isnan(actual)
        return
    expected = np.asarray(expected)
    tolerances = {'temperature': (0., .01), 'pressure': (1e-4, 2e-5),
                  'state': (1e-4, 2e-10), 'power': (2e-8, 2e-7), 'other': (1e-4, 2e-10)}
    rtol, atol = tolerances[kind]
    np.testing.assert_allclose(np.asarray(actual).reshape(expected.shape), expected, rtol=rtol, atol=atol, equal_nan=True)


def physical_field(field, direction):
    value = np.asarray(field).T if direction < 2 else np.asarray(field)
    return np.flip(value, axis=direction//2) if direction % 2 else value


def audit_thermal(thermal, record, dx, dy, *, full=False, outer=True):
    cfg = record['cfg']
    shape = (len(dx), len(dy))
    cell = lambda value: np.asarray(value).reshape(shape)
    result = thermal['result']
    temperatures = [cell(value) for value in thermal['temperature']]
    assert all(np.isfinite(value).all() and (value > 0).all() for value in temperatures)
    assert result['iterations'] > 0 and np.isfinite(result['residual'])
    if result['mode'] != 'model_h':
        return
    directions = [cfg['dir_'+side] for side in 'AB']
    inlet = [np.full(shape[1-direction//2], cfg['T_in'+side]) for side, direction in zip('AB', directions)]
    openings = []
    for side,direction in zip('AB',directions):
        port = cfg['cfg'+side]
        openings.append(_port_fractions_1d((dx,dy)[1-direction//2],
            port['in_ctr']-port['in_w']/2,port['in_ctr']+port['in_w']/2)[0])
    masses = [tuple(np.asarray(thermal[key][i]).reshape(tuple(n+int(a==axis) for a,n in enumerate(shape)))
                    for axis,key in enumerate(('mass_x', 'mass_y'))) for i in range(2)]
    balance = _model_h_balance(*temperatures, *[cell(x) for x in thermal['conductivity']],
        cell(thermal['solid_conductivity']), *[cell(x) for x in thermal['hv']], dx, dy, *masses,
        *[model_h_coefficients(cfg['fluid_'+side]) for side in 'AB'], *directions, *inlet, *openings,
        True, cell(result['last_a']), cell(result['last_b']))
    if full:
        balance['passed'] = balance['passed'] and outer
    from sjtu_tpmshx.tests.native.test_full_2d_refinement import compare_audit
    compare_audit(result['audit'], balance)
    q_b = np.sum(cell(thermal['hv'][1])*(temperatures[2]-temperatures[1])*dx[:,None]*dy[None,:])
    compare_array(result['q_b'], q_b, 'power')
    checks = result['finishing_checks']
    assert checks and checks[-1]['iterations'] <= result['iterations']
    assert all(b['iterations'] > a['iterations'] for a,b in zip(checks, checks[1:]))
    if result['stop'] == 0:
        assert checks[-1]['passed'] and checks[-1]['equations_ok']


def audit_coarse(actual, record, *, full=False):
    cfg, prepared = record['cfg'], record['prepared']
    assert not actual['cancelled']
    assert actual['post_after_last_thermal'] == (not actual['outer_converged'])
    history = actual['outer_history']
    assert len(history) == actual['iterations'] <= (cfg['compute_cfg'].solver.max_outer_ltne or 10)
    assert [row['iteration'] for row in history] == list(range(actual['iterations']))
    assert history[-1]['outer_converged'] == actual['outer_converged']
    assert not any(row['outer_converged'] for row in history[:-1])
    if actual['outer_converged']:
        assert history[-1]['thermal_converged']
        assert max(history[-1]['relative_density_change']) < .01
        assert max(history[-1]['temperature_change']) < (cfg['compute_cfg'].solver.outer_tol_K or 1.)
    for index, side in enumerate('AB'):
        flow, seed = actual['flow'][index], cfg['flow_inputs'][side]
        dx, dy = [np.asarray(flow[key]) for key in ('dx','dy')]
        shape = (len(dx), len(dy))
        view = SimpleNamespace(dx_arr=dx, dy_arr=dy, Nx=shape[0], Ny=shape[1],
            outlet_geom_frac=cfg['boundary_openings'][side]['out_geom_frac'],
            inlet_geom_frac=cfg['boundary_openings'][side]['in_geom_frac'],
            P_ref_abs=flow['reference_pressure'], cf_aniso=0.,
            fluid_type='ideal_gas' if cfg['fluid_'+side] == 'air' else 'incompressible',
            _K_field2d=seed.get('K_field_m2'), _cF_field2d=seed.get('cF_field_per_m'),
            _K_arr=np.asarray(seed['K_m2']), _cF_arr=np.asarray(seed['cF_per_m']))
        for source, target in (('density','rho_field'), ('epsilon','eps_field'), ('viscosity','mu_field'),
                               ('effective_viscosity','_mu_eff_field'), ('pressure','P')):
            setattr(view, target, np.asarray(flow[source]).reshape(shape))
        view.u = np.asarray(flow['u']).reshape(shape[0]+1,shape[1])
        view.v = np.asarray(flow['v']).reshape(shape[0],shape[1]+1)
        port = cfg['cfg'+side]
        view.outlet_u_frac = _port_overlap_1d(dx, port['out_ctr']-port['out_w']/2,
                                             port['out_ctr']+port['out_w']/2, staggered=True)
        result = flow['result']
        if result['post_closure_measured']:
            mass, count, _ = mass_balance(view, exclude_outlet=True)
            np.testing.assert_allclose([result['mass'][key] for key in ('local_residual','global_residual',
                'backflow_fraction','mass_in','mass_out')], mass, rtol=2e-12, atol=2e-12)
            assert result['mass']['counted_cells'] == count
            _, momentum = audit_momentum(view)
            np.testing.assert_allclose(result['momentum']['maximum'], momentum, rtol=2e-12, atol=2e-12)
        if result['converged']:
            assert result['stop'] == 1 and result['post_closure_certified']
            assert result['mass']['local_residual'] < 1e-6 and result['mass']['global_residual'] < 1e-6
            assert result['mass']['backflow_fraction'] <= .01 and result['momentum']['maximum'] < 1e-4
        assert len(flow['history']['legacy']) >= result['iterations'] - result['acceleration_attempts']
        assert np.isfinite(flow['history']['legacy']).all()
        direction = cfg['dir_'+side]
        pin = getattr(cfg['compute_cfg'], 'fluid_'+side).P_in_Pa
        pressure = physical_field(view.P, direction)
        if view.fluid_type == 'ideal_gas':
            pressure = pressure + view.P_ref_abs
        else:
            inlet, _ = pressure_face_values(view.P, dy)
            pressure = pin + pressure - np.average(inlet, weights=dx*view.inlet_geom_frac)
        compare_array(flow['absolute_pressure'], pressure, 'pressure')
        state = inlet_pressure_state(view, pin)
        if state is None:
            assert flow['pressure_state'] is None
        else:
            for key, value in state.items():
                if key == 'iterations':
                    continue
                if isinstance(value, (bool,str)):
                    assert flow['pressure_state'][key] == value
                else:
                    compare_array(flow['pressure_state'][key], value, 'pressure')
        split = cfg['thermal_geometry']['split_A']
        faces = [face * (split if side == 'A' else 1-split) for face in raw_faces(view)]
        if direction < 2:
            faces = [faces[1].T, faces[0].T]
        if direction % 2:
            faces[direction//2] = -faces[direction//2]
            faces = [np.flip(face, axis=direction//2) for face in faces]
        for key, value in zip(('mass_x','mass_y'), faces):
            compare_array(flow[key], value)
    audit_thermal(actual['thermal'], record, prepared['energy_dx'], prepared['energy_dy'],
                  full=full, outer=actual['outer_converged'])


@pytest.mark.parametrize('outer', [2, 4])
def test_prepared_air_water_model_h_coarse(native, outer):
    case = prepare_case(configuration(outer=outer), case_id=f'native-full2d-coarse-{outer}')
    reference = prepared_record(case)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    audit_coarse(actual, reference)


@pytest.mark.parametrize('directions,warm', [((1, 2), False), ((2, 1), False), ((3, 0), True)])
def test_prepared_directions_and_solid_warm_start(native, directions, warm):
    case = prepare_case(configuration(directions=directions, warm=warm), case_id='native-full2d-directed')
    reference = prepared_record(case)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    audit_coarse(actual, reference)


@pytest.mark.parametrize('mode', ['temperature', 'true_h'])
def test_prepared_other_thermal_routes(native, mode):
    case = prepare_case(configuration(mode=mode, outer=2), case_id='native-full2d-'+mode)
    reference = prepared_record(case)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    audit_coarse(actual, reference)


@pytest.mark.parametrize('shooting', [False, True])
def test_prepared_pressure_shooting_with_capped_simple(native, shooting):
    case = prepare_case(configuration(outer=2, simple_max=10), case_id='native-full2d-capped-flow')
    reference = prepared_record(case, pressure_shooting=shooting)
    code, error, actual = native(inputs(reference))
    assert code == 0, error
    audit_coarse(actual, reference)
    assert not all(flow['result']['converged'] for flow in actual['flow'])


@pytest.mark.parametrize('partial,continuous,directions', [
    (False, False, (0, 3)), (True, False, (0, 3)),
    (True, True, (0, 3)), (True, True, (1, 2)),
])
def test_prepared_completed_coarse_and_continuous_fields(native, partial, continuous, directions):
    cfg = configuration(partial=partial, directions=directions, outer=10)
    if continuous:
        cfg.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [6.7, 7.2, 7., 7.5, .45, .5, .55, .58],
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False,
            'spline_order': 1, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]})
    case = prepare_case(cfg, case_id='native-full2d-completed')
    reference = prepared_record(case)
    request = inputs(reference)
    if continuous:
        assert np.ptp(request['arrays'][6]) > 0
        assert np.ptp(request['arrays'][9]) > 0
        assert all(request['arrays'][index].size == np.prod(request['shape']) for index in (12, 13, 21, 22))
    code, error, actual = native(request)
    assert code == 0, error
    audit_coarse(actual, reference)
    assert actual['outer_converged']
    assert all(flow['result']['converged'] for flow in actual['flow'])
