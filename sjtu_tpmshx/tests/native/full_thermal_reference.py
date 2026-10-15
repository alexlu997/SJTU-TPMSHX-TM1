"""Same-map thermal components inside the original Python full outer tests.

Only test callers explicitly passing this fixture use the adapter. Properties,
Nu/D-F, pressure shooting, outer Anderson and outer stopping use Python orchestration.
The explicit fixed-density flow helper selects the current native SIMPLE component.
Independent backend tests keep the original Python SIMPLE algorithm. No thermal iterator is
implemented here. Historical no-fixture reference callers remain unchanged.
"""
from contextlib import contextmanager, nullcontext
import ctypes as ct
import inspect
from unittest.mock import patch
from dataclasses import replace
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_energy, ltne_energy_3d
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers.backends.cpp.model_h import NativeModelHDriver, _Callbacks, _Cancel, _Progress
from sjtu_tpmshx.solvers.backends.cpp.temperature import NativeTemperatureDriver
from sjtu_tpmshx.solvers.backends.cpp.enthalpy import NativeEnthalpyDriver


ROOT = Path(__file__).resolve().parents[3]


def native_table_metadata(record):
    # The Python reference keeps its original table-record name.
    if 'sco2_enthalpy_eos' not in record:
        return record
    assert 'enthalpy_eos' not in record
    return {('enthalpy_eos' if key == 'sco2_enthalpy_eos' else key): value
            for key, value in record.items()}


def fixed_density_flow(solver, arguments):
    """Use the selected native flow component inside the interface reference."""
    from sjtu_tpmshx.tests.native import test_simple_2d as simple

    assert solver.fluid_type != 'ideal_gas' and arguments['cancel_check'] is None
    with simple.Native(simple.library.__wrapped__(), solver) as native:
        result = native.call(solver, iterations=arguments['max_iter'], sweeps=arguments['n_inner'],
                             alpha_u=arguments['alpha_u'], alpha_p=arguments['alpha_p'], accelerate=True)
        for kind, name in enumerate(('residuals', 'mass_local_residuals', 'mass_global_residuals')):
            setattr(solver, name, native.history(kind).tolist())
        solver.mom_residuals = [dict(iter=int(row[0]), max=row[1], num=row[2:4].tolist(),
            den=row[4:6].tolist(), u=row[6], v=row[7]) for row in native.history(3).reshape(-1, 8)]
        if arguments['progress_cb'] is not None:
            for iteration, residual in native.history(4).reshape(-1, 2):
                arguments['progress_cb'](int(iteration), float(residual))
    for index, name in ((5, 'final_res'), (6, 'final_res_mom'), (7, 'final_res_mass_local'),
                        (8, 'final_res_mass_global'), (9, 'outlet_backflow_frac')):
        setattr(solver, name, None if np.isnan(result[index]) else float(result[index]))
    solver.exit_reason = simple.STOP[int(result[0])]
    solver.f2_cert_post_rescale_ok = bool(result[4]) if result[3] else None
    solver._p_clip_hits = int(result[12])
    if np.isfinite(result[13]):
        solver._massflux_target = float(result[13])
    return bool(result[1]), int(result[2])


def library(name, environment):
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    suffix = '.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'
    basename = ('' if os.name == 'nt' else 'lib') + name + suffix
    path = Path(os.environ.get(environment, ROOT / '.cache/native-deps/build' / ('pilot-'+host) / basename))
    if not path.is_file():
        message = f'full-reference component library not built: {path}'
        if environment in os.environ or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    return path.resolve()


def model_enthalpy(temperature, fluid):
    """Integrate the existing polynomial with NumPy for independent evidence checks."""
    from sjtu_tpmshx.models.tpms_props import model_h_coefficients
    a, b, c, origin, reference = model_h_coefficients(fluid)
    integral = np.polynomial.Polynomial((a, b, c)).integ()
    return integral(np.asarray(temperature) - origin) - integral(reference - origin)


def assert_selected_enthalpy(result):
    """Check returned mixed enthalpy with the independent polynomial integral."""
    record = result.metadata['execution_record']
    native = result.boundary_fluxes['true_h']
    scale = record['numerics']['enthalpy_update_normalization']
    assert scale['definition'] == 'inlet_cp_times_temperature_difference_v1'
    assert scale['unit'] == 'J/kg'
    from CoolProp.CoolProp import PropsSI
    for side in 'AB':
        model = record['sides'][side]
        fluid = model['fluid']
        temperature = result.fields['Ta' if side == 'A' else 'Tb']
        h = native['h_' + side]
        assert np.isfinite(h).all() and scale['sides'][side] >= 1.
        if fluid in ('air', 'water'):
            assert model['energy']['relation'] == 'integral_cp_T'
            expected = model_enthalpy(temperature, fluid)
        else:
            assert model['energy']['relation'] == 'eos_h_TP'
            pressure = result.fields['P_thermal_' + side]
            expected = np.array([PropsSI('H', 'T', t, 'P', p, 'CO2')
                                 for t, p in zip(temperature.flat, pressure.flat)]).reshape(temperature.shape)
        if temperature.ndim == 2:
            expected = expected[..., None]
        np.testing.assert_allclose(h, expected, rtol=1e-10, atol=1e-6)


@contextmanager
def selected_2d_heat_transfer_reference():
    """Select each fluid's existing Python heat-transfer rule for the reference."""
    from sjtu_tpmshx.domain.run_warnings import range_context
    from sjtu_tpmshx.solvers.backends.python.two_d import coupling
    original_outer = coupling.run_outer_coupling

    def outer(**arguments):
        step = inspect.unwrap(arguments['step'])
        prepare = inspect.getclosurevars(step).nonlocals['_prepare_thermal_inputs']
        inputs = inspect.getclosurevars(prepare).nonlocals
        cells = dict(zip(prepare.__code__.co_freevars, prepare.__closure__))
        cell = cells['_enthalpy_side_hv']
        original_hv = cell.cell_contents

        def selected(provider, temperature, pressure, speed, geometry, observation):
            if provider.name in ('co2', 'sco2'):
                return original_hv(provider, temperature, pressure, speed, geometry, observation)
            side = 'A' if provider is inputs['_pA'] else 'B'
            state = inputs['state']
            rho = coupling.cell_average(getattr(state, 'rho_'+side+'_field'), inputs['energy_dx'], inputs['energy_dy'])
            mu = coupling.cell_average(getattr(state, 'mu_'+side), inputs['energy_dx'], inputs['energy_dy'])
            inlet = inputs['T_in'+side]
            with range_context(layout='scalar'):
                conductivity = float(provider.k(inlet, pressure))
            for sample in inputs['thermal_sampling']:
                if sample['side'] == side and sample['stage'] == 'thermal_hv':
                    if sample['quantity'] in ('density', 'viscosity'):
                        sample.update(provider='outer_property_state', operation='volume_mean',
                                      pressure='previous_thermal_absolute' if sample['outer_index'] else 'inlet')
                    else:
                        sample.update(temperature='inlet', operation='scalar_evaluation')
            lengths = (inputs['za']['L_field']
                       if inputs['zone_config'] is not None and inputs['za'] is not None else None)
            return inputs['_build_hv_local_2d'](rho, mu, conductivity, speed, lengths,
                                               side_props=provider, side_T_for_Pr=inlet, side_P=pressure)

        # Reuse the two original closure functions without changing production code.
        cell.cell_contents = selected
        try:
            return original_outer(**arguments)
        finally:
            cell.cell_contents = original_hv

    with patch.object(coupling, 'run_outer_coupling', outer):
        yield


@contextmanager
def selected_energy_reference(case=None):
    """Keep the Python outer and use the current per-side thermal component."""
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as energy
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime
    driver = NativeEnthalpyDriver(library('tpmshx_enthalpy_shared', 'TPMSHX_ENTHALPY_LIBRARY'),
                                 table_directory=ROOT/'.cache/native-deps/tables')
    bridge = ct.CDLL(str(library('full_thermal_test', 'TPMSHX_FULL_THERMAL_TEST_LIBRARY')))
    dp = ct.POINTER(ct.c_double)
    call = bridge.test_full_thermal_selected
    call.argtypes, call.restype = [*driver.call.argtypes, dp, dp], ct.c_int
    current, observed = [None], {}
    dimension = 2 if case is not None and case.grid['dimension'] == 2 else 3
    if case is not None and case.grid['dimension'] == 2:
        from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
        cfg, _ = build_execution_inputs(case)
        fraction = cfg['thermal_geometry']['split_A']
        current[0] = tuple(np.asarray(cfg['za']['K_ff'+side+'_arr'] if cfg['za'] is not None
                                     else cfg['static_properties'][side]['K_ff']) * factor
                           for side, factor in zip('AB', (2*fraction, 2*(1-fraction))))
    original_warmup = runtime.solve_full_domain_3d
    def warmup(*args, **kwargs):
        bound = inspect.signature(original_warmup).bind(*args, **kwargs)
        bound.apply_defaults()
        current[0] = tuple(np.array(bound.arguments['K_ff'+side], copy=True) for side in 'AB')
        result = original_warmup(*args, **kwargs)
        observed['warmup'] = (tuple(bound.arguments.get(key+'_init') for key in ('Ta','Tb')),
                              tuple(np.array(x, copy=True) for x in result[:2]))
        return result
    def ranges(c, temperatures, stage, layout):
        from sjtu_tpmshx.domain.run_warnings import range_context
        from sjtu_tpmshx.models.tpms_props import record_temperature_ranges
        for side, temperature in zip('AB', temperatures):
            if temperature is not None:
                with range_context(side=side, stage=stage, layout=layout):
                    record_temperature_ranges(c['fluid_'+side],
                                              temperature[..., 0] if dimension == 2 else temperature)
    def selected(*args, **kwargs):
        shape = tuple(args[:3]) if args else tuple(kwargs[key] for key in ('Nx','Ny','Nz'))
        assert current[0] is not None
        fields = [np.ascontiguousarray(np.broadcast_to(value[..., None] if np.ndim(value)==2 else value, shape),
                                      dtype=np.float64) for value in current[0]]
        driver.call = lambda *packed: call(*packed, *(value.ctypes.data_as(dp) for value in fields))
        c = inspect.signature(driver).bind(*args, **kwargs)
        c.apply_defaults();c=c.arguments
        if dimension == 3:
            for values, layout in zip(observed.pop('warmup'),
                                      ('real-cell(x,y,z)-warm', 'real-cell(x,y,z)-return')):
                ranges(c, values, 'main', layout)
        else:
            ranges(c, (c['Ta_init'],c['Tb_init']), 'main-warm', 'real-cell(x,y)')
        result = driver(*args, **kwargs)
        ranges(c, result[:2], 'main-return' if dimension == 2 else 'main',
               'real-cell(x,y)' if dimension == 2 else 'real-cell(x,y,z)-return')
        observed['last'] = (c, result[:2])
        return result
    h_scalar, prop_field = energy._h_scalar, energy._prop_field
    def scalar(t, p, fluid):
        return float(model_enthalpy(t, fluid)) if fluid in ('air','water') else h_scalar(t, p, fluid)
    def field(name, t, p, fluid):
        return model_enthalpy(t, fluid) if name == 'H' and fluid in ('air','water') else prop_field(name,t,p,fluid)
    with patch.object(runtime, 'solve_full_domain_3d', warmup), \
         patch.object(energy, 'solve_ltne_enthalpy_3d_pipeline', selected), \
         patch.object(energy, '_h_scalar', scalar), patch.object(energy, '_prop_field', field), \
         (selected_2d_heat_transfer_reference() if dimension == 2 else nullcontext()):
        yield
        if 'last' in observed:
            ranges(*observed['last'], 'final', 'real-cell(x,y)' if dimension == 2 else 'real-cell(x,y,z)')


class SameMapThermal:
    def __init__(self):
        self.model_h = self.temperature = self.strict_library = None
        self.calls = []
        self.native_entries = []
        self.last_strict = None

    def close(self):
        if self.temperature is not None:
            self.temperature.close()

    def _call(self, route, function, **kwargs):
        row = dict(route=route, max_iterations=kwargs['max_iterations'], returned=False)
        self.calls.append(row)
        result = function(**kwargs)
        row.update(returned=True, iterations=int(result[3]['iterations']),
                   converged=bool(result[3]['converged']))
        return result

    def _native_entry(self, route, function, *args):
        row = dict(route=route, returned=False)
        self.native_entries.append(row)
        code = function(*args)
        row.update(returned=True, native_code=int(code))
        return code

    @staticmethod
    def _prepared(c, dimension):
        shape = tuple(int(c['N'+axis]) for axis in 'xyz'[:dimension])
        def field(value):
            if value is None:
                return None
            value = np.asarray(value, dtype=np.float64)
            if dimension == 2 and value.ndim == 3:
                assert value.shape[-1] == 1
                value = value[..., 0]
            return np.array(np.broadcast_to(value, shape), order='C', copy=True)
        def boundary(value):
            if value is None:
                return None
            value = np.asarray(value, dtype=np.float64)
            if dimension == 2 and value.ndim == 2:
                assert value.shape[-1] == 1
                value = value[..., 0]
            return np.ascontiguousarray(value)
        widths = tuple(np.asarray(c['d'+axis+'_arr'], dtype=np.float64) for axis in 'xyz'[:dimension])
        initial = tuple(field(c[key+'_init']) for key in ('Ta', 'Tb', 'Ts'))
        assert all(x is None for x in initial) or all(x is not None for x in initial)
        options = dict(widths=widths,
            conductivity=tuple(field(c[key]) for key in ('K_ffA', 'K_ffB', 'K_ss')),
            exchange=tuple(field(c['h_v'+s]) for s in 'AB'),
            directions=tuple(c['dir_'+s] for s in 'AB'), inlets=tuple(c['T_in'+s] for s in 'AB'),
            profiles=tuple(boundary(c['T_in'+s+'_profile']) for s in 'AB'),
            openings=tuple(boundary(c['inlet_mask_'+s]) for s in 'AB'),
            initial=None if initial[0] is None else initial,
            max_iterations=c['max_iter'], chunk_iterations=c['conv_chunk'] or (500 if dimension == 2 else 250),
            q_relative_tolerance=(c['q_rel_tol'] if c['q_rel_tol'] is not None else
                                  min(c['tol']*2e-3, 1e-3) if dimension == 2 else max(c['tol']*10, 1e-4)),
            cancel_check=c['cancel_check'], progress=c['progress_cb'])
        if dimension == 2:
            options['red_black'] = bool(ltne_energy._RB_ENERGY_2D and np.prod(shape) > ltne_energy._RB_ENERGY_2D_GATE)
        else:
            options['red_black'] = bool(ltne_energy_3d._RB_ENERGY and np.prod(shape) > ltne_energy_3d._RB_ENERGY_GATE)
        return options, field, boundary

    def _model(self, options, c, mass, dimension):
        if self.model_h is None:
            self.model_h = NativeModelHDriver(library('tpmshx_model_h_shared', 'TPMSHX_MODEL_H_PUBLIC_LIBRARY'))
            original_call = self.model_h.call
            self.model_h.call = lambda *args: self._native_entry('model_h', original_call, *args)
        if dimension == 3:
            alpha = tuple(c[key] if c[key] is not None else c['alpha_T']
                          for key in ('alpha_T_fA', 'alpha_T_s', 'alpha_T_fB'))
            sources = tuple(c[key] for key in ('mms_S_A_field', 'mms_S_B_field', 'mms_S_s_field'))
        else:
            alpha, sources = None, (None, None, None)
        return self._call('model_h_'+str(dimension)+'d', self.model_h, **options,
            mass_faces=mass, fluids=c['model_fluids'], sources=sources,
            alpha=alpha, accelerate=c['accelerate'])

    def plane(self, c, state, cfg):
        options, _, _ = self._prepared(c, 2)
        if c['model_fluids'] is not None:
            return self._model(options, c, (c['mass_flux_A'], c['mass_flux_B']), 2)
        # The old temperature-labelled full2D consumer now solves strict h(T).
        # Its raw mass already belongs to the observed original Python state.
        assert 'sco2' not in (cfg['fluid_A'], cfg['fluid_B'])
        assert c['Tb_prescribed'] is None
        return self._call('full_cc_2d', self._strict, **options, dimension=2,
            mass_faces=(state.mass_flux_A, state.mass_flux_B),
            fluids=(cfg['fluid_A'], cfg['fluid_B']), accelerate=True, alpha=(.2, 1., .2))

    def volume(self, c, prob):
        dimension = 2 if c['Nz'] == 1 else 3
        options, field, boundary = self._prepared(c, dimension)
        if c['model_fluids'] is not None:
            return self._model(options, c, (c['model_mass_A'], c['model_mass_B']), 3)
        staggered = dimension == 3 and c['ufA'] is not None
        true_h = any(fluid in ('sco2', 'co2') for fluid in (prob.fluid_type_A, prob.fluid_type_B))
        if true_h:
            # True-h warm-up and single-A sCO2 keep the original temperature map.
            return ltne_energy_3d.solve_full_domain_3d(**c)
        if not staggered and not true_h:
            from sjtu_tpmshx.solvers.backends.python.three_d import runtime
            from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes
            assert prob.sB is not None and c['Tb_prescribed'] is None
            assert all(c[key] is None for key in ('mms_S_A_field', 'mms_S_B_field', 'mms_S_s_field'))
            raw, mass = [], []
            for solver, mapping, eps in ((prob.sA, prob.axis_map, prob.eps_fA_arr),
                                         (prob.sB, prob.axis_map_B, prob.eps_fB_arr)):
                faces = runtime._solver_staggered_to_real(solver, mapping, (prob.Nx, prob.Ny, prob.Nz))
                raw.append(tuple(x.copy() for x in faces))
                # Match the live outer's local _rho_real mapping of this SIMPLE state.
                rho = solver.rho_field.transpose(mapping['solver_to_real_perm'])
                if mapping['is_reverse']:
                    rho = np.flip(rho, axis=mapping['stream_real_axis'])
                mass.append(face_mass_fluxes(*faces, np.ascontiguousarray(rho, dtype=np.float64), eps,
                                             prob.dx, prob.dy, prob.dz))
            depth = float(np.sum(prob.dz))
            native_mass = mass
            if dimension == 2:
                assert all(np.all(side[2] == 0.) for side in mass)
                native_mass = tuple(tuple(np.ascontiguousarray(x[..., 0]/depth) for x in side[:2]) for side in mass)
            alpha = (.2, 1., .2) if dimension == 2 else (c['alpha_T'],)*3
            result = self._call('full_cc_'+str(dimension)+'d', self._strict, **options,
                dimension=dimension, mass_faces=native_mass,
                fluids=(prob.fluid_type_A, prob.fluid_type_B), accelerate=False, alpha=alpha)
            if dimension == 2:
                result = (*(x[..., None].copy() for x in result[:3]), result[3])
            q = np.array(result[3]['_full_reference']['advective_inward'], copy=True)
            if dimension == 2:
                q *= depth
            self.last_strict = dict(prob=prob, mass=mass, faces=raw, state=tuple(x.copy() for x in result[:3]),
                                    q=q, complete=result[3]['_full_reference']['boundary_complete'])
            return result
        if self.temperature is None:
            self.temperature = NativeTemperatureDriver(library('tpmshx_temperature_shared', 'TPMSHX_TEMPERATURE_LIBRARY'))
            original_call = self.temperature.call
            self.temperature.call = lambda *args: self._native_entry('temperature', original_call, *args)
        velocity = tuple(tuple(c[prefix+s] for prefix in ('uf', 'vf', 'wf')) if staggered else
                         tuple(field(c[prefix+s]) for prefix in ('uc', 'vc', 'wc')[:dimension]) for s in 'AB')
        eps = tuple(field(c['eps_'+s] if c['eps_'+s] is not None else .5*np.asarray(c['epsilon'])) for s in 'AB')
        capacity = tuple(boundary(c['inlet_flux_'+s]) for s in 'AB')
        if dimension == 2:
            capacity = tuple(None if x is None else x/float(np.sum(prob.dz)) for x in capacity)
        alpha = None if dimension == 2 else tuple(c[key] if c[key] is not None else c['alpha_T']
                          for key in ('alpha_T_fA', 'alpha_T_s', 'alpha_T_fB'))
        if not staggered:
            options['red_black'] = options['red_black'] if dimension == 2 else False
        result = self._call('temperature_staggered' if staggered else 'temperature_cc_'+str(dimension)+'d',
            self.temperature, **options, scheme='staggered_3d' if staggered else 'cell_centered_'+str(dimension)+'d',
            epsilon=eps, rho_cp=tuple(field(c['rho_cp_f'+s]) for s in 'AB'), velocity=velocity,
            inlet_capacity=capacity, prescribed_b=field(c['Tb_prescribed']),
            sources=tuple(field(c[key]) for key in ('mms_S_A_field', 'mms_S_B_field', 'mms_S_s_field')),
            alpha=alpha, second_order_b=dimension == 3, conservative=staggered and c['conservative_ltne'])
        return (*(x[..., None].copy() for x in result[:3]), result[3]) if dimension == 2 else result

    def _strict(self, *, dimension, widths, conductivity, exchange, directions, inlets,
                profiles, openings, initial, max_iterations, chunk_iterations,
                q_relative_tolerance, red_black, mass_faces, fluids, accelerate, alpha,
                cancel_check, progress):
        if self.strict_library is None:
            self.strict_library = ct.CDLL(str(library('full_thermal_test', 'TPMSHX_FULL_THERMAL_TEST_LIBRARY')))
            dp, sp = ct.POINTER(ct.c_double), ct.POINTER(ct.c_size_t)
            self.strict_library.test_full_thermal_strict.argtypes = [sp, ct.POINTER(dp), sp, sp, dp, ct.POINTER(_Callbacks), sp, dp,
                                                                    ct.POINTER(ct.c_char), ct.c_size_t]
            self.strict_library.test_full_thermal_strict.restype = ct.c_int
        shape = tuple(len(x) for x in widths)
        state = [np.empty(shape) for _ in range(3)] if initial is None else [x.copy() for x in initial]
        optional = lambda x: np.empty(0) if x is None else np.ascontiguousarray(x)
        masses = [*mass_faces[0], *([np.empty(0)] if dimension == 2 else []),
                  *mass_faces[1], *([np.empty(0)] if dimension == 2 else [])]
        arrays = [*widths, *([np.ones(1)] if dimension == 2 else []), *state,
                  *conductivity, *exchange, *masses,
                  optional(profiles[0]), optional(openings[0]), optional(profiles[1]), optional(openings[1])]
        arrays = [np.ascontiguousarray(x, dtype=np.float64) for x in arrays]
        assert len(arrays) == 21
        dp = ct.POINTER(ct.c_double)
        config = (ct.c_size_t*10)(dimension, max_iterations, chunk_iterations, initial is not None,
            accelerate, red_black, *directions, *(('air', 'water').index(f) for f in fluids))
        values = (ct.c_double*6)(*inlets, q_relative_tolerance, *alpha)
        status, metrics, error = (ct.c_size_t*4)(), (ct.c_double*5)(), ct.create_string_buffer(2048)
        callback_errors = []
        @_Cancel
        def cancelled(_):
            if callback_errors:
                return 1
            try:
                return int(cancel_check()) if cancel_check is not None else 0
            except BaseException as error:
                callback_errors.append(error)
                return 1
        @_Progress
        def progressed(_, done, total):
            if not callback_errors and progress is not None:
                try:
                    progress(done, total)
                except BaseException as error:
                    callback_errors.append(error)
        callbacks = _Callbacks(cancelled, progressed, None)
        code = self._native_entry('strict_full_cc', self.strict_library.test_full_thermal_strict,
            (ct.c_size_t*3)(*shape, *([1] if dimension == 2 else [])),
            (dp*21)(*(x.ctypes.data_as(dp) for x in arrays)), (ct.c_size_t*21)(*(x.size for x in arrays)),
            config, values, ct.byref(callbacks), status, metrics, error, len(error))
        if callback_errors:
            raise callback_errors[0]
        assert code == 0, error.value.decode()
        if status[0] == 2:
            raise CancelledError('compute cancelled by user')
        assert status[0] in (0, 1) and status[2]
        info = dict(converged=status[0] == 0, iterations=int(status[1]), residual=metrics[0],
            _full_reference=dict(advective_inward=(metrics[3], metrics[4]),
                                 boundary_complete=bool(status[3]), energy_error_ratio=metrics[2]))
        return *state, info

    def volume_reporting(self, prob, outer, metrics):
        if self.last_strict is None:
            return metrics
        r = self.last_strict
        assert r['prob'] is prob
        changes = {}
        for s, label in enumerate('AB'):
            outer.native_evidence['mass_'+label] = tuple(x.copy() for x in r['mass'][s])
            outer.native_evidence['face_velocity_'+label] = tuple(x.copy() for x in r['faces'][s])
            direction = getattr(prob, 'f'+label)['dir']
            axis, sign = direction//2, 1. if direction % 2 == 0 else -1.
            inlet, outlet = (0, -1) if sign > 0 else (-1, 0)
            mass = r['mass'][s][axis]
            m_in = float(np.maximum(sign*np.take(mass, inlet, axis=axis), 0.).sum())
            weights = np.maximum(sign*np.take(mass, outlet, axis=axis), 0.)
            t_out = np.take(r['state'][s], outlet, axis=axis)
            changes['m_dot_'+label+'_simple'] = m_in
            changes['T_'+label+'_out'] = float(np.sum(weights*t_out)/weights.sum()) if weights.sum() > 0 else float('nan')
            changes['Q_enthalpy_'+label] = abs(float(r['q'][s])) if r['complete'] else float('nan')
        return replace(metrics, Q=changes['Q_enthalpy_A'], **changes)


@pytest.fixture
def same_thermal():
    adapter = SameMapThermal()
    try:
        yield adapter
    finally:
        adapter.close()
