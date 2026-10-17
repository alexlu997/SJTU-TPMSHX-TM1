"""Native QD property passes, component replay, and independent FV powers.

Fields retain rtol2e-12/atol2e-10 K in 2D and rtol2e-11/atol2e-9 K in 3D.
Properties retain rtol2e-10. Pass counts, warm starts, and budgets stay exact.
"""
import ctypes
from dataclasses import replace
import os
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import pytest

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

    def run(case, *, cancel_at=0, inject_side=0, inject_percent=0, inject_value=500., bad_size=None,
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
        values += [qtol, controls["alpha"], inject_value]
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


@pytest.fixture(scope='module')
def temperature_driver(quick_design_native):
    from sjtu_tpmshx.solvers.backends.cpp.temperature import NativeTemperatureDriver
    name = 'tpmshx_temperature_shared.dll' if os.name == 'nt' else 'libtpmshx_temperature_shared.dylib'
    driver = NativeTemperatureDriver(quick_design_native.build/name)
    try:
        yield driver
    finally:
        driver.close()


def check_prepared(case, native, temperature):
    from sjtu_tpmshx.models.design_fluids import fluid_props, fluid_nu
    from sjtu_tpmshx.tests.native.temperature_fv_oracle import physical
    actual = native(case)
    assert actual['code'] == 0, actual['error']
    status, metrics = actual['status'], actual['metrics']
    p, fixed = case.parameters, case.design_fields
    op, controls = p['operating_point'], p['controls']
    shape = tuple(len(case.grid['d'+axis]) for axis in 'xyz')
    plane, cross = shape[2] == 1, p['arrangement'] == 'cross'
    widths = tuple(case.grid['d'+axis] for axis in 'xyz')
    tin = [op['T_in_'+suffix] for suffix in ('h', 'c')]
    evaluation = list(tin)
    seed = p['initial_fields']
    chunk = controls['chunk'] or (500 if plane else 250)
    rtol, atol = (2e-12, 2e-10) if plane else (2e-11, 2e-9)
    field = lambda value: np.array(np.broadcast_to(value,shape), dtype=np.float64, order='C')
    planar = lambda value: value[...,0] if plane else value
    count = 2 if p['prop_model'] == 'mean' else 1
    assert status[1] == count and status[4] == 100
    for index in range(count):
        fluids, properties = [], []
        for side, suffix in enumerate(('h', 'c')):
            fluid = op['hot_fluid' if side == 0 else 'cold_fluid']
            props = fluid_props(fluid, evaluation[side], op['P_in_'+suffix])
            epsilon = fixed['eps_A'].flat[0]
            speed = op['mdot_'+suffix]/(props.rho*epsilon*(p['Lx'] if side == 1 and cross else p['s'])*p['height'])
            reynolds = props.rho*abs(speed)*p['D_h']/props.mu
            nu = fluid_nu(fluid,p['topology'],reynolds,epsilon,p['L_cell_m']*1000.,p['D_h']*1000.)
            hv = p['A_0']*nu*props.k/p['D_h']
            target = [evaluation[side],props.rho,props.mu,props.k,props.cp,props.Pr,reynolds,speed,hv,epsilon*props.k]
            np.testing.assert_allclose(metrics[index*20+side*10:index*20+side*10+10],target,rtol=2e-10,atol=0.)
            velocity = (speed,0.,0.) if side == 0 else (0.,speed,0.) if cross else (-speed,0.,0.)
            fluids.append([field(x) for x in (epsilon*props.k,hv,epsilon,props.rho*props.cp,*velocity)]
                          +[np.empty(0) for _ in range(3)])
            properties.append(props)
        *state, info = temperature(scheme='cell_centered_2d' if plane else 'cell_centered_3d',
            widths=widths[:2] if plane else widths,
            conductivity=tuple(planar(f[0]) for f in fluids)+(planar(fixed['K_ss']),),
            exchange=tuple(planar(f[1]) for f in fluids), epsilon=tuple(planar(f[2]) for f in fluids),
            rho_cp=tuple(planar(f[3]) for f in fluids),
            velocity=tuple(tuple(planar(f[i]) for i in range(4,6 if plane else 7)) for f in fluids),
            directions=(0,2 if cross else 1),inlets=tin,
            initial=None if seed is None else tuple(planar(x) for x in seed),
            max_iterations=controls['maxit'],chunk_iterations=controls['chunk'],q_relative_tolerance=controls['qtol'],
            tol=p['tol'],alpha=(.7,1.,1.) if plane else (controls['alpha'],)*3,second_order_b=not plane)
        seed = [x[...,None] if plane else x for x in state]
        assert status[5+index*2] == (0 if info['converged'] else 1)
        assert status[6+index*2] == info['iterations']
        assert metrics[40+index*2] == pytest.approx(info['residual'],rel=rtol,abs=atol)
        assert 0 < info['iterations'] <= controls['maxit']
        assert info['iterations'] == controls['maxit'] or info['iterations'] % chunk == 0
        audit = physical(dict(shape=shape,state=seed,widths=widths,a=fluids[0],b=fluids[1],
            ks=fixed['K_ss'],prescribed=np.empty(0),directions=(0,2 if cross else 1),tin=tin,sou_b=not plane))
        assert audit['boundary_complete'] and all(np.isfinite(x).all() for x in seed)
        boundary = float(np.sum(audit['powers']))
        assert abs(float(np.sum(audit['residual']))+boundary) <= 2e-8
        assert metrics[41+index*2] == pytest.approx(audit['qb'],rel=rtol,abs=1e-8)
        if info['converged']:
            assert (info['iterations']+chunk-1)//chunk >= 2
            assert max(np.abs(audit['residual']).reshape(3,-1).sum(axis=1).max(),abs(boundary))/audit['denominator'] <= 1e-7
        else:
            assert info['iterations'] == controls['maxit']
        evaluation = [.5*(tin[0]+seed[0][-1].mean()),
                      .5*(tin[1]+(seed[1][:,-1] if cross else seed[1][0]).mean())]
    for value, expected in zip(actual['fields'], seed):
        np.testing.assert_allclose(value,expected,rtol=rtol,atol=atol)
    assert status[0] == status[5+2*(count-1)]
    for side,suffix in enumerate(('h','c')):
        fraction = p['inlet_pressure_fractions']['AB'[side]]
        assert metrics[44+2*side] == op['P_in_'+suffix]
        assert metrics[45+2*side] == op['P_in_'+suffix]*(1.-fraction)
        assert bool(status[9+side]) == (fraction >= 1.)
    return actual


@pytest.mark.parametrize("arrangement", ["cross", "counter"])
@pytest.mark.parametrize("mode", ["const", "mean"])
@pytest.mark.parametrize("pair,topology", [("air_water", "Diamond"), ("water_air", "Gyroid"),
                                           ("sco2_sco2", "Diamond")])
def test_actual_prepared_geometry_full_property_passes(quick_design_native, temperature_driver, arrangement, mode, pair, topology):
    check_prepared(prepared(arrangement, mode, pair, topology), quick_design_native, temperature_driver)


@pytest.mark.parametrize("arrangement", ["cross", "counter"])
def test_external_warm_fields_and_budget_exhaustion(quick_design_native, temperature_driver, arrangement):
    case = prepared(arrangement, "mean")
    p = case.parameters
    shape = tuple(len(case.grid["d"+axis]) for axis in "xyz")
    seed = tuple(np.full(shape, t) for t in (345., 320., 332.))
    case = replace(case, parameters={**p, "initial_fields": seed,
                                    "controls": {**p["controls"], "maxit": 7, "chunk": 5}})
    actual = check_prepared(case, quick_design_native, temperature_driver)
    assert actual["status"][0] == 1
    assert actual["status"][6] == actual["status"][8] == 7


@pytest.mark.parametrize("mode", ["const", "mean"])
def test_prepared_inlet_pressure_fractions_are_never_recalculated(quick_design_native, temperature_driver, mode):
    case = prepared("cross", mode)
    case = replace(case, parameters={**case.parameters, "inlet_pressure_fractions": {"A": 1.2, "B": .03125}})
    actual = check_prepared(case, quick_design_native, temperature_driver)
    assert actual["status"][9:11] == (1, 0)


@pytest.mark.parametrize("where", ["inlet", "warm"])
@pytest.mark.parametrize("side", ["A", "B"])
def test_input_water_and_external_field_errors_remain_distinct(quick_design_native, where, side):
    case = prepared(pair="water_air" if side == "A" else "air_water")
    p = case.parameters
    if where == "inlet":
        suffix = "h" if side == "A" else "c"
        op = {**p["operating_point"], "T_in_"+suffix: 350., "P_in_"+suffix: 10000.}
        case = replace(case, parameters={**p, "operating_point": op})
        code, match = 1, "design inlet " + side
    else:
        shape = tuple(len(case.grid["d"+axis]) for axis in "xyz")
        seed = tuple(np.full(shape, t) for t in (340., 330., 335.))
        seed[0 if side == "A" else 1][0, 0, 0] = 500.
        case = replace(case, parameters={**p, "initial_fields": seed})
        code, match = 2, "design external warm start " + side
    actual = quick_design_native(case)
    assert actual["code"] == code and match in actual["error"]
    assert actual["status"][3] == 0


@pytest.mark.parametrize("side", [1, 2])
@pytest.mark.parametrize("mode,bad_pass", [("const", 1), ("mean", 1), ("mean", 2)])
def test_each_full_water_field_is_checked_before_reuse_or_return(quick_design_native, side, mode, bad_pass):
    case = prepared(mode=mode, pair="water_air" if side == 1 else "air_water")
    case = replace(case, parameters={**case.parameters,
        "controls": {**case.parameters["controls"], "maxit": 1, "chunk": 1}})
    stage = "design-inlet-pass" if bad_pass == 1 else "design-mean-pass"
    actual = quick_design_native(case, inject_side=side,
        inject_percent=(100 if mode == "const" or bad_pass == 2 else 50))
    assert actual["code"] == 2 and stage+" thermal return" in actual["error"]
    assert "index=(0, 0, 0), T=500 K" in actual["error"]


@pytest.mark.parametrize('mode,bad_pass,side,value', [
    ('const', 1, 1, np.nan), ('mean', 1, 3, np.inf), ('mean', 2, 2, np.nan),
])
def test_nonfinite_thermal_return_stops_before_reuse(quick_design_native, mode, bad_pass, side, value):
    case = prepared(mode=mode)
    case = replace(case, parameters={**case.parameters,
        'controls': {**case.parameters['controls'], 'maxit': 1, 'chunk': 1}})
    percent = 100 if mode == 'const' or bad_pass == 2 else 50
    actual = quick_design_native(case, inject_side=side, inject_percent=percent, inject_value=value)
    if mode == 'const':
        assert actual['code'] == 3 and 'design thermal return' in actual['error']
        assert 'non-finite' in actual['error']
    else:
        assert actual['code'] == 4 and actual['error'] == 'nonfinite temperature duty'
    assert actual['status'][3] == bad_pass and actual['status'][4] == percent


def test_real_water_hotspot_retains_native_field_failure(quick_design_native):
    case = prepare_quick_design(_case(), "Diamond", 7., .5, .084, .05,
                                case_id="native-qd-real-hotspot", prop_model="mean")
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
