"""Stable model-h C ABI: public metadata, callbacks and owned state.

Compare the public ABI with the same native component, then independently
audit its returned equations and boundary faces with the existing Python checks.
The historical Python iterator follows a different short-budget trajectory.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers.backends.cpp.model_h import NativeModelHDriver, _model_h_algorithm
from sjtu_tpmshx.tests.native import test_model_h_2d as plane
from sjtu_tpmshx.tests.native import test_model_h_3d as volume

native_plane = plane.native
native_volume = volume.native


@pytest.fixture(scope='module')
def driver():
    root = Path(__file__).resolve().parents[3]
    platform = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    suffix = '.dll' if os.name == 'nt' else ('.dylib' if sys.platform == 'darwin' else '.so')
    name = ('' if os.name == 'nt' else 'lib') + 'tpmshx_model_h_shared' + suffix
    override = os.environ.get('TPMSHX_MODEL_H_PUBLIC_LIBRARY')
    path = Path(override) if override else root / '.cache/native-deps/build' / ('pilot-'+platform) / name
    if not path.is_file():
        message = f'native model-h public library not built: {path}'
        if override or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    return NativeModelHDriver(path)


def arguments(c):
    dimension = len(c['shape'])
    optional = lambda x: x if x.size else None
    return dict(widths=c['widths'][:dimension], conductivity=(c['a'][0], c['b'][0], c['ks']),
        exchange=(c['a'][1], c['b'][1]), mass_faces=(c['a'][2:2+dimension], c['b'][2:2+dimension]),
        directions=c['directions'], inlets=c['tin'], fluids=tuple(('air', 'water')[f] for f in c['fluids']),
        profiles=tuple(optional(c[key][2+dimension]) for key in ('a', 'b')),
        openings=tuple(optional(c[key][3+dimension]) for key in ('a', 'b')),
        initial=c['state'] if c['warm'] else None,
        sources=tuple(optional(x) for x in (c['a'][7], c['b'][7], c['source_s'])) if dimension == 3 else (None,)*3,
        max_iterations=c['maxit'], chunk_iterations=c['chunk'], q_relative_tolerance=c['qtol'],
        alpha=c.get('alpha'), accelerate=c['accelerate'], red_black=c['rb'])


def compare(actual, expected, *, rtol, atol):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            compare(actual[key], expected[key], rtol=rtol, atol=atol)
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            compare(a, e, rtol=rtol, atol=atol)
    elif isinstance(expected, (str, bool, int)) or expected is None:
        assert actual == expected
    else:
        np.testing.assert_allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=True)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('kind', ['partial', 'cold', 'rb', 'zero', 'converged', 'anderson', 'unknown'])
def test_full_public_metadata(driver, native_plane, native_volume, dimension, kind):
    oracle = plane if dimension == 2 else volume
    c = oracle.straight_case() if kind in ('converged', 'anderson', 'unknown') else oracle.case()
    if kind == 'cold':
        c['warm'] = False
        for key in ('a', 'b'):
            c[key][2+dimension] = c[key][3+dimension] = np.empty(0)
    if kind == 'rb':
        c['rb'] = True
    if kind == 'zero':
        c['maxit'] = 0
    if kind == 'anderson':
        c.update(accelerate=True, maxit=139, chunk=67)
    if kind == 'unknown':
        c['a'][2][-1] = -.0001 if dimension == 2 else -.000001
    original = copy.deepcopy(c)
    reference = copy.deepcopy(c)
    component = (native_plane if dimension == 2 else native_volume)(reference)
    oracle.assert_actual_state(reference, component)
    actual = driver(**arguments(c))
    oracle.assert_equivalent(reference, component, actual)
    algorithm = ('shared_fv_model_h_2d_defect_v1' if dimension == 2
                 else 'shared_fv_model_h_3d_compensated_v1')
    assert _model_h_algorithm(driver.library, dimension) == algorithm
    info = actual[3].copy()
    assert info.pop('native_metadata') == dict(abi=1, algorithm=algorithm, red_black=c['rb'])
    compare(c, original, rtol=0, atol=0)
    if dimension == 2:
        json.dumps(actual[3], allow_nan=True)
    if kind == 'converged':
        assert actual[3]['converged']
    elif kind in ('zero', 'anderson', 'unknown'):
        assert not actual[3]['converged']


def test_manufactured_sources_preserve_certificate(driver, native_volume):
    c = volume.case(sweeps=31)
    c['a'][7] = np.full(c['shape'], 31.)
    c['b'][7] = np.full(c['shape'], -29.)
    c['source_s'] = np.full(c['shape'], 3.)
    reference = copy.deepcopy(c)
    component = native_volume(reference)
    volume.assert_actual_state(reference, component)
    volume.assert_equivalent(reference, component, driver(**arguments(c)))


def test_interrupt_after_native_return_releases_owner(driver, monkeypatch):
    call, release, released = driver.call, driver.release, []
    def interrupted(*args):
        assert call(*args) == 0
        raise KeyboardInterrupt('native-return')
    def tracked(pointer):
        assert pointer._obj.owner
        release(pointer)
        released.append(pointer._obj.owner)
    monkeypatch.setattr(driver, 'call', interrupted)
    monkeypatch.setattr(driver, 'release', tracked)
    with pytest.raises(KeyboardInterrupt, match='native-return'):
        driver(**arguments(plane.case()))
    assert released == [None]


@pytest.mark.parametrize('dimension', [2, 3])
def test_no_python_numerical_callbacks_and_owned_results(driver, monkeypatch, dimension):
    oracle = plane if dimension == 2 else volume
    c = oracle.case()
    def forbidden(*args, **kwargs):
        raise AssertionError('native driver called Python numerical implementation')
    for name in ('solve_full_domain' if dimension == 2 else 'solve_full_domain_3d', '_model_h_balance', '_model_h_faces'):
        monkeypatch.setattr(oracle.energy, name, forbidden)
    result = driver(**arguments(c))
    snapshot = copy.deepcopy(result)
    for _ in range(10):
        driver(**arguments(c))
    for key in ('a', 'b'):
        c[key][2][:] = 99
    compare(result, snapshot, rtol=0, atol=0)


@pytest.mark.parametrize('dimension', [2, 3])
def test_callbacks_cancel_recovery_and_concurrency(driver, dimension):
    c = (plane if dimension == 2 else volume).case()
    kwargs = arguments(c)
    events = []
    actual = driver(**kwargs, progress=lambda done, total: events.append((done, total)))
    assert events and events[-1] == (c['maxit'], c['maxit'])
    with pytest.raises(CancelledError):
        driver(**kwargs, cancel_check=lambda: True)
    class CallbackFailure(Exception):
        pass
    def fail(*args):
        raise CallbackFailure('callback test')
    for name in ('cancel_check', 'progress'):
        with pytest.raises(CallbackFailure, match='callback test'):
            driver(**kwargs, **{name: fail})
    compare(driver(**kwargs), actual, rtol=0, atol=0)
    with ThreadPoolExecutor(2) as pool:
        failed = pool.submit(driver, **kwargs, cancel_check=lambda: True)
        success = pool.submit(driver, **kwargs)
        with pytest.raises(CancelledError):
            failed.result()
        compare(success.result(), actual, rtol=0, atol=0)


@pytest.mark.parametrize('change', [dict(max_iterations=-1), dict(chunk_iterations=0), dict(fluids=('sco2', 'air')),
                                  dict(directions=(-1, 2)), dict(alpha=(.7, .7, .7))])
def test_invalid_contract_preserves_input(driver, change):
    c = plane.case()
    saved = copy.deepcopy(c)
    kwargs = arguments(c)
    kwargs.update(change)
    with pytest.raises(ValueError):
        driver(**kwargs)
    compare(c, saved, rtol=0, atol=0)


def test_binding_import_has_no_numba(driver):
    # Import and solve in a fresh process without importing either oracle.
    script = '''
import sys
import numpy as np
from sjtu_tpmshx.solvers.backends.cpp.model_h import NativeModelHDriver
d = NativeModelHDriver(sys.argv[1])
one=np.ones((1,1)); zero=np.zeros((1,1)); f=(np.zeros((2,1)),np.zeros((1,2)))
r=d(widths=(np.ones(1),np.ones(1)),conductivity=(zero,zero,zero),exchange=(one,one),
mass_faces=(f,f),directions=(0,1),inlets=(350.,300.),fluids=('air','water'),max_iterations=1,chunk_iterations=1)
assert r[3]['iterations']==1 and not r[3]['converged']
assert 'numba' not in sys.modules
assert 'sjtu_tpmshx.solvers.ltne_energy' not in sys.modules
assert 'sjtu_tpmshx.solvers.ltne_energy_3d' not in sys.modules
'''
    completed = subprocess.run([sys.executable, '-c', script, str(driver.path)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
