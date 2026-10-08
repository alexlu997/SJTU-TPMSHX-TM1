"""Public temperature ABI and prepared thin-adapter qualification."""
from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers.backends.cpp.temperature import NativeTemperatureDriver
from sjtu_tpmshx.tests.native import test_temperature_driver as cc
from sjtu_tpmshx.tests.native import test_temperature_staggered as stag
component_cc = cc.temperature_native
component_staggered = stag.native


@pytest.fixture(scope="module")
def library():
    root = Path(__file__).resolve().parents[3]
    platform = "windows-x64" if os.name == "nt" else "macos-arm64"
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    path = root / ".cache/native-deps/build" / ("pilot-"+platform) / (("" if os.name == "nt" else "lib")+"tpmshx_temperature_shared"+suffix)
    override = os.environ.get("TPMSHX_TEMPERATURE_LIBRARY")
    path = Path(override) if override else path
    if not path.is_file():
        message = f"native temperature library not built: {path}"
        if override or os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1": pytest.fail(message)
        pytest.skip(message)
    return path.resolve()


@pytest.fixture(scope="module")
def native(library):
    driver = NativeTemperatureDriver(library)
    yield driver
    driver.close()


def prepared(c, staggered=False):
    two_d = c["shape"][2] == 1
    dimension = 2 if two_d else 3

    def field(x):
        return np.ascontiguousarray(x[..., 0]) if two_d and x.ndim > 1 else x

    def optional(x):
        return field(x) if x.size else None

    return dict(scheme="staggered_3d" if staggered else ("cell_centered_2d" if two_d else "cell_centered_3d"),
        widths=c["widths"][:dimension], conductivity=tuple(field(x) for x in (c["a"][0], c["b"][0], c["ks"])),
        exchange=tuple(field(c[key][1]) for key in ("a", "b")),
        epsilon=tuple(field(c[key][2]) for key in ("a", "b")),
        rho_cp=tuple(field(c[key][3]) for key in ("a", "b")),
        velocity=tuple(tuple(field(x) for x in c[key][4:4+dimension]) for key in ("a", "b")),
        directions=c["directions"], inlets=c["tin"], profiles=tuple(optional(c[key][7]) for key in ("a", "b")),
        openings=tuple(optional(c[key][8]) for key in ("a", "b")),
        inlet_capacity=tuple(optional(c[key][9]) for key in ("a", "b")),
        initial=tuple(field(x) for x in c["state"]) if c["warm"] else None,
        prescribed_b=optional(c["prescribed"]), max_iterations=c["maxit"], chunk_iterations=c["chunk"],
        q_relative_tolerance=c["qtol"], alpha=c["alpha"],
        second_order_b=True if staggered else c["sou_b"],
        conservative=c["conservative"] if staggered else False, red_black=c.get("rb", False),
        sources=tuple(optional(x) for x in (c["a"][10], c["b"][10], c["source_s"])) if staggered else (None, None, None))


def equivalent(c, native, monkeypatch=None, staggered=False, reference=None):
    changed_map = c["maxit"] > 0
    if changed_map:
        # This file qualifies the public adapter against the already qualified
        # current-map native component. It does not reproduce a thermal solver.
        assert reference is not None
        reference_case = copy.deepcopy(c)
        result = reference(reference_case)
        code, status, metrics = result[:3]
        assert code == 0, result[-1]
        info = dict(converged=status[0] == 0, iterations=status[1], residual=metrics[0])
        if c["shape"][2] != 1:
            info["delegated_to_2d"] = False
        expected = (*reference_case["state"], info)
    else:
        # Zero-step states retain the original Python parity contract. The
        # shared solid row also changes nonconservative staggered iterations.
        expected = stag.python(c, monkeypatch) if staggered else cc.python_temperature(c)
    options = prepared(c, staggered)
    before = copy.deepcopy(options)
    actual = native(**options)
    two_d = c["shape"][2] == 1
    residuals = {}
    if staggered and c["conservative"]:
        # The new SOU endpoint equation also differs at zero iterations.
        # Reuse the independent face-power oracle on actual returned T.
        oracle_case = dict(c, state=actual[:3])
        for side, label in enumerate(("A", "B")):
            if side == 1 and c["prescribed"].size:
                expected[3][f"eps_{label}_strict"] = None
                expected[3][f"eps_{label}_strict_cellmax"] = None
                continue
            f = c[("a", "b")[side]]
            faces = stag.energy._project_faces_div_free(*f[4:7], f[2], f[3], *c["widths"])
            residual, exchange = stag.independent_conservative_face_balance(oracle_case, side, faces)
            residuals[label] = residual
            scale = max(abs(float(np.sum(exchange))), 1.)
            expected[3][f"eps_{label}_strict"] = abs(float(np.sum(residual)))/scale
            expected[3][f"eps_{label}_strict_cellmax"] = float(np.max(np.abs(residual)))*residual.size/scale
    rtol, atol = ((2e-10, 2e-8) if staggered else ((2e-12, 2e-10) if two_d else (2e-11, 2e-9)))
    for field, target in zip(actual[:3], expected[:3]):
        np.testing.assert_allclose(field, target[..., 0] if two_d else target, rtol=rtol, atol=atol)
    for key, value in expected[3].items():
        if value is None or isinstance(value, (bool, int)):
            assert actual[3][key] == value
        else:
            assert actual[3][key] == pytest.approx(value, rel=2e-8, abs=2e-8)
    evidence = actual[3]["_native_temperature"]
    assert evidence["scheme"] == options["scheme"] and evidence["driver"] == "cpp" and evidence["driver_abi"] == 1
    assert evidence["duty_units"] == ("W/m" if two_d else "W")
    if staggered and c["conservative"]:
        for side, label in enumerate(("A", "B")):
            if side == 1 and c["prescribed"].size:
                assert label not in evidence["equations"]
                continue
            residual = residuals[label]
            np.testing.assert_allclose(evidence["equations"][label]["residual_W"], residual, rtol=2e-8, atol=2e-8)
    if c["maxit"]:
        volume = c["widths"][0][:, None, None]*c["widths"][1][None, :, None]
        if not two_d:
            volume = volume*c["widths"][2][None, None, :]
        ts, tb = (field[..., None] if two_d else field for field in (actual[2], actual[1]))
        q = np.sum(c["b"][1]*(ts-tb)*volume)
        assert evidence["Q_B"] == pytest.approx(q, rel=2e-8, abs=2e-8)
    for key in ("conductivity", "exchange", "epsilon", "rho_cp", "widths"):
        for target, original in zip(options[key], before[key]): np.testing.assert_array_equal(target, original)
    if options["initial"] is not None:
        for target, original in zip(options["initial"], before["initial"]): np.testing.assert_array_equal(target, original)
    return actual


@pytest.mark.parametrize("direction", range(4))
@pytest.mark.parametrize("sou_b", [False, True])
@pytest.mark.parametrize("rb", [False, True])
def test_public_2d_cc(native, monkeypatch, direction, sou_b, rb, component_cc):
    c = cc.temperature_case(directions=(direction, (direction+1)%4))
    c.update(sou_b=sou_b, rb=rb)
    monkeypatch.setattr(cc.ltne_energy, "_RB_ENERGY_2D", rb)
    monkeypatch.setattr(cc.ltne_energy, "_RB_ENERGY_2D_GATE", 0)
    equivalent(c, native, reference=component_cc)


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("budget", [0, 1, 19])
def test_public_cc2d_rb_frozen_b_and_budget(native, monkeypatch, warm, budget, component_cc):
    c = cc.temperature_case((5, 4, 1), (3, 1), sweeps=budget)
    c.update(rb=True, warm=warm, sou_b=True)
    c["prescribed"] = np.linspace(301, 329, np.prod(c["shape"])).reshape(c["shape"])
    monkeypatch.setattr(cc.ltne_energy, "_RB_ENERGY_2D", True)
    monkeypatch.setattr(cc.ltne_energy, "_RB_ENERGY_2D_GATE", 0)
    equivalent(c, native, reference=component_cc)


@pytest.mark.parametrize("direction", range(6))
def test_public_3d_cc(native, direction, component_cc):
    equivalent(cc.temperature_case((4, 3, 2), (direction, (direction+1)%6)), native, reference=component_cc)


@pytest.mark.parametrize("direction", range(6))
@pytest.mark.parametrize("rb", [False, True])
@pytest.mark.parametrize("conservative", [False, True])
def test_public_staggered(native, monkeypatch, direction, rb, conservative, component_staggered):
    c = stag.case(directions=(direction, (direction+1)%6))
    c.update(rb=rb, conservative=conservative)
    equivalent(c, native, monkeypatch, True, component_staggered)


@pytest.mark.parametrize("scheme", [0, 1, 2])
@pytest.mark.parametrize("warm", [False, True])
def test_frozen_b_and_owned_outputs(native, monkeypatch, scheme, warm, component_cc, component_staggered):
    c = stag.case() if scheme == 2 else cc.temperature_case((4, 3, 1 if scheme == 0 else 2))
    c["prescribed"] = np.linspace(301, 329, np.prod(c["shape"])).reshape(c["shape"])
    c["warm"] = warm
    if scheme == 2:
        c["a"][10] = np.full(c["shape"], 200.)
        c["b"][10] = np.full(c["shape"], -100.)
        c["source_s"] = np.full(c["shape"], 50.)
        c["a"][9] = np.full(c["a"][8].shape, .0004)
    result = equivalent(c, native, monkeypatch, scheme == 2,
                        component_staggered if scheme == 2 else component_cc)
    expected = c["prescribed"][..., 0] if scheme == 0 else c["prescribed"]
    np.testing.assert_array_equal(result[1], expected)
    saved = copy.deepcopy(result)
    native(**prepared(stag.case(), True))
    for actual, before in zip(result[:3], saved[:3]): np.testing.assert_array_equal(actual, before)
    if scheme == 2:
        np.testing.assert_array_equal(result[3]["_native_temperature"]["equations"]["A"]["residual_W"],
                                      saved[3]["_native_temperature"]["equations"]["A"]["residual_W"])


def test_staggered_b_mms_and_signed_capacity(native, monkeypatch, component_staggered):
    c = stag.case(sweeps=27)
    c["b"][10] = np.linspace(-1000, 1000, np.prod(c["shape"])).reshape(c["shape"])
    c["b"][9] = np.linspace(-.0001, .001, c["b"][8].size).reshape(c["b"][8].shape)
    equivalent(c, native, monkeypatch, True, component_staggered)


@pytest.mark.parametrize("scheme", [0, 1, 2])
def test_zero_budget_and_current_metadata(native, monkeypatch, scheme):
    c = stag.case(sweeps=0) if scheme == 2 else cc.temperature_case((4, 3, 1 if scheme == 0 else 2), sweeps=0)
    result = equivalent(c, native, monkeypatch, scheme == 2)
    assert not result[3]["converged"] and result[3]["iterations"] == 0
    assert np.isnan(result[3]["_native_temperature"]["Q_B"])


@pytest.mark.parametrize("stage", ["cancel", "progress"])
def test_callback_exception_identity(native, stage):
    marker = BaseException("temperature callback sentinel")
    c = prepared(stag.case(), True)

    def fail(*_): raise marker

    c["cancel_check" if stage == "cancel" else "progress"] = fail
    with pytest.raises(BaseException) as caught: native(**c)
    assert caught.value is marker
    assert native(**prepared(stag.case(), True))[3]["iterations"] == 17


def test_interrupt_after_native_return_releases_owner(native, monkeypatch):
    call, release, released = native.call, native.release, []
    def interrupted(*args):
        assert call(*args) == 0
        raise KeyboardInterrupt('native-return')
    def tracked(pointer):
        assert pointer._obj.owner
        release(pointer)
        released.append(pointer._obj.owner)
    monkeypatch.setattr(native, 'call', interrupted)
    monkeypatch.setattr(native, 'release', tracked)
    with pytest.raises(KeyboardInterrupt, match='native-return'):
        native(**prepared(stag.case(), True))
    assert released == [None]


@pytest.mark.parametrize("cancel_at", [1, 2, 3])
def test_cancel_and_progress(native, cancel_at):
    calls, progress = [], []
    def cancel():
        calls.append(1)
        return len(calls) >= cancel_at
    with pytest.raises(CancelledError):
        native(**prepared(stag.case(), True), cancel_check=cancel, progress=lambda *x: progress.append(x))
    assert len(calls) == cancel_at
    assert len(progress) == (0 if cancel_at == 1 else 1)


@pytest.mark.parametrize("invalid", ["acceleration", "CC_conservative", "CC_RB", "CC_source", "missing_phase", "shape", "alpha", "direction", "width", "negative_budget"])
def test_public_rejects_unsupported_and_invalid(native, invalid):
    c = prepared(cc.temperature_case())
    if invalid == "acceleration": c["accelerate"] = True
    if invalid == "CC_conservative": c["conservative"] = True
    if invalid == "CC_RB":
        c = prepared(cc.temperature_case((4, 3, 2)))
        c["red_black"] = True
    if invalid == "CC_source": c["sources"] = (np.ones((5, 4)), None, None)
    if invalid == "missing_phase": c["initial"] = c["initial"][:2]
    if invalid == "shape": c["rho_cp"] = (np.ones((2, 2)), c["rho_cp"][1])
    if invalid == "alpha": c["alpha"] = (.7, .5, 1.)
    if invalid == "direction": c["directions"] = (4, 2)
    if invalid == "width": c["widths"][0][0] = 0
    if invalid == "negative_budget": c["max_iterations"] = -1
    with pytest.raises(ValueError): native(**c)


def test_readonly_inputs_and_no_python_numerical_work(native, monkeypatch):
    c = prepared(stag.case(), True)
    expected = native(**c)
    def forbidden(*_, **__): raise AssertionError("Python temperature numerical work was called")
    for name in ("_gs_full_chunk_3d_stag", "_gs_full_chunk_3d_stag_rb", "_project_faces_div_free", "_conservation_residual_sum", "solve_full_domain_3d"):
        monkeypatch.setattr(stag.energy, name, forbidden)
    monkeypatch.setattr(cc.ltne_energy, "solve_full_domain", forbidden)
    for key in ("widths", "conductivity", "exchange", "epsilon", "rho_cp", "initial"):
        for array in c[key]: array.flags.writeable = False
    actual = native(**c)
    for a, b in zip(actual[:3], expected[:3]): np.testing.assert_array_equal(a, b)


def test_independent_native_instances_and_close(library):
    def run(direction):
        driver = NativeTemperatureDriver(library)
        try: return driver(**prepared(stag.case(directions=(direction, (direction+1)%6)), True))
        finally: driver.close()
    expected = [run(0), run(5)]
    with ThreadPoolExecutor(2) as pool: actual = list(pool.map(run, (0, 5)))
    for a, b in zip(actual, expected):
        for x, y in zip(a[:3], b[:3]): np.testing.assert_array_equal(x, y)
    driver = NativeTemperatureDriver(library)
    driver.close(); driver.close()
    with pytest.raises(RuntimeError, match="closed"): driver(**prepared(stag.case(), True))


def test_fresh_process_without_numba_scipy_or_python_eos(library):
    script = r'''
import sys
sys.modules['numba'] = None
sys.modules['scipy'] = None
sys.modules['CoolProp'] = None
import numpy as np
from sjtu_tpmshx.solvers.backends.cpp.temperature import NativeTemperatureDriver
x=NativeTemperatureDriver(sys.argv[1])
for mode in ('cell_centered_2d','cell_centered_3d','staggered_3d'):
    dim=2 if mode.endswith('2d') else 3
    shape=(4,3) if dim==2 else (4,3,2)
    velocities=[]
    for side in range(2):
        velocities.append(tuple(np.full(tuple(n+(a==axis) for a,n in enumerate(shape)), .1 if side==axis else 0.)
            if mode=='staggered_3d' else np.full(shape,.1 if side==axis else 0.) for axis in range(dim)))
    if mode=='staggered_3d': velocities[0][0][1,0,0]+=.01
    answer=x(scheme=mode,widths=tuple(np.full(n,.01) for n in shape),conductivity=(.2,.2,5.),
        exchange=(10000.,10000.),epsilon=(.35,.35),rho_cp=(1200.,1200.),velocity=velocities,
        directions=(0,2),inlets=(350.,300.),max_iterations=20,chunk_iterations=5,
        conservative=mode=='staggered_3d')
    assert all(np.isfinite(a).all() for a in answer[:3])
    assert answer[3]['_native_temperature']['driver']=='cpp'
x.close()
assert sys.modules['numba'] is None and sys.modules['scipy'] is None and sys.modules['CoolProp'] is None
print('native temperature all modes without Python numerical libraries PASS')
'''
    result = subprocess.run([sys.executable, "-c", script, str(library)], cwd=Path(__file__).resolve().parents[3],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "all modes" in result.stdout


@pytest.mark.parametrize("kind", ["static", "shared"])
def test_pure_c_callers(library, kind):
    caller = library.parent / ("temperature_c_"+kind+(".exe" if os.name == "nt" else ""))
    assert caller.is_file(), f"native C caller not built: {caller}"
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "CONDA", "DYLD")) and k != "VIRTUAL_ENV"}
    if os.name != "nt": environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    result = subprocess.run([str(caller)], env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
    assert "PASS" in result.stdout
