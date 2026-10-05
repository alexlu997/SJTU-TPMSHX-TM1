"""Isolate initial flow and thermal qualification for the refined 24^3 case.

The original two-outer full-driver test remains separate. Both stages use its
prepared case and budgets; no saved field snapshots or altered solver policies
enter these comparisons. Flow retains the test_full_3d parity tolerances;
thermal qualification uses test_model_h_3d returned-state equations and gates.
Anderson candidates retain exact same-history cross-language comparisons.
"""
import copy
import ctypes as ct
import inspect
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.solvers import anderson_acceleration as anderson
from sjtu_tpmshx.tests.native import test_full_3d as full
from sjtu_tpmshx.tests.native import test_model_h_3d as model_h
from sjtu_tpmshx.tests.native import test_native_outer_anderson as outer

native_full = full.native
native_thermal = model_h.native
native_candidate = outer.native


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
        model_h.assert_actual_state(case, actual)
        # A formerly completed real-input solve must still complete within the
        # same budget. The new thermal map need not match the old trajectory.
        if expected[3]["converged"]:
            assert actual[1][0] == 0
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


class _FirstChunkComplete(BaseException):
    """The original chunk returned; stop before a second chunk or outer step."""


def test_refined_first_chunk_same_history_candidates(
        native_candidate, native_thermal, first_thermal_entry, monkeypatch, record_property):
    inputs = copy.deepcopy(first_thermal_entry[3])
    case = _thermal_case(inputs)
    assert case["shape"] == (24, 24, 24)
    assert (case["maxit"], case["chunk"], case["alpha"]) == (20000, 250, (.7, 1., .7))
    assert case["accelerate"] and not case["rb"]

    # This directory is deliberately outside every CI artifact upload path.
    evidence_root = Path.cwd() / ".cache/native-anderson-same-history"
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="qualification-", dir=evidence_root))
    original_candidate = anderson.AndersonSIMPLE.candidate
    original_advance = anderson.advance_energy
    call = native_candidate.lib.test_anderson_candidate
    call.argtypes = [outer.S, outer.S, outer.D, outer.D, outer.D, ct.c_double,
                     outer.D, ct.POINTER(ct.c_int), outer.C, outer.S]
    call.restype = ct.c_int
    records, step_calls = [], []
    stage_records = []
    states, observed_residuals = {}, {}
    requested = 0
    chunk_calls = 0
    chunk_residual = None

    def observe_candidate(accelerator, image):
        assert accelerator.m == 5 and accelerator.beta == 1. and accelerator.cond_max == 1e10
        # columns denotes history samples, not difference columns.
        x = np.ascontiguousarray(np.stack(list(accelerator._X), axis=1))
        residual = np.ascontiguousarray(np.stack(list(accelerator._R), axis=1))
        g = np.array(image, dtype=np.float64, order="C", copy=True)
        assert x.shape == residual.shape and x.shape[0] == 41472
        assert x.dtype == residual.dtype == g.dtype == np.float64
        expected, expected_applied = original_candidate(accelerator, image)
        actual = np.full_like(g, np.nan)
        applied, error = ct.c_int(), ct.create_string_buffer(512)
        code = call(*x.shape, x.ctypes.data_as(outer.D), residual.ctypes.data_as(outer.D),
                    g.ctypes.data_as(outer.D), accelerator.cond_max,
                    actual.ctypes.data_as(outer.D), ct.byref(applied), error, len(error))
        failure = None
        try:
            assert code == 0, error.value.decode()
            assert bool(applied.value) == expected_applied
            np.testing.assert_allclose(actual, expected, rtol=3e-10, atol=3e-12)
            if sys.platform == "darwin":
                np.testing.assert_array_equal(actual, expected)
        except AssertionError as exc:
            failure = str(exc)
        row = dict(index=len(records), requested_sweeps=requested, rows=x.shape[0],
                   history_samples=x.shape[1], difference_columns=x.shape[1]-1,
                   history_strides=list(x.strides), code=code, error=error.value.decode(),
                   python_applied=bool(expected_applied), native_applied=bool(applied.value),
                   array_equal=bool(np.array_equal(actual, expected)),
                   unequal=int(np.count_nonzero(actual != expected)),
                   max_abs=float(np.max(np.abs(actual-expected))), failure=failure)
        if failure is not None:
            filename = f"candidate-{row['index']:02d}.npz"
            np.savez(evidence / filename, X=x, R=residual, g=g,
                     python_candidate=expected, native_candidate=actual)
            row["failure_arrays"] = filename
        records.append(row)
        # The original Python candidate and applied decision drive every trial.
        return expected, expected_applied

    def observe_advance(step, fields, sweeps, snapshots=(), cancel_check=None):
        nonlocal requested, chunk_calls, chunk_residual
        chunk_calls += 1
        assert chunk_calls == 1 and sweeps == 250 and not snapshots
        states["before"] = tuple(field.copy() for field in fields)

        def observe_step(count):
            nonlocal requested
            residual = step(count)
            requested += count
            step_calls.append(dict(count=count, requested_sweeps=requested,
                                   residual=float(residual)))
            if requested == 25:
                states["25"] = tuple(field.copy() for field in fields)
                observed_residuals["25"] = float(residual)
            return residual

        chunk_residual = original_advance(
            observe_step, fields, sweeps, snapshots=snapshots, cancel_check=cancel_check)
        assert requested == 250
        states["250"] = tuple(field.copy() for field in fields)
        observed_residuals["250"] = float(chunk_residual)
        if any(row["failure"] is not None for row in records):
            np.savez(evidence / "python-first-chunk-fields.npz",
                     Ta=fields[0], Tb=fields[1], Ts=fields[2])
        raise _FirstChunkComplete

    monkeypatch.setattr(anderson.AndersonSIMPLE, "candidate", observe_candidate)
    monkeypatch.setattr(anderson, "advance_energy", observe_advance)
    completed = False
    try:
        with pytest.raises(_FirstChunkComplete):
            model_h.energy.solve_full_domain_3d(**inputs)
        completed = True
        for seed, actual_seed in zip(case["state"], states["before"]):
            np.testing.assert_array_equal(seed, actual_seed)
        for count, accelerate in ((25, False), (250, True)):
            short_case = copy.deepcopy(case)
            short_case.update(maxit=count, accelerate=accelerate)
            result = native_thermal(short_case)
            code, status, metrics, output, error = result
            reference = states[str(count)]
            rtol, atol = (2e-10, 2e-8) if accelerate else (2e-11, 2e-9)
            comparisons = {name: dict(
                max_abs=float(np.max(np.abs(a-b))),
                unequal=int(np.count_nonzero(a != b)),
                failing_original_tolerance=int(np.count_nonzero(
                    ~np.isclose(a, b, rtol=rtol, atol=atol, equal_nan=True))))
                for name, a, b in zip(("Ta", "Tb", "Ts"), short_case["state"], reference)}
            failure = None
            try:
                assert code == 0, error
                assert status[1] == count
                model_h.assert_actual_state(short_case, result)
            except AssertionError as exc:
                failure = str(exc)
            stage_records.append(dict(
                sweeps=count, accelerate=accelerate, rtol=rtol, atol=atol,
                temperature_comparison_role="historical trajectory diagnostic; actual-state equations gate",
                audit_rtol=2e-9, audit_atol=2e-9,
                native_status=list(status), native_error=error,
                native_residual=float(metrics[0]), python_residual=observed_residuals[str(count)],
                temperature_comparisons=comparisons, failure=failure))
            if failure is not None:
                arrays = {f"native_output_{i}": field for i, field in enumerate(output)}
                arrays.update({f"native_{name}": field for name, field in zip(("Ta", "Tb", "Ts"), short_case["state"])})
                for stage, fields in states.items():
                    arrays.update({f"python_{stage}_{name}": field for name, field in zip(("Ta", "Tb", "Ts"), fields)})
                np.savez(evidence / f"stage-{count}-failure.npz", **arrays)
    finally:
        summary = dict(first_chunk_completed=completed, original_thermal_budget=20000,
                       requested_chunk=250, requested_sweeps=requested,
                       chunk_calls=chunk_calls, chunk_residual=chunk_residual,
                       platform=sys.platform, numpy_version=np.__version__,
                       native_library=str(native_candidate.lib._name),
                       short_stage_records=stage_records,
                       candidate_records=records, step_calls=step_calls)
        if any(row["failure"] is not None for row in records + stage_records):
            np.savez(evidence / "python-captured-states.npz", **{
                f"{stage}_{name}": field for stage, fields in states.items()
                for name, field in zip(("Ta", "Tb", "Ts"), fields)})
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        record_property("anderson_same_history", json.dumps(summary, separators=(",", ":")))
        print("same-history qualification summary:", json.dumps(summary, separators=(",", ":")))
        print("local-only full failure arrays:", evidence)
    assert chunk_calls == 1 and requested == 250
    assert set(range(2, 7)) <= {row["history_samples"] for row in records}
    assert sum(row["history_samples"] == 6 for row in records) >= 2, "sliding window was not observed"
    failures = [row["index"] for row in records if row["failure"] is not None]
    stage_failures = [row["sweeps"] for row in stage_records if row["failure"] is not None]
    assert not failures and not stage_failures, (
        f"candidate mismatches {failures}; short-stage mismatches {stage_failures}; local evidence: {evidence}")
