"""Compare the bounded sCO2 V1 field solver with full-core experiment Q.

The workbook's ``u`` column is a mean-state reduction used for Re/f.  Solver
input velocity is rebuilt from the measured mass flow at the inlet state:

    A_void,side = (epsilon / 2) * (0.042 m)^2
    u_in = mdot_exp / (rho(T_in, P_in) * A_void,side)

The runner refuses to interpret Q error unless the mass flow reconstructed by
the production pipeline matches the workbook value.  Experimental pressure
drop is printed only as a diagnostic; V1 uses smooth-wall CFD D-F coefficients.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig,
    FluidConfig,
    GeometryConfig,
    PartialBCConfig,
    SolverConfig,
)
from sjtu_tpmshx.models import fluid_props
from sjtu_tpmshx.models.sco2_props import P_RANGE_PA
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry
from sjtu_tpmshx.validation.sco2_exp.load_sco2_exp import load_exp
from sjtu_tpmshx.validation.harness._provenance import _git_sha, _iso_now


CELL_M = 7.0e-3
N_STREAM = 26
N_CROSS = 6
CORE_LENGTH_M = N_STREAM * CELL_M
CORE_WIDTH_M = N_CROSS * CELL_M
CORE_DEPTH_M = CORE_WIDTH_M
GROSS_FACE_M2 = CORE_WIDTH_M * CORE_DEPTH_M
FLOW_REL_TOL = 1.0e-6
SMOKE_CASES = {"Diamond": 8, "Gyroid": 41}
Q_RMSRE_LIMITS = {
    "2d": {"Diamond": 0.20, "Gyroid": 0.06},
    "3d": {"Diamond": 0.21, "Gyroid": 0.06},
}
REPO_ROOT = Path(__file__).resolve().parents[3]


def _solver_geometry(topology: str) -> dict[str, float]:
    geo = tpms_geometry(topology, 7.0, 0.6, 16.0)
    return {
        "epsilon": float(geo["epsilon"]),
        "void_area_m2": 0.5 * float(geo["epsilon"]) * GROSS_FACE_M2,
        "heat_area_m2": float(geo["A_0"]) * GROSS_FACE_M2 * CORE_LENGTH_M,
    }


def _flow_velocity(mdot_kg_s: float, rho_in_kg_m3: float,
                   void_area_m2: float) -> float:
    if mdot_kg_s <= 0.0 or rho_in_kg_m3 <= 0.0 or void_area_m2 <= 0.0:
        raise ValueError("mass flow, inlet density, and void area must be positive")
    return mdot_kg_s / (rho_in_kg_m3 * void_area_m2)


def _reference_valid(df: pd.DataFrame) -> pd.Series:
    return (
        df["ok_done"]
        & df["ok_hb"]
        & df["ok_heat_flow"]
        & (df["mdot"] > 0)
        & (df["Tin_C"] + 273.15).between(280.0, 700.0)
        & (df["Tout_C"] + 273.15).between(280.0, 700.0)
        & df["Pin_abs_Pa"].between(*P_RANGE_PA)
        & df["Pout_abs_Pa"].between(*P_RANGE_PA)
    )


def _valid_case_numbers(df: pd.DataFrame) -> list[int]:
    counts = df[_reference_valid(df)].groupby("case")["side"].nunique()
    return [int(case) for case in counts[counts == 2].index]


def _case_rows(df: pd.DataFrame, case: int) -> tuple[pd.Series, pd.Series]:
    selected = df[df["case"] == case]
    if set(selected["side"]) != {"hot", "cold"}:
        raise ValueError(f"case {case} does not contain one hot and one cold row")
    return (
        selected[selected["side"] == "hot"].iloc[0],
        selected[selected["side"] == "cold"].iloc[0],
    )


def _config(topology: str, hot: pd.Series, cold: pd.Series,
            u_hot: float, u_cold: float, dimension: str) -> ComputeConfig:
    # ponytail: this is a porous-domain validation grid, not a grid-convergence
    # study; add a refinement sweep only after the smooth-wall model is useful.
    nz = N_CROSS if dimension == "3d" else 1
    return ComputeConfig(
        fluid_A=FluidConfig(
            type="sco2", u_mps=u_hot,
            T_in_K=float(hot["Tin_C"]) + 273.15,
            P_in_Pa=float(hot["Pin_abs_Pa"]),
        ),
        fluid_B=FluidConfig(
            type="sco2", u_mps=u_cold,
            T_in_K=float(cold["Tin_C"]) + 273.15,
            P_in_Pa=float(cold["Pin_abs_Pa"]),
        ),
        geometry=GeometryConfig(
            tpms=topology, L_cell_mm=7.0, t_wall_mm=0.6,
            k_s_W_mK=16.0, L_dom_m=CORE_LENGTH_M,
            H_dom_m=CORE_WIDTH_M,
            Lz_m=CORE_DEPTH_M if dimension == "3d" else None,
        ),
        solver=SolverConfig(
            Nx=2 * N_STREAM, Ny=2 * N_CROSS, Nz=nz,
        ),
        bc_A=PartialBCConfig(dir=0),
        bc_B=PartialBCConfig(dir=1),
    )


def _run_case(topology: str, case: int, dimension: str,
              df: pd.DataFrame) -> dict[str, object]:
    hot, cold = _case_rows(df, case)
    geo = _solver_geometry(topology)
    model = fluid_props.get("sco2")
    rho_hot = float(model.rho(
        float(hot["Tin_C"]) + 273.15, float(hot["Pin_abs_Pa"])))
    rho_cold = float(model.rho(
        float(cold["Tin_C"]) + 273.15, float(cold["Pin_abs_Pa"])))
    u_hot = _flow_velocity(float(hot["mdot"]), rho_hot, geo["void_area_m2"])
    u_cold = _flow_velocity(float(cold["mdot"]), rho_cold, geo["void_area_m2"])

    cfg = _config(topology, hot, cold, u_hot, u_cold, dimension)
    result = (Pipeline3D(cfg).run() if dimension == "3d"
              else Pipeline2D(cfg).run())
    if dimension == "3d":
        q_solver = float(result.Q_W)
        mdot_hot_actual = float(result.diagnostics["mass_flow_A_kg_s"])
        mdot_cold_actual = float(result.diagnostics["mass_flow_B_kg_s"])
    else:
        q_solver = float(result.Q_W) * CORE_DEPTH_M
        mdot_hot_actual = float(
            result.diagnostics["mass_flow_A_kg_s_per_m"]) * CORE_DEPTH_M
        mdot_cold_actual = float(
            result.diagnostics["mass_flow_B_kg_s_per_m"]) * CORE_DEPTH_M

    mdot_hot = float(hot["mdot"])
    mdot_cold = float(cold["mdot"])
    flow_err_hot = abs(mdot_hot_actual / mdot_hot - 1.0)
    flow_err_cold = abs(mdot_cold_actual / mdot_cold - 1.0)
    q_hot = abs(float(hot["Q_kW"])) * 1.0e3
    q_cold = abs(float(cold["Q_kW"])) * 1.0e3
    q_ref = 0.5 * (q_hot + q_cold)
    reference_ok = bool(_reference_valid(pd.DataFrame([hot, cold])).all())
    t_hot_out_exp = float(hot["Tout_C"]) + 273.15
    t_cold_out_exp = float(cold["Tout_C"]) + 273.15
    t_lo = min(cfg.fluid_A.T_in_K, cfg.fluid_B.T_in_K)
    t_hi = max(cfg.fluid_A.T_in_K, cfg.fluid_B.T_in_K)
    numerical_ok = bool(
        result.converged
        and flow_err_hot <= FLOW_REL_TOL
        and flow_err_cold <= FLOW_REL_TOL
        and result.residuals["mass_imbalance_rel_A"] <= 1.0e-6
        and result.residuals["mass_imbalance_rel_B"] <= 1.0e-6
        and result.residuals["enthalpy_imbalance_rel"] <= 0.05
        and math.isfinite(q_solver) and q_solver > 0.0
        and t_lo <= result.T_out_A_K <= t_hi
        and t_lo <= result.T_out_B_K <= t_hi
    )
    return {
        "topology": topology,
        "case": case,
        "dimension": dimension,
        "df_mode": result.metadata["darcy_forchheimer"]["mode"],
        "Pin_hot_gauge_MPa": float(hot["Pin_MPa"]),
        "Pout_hot_gauge_MPa": float(hot["Pout_MPa"]),
        "Pin_cold_gauge_MPa": float(cold["Pin_MPa"]),
        "Pout_cold_gauge_MPa": float(cold["Pout_MPa"]),
        "Pin_hot_abs_Pa": float(hot["Pin_abs_Pa"]),
        "Pout_hot_abs_Pa": float(hot["Pout_abs_Pa"]),
        "Pin_cold_abs_Pa": float(cold["Pin_abs_Pa"]),
        "Pout_cold_abs_Pa": float(cold["Pout_abs_Pa"]),
        "mdot_hot_exp_kg_s": mdot_hot,
        "mdot_hot_solver_kg_s": mdot_hot_actual,
        "flow_err_hot_rel": flow_err_hot,
        "mdot_cold_exp_kg_s": mdot_cold,
        "mdot_cold_solver_kg_s": mdot_cold_actual,
        "flow_err_cold_rel": flow_err_cold,
        "rho_hot_in_kg_m3": rho_hot,
        "rho_cold_in_kg_m3": rho_cold,
        "u_hot_solver_m_s": u_hot,
        "u_cold_solver_m_s": u_cold,
        "void_area_sheet_m2": float(df.attrs["A_flow_m2"]),
        "void_area_solver_m2": geo["void_area_m2"],
        "heat_area_sheet_m2": float(df.attrs["A_heat_m2"]),
        "heat_area_solver_m2": geo["heat_area_m2"],
        "Q_hot_exp_W": q_hot,
        "Q_cold_exp_W": q_cold,
        "Q_hot_signed_exp_W": float(hot["Q_kW"]) * 1.0e3,
        "Q_cold_signed_exp_W": float(cold["Q_kW"]) * 1.0e3,
        "Q_hot_cached_W": float(hot["Q_cached_kW"]) * 1.0e3,
        "Q_cold_cached_W": float(cold["Q_cached_kW"]) * 1.0e3,
        "HB_cached": float(hot["HB_cached"]),
        "HB": float(hot["HB"]),
        "ok_hb_cached": bool(hot["ok_hb_cached"]),
        "ok_hb": bool(hot["ok_hb"] and cold["ok_hb"]),
        "ok_done": bool(hot["ok_done"] and cold["ok_done"]),
        "ok_heat_flow": bool(hot["ok_heat_flow"] and cold["ok_heat_flow"]),
        "reference_ok": reference_ok,
        "Q_ref_W": q_ref,
        "Q_solver_W": q_solver,
        "Q_error_rel": q_solver / q_ref - 1.0,
        "Q_in_exp_band": min(q_hot, q_cold) <= q_solver <= max(q_hot, q_cold),
        "T_hot_out_exp_K": t_hot_out_exp,
        "T_hot_out_solver_K": float(result.T_out_A_K),
        "T_cold_out_exp_K": t_cold_out_exp,
        "T_cold_out_solver_K": float(result.T_out_B_K),
        "dP_hot_exp_Pa": float(hot["dP_MPa"]) * 1.0e6,
        "dP_hot_solver_Pa": float(result.dP_A_Pa),
        "dP_cold_exp_Pa": float(cold["dP_MPa"]) * 1.0e6,
        "dP_cold_solver_Pa": float(result.dP_B_Pa),
        "mass_imbalance_A_rel": float(
            result.residuals["mass_imbalance_rel_A"]),
        "mass_imbalance_B_rel": float(
            result.residuals["mass_imbalance_rel_B"]),
        "enthalpy_imbalance_rel": float(
            result.residuals["enthalpy_imbalance_rel"]),
        "converged": bool(result.converged),
        "numerical_ok": numerical_ok,
    }


def _print_geometry(topology: str, df: pd.DataFrame) -> None:
    geo = _solver_geometry(topology)
    area_flow = float(df.attrs["A_flow_m2"])
    area_heat = float(df.attrs["A_heat_m2"])
    print(
        f"{topology}: A_void sheet={area_flow:.9f}, "
        f"solver=(eps/2)A_gross={geo['void_area_m2']:.9f} m2 "
        f"({geo['void_area_m2'] / area_flow - 1.0:+.2%}); "
        f"A_heat sheet={area_heat:.6f}, solver=A0*V={geo['heat_area_m2']:.6f} "
        f"m2 ({geo['heat_area_m2'] / area_heat - 1.0:+.2%})"
    )


def _print_summary(results: pd.DataFrame) -> None:
    if results.empty:
        print("SUMMARY: no cases")
        return
    for (dimension, topology), group in results.groupby(
            ["dimension", "topology"], sort=False):
        err = _q_errors(group)
        outlet_errors = np.concatenate([
            group["T_hot_out_solver_K"].to_numpy(float)
            - group["T_hot_out_exp_K"].to_numpy(float),
            group["T_cold_out_solver_K"].to_numpy(float)
            - group["T_cold_out_exp_K"].to_numpy(float),
        ])
        print(
            f"SUMMARY {dimension} {topology}: n={len(group)}, "
            f"Q RMSRE={np.sqrt(np.mean(err**2)):.2%}, "
            f"median APE={np.median(np.abs(err)):.2%}, "
            f"P90 APE={np.quantile(np.abs(err), 0.9):.2%}, "
            f"bias={np.mean(err):+.2%}, "
            f"Q-band hit={group['Q_in_exp_band'].mean():.1%}, "
            f"Tout MAE={np.mean(np.abs(outlet_errors)):.2f} K"
        )


def _q_errors(group: pd.DataFrame) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (group["Q_solver_W"].to_numpy(float)
                / group["Q_ref_W"].to_numpy(float) - 1.0)


def _accept_q(results: pd.DataFrame, expected_cases: dict[str, list[int]],
              dimensions: list[str]) -> bool:
    """Check every preselected case, without filtering unsuccessful results."""
    expected = [(dim, topo, case) for dim in dimensions
                for topo, cases in expected_cases.items() for case in cases]
    actual = ([] if results.empty else list(results[
        ["dimension", "topology", "case"]].itertuples(index=False, name=None)))
    complete = bool(expected) and sorted(actual) == sorted(expected)
    accepted = complete
    for dimension in dimensions:
        for topology, cases in expected_cases.items():
            group = (results if results.empty else results[
                (results["dimension"] == dimension)
                & (results["topology"] == topology)])
            group_complete = (bool(cases) and not group.empty
                              and sorted(group["case"].tolist()) == sorted(cases))
            valid = group_complete
            rmsre = float("nan")
            if not group.empty:
                values = group[["Q_solver_W", "Q_ref_W"]].to_numpy(float)
                err = _q_errors(group)
                rmsre = float(np.sqrt(np.mean(err**2)))
                valid = bool(valid and np.isfinite(values).all()
                             and (values > 0.0).all()
                             and np.isfinite(err).all()
                             and group["numerical_ok"].eq(True).fillna(False).all()
                             and group["reference_ok"].eq(True).fillna(False).all())
            limit = Q_RMSRE_LIMITS[dimension][topology]
            # Only absorb floating-point roundoff at the inclusive boundary.
            passed = valid and (rmsre <= limit or math.isclose(
                rmsre, limit, rel_tol=1e-14, abs_tol=0.0))
            accepted = accepted and passed
            print(f"Q ACCEPT {dimension} {topology}: "
                  f"{'PASS' if passed else 'FAIL'}, n={len(group)}/{len(cases)}, "
                  f"complete={group_complete}, RMSRE={rmsre:.6%}, limit={limit:.0%}")
    print("Q verdict covers only the selected experiment/topology/dimension; "
          "it is not G1/G2 or full-core energy acceptance.")
    return bool(accepted)


def run(topologies: list[str], dimensions: list[str], *, case: int | None,
        all_valid: bool,
        fixed_cases: dict[str, list[int]] | None = None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    expected_cases: dict[str, list[int]] = {}
    ranges = {}
    references = {}
    for topology in topologies:
        df = load_exp(topology)
        _print_geometry(topology, df)
        cases = (fixed_cases[topology] if fixed_cases is not None else
                 _valid_case_numbers(df) if all_valid else
                 [case if case is not None else SMOKE_CASES[topology]])
        expected_cases[topology] = cases
        references[topology] = df.attrs["reference"]
        selected = df[df["case"].isin(cases)]
        ranges[topology] = {
            column: [float(selected[column].min()), float(selected[column].max())]
            for column in ("Tin_C", "Tout_C", "Pin_MPa", "Pout_MPa",
                           "Pin_abs_Pa", "Pout_abs_Pa", "mdot")
        } if cases else {}
        print(f"SELECTION {topology}: dimensions={dimensions}, cases={cases}, "
              f"ranges={ranges[topology]}")
        for case_no in cases:
            for dimension in dimensions:
                row = _run_case(topology, int(case_no), dimension, df)
                rows.append(row)
                print(
                    f"{topology} case {case_no:02d} {dimension}: "
                    f"mdot hot/cold err=({row['flow_err_hot_rel']:.2e}, "
                    f"{row['flow_err_cold_rel']:.2e}), "
                    f"Q={row['Q_solver_W']:.1f} W vs "
                    f"[{min(row['Q_hot_exp_W'], row['Q_cold_exp_W']):.1f}, "
                    f"{max(row['Q_hot_exp_W'], row['Q_cold_exp_W']):.1f}] W "
                    f"({row['Q_error_rel']:+.1%}), "
                    f"enthalpy={row['enthalpy_imbalance_rel']:.2%}, "
                    f"ok={row['numerical_ok']}, df_mode={row['df_mode']}"
                )
    result = pd.DataFrame(rows)
    result.attrs.update(expected_cases=expected_cases, ranges=ranges,
                        references=references)
    _print_summary(result)
    return result


def _read_manifest(path: Path, topologies: list[str]) -> dict[str, list[int]]:
    """Read the explicit member lists from a previous acceptance metadata file."""
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("case manifest must contain expected_cases")
    manifest = metadata["expected_cases"]
    if not isinstance(manifest, dict):
        raise ValueError("expected_cases must map topologies to case lists")
    selected = {}
    for topology in topologies:
        cases = manifest[topology]
        if (not isinstance(cases, list) or not cases
                or any(type(case) is not int or case <= 0 for case in cases)
                or len(cases) != len(set(cases))):
            raise ValueError(f"{topology}: expected unique positive integer case IDs")
        selected[topology] = cases
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", choices=("Diamond", "Gyroid"))
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", type=int)
    parser.add_argument("--dimension", choices=("2d", "3d", "both"),
                        default="both")
    selection.add_argument("--all-valid", action="store_true")
    selection.add_argument("--case-manifest", type=Path,
                           help="previous metadata JSON with fixed expected_cases")
    parser.add_argument("--accept-q", action="store_true",
                        help="require a fixed case manifest and per-group Q RMSRE limits")
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    if args.case is not None and args.topology is None:
        parser.error("--case requires --topology")
    if args.accept_q and args.case_manifest is None:
        parser.error("--accept-q requires --case-manifest; --all-valid is diagnostic only")

    topologies = [args.topology] if args.topology else ["Diamond", "Gyroid"]
    dimensions = (["2d", "3d"] if args.dimension == "both"
                  else [args.dimension])
    fixed_cases = None
    if args.case_manifest is not None:
        try:
            fixed_cases = _read_manifest(args.case_manifest, topologies)
        except (OSError, ValueError, KeyError) as exc:
            parser.error(str(exc))
    pin_path = REPO_ROOT / "data-revision.txt"
    metadata = {
        "script": str(Path(__file__).relative_to(REPO_ROOT)),
        "commit": _git_sha(short=False), "date": _iso_now(),
        "tracked_code_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT, text=True).strip()),
        "dataset": "data/raw_data/sCO2-Experient.xlsx",
        "sheets": [f"实验数据处理-{topo}" for topo in topologies],
        "recorded_data_pin": (pin_path.read_text(encoding="utf-8").strip()
                              if pin_path.exists() else None),
        "actual_data_revision": "unverified",
        "topologies": topologies, "dimensions": dimensions,
        "selection": ("fixed expected_cases from prior metadata; no quality-based reselection"
                      if fixed_cases is not None else
                      "all-valid: ok_done & ok_hb & ok_heat_flow, both sides Tin/Tout 280..700 K "
                      "and absolute Pin/Pout 7.9..16 MPa; no ok_dp/ok_dT exclusion"
                      if args.all_valid else "case/smoke diagnostic"),
        "case_manifest": str(args.case_manifest) if args.case_manifest is not None else None,
        "Q_definition": "Qref=0.5*(abs(Qhot)+abs(Qcold)); 2D Q and mdot * 0.042 m",
        "metrics": "e=Qsolver/Qref-1; RMSRE=sqrt(mean(e^2)); bias=mean(e)",
        "model": "production sCO2 Nu and D-F; no refit in this run; not a blind validation claim",
        "accept_q": args.accept_q,
    }
    print("RUN " + json.dumps(metadata))
    result = run(topologies, dimensions, case=args.case,
                 all_valid=args.all_valid, fixed_cases=fixed_cases)
    accepted = (_accept_q(result, result.attrs["expected_cases"], dimensions)
                if args.accept_q else
                not result.empty and bool(
                    result["numerical_ok"].eq(True).fillna(False).all()))
    metadata.update(result.attrs)
    metadata.update(df_modes=[] if result.empty else list(result["df_mode"].unique()),
                    exit_ok=accepted)
    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.csv, index=False, encoding="utf-8-sig")
        args.csv.with_suffix(args.csv.suffix + ".meta.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved: {args.csv.resolve()}")
    return int(not accepted)


if __name__ == "__main__":
    raise SystemExit(main())
