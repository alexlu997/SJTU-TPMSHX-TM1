"""Run cold model-image checks in a fresh test process."""
from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
import ctypes as ct
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import traceback


ROOT = Path(__file__).resolve().parents[4]
EOS_CALLS = {'water_pt', 'co2_scalar_bundle', 'co2_pt', 'sco2_pt', 'sco2_hp_scalar', 'sco2_hp'}
EXCLUDED_RAW_PATHS = {'flow.0.last.pressure.solve_seconds', 'flow.1.last.pressure.solve_seconds'}
RAW_KIND = 'NativeIsolationRawV1'


@dataclass
class RawRecord:
    data: dict


def configured_python():
    lines = (ROOT / '.venv-path').read_text(encoding='utf-8').splitlines()
    assert lines and lines[0].strip(), '.venv-path must name the configured interpreter'
    python = Path(lines[0].strip())
    assert python.is_absolute() and python.is_file(), 'the configured interpreter must exist at an absolute path'
    assert Path(sys.executable).resolve() == python.resolve(), 'run tests with the configured interpreter'
    return python


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def same(actual, expected, path=''):
    import numpy as np
    if path in EXCLUDED_RAW_PATHS:
        return
    if isinstance(expected, Mapping):
        assert isinstance(actual, Mapping) and set(actual) == set(expected), (path, 'mapping keys')
        for key in expected:
            same(actual[key], expected[key], f'{path}.{key}'.lstrip('.'))
    elif isinstance(expected, np.ndarray):
        assert isinstance(actual, np.ndarray), (path, 'array type')
        np.testing.assert_array_equal(actual, expected, strict=True, err_msg=path)
        if expected.dtype.kind == 'f':
            zeros = (actual == 0.) & (expected == 0.)
            np.testing.assert_array_equal(np.signbit(actual)[zeros], np.signbit(expected)[zeros], err_msg=path)
    elif isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected), (path, 'sequence extent')
        for index, (left, right) in enumerate(zip(actual, expected)):
            same(left, right, f'{path}.{index}'.lstrip('.'))
    elif isinstance(expected, (float, np.floating)) and math.isnan(expected):
        assert isinstance(actual, (float, np.floating)) and math.isnan(actual), path
    else:
        assert actual == expected, (path, actual, expected)
        if isinstance(expected, (float, np.floating)) and expected == 0.:
            assert math.copysign(1., actual) == math.copysign(1., expected), (path, 'zero sign')


def encoded(value):
    import numpy as np
    array = np.asarray(value)
    return {'dtype': array.dtype.str, 'shape': list(array.shape), 'values': array.tolist()}


def rejection(function, expected_type, text):
    try:
        function()
    except expected_type as error:
        assert text.lower() in str(error).lower(), str(error)
        return {'type': type(error).__name__, 'message': str(error),
                'cause_type': type(error.__cause__).__name__ if error.__cause__ else None,
                'cause': str(error.__cause__) if error.__cause__ else None}
    raise AssertionError('an original rejected state was accepted')


class NativeTrace:
    def __init__(self, roles, version):
        self.roles, self.version = roles, version
        self.barrier = threading.Barrier(len(roles)) if len(roles) > 1 else None
        self.local, self.lock = threading.local(), threading.Lock()
        self.events, self.first, self.live_owners = [], {}, set()

    def call(self, function, symbol, source, args):
        role = getattr(self.local, 'role', None)
        assert role in self.roles, f'unexpected EOS/solve call before worker dispatch: {symbol}'
        assert role.startswith(source), (role, source, symbol)
        with self.lock:
            first = role not in self.first
            if first:
                self.first[role] = None
        if first and self.barrier:
            self.barrier.wait(timeout=60)
        event = {'role': role, 'symbol': symbol, 'image': source,
                 'native_thread_id': threading.get_native_id(), 'start_ns': time.perf_counter_ns()}
        try:
            code = function(*args)
            event['end_ns'], event['status'] = time.perf_counter_ns(), int(code)
            if source == 'solver':
                from sjtu_tpmshx.solvers.backends.cpp._full_3d_abi import _Result
                pointer = ct.cast(args[-3], ct.POINTER(_Result))
                event['result_slot'] = ct.cast(pointer, ct.c_void_p).value
                owner = pointer.contents.owner
                event['result_owner'] = owner
                if not code:
                    assert owner, 'successful native solve has no result owner'
                    with self.lock:
                        assert owner not in self.live_owners, 'two live runs share a result owner'
                        self.live_owners.add(owner)
                    assert pointer.contents.has_true_h, 'the mixed case did not execute its EOS route'
                    event['compiled_coolprop_version'] = bytes(pointer.contents.true_h.coolprop_version).decode()
                    assert event['compiled_coolprop_version'] == self.version
            return code
        finally:
            event.setdefault('end_ns', time.perf_counter_ns())
            with self.lock:
                self.events.append(event)
                if first:
                    self.first[role] = event

    def release(self, function, args):
        from sjtu_tpmshx.solvers.backends.cpp._full_3d_abi import _Result
        pointer = ct.cast(args[0], ct.POINTER(_Result))
        owner = pointer.contents.owner
        with self.lock:
            function(*args)
            assert not pointer.contents.owner, 'the creating library did not clear its released result'
            if owner:
                assert owner in self.live_owners
                self.live_owners.remove(owner)
                self.events.append({'role': self.local.role, 'release_owner': owner,
                                    'native_thread_id': threading.get_native_id()})

    def finish(self):
        assert not self.live_owners, 'a successful result owner was not released'
        assert set(self.first) == set(self.roles) and all(self.first.values())
        if not self.barrier:
            return
        first = list(self.first.values())
        assert len({event['native_thread_id'] for event in first}) == len(self.roles)
        assert all(event['status'] == 0 for event in first)
        overlap = min(event['end_ns'] for event in first) - max(event['start_ns'] for event in first)
        assert overlap > 0, 'the first C ABI call intervals did not overlap'
        if all(role.startswith('solver') for role in self.roles):
            assert len({event['result_slot'] for event in first}) == len(self.roles)
        # These intervals include FFI/GIL handoff, not internal factory entry times.


class SolverCall:
    def __init__(self, function, trace):
        object.__setattr__(self, 'function', function)
        object.__setattr__(self, 'trace', trace)

    def __getattr__(self, name):
        return getattr(self.function, name)

    def __setattr__(self, name, value):
        setattr(self.function, name, value)

    def __call__(self, *args):
        return self.trace.call(self.function, 'tpmshx_solve_full_3d_v5', 'solver', args)


def oracle():
    import CoolProp.CoolProp as cp
    keys = ('D', 'V', 'L', 'C', 'H')
    values = [[cp.PropsSI(key, 'T', temperature, 'P', pressure, 'CO2')
               for temperature, pressure in ((320., 9e6), (500., 12e6))] for key in keys]
    for temperature in (300., 350.):
        state = cp.AbstractState('HEOS', 'Water')
        state.update(cp.PT_INPUTS, 2e6, temperature)
        assert state.phase() == cp.iphase_liquid
    return {'version': cp.get_global_param_string('version'),
            'revision': cp.get_global_param_string('gitrevision'), 'co2_values': values}


def backend(preparation):
    function = preparation.tpmshx_preparation_property_backend_v1
    function.argtypes = [ct.POINTER(ct.c_char), ct.c_size_t] * 3
    function.restype = ct.c_int
    version, revision, error = ct.create_string_buffer(128), ct.create_string_buffer(128), ct.create_string_buffer(2048)
    assert function(version, len(version), revision, len(revision), error, len(error)) == 0, error.value
    return {'version': version.value.decode(), 'revision': revision.value.decode()}


def child(plan_file):
    configured_python()
    plan_file = Path(plan_file)
    plan = json.loads(plan_file.read_text(encoding='utf-8'))
    directory = plan_file.parent
    import sjtu_tpmshx
    assert Path(sjtu_tpmshx.__file__).resolve().parent == ROOT / 'sjtu_tpmshx'
    os.environ['TPMSHX_PREPARATION_LIBRARY'] = plan['preparation']
    report, trace = {'state': 'running'}, None
    try:
        python_oracle = oracle() if plan['oracle_position'] == 'before' else None
        order = (['preparation'] if plan['mode'] == 'prep-reference' else ['solver']
                 if plan['mode'] == 'solver-reference' else plan['order'])
        libraries = {name: ct.CDLL(plan[name]) for name in order}
        report['load_order'] = order
        if 'preparation' in libraries:
            assert backend(libraries['preparation']) == plan['coolprop']
        if python_oracle is not None:
            assert {key: python_oracle[key] for key in ('version', 'revision')} == plan['coolprop']
        import numpy as np
        from sjtu_tpmshx.shared.models import _native_preparation, _native_properties
        roles = (['prep-0'] if plan['mode'] == 'prep-reference' else ['solver-0']
                 if plan['mode'] == 'solver-reference' else ['prep-0', 'solver-0']
                 if plan['mode'] == 'pair' else ['prep-0', 'prep-1']
                 if plan['mode'] == 'prep-pair' else ['solver-0', 'solver-1'])
        trace = NativeTrace(roles, plan['coolprop']['version'])
        original_load, original_function = _native_preparation._load_library, _native_properties._function

        def monitored_load(path):
            assert plan['mode'] != 'solver-reference', 'solver-only execution loaded the preparation image'
            assert Path(path).resolve() == Path(plan['preparation']).resolve()
            return original_load(path)

        def traced_property(owner, name):
            function = original_function(owner, name)
            if name not in EOS_CALLS:
                return function
            return lambda *args: trace.call(function, 'tpmshx_preparation_' + name + '_v1', 'prep', args)

        _native_preparation._load_library = monitored_load
        _native_properties._function = traced_property
        from sjtu_tpmshx.shared.models import fluid_props, co2_props, sco2_props
        from sjtu_tpmshx.shared.io.case_io import load_case
        from sjtu_tpmshx.shared.io.hdf5_data import write_record
        from sjtu_tpmshx.shared.domain.module_ports import RunControl
        case = load_case(plan['case'])
        assert case.grid['dimension'] == 3
        assert {case.parameters['fluid_type_' + side] for side in 'AB'} == {'water', 'sco2'}
        drivers, inputs = {}, {}
        if any(role.startswith('solver') for role in roles):
            from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
            from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
            for role in roles:
                if role.startswith('solver'):
                    inputs[role] = build_execution_inputs(case)
                    driver = NativeFull3DDriver(plan['solver'])
                    function = driver.library.tpmshx_solve_full_3d_v5
                    driver.library.tpmshx_solve_full_3d_v5 = SolverCall(function, trace)
                    release = driver.release
                    driver.release = lambda *args, function=release: trace.release(function, args)
                    drivers[role] = driver
        assert not trace.events, 'EOS or solve execution occurred during input assembly'
        if plan['oracle_position'] != 'before':
            assert not any(name == 'CoolProp' or name.startswith('CoolProp.') for name in sys.modules)
        temperatures, pressures = np.array([320., 500.]), np.array([9e6, 12e6])

        def preparation_once():
            fluid_props.check_water_state('water', np.array([300., 350.]), 2e6, where='model isolation')
            water = fluid_props.get('water')
            values = {key: encoded(getattr(water, key)(np.array([300., 350.]), 2e6))
                      for key in ('rho', 'mu', 'k', 'cp')}
            co2 = co2_props.co2_prop(('D', 'V', 'L', 'C', 'H'), temperatures, pressures)
            sco2 = sco2_props.sco2_prop(('D', 'V', 'L', 'C', 'H'), temperatures, pressures)
            return {'water_empirical': values, 'co2': encoded(np.stack(co2)), 'sco2': encoded(sco2)}

        def preparation_job():
            first = preparation_once()
            same(preparation_once(), first)
            errors = {
                'water_gas': rejection(lambda: fluid_props.check_water_state('water', [300., 350.],
                    [2e6, 10000.], where='model isolation'), fluid_props.WaterStateError, 'index=(1,)'),
                'co2_triple': rejection(lambda: co2_props.co2_prop('D', np.array([320., 210.]), 9e6), ValueError, 'CO2'),
                'sco2_bounds': rejection(lambda: sco2_props.sco2_prop('D', np.array([320., 701.]), 9e6), ValueError, '700'),
            }
            return {'kind': 'preparation', 'valid': first, 'rejected': errors}

        def solver_job(role):
            driver, (cfg, prepared) = drivers[role], inputs[role]
            control = RunControl(backend='cpp', native_library=plan['solver'], cpu_threads=1)
            first = driver.run_prepared(cfg, prepared, control)
            same(driver.run_prepared(cfg, prepared, control), first)
            path = directory / (role + '-raw.h5')
            write_record(path, RawRecord(first), RAW_KIND)
            water_side = next(side for side in 'AB' if cfg['fluid_type_' + side] == 'water')
            invalid = dict(cfg, **{'T_in' + water_side: 500., 'P_in' + water_side: 10000.})
            error = rejection(lambda: driver.run_prepared(invalid, prepared, control),
                              fluid_props.WaterStateError, 'water')
            return {'kind': 'solver', 'raw': str(path), 'rejected_water': error, 'abi': driver.abi}

        def worker(role):
            trace.local.role = role
            return preparation_job() if role.startswith('prep') else solver_job(role)

        with ThreadPoolExecutor(max_workers=len(roles)) as executor:
            futures = {role: executor.submit(worker, role) for role in roles}
            results = {role: future.result() for role, future in futures.items()}
        trace.finish()
        if plan['oracle_position'] == 'after':
            python_oracle = oracle()
        elif plan['oracle_position'] == 'none':
            assert not any(name == 'CoolProp' or name.startswith('CoolProp.') for name in sys.modules)
        if python_oracle is not None:
            assert {key: python_oracle[key] for key in ('version', 'revision')} == plan['coolprop']
            expected = np.asarray(python_oracle['co2_values'])
            for result in results.values():
                if result['kind'] == 'preparation':
                    np.testing.assert_allclose(result['valid']['co2']['values'], expected, rtol=2e-13, atol=0.)
                    for row, atol in enumerate((2e-8, 2e-14, 2e-10, 2e-5, 0.)):
                        np.testing.assert_allclose(result['valid']['sco2']['values'][row], expected[row], rtol=2e-10, atol=atol)
        report.update(state='passed', results=results)
    except BaseException:
        report.update(state='failed', traceback=traceback.format_exc())
    finally:
        if trace is not None:
            report['events'] = trace.events
        write_json(directory / 'report.json', report)
    return 0 if report['state'] == 'passed' else 1


if __name__ == '__main__':
    assert len(sys.argv) == 2, 'the test child requires one plan path'
    raise SystemExit(child(sys.argv[1]))
