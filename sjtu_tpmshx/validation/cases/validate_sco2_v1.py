"""sCO2 V1 gate: fixed-CFD pressure loss plus 2D/3D conservation."""

from __future__ import annotations

import sys

import numpy as np

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import (
    FullCore3CellFixedDFV2,
)
from sjtu_tpmshx.df_surrogate.load_sco2_cfd import load_core
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig,
    FluidConfig,
    GeometryConfig,
    PartialBCConfig,
    SolverConfig,
)


def _fixed_dp(row, model) -> float:
    K, cF = model.predict(row.L_mm, row.t_mm)
    dpdl = row.mu_Pa_s * row.Um_m_s / K \
        + row.rho_kg_m3 * cF * row.Um_m_s**2
    return float(dpdl * row.core_length_m)


def _cfd_check() -> tuple[dict, object]:
    metrics = {}
    selected = None
    for topology, limit in (("Diamond", 20.0), ("Gyroid", 15.0)):
        data = load_core(topology)
        model = FullCore3CellFixedDFV2(topology)
        predicted = np.array([_fixed_dp(row, model)
                              for row in data.itertuples()])
        relative = (predicted - data["dp_core_Pa"].to_numpy()) \
            / data["dp_core_Pa"].to_numpy()
        rmsre = float(np.sqrt(np.mean(relative**2)))
        bias = float(np.mean(relative))
        metrics[topology] = {"rmsre": rmsre, "bias": bias, "limit": limit / 100}
        if topology == "Diamond":
            candidates = data[
                (data["geometry_id"] == "D_7_6")
                & (data["P_MPa"] == 12.0)
                & (data["dT_pc"] == 2.0)
            ]
            selected = min(candidates.itertuples(),
                           key=lambda row: abs(row.Re - 10080.0))
    if selected is None:
        raise RuntimeError("D_7_6 12 MPa CFD validation point is missing")
    return metrics, selected


def _config(nz: int, cold_velocity: float, cold_temperature: float) -> ComputeConfig:
    return ComputeConfig(
        fluid_A=FluidConfig(type="sco2", u_mps=0.8, T_in_K=500.0,
                            P_in_Pa=12.0e6),
        fluid_B=FluidConfig(type="sco2", u_mps=cold_velocity,
                            T_in_K=cold_temperature, P_in_Pa=12.0e6),
        geometry=GeometryConfig(
            tpms="Diamond", L_cell_mm=7.0, t_wall_mm=0.6,
            k_s_W_mK=16.0, L_dom_m=0.021, H_dom_m=0.021,
            Lz_m=0.021 if nz > 1 else None,
        ),
        solver=SolverConfig(Nx=24, Ny=20, Nz=nz),
        bc_A=PartialBCConfig(dir=0),
        bc_B=PartialBCConfig(dir=1),
    )


def run_validation() -> dict:
    cfd, point = _cfd_check()
    model = FullCore3CellFixedDFV2("Diamond")
    fixed_point_dp = _fixed_dp(point, model)
    fixed_point_error = abs(fixed_point_dp / point.dp_core_Pa - 1.0)

    result_2d = Pipeline2D(_config(1, point.Um_m_s, point.Tref)).run()
    result_3d = Pipeline3D(_config(4, point.Um_m_s, point.Tref)).run()
    depth = 0.021
    q_2d = result_2d.Q_W * depth
    q_3d = result_3d.Q_W

    def _relative(a, b):
        return abs(a - b) / max(abs(a), abs(b), 1e-30)

    parity = {
        "Q": _relative(q_2d, q_3d),
        "dP_A": _relative(result_2d.dP_A_Pa, result_3d.dP_A_Pa),
        "dP_B": _relative(result_2d.dP_B_Pa, result_3d.dP_B_Pa),
    }
    q_definition_error = _relative(
        result_2d.Q_W, abs(result_2d.residuals["Q_A"]))
    cold_dp_errors = {
        "2D": abs(result_2d.dP_B_Pa / point.dp_core_Pa - 1.0),
        "3D": abs(result_3d.dP_B_Pa / point.dp_core_Pa - 1.0),
    }

    print("sCO2 V1 validation")
    for topology, metric in cfd.items():
        print(f"  {topology:7s} CFD: RMSRE={metric['rmsre']:.2%}, "
              f"bias={metric['bias']:+.2%}")
    print(f"  selected CFD: D_7_6, 12 MPa, T={point.Tref:.2f} K, "
          f"Re={point.Re:.0f}, dP={point.dp_core_Pa:.3f} Pa")
    print(f"  fixed D-F: dP={fixed_point_dp:.3f} Pa, "
          f"error={fixed_point_error:.2%}")
    for label, result, q in (("2D", result_2d, q_2d),
                             ("3D", result_3d, q_3d)):
        print(f"  {label}: Q={q:.3f} W, dP_A={result.dP_A_Pa:.3f} Pa, "
              f"dP_B={result.dP_B_Pa:.3f} Pa, "
              f"mass=({result.residuals['mass_imbalance_rel_A']:.2e}, "
              f"{result.residuals['mass_imbalance_rel_B']:.2e}), "
              f"enthalpy={result.residuals['enthalpy_imbalance_rel']:.2%}, "
              f"converged={result.converged}")
    print(f"  2D/3D parity: Q={parity['Q']:.2%}, "
          f"dP_A={parity['dP_A']:.2%}, dP_B={parity['dP_B']:.2%}")

    gated_values = [
        fixed_point_error, q_definition_error,
        *cold_dp_errors.values(), *parity.values(),
        *(value for metric in cfd.values()
          for value in (metric["rmsre"], metric["bias"])),
    ]
    failed = not np.isfinite(gated_values).all()
    failed |= any(
        metric["rmsre"] > metric["limit"] or abs(metric["bias"]) > 0.02
        for metric in cfd.values()
    )
    failed |= fixed_point_error > 0.15
    failed |= any(not result.converged for result in (result_2d, result_3d))
    failed |= any(
        not np.isfinite(result.residuals[key])
        or result.residuals[key] > limit
        for result in (result_2d, result_3d)
        for key, limit in (
            ("mass_imbalance_rel_A", 1e-6),
            ("mass_imbalance_rel_B", 1e-6),
            ("enthalpy_imbalance_rel", 0.05),
        )
    )
    failed |= any(error > 0.20 for error in cold_dp_errors.values())
    failed |= q_definition_error > 1e-12
    failed |= parity["Q"] > 0.05
    failed |= any(parity[key] > 0.10 for key in ("dP_A", "dP_B"))
    print(f"GATE {'FAIL' if failed else 'PASS'}")
    return {
        "passed": not failed,
        "cfd": cfd,
        "fixed_point_error": fixed_point_error,
        "cold_dp_errors": cold_dp_errors,
        "parity": parity,
        "q_definition_error": q_definition_error,
        "result_2d": result_2d,
        "result_3d": result_3d,
    }


def main() -> int:
    return int(not run_validation()["passed"])


if __name__ == "__main__":
    sys.exit(main())
