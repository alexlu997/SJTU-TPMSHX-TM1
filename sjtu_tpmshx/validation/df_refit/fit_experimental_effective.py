"""Evaluate frozen sCO2 corrections and rebuild other V3 D-F candidates.

Outputs under reports/df_refit are review artifacts, not runtime inputs.
No campaign is interpreted as fluid-intrinsic physics.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from sjtu_tpmshx.df_surrogate.experimental_correction import (
    correction_scale, hx_velocity_bounds)
from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2
from sjtu_tpmshx.df_surrogate.load_data import load_all
from sjtu_tpmshx.validation.hx_experiments import (
    A_FLOW, L_FLOW, P_ATM, R_AIR, air_mu, load_air_cases, load_water_cases)
from sjtu_tpmshx.validation.sco2_exp.load_sco2_exp import load_exp
from sjtu_tpmshx.models.tpms_props import water_density, water_viscosity


_REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = _REPO / "reports" / "df_refit"
RMSRE_GATE = 0.10
BIAS_GATE = 0.10


def _fit_sf(darcy: np.ndarray, forch_base: np.ndarray,
            measured: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    a = forch_base / measured
    b = (measured - darcy) / measured
    sf = float(a @ b / (a @ a))
    err = (darcy + sf * forch_base) / measured - 1.0
    return sf, float(np.sqrt(np.mean(err * err))), float(err.mean()), err


def fit_air() -> tuple[pd.DataFrame, list[tuple[str, str, float, float, float]]]:
    rows: list[dict[str, object]] = []
    shared: list[tuple[str, str, float, float, float]] = []
    data = load_all()
    for (tp, L, t), g in data.groupby(["tpms", "L_mm", "t_mm"]):
        status = "approved" if L in (6.0, 8.0) else "high_uncertainty"
        K0, cF0 = FullCore3CellFixedDFV2(tp).predict(float(L), float(t))
        length = 10.0 * float(L) * 1e-3
        darcy = g.mu.to_numpy(float) * g.u_mps.to_numpy(float) / K0 * length
        forch = (g.rho.to_numpy(float) * cF0
                 * g.u_mps.to_numpy(float) ** 2 * length)
        measured = g.dP_Pa.to_numpy(float)
        sf, rmsre, bias, _ = _fit_sf(darcy, forch, measured)
        packaged = np.nan
        if status == "approved":
            _, packaged, _, _ = correction_scale(tp, "air", L, t)
            packaged = float(np.asarray(packaged))
            shared.extend(("air", tp, d, f, y)
                          for d, f, y in zip(darcy, forch, measured))
        rows.append(dict(
            fluid="air", topology=tp, L_mm=L, t_mm=t, sK=1.0, sF=sf,
            packaged_sF=packaged, n=len(g), rmsre=rmsre, bias=bias,
            darcy_fraction_median=float(np.median(darcy / measured)),
            identifiability="K weak; fixed at CFD K0",
            source='experiments/air/air_DG_specimen_experiment_summary.xlsx',
            filter="L8 Re>=1600" if L == 8.0 else "original valid rows",
            status=status, scope="core-calibrated"))
    return pd.DataFrame(rows), shared


def evaluate_sco2() -> tuple[pd.DataFrame, list[tuple[str, str, float, float, float]]]:
    """Check the existing sF at corrected experiment pressure without refitting."""
    from CoolProp.CoolProp import PropsSI

    rows: list[dict[str, object]] = []
    shared: list[tuple[str, str, float, float, float]] = []
    for tp in ("Diamond", "Gyroid"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = load_exp(tp)
        A = float(raw.attrs["A_flow_m2"])
        length = float(raw.attrs["L_ch_m"])
        hot = raw[raw.side == "hot"]
        g = hot[hot.ok_dp]
        K0, cF0 = FullCore3CellFixedDFV2(tp).predict(7.0, 0.6)
        u = g.mdot.to_numpy(float) / (g.rho.to_numpy(float) * A)
        rho_in = PropsSI(
            "D", "T", g.Tin_C.to_numpy(float) + 273.15,
            "P", g.Pin_abs_Pa.to_numpy(float), "CO2")
        u_in = g.mdot.to_numpy(float) / (np.asarray(rho_in) * A)
        u_lo, u_hi = hx_velocity_bounds("sco2", tp)
        if not (np.isclose(u_in.min(), u_lo, rtol=0.0, atol=1e-12)
                and np.isclose(u_in.max(), u_hi, rtol=0.0, atol=1e-12)):
            raise RuntimeError(f"{tp}: reviewed sCO2 velocity window drifted")
        darcy = g.mu.to_numpy(float) * u / K0 * length
        forch = g.rho.to_numpy(float) * cF0 * u * u * length
        measured = g.dP_MPa.to_numpy(float) * 1e6
        _, packaged, _, _ = correction_scale(
            tp, "sco2", 7.0, 0.6, float(np.median(u_in)))
        sf = float(np.asarray(packaged))
        error = (darcy + sf * forch) / measured - 1.0
        rmsre, bias = float(np.sqrt(np.mean(error * error))), float(error.mean())
        shared.extend(("sco2", tp, d, f, y)
                      for d, f, y in zip(darcy, forch, measured))
        rows.append(dict(
            fluid="sco2", topology=tp, L_mm=7.0, t_mm=0.6,
            sK=1.0, sF=sf, packaged_sF=sf, n=len(g),
            rmsre=rmsre, bias=bias,
            darcy_fraction_median=float(np.median(darcy / measured)),
            identifiability="K unidentifiable; fixed at CFD K0",
            source='experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx',
            filter=("hot side & ok_dp; require "
                    f"{u_lo:.6g}<=u_in<={u_hi:.6g} m/s"),
            status="approved", scope="HX-effective",
            n_total=len(hot), n_excluded=int((~hot.ok_dp).sum()),
            n_outside_scope=0,
            excluded_cases=";".join(
                hot.loc[~hot.ok_dp, "case"].astype(str)),
            outside_scope_cases="",
            A_flow_m2=A, L_flow_m=length,
            u_min_mps=u_lo, u_max_mps=u_hi,
            campaign="sco2-hx-hot-ok-dp",
            evaluation="frozen sF; corrected absolute pressure; no refit"))
    return pd.DataFrame(rows), shared


def _quality_reason(row: pd.Series) -> str:
    reasons = []
    if bool(row.get("dp_nonphysical", False)):
        reasons.append("dp_nonphysical")
    if bool(row.get("dp_floor", False)):
        reasons.append("dp_floor")
    if bool(row.get("dup_row", False)):
        reasons.append("duplicate_row")
    return ";".join(reasons) if reasons else "included"


def fit_water_hx() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit fixed-K0 water in the reviewed high-velocity campaign window."""
    summaries, quality = [], []
    for tp in ("Diamond", "Gyroid"):
        K0, cF0 = FullCore3CellFixedDFV2(tp).predict(7.0, 0.6)
        raw = load_water_cases(tp)
        quality_valid = ~(raw.dp_nonphysical | raw.dup_row)
        T = (0.5 * (raw["水进口温度/℃"].to_numpy(float)
                    + raw["水出口温度/℃"].to_numpy(float)) + 273.15)
        from sjtu_tpmshx.models.fluid_props import check_water_state
        check_water_state('water', T,
                          0.5 * (raw.water_P_in_abs_Pa + raw.water_P_out_abs_Pa),
                          where='water HX mean properties')
        rho = np.asarray(water_density(T), dtype=float)
        mu = np.asarray(water_viscosity(T), dtype=float)
        mdot = raw["样机水流量kg/s"].to_numpy(float)
        u = mdot / (rho * A_FLOW[tp])
        u_lo, u_hi = hx_velocity_bounds("water", tp)
        included = quality_valid & (u >= u_lo) & (u <= u_hi)
        darcy = mu * u / K0 * L_FLOW
        forch = rho * cF0 * u * u * L_FLOW
        measured = raw["水侧压差/Pa"].to_numpy(float)
        sF, rmsre, bias, _ = _fit_sf(
            darcy[included], forch[included], measured[included])
        predicted = darcy + sF * forch
        passed = rmsre <= RMSRE_GATE and abs(bias) <= BIAS_GATE
        _, packaged, _, _ = correction_scale(
            tp, "water", 7.0, 0.6, 0.5 * (u_lo + u_hi))
        excluded = [
            f"{r.case}:{_quality_reason(r)}"
            for _, r in raw.loc[~quality_valid].iterrows()
        ]
        outside = raw.loc[quality_valid & ~included, "case"].astype(str).tolist()
        summaries.append(dict(
            fluid="water", topology=tp, L_mm=7.0, t_mm=0.6,
            sK=1.0, sF=sF, packaged_sF=float(np.asarray(packaged)),
            n=int(included.sum()), n_total=len(raw),
            n_excluded=int((~quality_valid).sum()),
            n_outside_scope=int((quality_valid & ~included).sum()),
            excluded_cases=";".join(excluded),
            outside_scope_cases=";".join(outside), rmsre=rmsre, bias=bias,
            darcy_fraction_median=float(np.median(
                darcy[included] / predicted[included])),
            identifiability="K fixed at production CFD K0",
            source='experiments/water_air/water-air_DG7-t0p6_hx_water-dp_with-air-temperature.xlsx',
            filter=("exclude dp_nonphysical and duplicate_row; fit only "
                    f"{u_lo:.6g}<=u<={u_hi:.6g} m/s"),
            A_flow_m2=A_FLOW[tp], L_flow_m=L_FLOW,
            u_min_mps=u_lo, u_max_mps=u_hi,
            status="approved" if passed else "rejected_accuracy_gate",
            scope="HX-effective", campaign="water-air-hx-7-6"))
        for i, (_, row) in enumerate(raw.iterrows()):
            reason = _quality_reason(row)
            if quality_valid.iloc[i] and not included.iloc[i]:
                reason = "outside_velocity_window"
            quality.append(dict(
                topology=tp, case=str(row.case), included=bool(included.iloc[i]),
                quality_valid=bool(quality_valid.iloc[i]),
                exclusion_reason=reason,
                measured_dP_Pa=measured[i], predicted_dP_Pa=predicted[i],
                relative_error=(predicted[i] / measured[i] - 1.0
                                if quality_valid.iloc[i] else np.nan),
                mdot_kg_s=mdot[i], u_mps=u[i],
                u_min_mps=u_lo, u_max_mps=u_hi,
                A_flow_m2=A_FLOW[tp], L_flow_m=L_FLOW,
                dp_nonphysical=bool(row.dp_nonphysical),
                duplicate_row=bool(row.dup_row)))
    return pd.DataFrame(summaries), pd.DataFrame(quality)


def fit_air_hx() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit the matching compressible air side of the water+air HX campaign."""
    summaries, quality = [], []
    for tp in ("Diamond", "Gyroid"):
        K0, cF0 = FullCore3CellFixedDFV2(tp).predict(7.0, 0.6)
        raw = load_air_cases(tp)
        included = ~(raw.dp_floor | raw.dup_row)
        g = raw.loc[included]
        G = g["样机空气流量kg/s"].to_numpy(float) / A_FLOW[tp]
        T_bar = (0.5 * (g["空气进口温度/℃"].to_numpy(float)
                        + g["空气出口温度/℃"].to_numpy(float)) + 273.15)
        P_in = P_ATM + g["空气进口压力/Pa"].to_numpy(float)
        T_in = g["空气进口温度/℃"].to_numpy(float) + 273.15
        u_in = G * R_AIR * T_in / P_in
        u_lo, u_hi = hx_velocity_bounds("air", tp)
        if np.any((u_in < u_lo - 1e-12) | (u_in > u_hi + 1e-12)):
            raise RuntimeError(f"{tp}: reviewed HX-air velocity window drifted")
        measured = (g["空气进口压力/Pa"].to_numpy(float)
                    - g["空气出口压力/Pa"].to_numpy(float))
        mu = np.array([air_mu(T) for T in T_bar])
        darcy = mu * G / K0
        forch = cF0 * G * G
        upper = float(np.min(
            (P_in * P_in / (2.0 * R_AIR * T_bar * L_FLOW) - darcy)
            / forch) * (1.0 - 1e-12))

        def loss(sF: float) -> float:
            P_out_sq = (P_in * P_in - 2.0 * R_AIR * T_bar * L_FLOW
                        * (darcy + sF * forch))
            error = (P_in - np.sqrt(P_out_sq)) / measured - 1.0
            return float(np.mean(error * error))

        fit = minimize_scalar(loss, bounds=(0.0, upper), method="bounded",
                              options={"xatol": 1e-12})
        if not fit.success:
            raise RuntimeError(f"{tp}: matching HX air sF fit failed")
        sF = float(fit.x)
        P_out_sq = (P_in * P_in - 2.0 * R_AIR * T_bar * L_FLOW
                    * (darcy + sF * forch))
        predicted = P_in - np.sqrt(P_out_sq)
        error = predicted / measured - 1.0
        rmsre = float(np.sqrt(np.mean(error * error)))
        bias = float(error.mean())
        passed = rmsre <= RMSRE_GATE and abs(bias) <= BIAS_GATE
        _, packaged, campaign, _ = correction_scale(
            tp, "air", 7.0, 0.6, float(np.median(u_in)))
        excluded = [
            f"{r.case}:{_quality_reason(r)}"
            for _, r in raw.loc[~included].iterrows()
        ]
        summaries.append(dict(
            fluid="air", topology=tp, L_mm=7.0, t_mm=0.6,
            sK=1.0, sF=sF, packaged_sF=float(np.asarray(packaged)),
            n=int(included.sum()), n_total=len(raw),
            n_excluded=int((~included).sum()),
            excluded_cases=";".join(excluded), rmsre=rmsre, bias=bias,
            darcy_fraction_median=float(np.median(
                darcy / (darcy + sF * forch))),
            identifiability="K fixed at production CFD K0",
            source=raw.attrs["source"], sheet=raw.attrs["sheet"],
            excel_rows=";".join(g.excel_row.astype(str)),
            filter=("exclude dp_floor and duplicate_row; require "
                    f"{u_lo:.6g}<=u<={u_hi:.6g} m/s"),
            A_flow_m2=A_FLOW[tp], L_flow_m=L_FLOW,
            u_min_mps=u_lo, u_max_mps=u_hi,
            status="approved" if passed else "rejected_accuracy_gate",
            scope="HX-effective", campaign=campaign))
        valid_i = iter(u_in)
        for i, (_, row) in enumerate(raw.iterrows()):
            row_u = next(valid_i) if included.iloc[i] else np.nan
            quality.append(dict(
                topology=tp, case=str(row.case), included=bool(included.iloc[i]),
                source=raw.attrs["source"], sheet=raw.attrs["sheet"],
                excel_row=int(row.excel_row),
                exclusion_reason=_quality_reason(row),
                u_mps=row_u, u_min_mps=u_lo, u_max_mps=u_hi,
                dp_floor=bool(row.dp_floor), duplicate_row=bool(row.dup_row)))
    return pd.DataFrame(summaries), pd.DataFrame(quality)


def shared_counterexample(records: list[tuple[str, str, float, float, float]]) -> pd.DataFrame:
    darcy = np.array([r[2] for r in records])
    forch = np.array([r[3] for r in records])
    measured = np.array([r[4] for r in records])
    sf, rmsre, bias, _ = _fit_sf(darcy, forch, measured)
    sco2 = np.array([r[0] == "sco2" for r in records])
    e_sco2 = (darcy[sco2] + sf * forch[sco2]) / measured[sco2] - 1.0
    return pd.DataFrame([dict(
        model="forced_single_sF_air_plus_sco2", sF=sf, n=len(records),
        rmsre=rmsre, bias=bias, sco2_bias=float(e_sco2.mean()),
        verdict="rejected: campaign/system effects cannot be shared")])


def main() -> int:
    air, a_records = fit_air()
    sco2, s_records = evaluate_sco2()
    water_hx, water_quality = fit_water_hx()
    air_hx, air_quality = fit_air_hx()
    if not (water_hx.status == "approved").all():
        blocked = air_hx.status == "approved"
        air_hx.loc[blocked, "status"] = "evidence_pass_companion_blocked"
        air_hx.loc[blocked, "packaged_sF"] = np.nan
    candidates = pd.concat([air, sco2, water_hx, air_hx], ignore_index=True)
    packaged = candidates[candidates.packaged_sF.notna()]
    if not np.allclose(packaged.sF, packaged.packaged_sF,
                       rtol=0, atol=1e-12):
        raise RuntimeError("packaged correction values do not match the current refit")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(REPORT_DIR / "experimental_effective_candidates.csv",
                      index=False, encoding="utf-8-sig")
    water_quality.to_csv(
        REPORT_DIR / "experimental_effective_water_quality.csv",
        index=False, encoding="utf-8-sig")
    air_quality.to_csv(
        REPORT_DIR / "experimental_effective_hx_air_quality.csv",
        index=False, encoding="utf-8-sig")
    counter = shared_counterexample(a_records + s_records)
    counter.to_csv(REPORT_DIR / "experimental_effective_shared_rejected.csv",
                   index=False, encoding="utf-8-sig")
    print(candidates[["fluid", "topology", "L_mm", "t_mm", "n", "sF",
                      "rmsre", "bias", "status", "scope"]].to_string(index=False))
    if not (water_hx.status == "approved").all():
        print("\nWater failed the fixed 10% accuracy gate; neither water nor "
              "its matching HX-air companion is packaged for production.")
    print("\nRejected shared fit:\n" + counter.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
