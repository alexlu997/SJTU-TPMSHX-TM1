"""Isolated CoolProp 7.2.0 C++ capability qualification, no production binding.

Fixed before comparison: HEOS property rtol=2e-10; BICUBIC rtol=2e-9.
SI absolute tolerances for rho/cp/mu/k/h are 2e-8/2e-5/2e-14/2e-10/2e-5.
T absolute tolerances are 2e-8 K (HEOS), 2e-7 K (BICUBIC).
These compare the SAME backend; BICUBIC-vs-HEOS interpolation error is a
separate observation, not a change to the existing HEOS finishing contract.
"""
import csv
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]
FIELDS = ("T_K", "rho_kg_m3", "cp_J_kgK", "mu_Pas", "k_W_mK", "h_J_kg")
PROPERTY_ATOL = np.array([2e-8, 2e-5, 2e-14, 2e-10, 2e-5])

# Run the Python oracle in a separate process. Its table directory/config and
# mutable AbstractState objects never change the calling test process's EOS.
REFERENCE = r'''
import json, math, sys
from pathlib import Path
import CoolProp.CoolProp as CP
sys.path.insert(0, sys.argv[2])
from sjtu_tpmshx.models.fluid_props import check_water_state
from sjtu_tpmshx.models.sco2_props import _validate_state
payload = json.load(sys.stdin)
tables = str(Path(sys.argv[1]).resolve()) + "/"
Path(tables).mkdir(parents=True, exist_ok=True)
CP.set_config_string(CP.ALTERNATIVE_TABLES_DIRECTORY, tables)
if payload["mode"] == "boundaries":
    guard = CP.AbstractState("HEOS", "Water")
    print(json.dumps(dict(psat=CP.PropsSI("P", "T", 380., "Q", 0., "Water"),
                         melting=[guard.melting_line(CP.iT, CP.iP, p) for p in (101325., 200000.)])))
    raise SystemExit(0)
states = {}
rows = []
for request in payload["requests"]:
    row = dict(id=request["id"], status=0, fields=[float("nan")]*6,
               phase=-1, melting=float("nan"), error="")
    fluid, backend, pair = request["fluid"], request["backend"], request["pair"]
    value, pressure = request["value"], request["pressure"]
    try:
        if backend not in ("HEOS", "BICUBIC&HEOS") or fluid not in ("CO2", "Water") or pair not in ("TP", "HP"):
            raise ValueError("unsupported EOS request")
        if not math.isfinite(value) or not math.isfinite(pressure) or pressure <= 0:
            raise ValueError("EOS input requires finite value and positive Pa(abs)")
        if fluid == "CO2":
            if pair == "TP": _validate_state(value, pressure)
            elif not 7.9e6 <= pressure <= 16e6: raise ValueError("sCO2 pressure must be within 7.9..16 MPa")
        elif pair == "TP": check_water_state("water", value, pressure)
    except (ValueError, RuntimeError) as exc:
        row.update(status=1, error=str(exc))
        rows.append(row)
        continue
    try:
        key = backend, fluid
        if key not in states:
            state = CP.AbstractState(backend, fluid)
            state.update(CP.PT_INPUTS, 8e6 if fluid == "CO2" else 2e5, 300.)
            states[key] = state
        state = states[key]
        state.update(CP.PT_INPUTS if pair == "TP" else CP.HmassP_INPUTS,
                     pressure if pair == "TP" else value, value if pair == "TP" else pressure)
        temperature = state.T()
    except (ValueError, RuntimeError) as exc:
        row.update(status=2, error=str(exc))
        rows.append(row)
        continue
    try:
        if fluid == "CO2": _validate_state(temperature, pressure)
        else:
            check_water_state("water", temperature, pressure)
            guard = CP.AbstractState("HEOS", "Water")
            row["melting"] = guard.melting_line(CP.iT, CP.iP, pressure)
    except (ValueError, RuntimeError) as exc:
        row.update(status=1, error=str(exc), melting=float("nan"))
        rows.append(row)
        continue
    try:
        fields = [temperature, state.rhomass(), state.cpmass(), state.viscosity(), state.conductivity(), state.hmass()]
        if not all(math.isfinite(x) for x in fields) or not all(x > 0 for x in fields[:5]):
            raise ValueError("nonfinite/nonpositive EOS output")
        row.update(fields=fields, phase=int(state.phase()))
    except (ValueError, RuntimeError) as exc:
        row.update(status=2, error=str(exc), melting=float("nan"))
    rows.append(row)
print(json.dumps(dict(version=CP.get_global_param_string("version"), tables=tables, rows=rows)))
'''


def request(identifier, backend="HEOS", fluid="CO2", pair="TP", value=320., pressure=9e6):
    return dict(id=identifier, backend=backend, fluid=fluid, pair=pair, value=value, pressure=pressure)


@pytest.fixture(scope="module")
def eos_program():
    os_name = "macos" if sys.platform == "darwin" else ("windows" if os.name == "nt" else "linux")
    arch = platform.machine().lower()
    if arch in ("amd64", "x86_64"):
        arch = "x64" if os.name == "nt" else "x86_64"
    default = ROOT / ".cache/native-deps/build" / ("pilot-" + os_name + "-" + arch) / (
        "eos_smoke.exe" if os.name == "nt" else "eos_smoke")
    path = Path(os.environ.get("TPMSHX_EOS_SMOKE", str(default))).resolve()
    if not path.is_file():
        message = "native EOS pilot executable is not built: " + str(path)
        if os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1" or "TPMSHX_EOS_SMOKE" in os.environ:
            pytest.fail(message)
        pytest.skip(message)
    # The absolute executable must run without Python/venv search variables.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTHON", "CONDA")) and key not in (
               "VIRTUAL_ENV", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH")}
    if os.name != "nt": env["PATH"] = "/usr/bin:/bin"
    version = subprocess.run([str(path), "--version"], env=env, capture_output=True, text=True, check=True)
    assert version.stdout.split()[0] == "7.2.0"
    return path, env


@pytest.fixture(scope="module")
def eos_tables():
    base = ROOT / ".cache/native-deps/tables/eos-qualification"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture(scope="module")
def python_eos(eos_tables):
    def run(requests=(), *, mode="states"):
        result = subprocess.run([sys.executable, "-c", REFERENCE,
                                 str(eos_tables / "python"), str(ROOT)],
            cwd=ROOT, input=json.dumps(dict(mode=mode, requests=requests)),
            capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    return run


@pytest.fixture(scope="module")
def native_eos(eos_program, eos_tables):
    path, env = eos_program
    def run(requests=(), *, workers=1, text=None, table_directory=None):
        if text is None:
            text = "".join("{id} {backend} {fluid} {pair} {value:.17g} {pressure:.17g}\n".format(**row)
                           for row in requests)
        tables = table_directory or (eos_tables / "native")
        process = subprocess.run([str(path), "--tables", str(tables), "--workers", str(workers)],
            cwd=ROOT, env=env, input=text, capture_output=True, text=True, check=True)
        metadata, data = {}, []
        for line in process.stdout.splitlines():
            if line.startswith("#"):
                key, value = line[1:].split("\t", 1)
                metadata[key] = value
            else: data.append(line)
        rows = list(csv.DictReader(io.StringIO("\n".join(data)), delimiter="\t"))
        for row in rows:
            row["status"] = int(row["status"])
            row["phase"] = int(row["phase"])
            row["fields"] = [float(row[key]) for key in FIELDS]
            row["melting"] = float(row["melting_K"])
            row["error"] = bytes.fromhex(row["error_hex"]).decode("utf-8")
        assert metadata["version"] == "7.2.0"
        assert Path(metadata["tables"]).resolve() == Path(tables).resolve()
        assert int(metadata["workers"]) == workers
        return rows, metadata
    return run


def assert_rows_equal(actual, expected, requests):
    assert len(actual) == len(expected) == len(requests)
    for got, target, inp in zip(actual, expected, requests):
        assert got["id"] == target["id"] == inp["id"]
        assert got["status"] == target["status"], (inp, got, target)
        if got["status"]:
            assert got["error"] and target["error"]
            assert np.isnan(got["fields"]).all() and got["phase"] == -1
            assert np.isnan(got["melting"])
            continue
        assert not got["error"]
        backend = inp["backend"]
        rtol = 2e-10 if backend == "HEOS" else 2e-9
        assert got["fields"][0] == pytest.approx(target["fields"][0], rel=0.,
                                                  abs=2e-8 if backend == "HEOS" else 2e-7)
        for value, reference, atol in zip(got["fields"][1:], target["fields"][1:], PROPERTY_ATOL):
            np.testing.assert_allclose(value, reference, rtol=rtol, atol=float(atol))
        assert got["phase"] == target["phase"]
        if inp["fluid"] == "Water":
            assert got["melting"] == pytest.approx(target["melting"], rel=0., abs=2e-8)


def forward_grid(backend):
    rows = [request(f"co2-{i}-{j}", backend=backend, value=t, pressure=p)
            for i, t in enumerate((280., 300., 304., 307., 310., 320., 450., 700.))
            for j, p in enumerate((7.9e6, 8e6, 9e6, 12e6, 16e6))]
    rows.extend(request(f"water-{i}", backend=backend, fluid="Water", value=t, pressure=p)
                for i, (t, p) in enumerate(((273.2, 2e5), (274., 101325.), (280., 2e5),
                    (300., 2e5), (350., 2e5), (380., 2e5), (400., 3e6), (500., 3e6), (300., 20e6))))
    return rows


@pytest.mark.parametrize("backend", ["HEOS", "BICUBIC&HEOS"])
def test_forward_properties_at_project_bounds_and_pseudocritical_states(native_eos, python_eos, backend):
    rows = forward_grid(backend)
    expected = python_eos(rows)
    actual, _ = native_eos(rows)
    assert expected["version"] == "7.2.0"
    assert all(row["status"] == 0 for row in expected["rows"])
    assert_rows_equal(actual, expected["rows"], rows)


@pytest.mark.parametrize("backend", ["HEOS", "BICUBIC&HEOS"])
def test_inverse_uses_actual_enthalpy_pressure_and_same_backend(native_eos, python_eos, backend):
    base = [request(f"co2-h-{i}", value=t, pressure=p) for i, (t, p) in enumerate(
        ((281., 7.9e6), (304., 8e6), (307., 8e6), (310., 9e6), (400., 12e6), (699., 16e6)))]
    base.extend(request(f"water-h-{i}", fluid="Water", value=t, pressure=p) for i, (t, p) in enumerate(
        ((274., 101325.), (300., 2e5), (380., 2e5), (500., 3e6))))
    heos = python_eos(base)["rows"]
    assert all(row["status"] == 0 for row in heos)
    inverse = [dict(row, backend=backend, pair="HP", value=state["fields"][5]) for row, state in zip(base, heos)]
    expected = python_eos(inverse)["rows"]
    actual, _ = native_eos(inverse)
    assert all(row["status"] == 0 for row in expected)
    assert_rows_equal(actual, expected, inverse)
    if backend == "HEOS":
        np.testing.assert_allclose([row["fields"][0] for row in actual],
                                   [row["value"] for row in base], rtol=0., atol=2e-8)


def test_water_saturation_melting_high_pressure_and_invalid_input_guards(native_eos, python_eos):
    boundaries = python_eos(mode="boundaries")
    rows = [request(f"sat-{i}", fluid="Water", value=380., pressure=boundaries["psat"]*ratio)
            for i, ratio in enumerate((.999, 1., 1.001))]
    for i, (pressure, melting) in enumerate(zip((101325., 200000.), boundaries["melting"])):
        for j, delta in enumerate((-.001, .001)):
            rows.append(request(f"melt-{i}-{j}", fluid="Water", value=melting+delta, pressure=pressure))
    rows.extend(request(f"bad-water-{i}", fluid="Water", value=t, pressure=p) for i, (t, p) in enumerate(
        ((300., 3e7), (700., 3e7), (260., 101325.), (float("nan"), 1e5), (300., 0.), (300., float("inf")))))
    rows.extend(request(f"bad-co2-{i}", value=t, pressure=p) for i, (t, p) in enumerate(
        ((279.99, 9e6), (700.01, 9e6), (300., 7.899e6), (300., 16.001e6), (float("nan"), 9e6))))
    rows.extend([request("bad-air", fluid="Air"), request("bad-backend", backend="TTSE&HEOS"),
                 request("bad-h-co2", pair="HP", value=-1e12),
                 request("bad-h-water", fluid="Water", pair="HP", value=-1e12, pressure=2e5)])
    expected = python_eos(rows)["rows"]
    actual, _ = native_eos(rows)
    assert_rows_equal(actual, expected, rows)
    assert [row["status"] for row in actual[:3]] == [1, 1, 0]
    assert "high-pressure liquid" in next(row for row in actual if row["id"] == "bad-water-0")["error"]
    assert "freezing" in next(row for row in actual if row["id"] == "melt-0-0")["error"]
    assert "Air" in next(row for row in actual if row["id"] == "bad-air")["error"]


@pytest.mark.parametrize("backend", ["HEOS", "BICUBIC&HEOS"])
def test_parallel_independent_states_and_input_order_isolation(native_eos, python_eos, backend):
    rows = []
    for repeat in range(6):
        rows.extend([request(f"ca-{repeat}", backend=backend, value=304.+repeat, pressure=8e6),
                     request(f"cb-{repeat}", backend=backend, value=400.+repeat, pressure=12e6),
                     request(f"wa-{repeat}", backend=backend, fluid="Water", value=300.+repeat, pressure=2e5),
                     request(f"wb-{repeat}", backend=backend, fluid="Water", value=370.+repeat, pressure=2e5)])
    rows.insert(8, request("invalid-middle", backend=backend, fluid="Water", value=700., pressure=3e7))
    expected = python_eos(rows)["rows"]
    serial, _ = native_eos(rows, workers=1)
    parallel, _ = native_eos(rows, workers=2)
    assert_rows_equal(serial, expected, rows)
    assert_rows_equal(parallel, expected, rows)
    reversed_rows = rows[::-1]
    reversed_actual, _ = native_eos(reversed_rows, workers=2)
    assert_rows_equal(reversed_actual, expected[::-1], reversed_rows)


def test_native_protocol_rejects_bad_rows_and_requires_explicit_table_path(native_eos, eos_program):
    actual, _ = native_eos(text="missing\na HEOS CO2 TP not-a-number 9000000\nb HEOS CO2 PQ 320 9000000\n")
    assert len(actual) == 3 and all(row["status"] == 1 and row["error"] for row in actual)
    assert all(np.isnan(row["fields"]).all() for row in actual)
    path, env = eos_program
    process = subprocess.run([str(path)], env=env, capture_output=True, text=True)
    assert process.returncode == 2 and "absolute table directory" in process.stderr


def test_child_table_paths_and_reference_work_do_not_change_parent_eos(native_eos, python_eos, eos_tables):
    import CoolProp.CoolProp as CP
    before = CP.get_config_as_json_string()
    rows = [request("isolation", backend="BICUBIC&HEOS", value=320., pressure=9e6)]
    actual, _ = native_eos(rows)
    expected = python_eos(rows)["rows"]
    assert_rows_equal(actual, expected, rows)
    assert CP.get_config_as_json_string() == before
    for owner in ("native", "python"):
        files = [p for p in (eos_tables / owner).rglob("*") if p.is_file()]
        assert files, "tabular backend did not write its explicit table cache"
        assert all(eos_tables.resolve() in p.resolve().parents for p in files)
