"""Native QD properties/orchestration against the same current thermal map.

Fixed before comparison: 2D fields rtol=2e-12 / atol=2e-10 K;
3D fields rtol=2e-11 / atol=2e-9 K. Pass properties/Re/u/hv/K use
rtol=2e-10, atol=0; status, pass count and iteration budgets are exact.
The explicit test fixture supplies current C++ thermal iteration to the
Python orchestration reference; independent FV powers check each returned
pass. Historical Python thermal helpers remain the default for other callers.
"""
import ctypes
from dataclasses import replace
import importlib
import os
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.models.fluid_props import QuickDesignWaterFieldError, WaterStateError
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.tests.design.test_forward import _case


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def quick_design_native():
    system = "macos" if sys.platform == "darwin" else ("windows" if os.name == "nt" else "linux")
    arch = platform.machine().lower()
    if arch in ("amd64", "x86_64"):
        arch = "x64" if os.name == "nt" else "x86_64"
    build = ROOT / ".cache/native-deps/build" / f"pilot-{system}-{arch}"
    name = "quick_design_test.dll" if os.name == "nt" else (
        "libquick_design_test.dylib" if sys.platform == "darwin" else "libquick_design_test.so")
    path = Path(os.environ.get("TPMSHX_QUICK_DESIGN_LIBRARY", str(build / name))).resolve()
    if not path.is_file():
        message = f"native QD qualification library is not built: {path}"
        if os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1" or "TPMSHX_QUICK_DESIGN_LIBRARY" in os.environ:
            pytest.fail(message)
        pytest.skip(message)
    lib = ctypes.CDLL(str(path))
    fn = lib.test_quick_design_driver
    size_p, double_p = ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double)
    fn.argtypes = [size_p, ctypes.POINTER(double_p), size_p, size_p, double_p,
                   size_p, double_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    fn.restype = ctypes.c_int

    def run(case, *, cancel_at=0, inject_side=0, inject_percent=0, bad_size=None,
            enum_override=None):
        p, fields = case.parameters, case.design_fields
        op, controls = p["operating_point"], p["controls"]
        shape = tuple(len(case.grid["d" + axis]) for axis in "xyz")
        seed = p["initial_fields"]
        state = [np.zeros(shape) for _ in range(3)] if seed is None else [np.array(a, copy=True) for a in seed]
        arrays = [np.array(case.grid["d" + axis], copy=True) for axis in "xyz"]
        arrays += [np.array(fields[key], copy=True) for key in ("eps", "eps_A", "K_ss")]
        arrays += state
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        pointers = (double_p * len(arrays))(*(a.ctypes.data_as(double_p) for a in arrays))
        sizes = (ctypes.c_size_t * len(arrays))(*(a.size for a in arrays))
        if bad_size is not None:
            sizes[bad_size] -= 1
        fluid = {"air": 0, "water": 1, "sco2": 2}
        config = [(0 if p["topology"] == "Diamond" else 1),
                  (0 if p["arrangement"] == "cross" else 1),
                  (0 if p["prop_model"] == "const" else 1),
                  fluid[op["hot_fluid"]], fluid[op["cold_fluid"]],
                  controls["maxit"], controls["chunk"] or (500 if shape[2] == 1 else 250),
                  int(seed is not None), cancel_at, inject_side, inject_percent]
        if enum_override is not None:
            config[enum_override] = 9
        qtol = controls["qtol"]
        if qtol is None:
            qtol = min(p["tol"]*2e-3, 1e-3) if shape[2] == 1 else max(p["tol"]*10, 1e-4)
        values = [p[k] for k in ("Lx", "s", "height", "L_cell_m", "A_0", "D_h")]
        for suffix, side in (("h", "A"), ("c", "B")):
            values.extend([op["T_in_"+suffix], op["P_in_"+suffix], op["mdot_"+suffix],
                           p["inlet_pressure_fractions"][side]])
        values += [qtol, controls["alpha"]]
        status, metrics = (ctypes.c_size_t * 11)(), (ctypes.c_double * 48)()
        error = ctypes.create_string_buffer(1024)
        code = fn((ctypes.c_size_t * 3)(*shape), pointers, sizes,
                  (ctypes.c_size_t * len(config))(*config),
                  (ctypes.c_double * len(values))(*values), status, metrics, error, len(error))
        return dict(code=code, status=tuple(status), metrics=np.array(metrics), fields=state,
                    error=error.value.decode())

    run.build = path.parent
    return run


def prepared(arrangement="cross", mode="const", pair="air_water", topology="Diamond"):
    changes = dict(T_in_h=380., T_in_c=300., P_in_h=2e5, P_in_c=2e5, mdot_h=.04, mdot_c=.2)
    if pair == "water_air":
        changes.update(hot_fluid="water", cold_fluid="air", T_in_h=355., mdot_h=.2, mdot_c=.04)
    elif pair == "sco2_sco2":
        changes.update(hot_fluid="sco2", cold_fluid="sco2", T_in_h=500., T_in_c=350.,
                       P_in_h=9e6, P_in_c=8e6, mdot_h=.2, mdot_c=.2)
    return prepare_quick_design(replace(_case(), **changes), topology, 7., .5, .084, .025,
                                arrangement, case_id="native-qd-qualification", prop_model=mode,
                                height=.06)


@pytest.fixture(scope="module")
def same_qd_thermal(quick_design_native):
    """Keep Python QD properties/orchestration; use the current thermal map."""
    from sjtu_tpmshx.solvers.backends.cpp.temperature import NativeTemperatureDriver
    from sjtu_tpmshx.tests.native.temperature_fv_oracle import physical

    name = "tpmshx_temperature_shared.dll" if os.name == "nt" else (
        "libtpmshx_temperature_shared.dylib" if sys.platform == "darwin" else "libtpmshx_temperature_shared.so")
    path = Path(os.environ.get("TPMSHX_TEMPERATURE_LIBRARY", str(quick_design_native.build / name))).resolve()
    driver = NativeTemperatureDriver(path)

    def run(*args, **kwargs):
        shape = tuple(args[3:6])
        plane = shape[2] == 1
        dimension = 2 if plane else 3

        def field(value):
            value = np.asarray(value)
            return value[..., 0] if plane and value.ndim == 3 else value

        initial = None if kwargs["Ta_init"] is None else tuple(
            field(kwargs[key]) for key in ("Ta_init", "Tb_init", "Ts_init"))
        entry = dict(shape=shape, max_iterations=kwargs["max_iter"],
                     chunk_iterations=kwargs["conv_chunk"] or (500 if plane else 250),
                     warm=initial is not None, returned=False)
        run.calls.append(entry)
        *state, info = driver(
            scheme="cell_centered_2d" if plane else "cell_centered_3d",
            widths=tuple(kwargs["d" + axis + "_arr"] for axis in "xyz"[:dimension]),
            conductivity=tuple(field(value) for value in args[8:11]),
            exchange=tuple(field(value) for value in args[11:13]),
            epsilon=(field(args[15] / 2),) * 2, rho_cp=args[13:15],
            velocity=tuple(tuple(field(value) for value in args[start:start+dimension])
                           for start in (16, 19)),
            directions=(kwargs["dir_A"], kwargs["dir_B"]), inlets=args[6:8],
            initial=initial, max_iterations=kwargs["max_iter"],
            chunk_iterations=kwargs["conv_chunk"], q_relative_tolerance=kwargs["q_rel_tol"],
            tol=kwargs["tol"], alpha=(.7, 1., 1.) if plane else (kwargs["alpha_T"],) * 3,
            second_order_b=not plane, cancel_check=kwargs.get("cancel_check"),
            progress=kwargs.get("progress_cb"))
        entry.update(returned=True, iterations=info["iterations"], converged=info["converged"])
        state = [value[..., None] if plane else value for value in state]
        fluids = []
        for side, start in enumerate((16, 19)):
            fluids.append([np.full(shape, value) for value in
                           (args[8+side], args[11+side], args[15]/2, args[13+side])]
                          + list(args[start:start+3]) + [np.empty(0) for _ in range(3)])
        audit = physical(dict(shape=shape, state=state,
            widths=tuple(kwargs["d" + axis + "_arr"] for axis in "xyz"),
            a=fluids[0], b=fluids[1], ks=args[10], prescribed=np.empty(0),
            directions=(kwargs["dir_A"], kwargs["dir_B"]), tin=args[6:8], sou_b=not plane))
        evidence = info.pop("_native_temperature")
        assert evidence["duty_units"] == ("W/m" if plane else "W")
        assert evidence["Q_B"] == pytest.approx(audit["qb"], rel=2e-12 if plane else 2e-11, abs=1e-8)
        assert audit["boundary_complete"] and all(np.isfinite(value).all() for value in state)
        boundary = float(np.sum(audit["powers"]))
        assert abs(float(np.sum(audit["residual"])) + boundary) <= 2e-8
        count, chunk = info["iterations"], entry["chunk_iterations"]
        assert 0 < count <= kwargs["max_iter"]
        assert count == kwargs["max_iter"] or count % chunk == 0
        if info["converged"]:
            assert (count + chunk - 1) // chunk >= 2
            assert max(np.abs(audit["residual"]).reshape(3, -1).sum(axis=1).max(),
                       abs(boundary)) / audit["denominator"] <= 1e-7
        else:
            assert count == kwargs["max_iter"]
        info["delegated_to_2d"] = plane
        return *state, info

    run.calls, run.native_entries = [], []
    native_call = driver.call

    def traced_call(*args):
        entry = dict(returned=False)
        run.native_entries.append(entry)
        code = native_call(*args)
        entry.update(returned=True, code=int(code))
        return code

    driver.call = traced_call
    try:
        yield run
    finally:
        driver.close()
def python_run(case, monkeypatch, *, inject_side=0, inject_pass=0, thermal=None, public=False):
    execution = importlib.import_module("sjtu_tpmshx.solvers.backends.python.quick_design.execution")
    model = importlib.import_module("sjtu_tpmshx.models.quick_design")
    hvol = model._hvol
    thermal = thermal or execution.solve_full_domain_3d
    evaluations, results, progress = [], [], []

    def capture_hvol(*args, **kwargs):
        values = hvol(*args, **kwargs)
        evaluations.append((args[9], *values))  # T evaluation, hv, Re, u, props
        return values

    def capture_thermal(*args, **kwargs):
        result = thermal(*args, **kwargs)
        if inject_side and len(results)+1 == inject_pass:
            result[inject_side-1][0, 0, 0] = 500.
        results.append(result)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(model, "_hvol", capture_hvol)
        patch.setattr(execution, "solve_full_domain_3d", capture_thermal)
        from sjtu_tpmshx.solvers.api import run_case
        result = (run_case if public else execution.run_case)(case, RunControl(progress=progress.append))
    return result, evaluations, results, progress


def assert_equivalent(case, native, monkeypatch, thermal=None):
    expected, evaluations, passes, progress = python_run(case, monkeypatch, thermal=thermal)
    actual = native(case)
    assert actual["code"] == 0, actual["error"]
    status, metrics = actual["status"], actual["metrics"]
    assert status[1] == len(passes) == (2 if case.parameters["prop_model"] == "mean" else 1)
    assert status[0] == (0 if expected.run_status["converged"] else 1)
    assert status[4] == 100 and progress[-1] == 100
    plane = len(case.grid["dz"]) == 1
    rtol, atol = (2e-12, 2e-10) if plane else (2e-11, 2e-9)
    for field, name in zip(actual["fields"], ("Ta", "Tb", "Ts")):
        np.testing.assert_allclose(field, expected.fields[name], rtol=rtol, atol=atol)
    for index, result in enumerate(passes):
        info = result[3]
        assert status[5+index*2] == (0 if info["converged"] else 1)
        assert status[6+index*2] == info["iterations"]
        assert metrics[40+index*2] == pytest.approx(info["residual"], rel=rtol, abs=atol)
        for side in range(2):
            temperature, hv, reynolds, speed, props = evaluations[index*2+side]
            conductivity = case.design_fields["eps_A"].flat[0]*props.k
            target = [temperature, props.rho, props.mu, props.k, props.cp, props.Pr,
                      reynolds, speed, hv, conductivity]
            np.testing.assert_allclose(metrics[index*20+side*10:index*20+side*10+10],
                                       target, rtol=2e-10, atol=0.)
    for index, side in enumerate(("A", "B")):
        pressure = expected.pressure_evidence[side]
        assert metrics[44+index*2] == pressure["inlet_absolute_Pa"]
        assert metrics[45+index*2] == pressure["outlet_absolute_Pa"]
        assert bool(status[9+index]) == pressure["choked"]
    return actual, expected


@pytest.mark.parametrize("arrangement", ["cross", "counter"])
@pytest.mark.parametrize("mode", ["const", "mean"])
@pytest.mark.parametrize("pair,topology", [("air_water", "Diamond"), ("water_air", "Gyroid"),
                                           ("sco2_sco2", "Diamond")])
def test_actual_prepared_geometry_full_property_passes(quick_design_native, same_qd_thermal, monkeypatch, arrangement, mode, pair, topology):
    assert_equivalent(prepared(arrangement, mode, pair, topology), quick_design_native, monkeypatch, same_qd_thermal)


@pytest.mark.parametrize("arrangement", ["cross", "counter"])
def test_external_warm_fields_and_budget_exhaustion(quick_design_native, same_qd_thermal, monkeypatch, arrangement):
    case = prepared(arrangement, "mean")
    p = case.parameters
    shape = tuple(len(case.grid["d"+axis]) for axis in "xyz")
    seed = tuple(np.full(shape, t) for t in (345., 320., 332.))
    case = replace(case, parameters={**p, "initial_fields": seed,
                                    "controls": {**p["controls"], "maxit": 7, "chunk": 5}})
    actual, _ = assert_equivalent(case, quick_design_native, monkeypatch, same_qd_thermal)
    assert actual["status"][0] == 1
    assert actual["status"][6] == actual["status"][8] == 7


@pytest.mark.parametrize("mode", ["const", "mean"])
def test_prepared_inlet_pressure_fractions_are_never_recalculated(quick_design_native, same_qd_thermal, monkeypatch, mode):
    case = prepared("cross", mode)
    case = replace(case, parameters={**case.parameters, "inlet_pressure_fractions": {"A": 1.2, "B": .03125}})
    actual, _ = assert_equivalent(case, quick_design_native, monkeypatch, same_qd_thermal)
    assert actual["status"][9:11] == (1, 0)


@pytest.mark.parametrize("where", ["inlet", "warm"])
@pytest.mark.parametrize("side", ["A", "B"])
def test_input_water_and_external_field_errors_remain_distinct(quick_design_native, monkeypatch, where, side):
    case = prepared(pair="water_air" if side == "A" else "air_water")
    p = case.parameters
    if where == "inlet":
        suffix = "h" if side == "A" else "c"
        op = {**p["operating_point"], "T_in_"+suffix: 350., "P_in_"+suffix: 10000.}
        case = replace(case, parameters={**p, "operating_point": op})
        error_type, code, match = WaterStateError, 1, "design inlet " + side
    else:
        shape = tuple(len(case.grid["d"+axis]) for axis in "xyz")
        seed = tuple(np.full(shape, t) for t in (340., 330., 335.))
        seed[0 if side == "A" else 1][0, 0, 0] = 500.
        case = replace(case, parameters={**p, "initial_fields": seed})
        error_type, code, match = QuickDesignWaterFieldError, 2, "design external warm start " + side
    with pytest.raises(error_type, match=match) as expected:
        python_run(case, monkeypatch)
    assert type(expected.value) is error_type
    actual = quick_design_native(case)
    assert actual["code"] == code and match in actual["error"]
    assert actual["status"][3] == 0


@pytest.mark.parametrize("side", [1, 2])
@pytest.mark.parametrize("mode,bad_pass", [("const", 1), ("mean", 1), ("mean", 2)])
def test_each_full_water_field_is_checked_before_reuse_or_return(quick_design_native, monkeypatch, side, mode, bad_pass):
    case = prepared(mode=mode, pair="water_air" if side == 1 else "air_water")
    case = replace(case, parameters={**case.parameters,
        "controls": {**case.parameters["controls"], "maxit": 1, "chunk": 1}})
    stage = "design-inlet-pass" if bad_pass == 1 else "design-mean-pass"
    with pytest.raises(QuickDesignWaterFieldError, match=stage+" thermal return"):
        python_run(case, monkeypatch, inject_side=side, inject_pass=bad_pass)
    actual = quick_design_native(case, inject_side=side,
        inject_percent=(100 if mode == "const" or bad_pass == 2 else 50))
    assert actual["code"] == 2 and stage+" thermal return" in actual["error"]
    assert "index=(0, 0, 0), T=500 K" in actual["error"]


def test_real_water_hotspot_retains_native_field_failure(quick_design_native, monkeypatch):
    case = prepare_quick_design(_case(), "Diamond", 7., .5, .084, .05,
                                case_id="native-qd-real-hotspot", prop_model="mean")
    with pytest.raises(QuickDesignWaterFieldError, match="design-inlet-pass thermal return B"):
        python_run(case, monkeypatch)
    actual = quick_design_native(case)
    assert actual["code"] == 2 and "design-inlet-pass thermal return B" in actual["error"]


@pytest.mark.parametrize("cancel_at", [1, 2, 3, 4])
def test_cancellation_returns_no_successful_qd_result(quick_design_native, cancel_at):
    actual = quick_design_native(prepared(mode="mean"), cancel_at=cancel_at)
    assert actual["code"] == 0 and actual["status"][0] == 2
    assert actual["status"][1] == 0 and actual["status"][2] == cancel_at


@pytest.mark.parametrize("bad", ["nonuniform", "porosity", "extent", "fraction", "warm_nan", "state_size", "topology", "arrangement", "property_mode"])
def test_prepared_contract_errors_fail_before_thermal_progress(quick_design_native, bad):
    case = prepared()
    p, fields, options = dict(case.parameters), dict(case.design_fields), {}
    if bad == "nonuniform":
        fields["K_ss"] = np.array(fields["K_ss"], copy=True)
        fields["K_ss"].flat[1] += 1.
    elif bad == "porosity": fields["eps_A"] = np.full_like(fields["eps_A"], .49)
    elif bad == "extent": p["Lx"] *= 1.1
    elif bad == "fraction": p["inlet_pressure_fractions"] = {"A": -1., "B": .01}
    elif bad == "warm_nan":
        p["initial_fields"] = tuple(np.full_like(fields["eps"], 330.) for _ in range(3))
        p["initial_fields"][2].flat[0] = np.nan
    elif bad == "state_size": options["bad_size"] = 7
    else: options["enum_override"] = {"topology": 0, "arrangement": 1, "property_mode": 2}[bad]
    case = replace(case, parameters=p, design_fields=fields)
    actual = quick_design_native(case, **options)
    assert actual["code"] == 3 and actual["error"]
    assert actual["status"][3] == 0


def test_standalone_qd_smoke_without_python_environment(quick_design_native):
    program = quick_design_native.build / ("quick_design_driver_smoke.exe" if os.name == "nt" else "quick_design_driver_smoke")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "CONDA"))
           and k not in ("VIRTUAL_ENV", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH")}
    if os.name != "nt": env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run([str(program)], env=env, capture_output=True, text=True, check=True)
    assert "quick_design_driver_smoke ok" in result.stdout
