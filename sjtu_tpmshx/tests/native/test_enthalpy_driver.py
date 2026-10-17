"""Native true-h state, EOS, independent energy equations, and stop budgets."""
import ctypes
import os
from pathlib import Path
import platform
import subprocess
import sys

import CoolProp.CoolProp as CP
import numpy as np
import pytest

from sjtu_tpmshx.tests.native.enthalpy_fv_audit import energy


ROOT = Path(__file__).resolve().parents[3]
TABLES = ROOT / ".cache/native-deps/trueh-tables"
FLUID = {"air": 0, "water": 1, "sco2": 2}


def library_path():
    system = "macos" if sys.platform == "darwin" else ("windows" if os.name == "nt" else "linux")
    arch = platform.machine().lower()
    if arch in ("amd64", "x86_64"):
        arch = "x64" if os.name == "nt" else "x86_64"
    name = "enthalpy_driver_test.dll" if os.name == "nt" else (
        "libenthalpy_driver_test.dylib" if sys.platform == "darwin" else "libenthalpy_driver_test.so")
    return Path(os.environ.get("TPMSHX_ENTHALPY_DRIVER_LIBRARY",
        str(ROOT / ".cache/native-deps/build" / f"pilot-{system}-{arch}" / name))).resolve()


def load_native(path):
    lib = ctypes.CDLL(str(path))
    fn = lib.test_enthalpy_driver
    size_p, double_p = ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double)
    fn.argtypes = [size_p, ctypes.POINTER(double_p), size_p, size_p, double_p, ctypes.c_char_p,
                   size_p, double_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    fn.restype = ctypes.c_int

    def run(case, *, cancel_at=0, bad_size=None, table_directory=TABLES):
        shape = (case["Nx"], case["Ny"], case["Nz"])
        arrays = [np.array(case[key], dtype=float, copy=True) for key in ("dx", "dy", "dz", "K_ss")]
        for side in "AB":
            arrays += [np.array(case[key], dtype=float, copy=True) for key in
                       (f"pressure_{side}_field", f"eps_{side}_field", f"h_v{side}_field")]
            arrays += [np.array(x, copy=True) for x in case[f"mass_flux_{side}"]]
        states = [np.zeros(shape), np.zeros(shape)]
        states += [np.array(case[key], dtype=float, copy=True) if case.get(key) is not None
                   else np.zeros(shape) for key in ("Ta_init", "Tb_init", "Ts_init")]
        arrays += states
        assert all(a.flags.c_contiguous for a in arrays)
        pointers = (double_p * len(arrays))(*(a.ctypes.data_as(double_p) for a in arrays))
        sizes = (ctypes.c_size_t * len(arrays))(*(a.size for a in arrays))
        if bad_size is not None:
            sizes[bad_size] -= 1
        config = [FLUID[case["fluid_A"]], FLUID[case["fluid_B"]], case["n_outer"], case["n_sweep"],
                  *(int(case.get(key) is not None) for key in ("Ta_init", "Tb_init", "Ts_init")),
                  cancel_at, int(case["coupled_energy_tol"] is not None),
                  int(case["equation_energy_tol"] is not None)]
        values = [case[key] for key in ("T_inA", "P_A", "T_inB", "P_B", "omega", "tol")]
        values += [case[key] if case[key] is not None else 0.
                   for key in ("coupled_energy_tol", "equation_energy_tol")]
        status, metrics = (ctypes.c_size_t * 12)(), (ctypes.c_double * 17)()
        error = ctypes.create_string_buffer(2048)
        code = fn((ctypes.c_size_t * 3)(*shape), pointers, sizes,
                  (ctypes.c_size_t * len(config))(*config),
                  (ctypes.c_double * len(values))(*values), str(table_directory).encode(),
                  status, metrics, error, len(error))
        return dict(code=code, status=tuple(status), metrics=np.array(metrics), h=states[:2],
                    fields=states[2:], error=error.value.decode())

    run.lib = lib
    run.path = path
    return run


@pytest.fixture(scope="module")
def enthalpy_native():
    path = library_path()
    if not path.is_file():
        message = f"complete true-h qualification library is not built: {path}"
        if os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1" or "TPMSHX_ENTHALPY_DRIVER_LIBRARY" in os.environ:
            pytest.fail(message)
        pytest.skip(message)
    TABLES.mkdir(parents=True, exist_ok=True)
    return load_native(path)


def case_data(pair=("air", "water"), shape=(4, 3, 2), directions=(0, 1), warm=False):
    cells = np.arange(np.prod(shape)).reshape(shape)
    widths = [np.linspace(.004, .007, n) for n in shape]
    temperatures = [380. if pair[0] == "air" else (350. if pair[0] == "water" else 550.),
                    315. if pair[1] == "sco2" else 300.]
    pressures = [9e6 if pair[0] == "sco2" else 3e5,
                 8e6 if pair[1] == "sco2" else 2e5]
    result = dict(zip(("Nx", "Ny", "Nz", "dx", "dy", "dz"), (*shape, *widths)))
    result.update(eps_arr=np.full(shape, .64), K_ss=4.+.01*cells,
                  fluid_A=pair[0], fluid_B=pair[1], T_inA=temperatures[0], T_inB=temperatures[1],
                  P_A=pressures[0], P_B=pressures[1], n_outer=1200, n_sweep=5,
                  omega=.6, tol=2e-5, coupled_energy_tol=1e-3, equation_energy_tol=1e-3)
    for index, side in enumerate("AB"):
        pressure = pressures[index] - cells*20.
        result[f"pressure_{side}_field"] = pressure
        result[f"eps_{side}_field"] = .27+.001*cells if index == 0 else .37-.001*cells
        result[f"h_v{side}_field"] = (1e5 if index == 0 else 1.4e5)+cells*500.
        faces = [np.zeros(tuple(n+(axis == k) for k, n in enumerate(shape))) for axis in range(3)]
        direction = directions[index]
        axis = direction//2
        faces[axis].fill((1. if direction % 2 == 0 else -1.)*(.001 if index == 0 else .003))
        result[f"mass_flux_{side}"] = tuple(faces)
    if warm:
        result.update(Ta_init=np.full(shape, temperatures[0]-2.)+.003*cells,
                      Tb_init=np.full(shape, temperatures[1]+2.)-.003*cells,
                      Ts_init=np.full(shape, sum(temperatures)/2.))
    return result


def assert_audited(case, native):
    assert native['code'] == 0, native['error']
    status, metric = native['status'], native['metrics']
    widths = tuple(case[key] for key in ('dx', 'dy', 'dz'))
    conductivity, inlet = [], []
    for side, temperature, enthalpy, used in zip('AB', native['fields'], native['h'], status[7:9]):
        fluid = case['fluid_'+side]
        name = {'air':'Air', 'water':'Water', 'co2':'CO2', 'sco2':'CO2'}[fluid]
        pressure = case['pressure_'+side+'_field']
        expected = CP.PropsSI('H', 'T', temperature.ravel(), 'P', pressure.ravel(), name).reshape(temperature.shape)
        np.testing.assert_allclose(enthalpy, expected, rtol=2e-10, atol=2e-5)
        k = CP.PropsSI('L', 'T', temperature.ravel(), 'P', pressure.ravel(), name).reshape(temperature.shape)
        conductivity.append(case['eps_'+side+'_field']*k)
        inlet.append(CP.PropsSI('H', 'T', case['T_in'+side], 'P', case['P_'+side], name))
        assert used in (0, 1)
        assert not used or fluid in ('co2', 'sco2')
    for temperature in native['fields']:
        assert np.all(np.isfinite(temperature) & (temperature > 0.))
    residuals, measured = energy(widths, native['h'], native['fields'][:2], native['fields'][2],
        conductivity, [case['h_v'+side+'_field'] for side in 'AB'], case['K_ss'],
        [case['mass_flux_'+side] for side in 'AB'], inlet)
    assert sum(r.sum() for r in residuals) == pytest.approx(measured[2], rel=2e-8, abs=2e-8)
    np.testing.assert_allclose(metric[1:3], measured[:2], rtol=2e-8, atol=2e-8)
    np.testing.assert_allclose(metric[4:6], inlet, rtol=2e-10, atol=2e-5)
    imbalance = abs(measured[2])/max(*(abs(q) for q in measured[:2]),1e-30)
    assert metric[3] == pytest.approx(imbalance, rel=2e-8, abs=2e-8)
    assert np.isfinite(metric[0]) and metric[0] >= 0.
    coupled, equation = (case[key] for key in ('coupled_energy_tol','equation_energy_tol'))
    assert bool(status[10]) == (coupled is not None or equation is not None)
    assert bool(status[11]) == (equation is not None)
    if status[10]:
        np.testing.assert_allclose(metric[6:12], measured[:6], rtol=2e-8, atol=2e-8)
    if status[11]:
        np.testing.assert_allclose(metric[12:17], measured[6:], rtol=2e-8, atol=2e-8)
    elif status[10]:
        assert np.isnan(metric[12:17]).all()
    assert status[0] in (0,1,2) and status[9] in (0,1)
    iterations = status[1]
    assert 0 < iterations <= case['n_outer']
    max_clips = case['Nx']*case['Ny']*case['Nz']*case['n_sweep']
    for last,total in zip(status[3:5], status[5:7]):
        assert 0 <= last <= max_clips and last <= total <= max_clips*iterations
    converged = (metric[0] < case['tol'] and metric[3] < .05 and not any(status[3:5])
        and (coupled is None or measured[5] <= coupled)
        and (equation is None or measured[10] <= equation))
    assert (status[0] == 0) == converged
    if not converged:
        assert iterations == case['n_outer']
        assert (status[0] == 1) == bool(sum(status[3:5]))
    if case['n_sweep'] == 0:
        for index, side in enumerate('AB'):
            warm = case.get('T'+side.lower()+'_init')
            name = {'air':'Air', 'water':'Water', 'co2':'CO2', 'sco2':'CO2'}[case['fluid_'+side]]
            expected = inlet[index] if warm is None else CP.PropsSI('H', 'T', warm.ravel(),
                'P', case['pressure_'+side+'_field'].ravel(), name).reshape(warm.shape)
            np.testing.assert_allclose(native['h'][index],expected,rtol=2e-10,atol=2e-5)
        solid = case.get('Ts_init')
        if solid is None:
            solid = .5*(case['T_inA']+case['T_inB'])
        np.testing.assert_array_equal(native['fields'][2], np.broadcast_to(solid,native['fields'][2].shape))
    return dict(exit_reason=('converged','enthalpy_limited','iteration_limit')[status[0]],
        iterations=iterations, enthalpy_clip_counts=dict(last=list(status[3:5]),total=list(status[5:7])))


@pytest.mark.parametrize("pair", [("air", "water"), ("water", "air"), ("sco2", "sco2"), ("sco2", "water")])
@pytest.mark.parametrize("shape,warm", [((4, 3, 1), False), ((4, 3, 2), True)])
def test_complete_picard_eos_and_exact_energy(enthalpy_native, pair, shape, warm):
    case = case_data(pair, shape, warm=warm)
    assert_audited(case, enthalpy_native(case))


@pytest.mark.parametrize("direction", range(6))
def test_all_signed_face_directions(enthalpy_native, direction):
    case = case_data(directions=(direction, direction ^ 1), shape=(3, 2, 2))
    assert_audited(case, enthalpy_native(case))


@pytest.mark.parametrize("gates", [(None, None), (1e-3, None), (None, 1e-3)])
@pytest.mark.parametrize("budget", [1, 1200])
def test_optional_gates_and_original_budget(enthalpy_native, gates, budget):
    case = case_data(("sco2", "water"), shape=(3, 2, 1))
    case.update(coupled_energy_tol=gates[0], equation_energy_tol=gates[1], n_outer=budget)
    assert_audited(case, enthalpy_native(case))


def test_sub274_liquid_warm_enthalpy_is_not_clipped(enthalpy_native):
    case = case_data(("water", "water"), shape=(2, 1, 1))
    case.update(T_inA=300., T_inB=273.2, P_A=1e5, P_B=1e5,
                pressure_A_field=np.full((2, 1, 1), 1e5), pressure_B_field=np.full((2, 1, 1), 1e5),
                Ta_init=np.full((2, 1, 1), 300.), Tb_init=np.full((2, 1, 1), 273.2),
                Ts_init=np.full((2, 1, 1), 286.6))
    native = enthalpy_native(case)
    info = assert_audited(case, native)
    assert info["enthalpy_clip_counts"]["total"] == [0, 0]
    assert native["status"][5:7] == (0, 0)


def test_equal_temperature_roundoff_clipping_is_preserved(enthalpy_native):
    # The first qualification exposed this existing zero-duty behavior in
    # both implementations. Keep its native exit; do not relax the clip gate.
    case = case_data(("water", "water"), shape=(2, 1, 1))
    case.update(T_inA=273.2, T_inB=273.2, P_A=1e5, P_B=1e5, n_outer=3,
                pressure_A_field=np.full((2, 1, 1), 1e5), pressure_B_field=np.full((2, 1, 1), 1e5),
                Ta_init=np.full((2, 1, 1), 273.2), Tb_init=np.full((2, 1, 1), 273.2),
                Ts_init=np.full((2, 1, 1), 273.2))
    info = assert_audited(case, enthalpy_native(case))
    assert info["exit_reason"] == "enthalpy_limited"
    assert sum(info["enthalpy_clip_counts"]["total"]) > 0


@pytest.mark.parametrize("key", ["Ta_init", "Tb_init", "Ts_init"])
def test_independent_partial_warm_fields(enthalpy_native, key):
    case = case_data(shape=(3, 2, 1))
    case[key] = np.full((3, 2, 1), {"Ta_init": 375., "Tb_init": 302., "Ts_init": 335.}[key])
    assert_audited(case, enthalpy_native(case))


def test_limit_clipping_preserves_native_exit(enthalpy_native):
    case = case_data(("air", "air"), shape=(2, 1, 1))
    case.update(Ts_init=np.full((2, 1, 1), 5000.), n_outer=1, n_sweep=1, omega=1.,
                h_vA_field=np.full((2, 1, 1), 1e9), h_vB_field=np.full((2, 1, 1), 1e9))
    result = enthalpy_native(case)
    info = assert_audited(case, result)
    assert info["exit_reason"] == "enthalpy_limited"
    assert sum(info["enthalpy_clip_counts"]["last"]) > 0


def test_zero_sweep_budget_keeps_initial_fields(enthalpy_native):
    case = case_data(shape=(2, 1, 1))
    case.update(n_sweep=0, n_outer=2)
    info = assert_audited(case, enthalpy_native(case))
    assert info["iterations"] == 2 and info["exit_reason"] == "iteration_limit"


def test_mixed_inlet_outlet_patches_and_closed_faces(enthalpy_native):
    case = case_data(shape=(3, 3, 2))
    for side in "AB":
        fx, fy, fz = case[f"mass_flux_{side}"]
        fx[:, 0, :] = 0.
        fx[:, 2, :] *= -1.
        assert not fy.any() and not fz.any()
    assert_audited(case, enthalpy_native(case))


@pytest.mark.parametrize("bad_size", range(21))
def test_bad_array_sizes_rejected(enthalpy_native, bad_size):
    result = enthalpy_native(case_data(), bad_size=bad_size)
    assert result["code"] == 1
    assert "length" in result["error"]


@pytest.mark.parametrize("cancel_at", [1, 2, 3])
def test_cancellation_at_chunk_boundaries(enthalpy_native, cancel_at):
    case = case_data(("sco2", "water"))
    result = enthalpy_native(case, cancel_at=cancel_at)
    assert result["code"] == 0 and result["status"][0] == 3
    assert result["status"][1] == cancel_at//2
    assert result["status"][2] == cancel_at


def test_first_cancellation_precedes_tabular_initialization(enthalpy_native):
    result = enthalpy_native(case_data(("sco2", "water")), cancel_at=1, table_directory="")
    assert result["code"] == 0 and result["status"][0] == 3
    assert result["status"][1:3] == (0, 1)


@pytest.mark.parametrize("stage", ["inlet", "warm", "local_cold_return"])
def test_water_guard_keeps_stage_and_index(enthalpy_native, stage):
    case = case_data(("water", "air"), shape=(2, 1, 1))
    if stage == "inlet":
        case["T_inA"] = 500.
    elif stage == "warm":
        case["Ta_init"] = np.array([350., 500.]).reshape(2, 1, 1)
    else:
        case["pressure_A_field"] = np.full((2, 1, 1), 1000.)
    native = enthalpy_native(case)
    assert native["code"] == 2
    assert "enthalpy" in native["error"] and "water" in native["error"]
    assert "P_abs=" in native["error"]
    if stage != "inlet":
        assert "index=(" in native["error"]


def test_coupled_only_never_reads_absent_conductivity(enthalpy_native):
    fn = enthalpy_native.lib.test_coupled_only_audit
    double_p = ctypes.POINTER(ctypes.c_double)
    fn.argtypes = [double_p, double_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    metrics, fluid = (ctypes.c_double*9)(), (ctypes.c_double*2)()
    error = ctypes.create_string_buffer(1024)
    assert fn(metrics, fluid, error, len(error)) == 0, error.value.decode()
    values = np.array(metrics)
    assert (values[[0, 1, 7, 8]] == 0).all()
    assert np.isnan(values[2:7]).all() and np.isnan(np.array(fluid)).all()


def test_native_tables_do_not_mutate_python_coolprop_configuration(enthalpy_native):
    before = CP.get_config_as_json_string()
    result = enthalpy_native(case_data(("sco2", "water"), shape=(3, 2, 1)))
    assert result["code"] == 0, result["error"]
    assert CP.get_config_as_json_string() == before


@pytest.mark.parametrize("path", ["", "relative-tables", str(TABLES.parent / "different-tables")])
def test_invalid_or_conflicting_table_directory_rejected(enthalpy_native, path):
    # Establish this library's lifetime configuration before checking conflict.
    fn = enthalpy_native.lib.test_enthalpy_tables
    fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    error = ctypes.create_string_buffer(1024)
    assert fn(str(TABLES).encode(), error, len(error)) == 0
    assert fn(path.encode(), error, len(error)) == 1
    assert error.value


def test_concurrent_first_eos_and_table_use_in_fresh_process(enthalpy_native):
    script = r'''
import json
import sys
from concurrent.futures import ThreadPoolExecutor
import CoolProp.CoolProp as CP
from sjtu_tpmshx.tests.native.test_enthalpy_driver import load_native, case_data, assert_audited
native = load_native(sys.argv[1])
case = case_data(("sco2", "water"), shape=(3, 2, 1))
before = CP.get_config_as_json_string()
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(native, [case, case]))
assert CP.get_config_as_json_string() == before
for result in results:
    assert_audited(case, result)
assert results[0]["status"] == results[1]["status"]
print(json.dumps({"concurrent_runs": 2, "iterations": results[0]["status"][1], "python_config_unchanged": True}))
'''
    process = subprocess.run([sys.executable, "-c", script, str(enthalpy_native.path)],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stdout+process.stderr
    assert '"concurrent_runs": 2' in process.stdout
