"""minmod (solvers/_kernels_2d) must stay byte-identical to the inline block
the SOU deferred-correction kernels used before extraction (DUP-C / #4)."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers._kernels_2d import minmod


def test_model_enthalpy_does_not_depend_on_first_caller(tmp_path):
    import json
    import os
    import subprocess
    import sys

    # 3D uses fastmath; 2D calls the same polynomial without it. Either
    # caller can be the first compiler in an isolated process/cache.
    script = '''
import json, sys
import numpy as np
from numba import njit
from sjtu_tpmshx.solvers._kernels_2d import _model_h
from sjtu_tpmshx.models.tpms_props import model_h_coefficients

@njit(fastmath=True)
def fast_caller(t, coefficients):
    return _model_h(t, coefficients)

coefficients = [model_h_coefficients(fluid) for fluid in ('air', 'water')]
temperatures = np.random.default_rng(41).uniform(280., 363., 38).tolist()
first = fast_caller if sys.argv[1] == 'fast-first' else _model_h
first(temperatures[0], coefficients[0])
values = [_model_h(t, cp) for cp in coefficients for t in temperatures]
from sjtu_tpmshx.solvers.ltne_energy import _model_h_faces
T = np.array(temperatures[:6]).reshape(3, 2)
mass = (np.full((4, 2), .0123), np.full((3, 3), -.0187))
for cp in coefficients:
    capacity, deferred = _model_h_faces(T, mass, cp, 0, np.full(2, 320.5), np.ones(2), True)
    values.extend(np.concatenate((*[f.ravel() for f in capacity], *[f.ravel() for f in deferred])).tolist())
from sjtu_tpmshx.solvers.ltne_energy import _gs_full_chunk
rng = np.random.default_rng(9)
nx, ny = 7, 5
shape = (nx, ny)
Ta, Tb, Ts = (rng.uniform(300., 350., shape) for _ in range(3))
last_a, last_b = np.empty(shape), np.empty(shape)
one = np.ones(shape)
mass_a = (np.full((nx+1, ny), .0123), np.zeros((nx, ny+1)))
mass_b = (np.zeros((nx+1, ny)), np.full((nx, ny+1), -.0187))
change = _gs_full_chunk(
    Ta, Tb, Ts, nx, ny, rng.uniform(.001, .003, nx), rng.uniform(.001, .003, ny),
    one*.04, one*.6, one*5., one*1e5, one*2e5, one*.4, one*.4,
    one*1200., one*4.18e6, one*2., one*0., one*0., one*-.01,
    0, 3, np.full(ny, 350.), np.full(nx, 300.), np.ones(ny), np.ones(nx),
    9, 0, 0, None, None, mass_a, mass_b, coefficients[0], coefficients[1], last_a, last_b)
values.extend(np.concatenate([v.ravel() for v in (Ta, Tb, Ts, last_a, last_b)]).tolist())
values.append(change)
print(json.dumps(values))
'''
    results = []
    for order in ('fast-first', 'strict-first'):
        child = subprocess.run(
            [sys.executable, '-c', script, order], check=True, capture_output=True,
            text=True, env=os.environ | {'NUMBA_CACHE_DIR': str(tmp_path / order)})
        results.append(json.loads(child.stdout))
    np.testing.assert_array_equal(*results)


def _minmod_ref(gu, gd):
    """The exact block minmod() replaced in every _sou_corr_* kernel."""
    phi = 0.0
    if gu * gd > 0:
        phi = min(abs(gu), abs(gd))
        if gu < 0:
            phi = -phi
    return phi


@pytest.mark.parametrize("gu,gd", [
    (0.0, 0.0), (1.0, 0.0), (0.0, 1.0),
    (2.0, 3.0), (3.0, 2.0), (-2.0, -3.0), (-3.0, -2.0),
    (1.0, -1.0), (-1.0, 1.0), (1e-12, 1e-12), (5.0, -0.1),
    (-0.1, -5.0), (1.5, 1.5),
])
def test_minmod_matches_reference_scalar(gu, gd):
    assert minmod(gu, gd) == _minmod_ref(gu, gd)


def test_minmod_matches_reference_random():
    rng = np.random.default_rng(7)
    a = rng.standard_normal(5000)
    b = rng.standard_normal(5000)
    for gu, gd in zip(a, b):
        assert minmod(float(gu), float(gd)) == _minmod_ref(float(gu), float(gd))


def test_minmod_properties():
    assert minmod(2.0, 5.0) == 2.0      # same sign -> signed min magnitude
    assert minmod(-2.0, -5.0) == -2.0
    assert minmod(2.0, -5.0) == 0.0     # opposite sign -> 0
    assert minmod(0.0, 5.0) == 0.0      # zero -> 0
