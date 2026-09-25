"""Mass-flow mapping used by the sCO2 experimental-Q validation."""

import numpy as np
import pytest

from sjtu_tpmshx.df_surrogate.predict import SCO2_DF_METHOD
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.validation.cases.validate_sco2_exp_q import (
    GROSS_FACE_M2,
    _flow_velocity,
    _solver_geometry,
)


@pytest.mark.parametrize("topology", ["Diamond", "Gyroid"])
def test_solver_velocity_reconstructs_measured_mass_flow(topology):
    mdot = 0.05
    rho_in = 125.0
    geo = _solver_geometry(topology)
    u_in = _flow_velocity(mdot, rho_in, geo["void_area_m2"])

    assert geo["void_area_m2"] == pytest.approx(
        0.5 * geo["epsilon"] * GROSS_FACE_M2)
    assert rho_in * u_in * geo["void_area_m2"] == pytest.approx(
        mdot, rel=1e-12)


def test_explicit_reference_keeps_variable_density_inlet_mass_flux():
    rho = np.full((4, 5), 100.0)
    rho[:, 0] = 110.0
    solver = SIMPLESolver(
        W=0.04, H=0.05, Nx=4, Ny=5,
        tpms_type="Gyroid", L_cell_mm=7.0, t_mm=0.6,
        eps=0.7, r_h=1.0e-3, rho=rho, mu=2.0e-5, T_in=400.0,
        inlet_lo=0.0, inlet_hi=0.04, v_inlet=0.5,
        wall_refine=False, fluid_type="incompressible",
        rho_inlet_ref=125.0, df_method=SCO2_DF_METHOD,
    )
    solver.solve(max_iter=1, verbose=False)

    assert np.allclose(solver.rho_field[:, 0] * solver.v[:, 0], 62.5)


# Synthetic full selections: no workbook or production pipeline is run.
def _q_results(diamond=0.20, gyroid=0.05):
    import pandas as pd

    rows = [dict(dimension=dim, topology=topo, case=case,
                 Q_ref_W=100.0, Q_solver_W=100.0 * (1.0 + error),
                 Q_error_rel=0.0, numerical_ok=True, reference_ok=True,
                 df_mode="cfd_smooth")
            for dim in ("2d", "3d")
            for topo, error in (("Diamond", diamond), ("Gyroid", gyroid))
            for case in (1, 2)]
    result = pd.DataFrame(rows)
    result.attrs["expected_cases"] = {"Diamond": [1, 2], "Gyroid": [1, 2]}
    return result


@pytest.mark.parametrize("diamond,gyroid,passed", [
    (0.20, 0.06, True), (0.20 - 1e-8, 0.06 - 1e-8, True),
    (0.20 + 1e-8, 0.0, False), (0.0, 0.06 + 1e-8, False),
    (-0.20, -0.06, True), (-0.20 - 1e-8, 0.0, False),
])
def test_q_limits_use_actual_q_per_group(diamond, gyroid, passed):
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(diamond, gyroid)
    # Deliberately inconsistent error column must never manufacture a pass.
    assert runner._accept_q(result, result.attrs["expected_cases"],
                            ["2d", "3d"]) is passed


@pytest.mark.parametrize("dimension,topology,limit", [
    ("2d", "Diamond", 0.20), ("2d", "Gyroid", 0.06),
    ("3d", "Diamond", 0.21), ("3d", "Gyroid", 0.06),
])
@pytest.mark.parametrize("offset,passed", [(-1e-8, True), (0., True), (1e-8, False)])
@pytest.mark.parametrize("sign", [-1, 1])
def test_q_dimension_boundaries(dimension, topology, limit, offset, passed, sign):
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(0., 0.)
    result = result[result.dimension == dimension].copy()
    result.loc[result.topology == topology, "Q_solver_W"] = (
        100. * (1. + sign * (limit + offset)))
    assert runner._accept_q(result, result.attrs["expected_cases"], [dimension]) is passed


def test_3d_limits_do_not_relax_2d_or_combined_acceptance():
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(0.205, 0.055)
    expected = result.attrs["expected_cases"]
    assert runner._accept_q(result[result.dimension == "3d"], expected, ["3d"])
    assert not runner._accept_q(result[result.dimension == "2d"], expected, ["2d"])
    assert not runner._accept_q(result, expected, ["2d", "3d"])


@pytest.mark.parametrize("dimension", ["2d", "3d"])
@pytest.mark.parametrize("qualification", ["numerical_ok", "reference_ok"])
def test_q_limits_require_qualifications_in_each_dimension(dimension, qualification):
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(0., 0.)
    result.loc[result.dimension == dimension, qualification] = False
    expected = result.attrs["expected_cases"]
    assert not runner._accept_q(result[result.dimension == dimension], expected, [dimension])
    assert not runner._accept_q(result, expected, ["2d", "3d"])


@pytest.mark.parametrize("failure", [
    "empty", "missing_group", "missing_case", "duplicate", "unexpected",
    "nan", "inf", "zero_ref", "negative_ref", "numerical", "null_numerical",
    "empty_expected", "one_bad_dimension", "reference", "null_reference",
])
def test_q_acceptance_rejects_incomplete_or_invalid_results(failure):
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(0.0, 0.0)
    expected = result.attrs["expected_cases"]
    if failure == "empty":
        result = pd.DataFrame()
    elif failure == "missing_group":
        result = result.iloc[2:]
    elif failure == "missing_case":
        result = result.iloc[1:]
    elif failure == "duplicate":
        result.loc[1, "case"] = 1
    elif failure == "unexpected":
        result.loc[1, "case"] = 99
    elif failure in ("nan", "inf"):
        result.loc[0, "Q_solver_W"] = float(failure)
    elif failure in ("zero_ref", "negative_ref"):
        result.loc[0, "Q_ref_W"] = 0.0 if failure == "zero_ref" else -100.0
    elif failure == "numerical":
        result.loc[0, "numerical_ok"] = False
    elif failure == "null_numerical":
        result["numerical_ok"] = result["numerical_ok"].astype("boolean")
        result.loc[0, "numerical_ok"] = pd.NA
    elif failure == "empty_expected":
        expected = {"Diamond": [], "Gyroid": [1, 2]}
    elif failure == "reference":
        result.loc[0, "reference_ok"] = False
    elif failure == "null_reference":
        result["reference_ok"] = result["reference_ok"].astype("boolean")
        result.loc[0, "reference_ok"] = pd.NA
    else:
        result.loc[4:5, "Q_solver_W"] = 130.0  # 3D Diamond alone exceeds 21%.
    assert not runner._accept_q(result, expected, ["2d", "3d"])


def test_fixed_selection_and_run_manifest(monkeypatch):
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    df = pd.DataFrame([
        dict(case=case, side=side, ok_done=True, ok_hb=True, ok_heat_flow=True,
             ok_dp=False, ok_dT=False, Tin_C=100.0, Tout_C=110.0,
             Pin_MPa=9.0, Pout_MPa=8.0, mdot=0.05,
             Pin_abs_Pa=9101325., Pout_abs_Pa=8101325.)
        for case in range(1, 6) for side in ("hot", "cold")])
    df.loc[df.case == 3, "ok_hb"] = False
    df.loc[(df.case == 4) & (df.side == "cold"), "Pin_abs_Pa"] = 17101325.
    df.loc[df.case == 5, "ok_done"] = False
    df.loc[df.case == 2, "Pout_abs_Pa"] = 7.9e6
    assert runner._valid_case_numbers(df) == [1, 2]
    df.attrs["reference"] = {"version": "synthetic"}
    monkeypatch.setattr(runner, "load_exp", lambda topology: df)
    monkeypatch.setattr(runner, "_print_geometry", lambda *args: None)
    monkeypatch.setattr(runner, "_print_summary", lambda *args: None)
    calls = []

    def fake_case(topology, case, dimension, frame):
        calls.append((topology, case, dimension))
        return dict(topology=topology, case=case, dimension=dimension,
                    flow_err_hot_rel=0., flow_err_cold_rel=0., Q_solver_W=100.,
                    Q_hot_exp_W=100., Q_cold_exp_W=100., Q_error_rel=0.,
                    enthalpy_imbalance_rel=0., numerical_ok=False, df_mode="cfd_smooth")

    monkeypatch.setattr(runner, "_run_case", fake_case)
    result = runner.run(["Diamond", "Gyroid"], ["2d", "3d"],
                        case=None, all_valid=True)
    assert len(calls) == len(result) == 8  # Failed cases remain in the result.
    assert result.attrs["expected_cases"] == {"Diamond": [1, 2], "Gyroid": [1, 2]}
    assert result.attrs["ranges"]["Diamond"]["Pin_MPa"] == [9., 9.]
    calls.clear()
    fixed = {"Diamond": [1, 3], "Gyroid": [3]}
    result = runner.run(["Diamond", "Gyroid"], ["2d", "3d"],
                        case=None, all_valid=False, fixed_cases=fixed)
    assert len(calls) == len(result) == 6
    assert result.attrs["expected_cases"] == fixed
    assert set(result["case"]) == {1, 3}  # Failed HB retained; valid case 2 not added.


@pytest.mark.parametrize('endpoint', ['Pin_abs_Pa', 'Pout_abs_Pa'])
def test_reference_pressure_bounds(endpoint):
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    df = pd.DataFrame([dict(ok_done=True, ok_hb=True, ok_heat_flow=True,
                           mdot=.05, Tin_C=100., Tout_C=110.,
                           Pin_abs_Pa=8e6, Pout_abs_Pa=8e6)] * 6)
    df[endpoint] = [np.nextafter(7.9e6, -np.inf), 7.9e6, 7.99e6,
                    8e6, 16e6, np.nextafter(16e6, np.inf)]
    assert runner._reference_valid(df).tolist() == [False, True, True, True, True, False]


@pytest.mark.parametrize("args", [
    ["--accept-q"], ["--accept-q", "--case", "1", "--topology", "Diamond"],
    ["--accept-q", "--all-valid"],
    ["--accept-q", "--all-valid", "--case", "1", "--topology", "Diamond"],
])
def test_q_cli_requires_fixed_selection_before_loading(monkeypatch, args):
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    monkeypatch.setattr("sys.argv", ["validate_sco2_exp_q", *args])
    monkeypatch.setattr(runner, "load_exp", lambda *args: pytest.fail("loaded data"))
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2


@pytest.mark.parametrize('destination', ['direct', 'csv_symlink', 'meta_symlink'])
def test_q_cli_rejects_frozen_outputs_before_running(monkeypatch, tmp_path, capsys, destination):
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner
    from sjtu_tpmshx.validation.harness import _provenance

    reference_dir = tmp_path / 'references'
    reference_dir.mkdir()
    reference = reference_dir / 'frozen.csv'
    reference.write_bytes(b'original reference')
    monkeypatch.setattr(_provenance, 'REFERENCE_DIR', reference_dir)
    output = tmp_path / 'q.csv'
    if destination == 'direct':
        output = reference
    else:
        link = output if destination == 'csv_symlink' else output.with_suffix('.csv.meta.json')
        link.symlink_to(reference)
    monkeypatch.setattr('sys.argv', ['runner', '--csv', str(output)])
    monkeypatch.setattr(runner, 'run', lambda *a, **kw: pytest.fail('started solver'))

    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
    assert 'reference directory is read-only' in capsys.readouterr().err
    assert reference.read_bytes() == b'original reference'


@pytest.mark.parametrize('failure', ['csv', 'metadata'])
def test_q_cli_preserves_previous_output_pair_on_write_failure(monkeypatch, tmp_path, failure):
    from pathlib import Path
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    output = tmp_path / 'q.csv'
    metadata = output.with_suffix('.csv.meta.json')
    output.write_bytes(b'old csv')
    metadata.write_bytes(b'old metadata')
    monkeypatch.setattr('sys.argv', ['runner', '--csv', str(output)])
    monkeypatch.setattr(runner, 'run', lambda *a, **kw: _q_results())

    def fail(*args, **kwargs):
        raise OSError('disk full')

    if failure == 'csv':
        monkeypatch.setattr(pd.DataFrame, 'to_csv', fail)
    else:
        monkeypatch.setattr(Path, 'write_text', fail)
    with pytest.raises(OSError, match='disk full'):
        runner.main()
    assert output.read_bytes() == b'old csv'
    assert metadata.read_bytes() == b'old metadata'
    assert not list(tmp_path.glob('.tm1-publish-*'))


@pytest.mark.parametrize("accept,over_limit,exit_code", [
    (False, True, 0), (True, True, 1), (True, False, 0),
])
def test_q_cli_verdict_and_legacy_csv(monkeypatch, tmp_path, capsys,
                                     accept, over_limit, exit_code):
    import json
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(0.21 if over_limit else 0.20, 0.05).iloc[:2].copy()
    result.attrs["expected_cases"] = {"Diamond": [1, 2]}
    output = tmp_path / "q.csv"
    args = ["runner", "--topology", "Diamond", "--dimension", "2d",
            "--csv", str(output)]
    if accept:
        manifest = tmp_path / "prior.meta.json"
        manifest.write_text(json.dumps({"expected_cases": {"Diamond": [1, 2]}}))
        args += ["--case-manifest", str(manifest), "--accept-q"]
    monkeypatch.setattr("sys.argv", args)

    def fake_run(topologies, dimensions, *, case, all_valid, fixed_cases):
        assert topologies == ["Diamond"] and dimensions == ["2d"]
        assert case is None and not all_valid
        assert fixed_cases == ({"Diamond": [1, 2]} if accept else None)
        return result

    monkeypatch.setattr(runner, "run", fake_run)
    assert runner.main() == exit_code
    assert len(pd.read_csv(output)) == 2  # No comment-header format change.
    metadata = json.loads(output.with_suffix(".csv.meta.json").read_text(
        encoding="utf-8"))
    assert metadata["expected_cases"] == {"Diamond": [1, 2]}
    assert metadata["dimensions"] == ["2d"]
    assert metadata["df_modes"] == ["cfd_smooth"]
    assert metadata["actual_data_revision"] == "unverified"
    assert metadata["exit_ok"] is (exit_code == 0)
    assert bool(metadata["commit"])
    if accept:
        assert "not G1/G2 or full-core energy acceptance" in capsys.readouterr().out


def test_q_cli_metadata_on_strict_cp1252_stdout(monkeypatch, tmp_path):
    import io
    import json
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    manifest = tmp_path / "prior.meta.json"
    manifest.write_text(json.dumps({"expected_cases": _q_results().attrs["expected_cases"]}))
    monkeypatch.setattr("sys.argv", ["runner", "--case-manifest", str(manifest), "--accept-q"])
    monkeypatch.setattr(runner, "run", lambda *args, **kwargs: _q_results())
    with io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict") as stream:
        monkeypatch.setattr("sys.stdout", stream)
        assert runner.main() == 0
        stream.flush()
        output = stream.buffer.getvalue().decode("cp1252")
    metadata = json.loads(output.splitlines()[0].removeprefix("RUN "))
    assert metadata["sheets"] == ["实验数据处理-Diamond", "实验数据处理-Gyroid"]


@pytest.mark.parametrize("dimension", ["2d", "3d"])
def test_zero_reference_still_fails_diagnostic_case(monkeypatch, dimension):
    from types import SimpleNamespace
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    row = pd.Series(dict(Tin_C=100., Tout_C=100., Pin_MPa=9., Pout_MPa=8.99,
                         Pin_abs_Pa=9101325., Pout_abs_Pa=9091325., mdot=0.05,
                         Q_kW=0., Q_cached_kW=0., HB=0., HB_cached=0.,
                         ok_done=True, ok_hb=True, ok_hb_cached=True,
                         ok_heat_flow=False, dP_MPa=0.01))
    frame = pd.DataFrame()
    frame.attrs.update(A_flow_m2=0.001, A_heat_m2=1.)
    monkeypatch.setattr(runner, "_case_rows", lambda *args: (row, row))
    monkeypatch.setattr(runner, "_solver_geometry", lambda *args: dict(
        void_area_m2=0.001, heat_area_m2=1.))
    def density(temperature, pressure):
        assert temperature == 373.15 and pressure == 9101325.
        return 100.

    monkeypatch.setattr(runner.fluid_props, "get", lambda *args: SimpleNamespace(
        rho=density))
    result = SimpleNamespace(
        Q_W=100., converged=True, T_out_A_K=373.15, T_out_B_K=373.15,
        diagnostics=dict(mass_flow_A_kg_s_per_m=0.05 / runner.CORE_DEPTH_M,
                         mass_flow_B_kg_s_per_m=0.05 / runner.CORE_DEPTH_M,
                         mass_flow_A_kg_s=0.05, mass_flow_B_kg_s=0.05),
        residuals=dict(mass_imbalance_rel_A=0., mass_imbalance_rel_B=0.,
                       enthalpy_imbalance_rel=0.),
        metadata={"darcy_forchheimer": {"mode": "cfd_smooth"}})
    def pipeline(config):
        assert config.fluid_A.P_in_Pa == config.fluid_B.P_in_Pa == 9101325.
        for side in (config.fluid_A, config.fluid_B):
            assert 100. * side.u_mps * .001 == pytest.approx(.05)
        return SimpleNamespace(run=lambda: result)

    monkeypatch.setattr(runner, "Pipeline2D", pipeline)
    monkeypatch.setattr(runner, "Pipeline3D", pipeline)
    with pytest.raises(ZeroDivisionError):
        runner._run_case("Diamond", 1, dimension, frame)


@pytest.mark.parametrize("cases", [[], [1, 1], [0], [True], [1.5], ["1"]])
def test_case_manifest_rejects_invalid_members(tmp_path, cases):
    import json
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    path = tmp_path / "previous.meta.json"
    path.write_text(json.dumps({"expected_cases": {"Diamond": cases}}))
    with pytest.raises(ValueError, match="unique positive integer"):
        runner._read_manifest(path, ["Diamond"])


def test_q_cli_uses_explicit_manifest(monkeypatch, tmp_path):
    import json
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    path = tmp_path / "previous.meta.json"
    path.write_text(json.dumps({"expected_cases": {"Diamond": [1, 2]}}))
    monkeypatch.setattr("sys.argv", ["runner", "--topology", "Diamond",
                                   "--dimension", "2d", "--accept-q",
                                   "--case-manifest", str(path)])

    def fake_run(topologies, dimensions, *, case, all_valid, fixed_cases):
        assert topologies == ["Diamond"] and dimensions == ["2d"]
        assert case is None and not all_valid
        assert fixed_cases == {"Diamond": [1, 2]}
        result = _q_results().iloc[:2].copy()
        result.attrs["expected_cases"] = fixed_cases
        return result

    monkeypatch.setattr(runner, "run", fake_run)
    assert runner.main() == 0
