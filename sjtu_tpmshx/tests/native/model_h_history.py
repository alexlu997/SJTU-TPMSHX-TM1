"""Read-only test-bridge observations and fixed previously qualified AA inputs."""
import copy
import ctypes

import numpy as np
import pytest


def driver_function(library, dimension):
    function = getattr(library, f"test_model_h_{dimension}d")
    sp, dp = ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double)
    function.argtypes = [sp, ctypes.POINTER(dp), sp, sp, dp, sp, dp,
                         ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    function.restype = ctypes.c_int
    return function


def read_progress(library, shape):
    size, read = library.test_model_h_progress_size, library.test_model_h_progress_read
    size.argtypes, size.restype = [], ctypes.c_size_t
    dp = ctypes.POINTER(ctypes.c_double)
    read.argtypes, read.restype = [ctypes.c_size_t, dp, ctypes.c_size_t], ctypes.c_int
    count = int(np.prod(shape))
    rows = []
    for index in range(size()):
        values = np.empty(1+3*count)
        assert read(index, values.ctypes.data_as(dp), values.size) == 0
        rows.append((int(values[0]), [x.copy().reshape(shape) for x in values[1:].reshape(3, count)]))
    return rows


def read_trace(library, shape):
    size, read = library.test_model_h_trace_size, library.test_model_h_trace_read
    size.argtypes, size.restype = [], ctypes.c_size_t
    dp = ctypes.POINTER(ctypes.c_double)
    read.argtypes, read.restype = [ctypes.c_size_t, dp, ctypes.c_size_t], ctypes.c_size_t
    rows = []
    for index in range(size()):
        values = np.empty(4+5*int(np.prod(shape)))
        length = read(index, values.ctypes.data_as(dp), values.size)
        assert length > 0
        rows.append(values[:length].copy())
    return rows


def heat_in_driver_order(c, state):
    """Same physical volume integral, with sequential binary64 accumulation."""
    volume = c["widths"][0][:, None]*c["widths"][1][None, :]
    if len(c["shape"]) == 3:
        volume = volume[:, :, None]*c["widths"][2][None, None, :]
    terms = c["b"][1]*(state[2]-state[1])*volume
    heat = 0.
    for term in terms.flat:
        heat += float(term)
    return heat


def stable_chunks(c, history):
    """Independently reconstruct which accepted chunk states trigger finishing."""
    previous, previous_q = None, None
    for done, state in history:
        heat = heat_in_driver_order(c, state)
        stable = previous is not None and (
            abs(heat-previous_q)/max(abs(heat), abs(previous_q), 1.) < c["qtol"]
            and max(float(np.max(np.abs(a-b))) for a, b in zip(state, previous)) < .01)
        yield done, state, stable
        previous, previous_q = state, heat


def compare_shadow(c, native, dimension):
    """Exactly one official and one observed call, using identical fresh inputs."""
    other = copy.deepcopy(c)
    history, observed_history, trace = [], [], []
    actual = native(c, history=history)
    observed = native(other, history=observed_history, shadow=True, trace=trace)
    assert actual[0] == observed[0] == 0, (actual[-1], observed[-1])
    assert actual[1] == observed[1] and actual[-1] == observed[-1]
    for a, b in zip([*c["state"], actual[2], *actual[3]],
                    [*other["state"], observed[2], *observed[3]]):
        assert a.shape == b.shape and a.dtype == b.dtype and a.tobytes() == b.tobytes()
    assert len(history) == len(observed_history)
    for (done, state), (seen_done, seen_state) in zip(history, observed_history):
        assert done == seen_done
        assert all(a.tobytes() == b.tobytes() for a, b in zip(state, seen_state))
    decisions = []
    selected, ordinary, trial = None, None, None
    resets = 0
    for row in trace:
        kind = int(row[0])
        if kind == 4:
            assert dimension == 3 and row[3] == 0.
            resets += 1
        elif kind == 0:
            assert row[1] >= 1 and np.isfinite(row[2]) and row[2] >= 0
            selected = row
        elif kind == 1:
            assert selected is not None and selected[1] == 1
            assert row[2] == selected[2]
            np.testing.assert_array_equal(row[4:], selected[4:])
            ordinary = row
        elif kind == 2:
            assert ordinary is not None and selected[1] == 1
            assert row[1] == ordinary[1]+1 and row[2] == selected[2]
            np.testing.assert_array_equal(row[4:], selected[4:])
            trial = row
        elif kind == 3:
            assert ordinary is not None and trial is not None
            accepted = bool(np.isfinite(trial[2]) and trial[2] <= ordinary[2])
            expected = trial if accepted else ordinary
            assert row[1] == trial[1] and row[2] == expected[2]
            # These include actual 2D last_a/b, not reconstructed snapshots.
            assert row[4:].tobytes() == expected[4:].tobytes()
            decisions.append(accepted)
            selected, ordinary, trial = row, None, None
        else:
            pytest.fail(f"unknown model-h observation kind {kind}")
    assert ordinary is None and trial is None and selected is not None
    assert actual[2][0] == selected[2]  # Last accepted executor-reported update.
    count = int(np.prod(c["shape"]))
    assert selected[3] == count
    expected_fields = selected[4:].reshape(5 if dimension == 2 else 3, count)
    actual_fields = [*c["state"], *actual[3][:2]] if dimension == 2 else c["state"]
    assert all(a.ravel().tobytes() == b.tobytes() for a, b in zip(actual_fields, expected_fields))
    assert resets == (2*len(decisions) if dimension == 3 else 0)
    return actual, history, decisions, trace


def n4_solved_case(factory, dimension):
    """Frozen N4 solved/rb0 case: both dimensions observed reject then accept.

    Reproduce N4 lifecycle() and its strict 139/67 controls, without loading
    cache artifacts or adding a parameter search to the test population.
    """
    shape = (8, 3) if dimension == 2 else (8, 3, 3)
    c = factory(shape=shape, directions=(0, 1), sweeps=139, chunk=67)
    c.update(widths=[.01*(1+.1*np.arange(8)), .01*(1+.07*np.arange(3)),
                     np.ones(1) if dimension == 2 else .01*(1+.05*np.arange(3))],
             tin=(360., 300.), warm=False, accelerate=True, rb=False, qtol=1e-12, strict=True)
    indices = np.indices(shape)
    i, j = indices[:2]
    k = np.zeros(shape) if dimension == 2 else indices[2]
    c["state"] = [335+.1*i+.2*j+.3*k, 310+.2*i+.1*j+.1*k, 325+.15*i+0*j+0*k]
    ids = np.arange(int(np.prod(shape))).reshape(shape)
    c["ks"] = 2.*(1+.01*ids)
    area = c["widths"][1] if dimension == 2 else c["widths"][1][:, None]*c["widths"][2][None, :]
    for index, (key, conductivity, hv, mass) in enumerate((
            ("a", .03, 25000., .08), ("b", .2, 17000., -.2))):
        side = c[key]
        side[0], side[1] = conductivity*(1+.01*ids), hv*(1+.005*ids)
        for axis in range(dimension):
            side[2+axis][:] = 0.
        side[2][:] = mass*area
        side[2+dimension] = np.full(shape[1:], c["tin"][index])
        side[3+dimension] = np.ones(shape[1:])
        if dimension == 3:
            side[7] = np.zeros(shape)
    if dimension == 3:
        c.update(alpha=(.7, 1., 1.), source_s=np.zeros(shape))
    return c
