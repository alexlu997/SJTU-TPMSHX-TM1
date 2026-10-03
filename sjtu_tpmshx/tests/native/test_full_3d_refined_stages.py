"""Isolate initial flow and fixed-input thermal parity for the refined 24^3 case.

The original two-outer full-driver test remains separate. Both stages use its
prepared case and budgets; no saved field snapshots or altered solver policies
enter these comparisons. Flow tolerances come from test_full_3d; fixed-input
thermal tolerances and physical gates come from test_model_h_3d.
"""
import copy
import inspect
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.tests.native import test_full_3d as full
from sjtu_tpmshx.tests.native import test_model_h_3d as model_h

native_full = full.native
native_thermal = model_h.native


class _FirstThermalEntry(BaseException):
    """Stop the reference after production preparation, before any thermal sweep."""


@pytest.fixture(scope="module")
def first_thermal_entry():
    cfg, prepared = full.prepared(
        "air-air", counts=(8, 8, 8), mesh="wall_refine_3d", port_wall_refine=True)
    prepared["max_outer"] = 2
    assert tuple(prepared[key] for key in ("Nx", "Ny", "Nz")) == (24, 24, 24)
    assert prepared["ltne_max_iter"] == 20000
    signature = inspect.signature(full.runtime.solve_full_domain_3d)
    captured = {}
    original = full.runtime.SIMPLESolver3D.solve

    def observed(solver, *args, **kwargs):
        result = original(solver, *args, **kwargs)
        solver._full_native_last_iterations = result[1]
        return result

    def capture(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        captured.update(copy.deepcopy(bound.arguments))
        raise _FirstThermalEntry

    with patch.object(full.runtime.SIMPLESolver3D, "solve", observed), \
            patch.object(full.runtime, "solve_full_domain_3d", capture):
        problem = full.runtime.build_problem(copy.deepcopy(cfg), copy.deepcopy(prepared))
        with pytest.raises(_FirstThermalEntry):
            full.runtime._run_outer_coupling_3d(problem, full.runtime._build_hv_machinery(problem))
    assert problem._ltne_info == []
    assert captured["model_fluids"] == ("air", "air")
    assert captured["max_iter"] == 20000
    assert captured["accelerate"] is True
    assert captured["conservative_ltne"] is True
    return cfg, prepared, problem, captured


def test_refined_initial_flow_before_first_thermal(native_full, first_thermal_entry):
    cfg, prepared, problem, _ = first_thermal_entry
    actual = native_full.run(cfg, prepared, cancel_before_thermal=True)
    assert actual["code"] == 0, actual["error"]
    stats = actual[202]
    assert stats[0] == 2  # Full3DStop::cancelled: partial state, never acceptance.
    assert stats[1] == stats[3] == stats[4] == stats[7] == 0
    assert actual[200].shape == (0, 16)
    assert all(actual[key].size == 0 for key in range(27))
    failures = []

    def compare(key, expected, rtol, atol, name):
        try:
            np.testing.assert_allclose(actual[key], np.asarray(expected).ravel(),
                                       rtol=rtol, atol=atol, err_msg=name)
        except AssertionError as error:
            print(error)
            failures.append(name)

    for side, (solver, axes) in enumerate(((problem.sA, problem.axis_map),
                                          (problem.sB, problem.axis_map_B))):
        base = 100 + 40*side
        for code, name in enumerate(full.FLOW_FIELDS):
            compare(base+code, getattr(solver, name), 2e-7,
                    1e-5 if name in ("P", "Pp") else 1e-7, f"{'AB'[side]}:{name}")
        compare(base+24, full.runtime._pressure_real_3d(solver, axes, solver.P_ref_abs),
                2e-7, 1e-5, f"{'AB'[side]}:pressure_real")
        density = solver.rho_field.transpose(axes["solver_to_real_perm"])
        if axes["is_reverse"]:
            density = np.flip(density, axis=axes["stream_real_axis"])
        compare(base+25, density, 2e-7, 1e-7, f"{'AB'[side]}:density_real")
        shape = (prepared["Nx"], prepared["Ny"], prepared["Nz"])
        for offset, fields, atol in (
            (26, full.runtime._solver_velocity_to_real(solver, axes, shape), 1e-7),
            (29, full.runtime._solver_staggered_to_real(solver, axes, shape), 1e-10),
        ):
            for axis, field in enumerate(fields):
                compare(base+offset+axis, field, 2e-7, atol, f"{'AB'[side]}:{offset}:{axis}")
        start = 24 + 10*side
        print(f"{'AB'[side]} initial native stop/statistics:", stats[start:start+10].tolist())
        print(f"{'AB'[side]} initial Python stop/statistics:", dict(
            exit_reason=solver.exit_reason, iterations=solver._full_native_last_iterations,
            momentum=solver.final_res_mom, mass_local=solver.final_res_mass_local,
            mass_global=solver.final_res_mass_global, backflow=solver.outlet_backflow_frac))
        assert bool(stats[start+2]) == (solver.exit_reason == "tol")
        assert stats[start+1] == {"tol": 1, "stall": 2, "max_iter": 3, "nonfinite": 4,
                                 "cancelled": 5, "pressure_failure": 6, "post_closure": 7}[solver.exit_reason]
        assert stats[start+3] == solver._full_native_last_iterations
        assert len(actual[base+32]) == len(solver.residuals)
        np.testing.assert_allclose(stats[start+4:start+8],
            [solver.final_res_mom, solver.final_res_mass_local, solver.final_res_mass_global,
             solver.outlet_backflow_frac], rtol=3e-5, atol=1e-10)
    assert not failures, f"Initial flow fields outside original tolerances: {failures}"


def _thermal_case(inputs):
    """Translate only the existing model-h bridge's fields from the real entry."""
    shape = tuple(inputs[key] for key in ("Nx", "Ny", "Nz"))

    def array(value):
        return np.empty(0) if value is None else np.array(value, dtype=np.float64, order="C", copy=True)

    def field(value):
        return array(np.broadcast_to(value, shape))

    sides = []
    for side in "AB":
        assert inputs["model_mass_"+side] is not None
        sides.append([field(inputs["K_ff"+side]), field(inputs["h_v"+side]),
                      *[array(mass) for mass in inputs["model_mass_"+side]],
                      array(inputs["T_in"+side+"_profile"]), array(inputs["inlet_mask_"+side]),
                      array(inputs["mms_S_"+side+"_field"])])
    assert all(inputs[key] is None for key in ("Ta_init", "Tb_init", "Ts_init", "Tb_prescribed"))
    alpha = tuple(inputs[key] if inputs[key] is not None else inputs["alpha_T"]
                  for key in ("alpha_T_fA", "alpha_T_s", "alpha_T_fB"))
    chunk = model_h.energy.DEFAULT_CONV_CHUNK if inputs["conv_chunk"] is None else inputs["conv_chunk"]
    qtol = max(inputs["tol"]*10., 1e-4) if inputs["q_rel_tol"] is None else inputs["q_rel_tol"]
    rb = bool(model_h.energy._RB_ENERGY and np.prod(shape) > model_h.energy._RB_ENERGY_GATE)
    assert alpha == (.7, 1., .7)
    assert chunk == 250
    assert not rb
    tin = (inputs["T_inA"], inputs["T_inB"])
    return dict(shape=shape, widths=[array(inputs["d"+axis+"_arr"]) for axis in "xyz"],
                a=sides[0], b=sides[1], ks=field(inputs["K_ss"]),
                source_s=array(inputs["mms_S_s_field"]),
                state=[field(tin[0]), field(tin[1]), field(.5*sum(tin))],
                tin=tin, directions=(inputs["dir_A"], inputs["dir_B"]), fluids=(0, 0),
                maxit=inputs["max_iter"], chunk=chunk, warm=False, accelerate=inputs["accelerate"],
                rb=rb, alpha=alpha, qtol=qtol)


def test_refined_first_thermal_from_identical_inputs(native_thermal, first_thermal_entry):
    inputs = copy.deepcopy(first_thermal_entry[3])
    case = _thermal_case(inputs)
    expected = model_h.energy.solve_full_domain_3d(**inputs)
    actual = native_thermal(case)
    try:
        model_h.assert_equivalent(case, actual, expected)
    except AssertionError:
        print("fixed-input native return/status:", actual[0], actual[1], actual[4])
        print("fixed-input Python stopping:", {key: expected[3][key]
              for key in ("iterations", "converged", "residual", "energy_finishing_checks")})
        for name, native, reference in zip(("Ta", "Tb", "Ts"), case["state"], expected[:3]):
            print("fixed-input temperature comparison:", name, dict(
                max_abs=float(np.max(np.abs(native-reference))), rtol=2e-10, atol=2e-8,
                failing_values=int(np.count_nonzero(~np.isclose(
                    native, reference, rtol=2e-10, atol=2e-8, equal_nan=True)))))
        raise
