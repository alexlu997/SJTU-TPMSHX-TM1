"""Shanghai 2D validation through the current public pipeline.

Both fluid fields are solved with the confirmed staggered water ports.
The retired frozen-water loop and its original scores remain at Git 8423bf4.
Current outputs are separate from those historical references. Q_sim retains
its labelled measured-flow/cp(T_in) reduction; Q_native records current W/m.
This entry reports experiment differences but has no accuracy threshold.
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from sjtu_tpmshx.models.tpms_calc import air_cp
from sjtu_tpmshx.validation.harness._harness import load_cases_df
from sjtu_tpmshx.validation.harness._case_sets import SHANGHAI_XLSX, SHANGHAI_N_CASES
from sjtu_tpmshx.validation.harness._provenance import (
    output_directory, output_path, write_csv_with_provenance,
)


def _pipeline_config(ci, df):
    from sjtu_tpmshx.domain.compute_config import SolverConfig
    from sjtu_tpmshx.models.grid import SHANGHAI_GRID_2D
    from sjtu_tpmshx.validation.harness._case_sets import shanghai_pipeline_config
    nx, ny, nz = SHANGHAI_GRID_2D
    return shanghai_pipeline_config(ci, df, SolverConfig(Nx=nx, Ny=ny, Nz=nz),
                                    port_wall_refine=True)


def _run_one_case_pipeline(ci, df):
    """Run current Pipeline2D, retaining the explicitly named legacy Q reduction."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    cc = _pipeline_config(ci, df)
    case = ci + 1
    m_air = float(df.iloc[ci, 5])
    u_A, u_B = cc.fluid_A.u_mps, cc.fluid_B.u_mps
    T_Ain_K, T_Bin_K = cc.fluid_A.T_in_K, cc.fluid_B.T_in_K
    P_Ain = cc.fluid_A.P_in_Pa
    dP_A_exp = float(df.iloc[ci, 30]) - float(df.iloc[ci, 31])
    Q_exp = float(df.iloc[ci, 33])
    res = Pipeline2D(cc).run()

    dP_A_sim = float(res.dP_A_Pa)

    # Q via the AIR-SIDE ENTHALPY BALANCE, using measured total mass flow. This legacy comparison definition
    # remains separate from native boundary Q per metre.
    #
    # Do NOT use `res.Q_W` here. The 2D pipeline's Q is a domain integral over a
    # 2D cell AREA (`solve_2d.py`: `cell_area = dx * dy`, and h_v is W/(m³·K)),
    # so it is **W per metre of depth**, not watts — the 2D model has no third
    # dimension. Converting it would need the machine depth (for Shanghai,
    # Lz = 0.042 m: 60 737 W/m x 0.042 m = 2551 W vs the measured 2514 W, which
    # is how this was diagnosed). The enthalpy balance sidesteps the whole
    # question because `m_air` is the measured TOTAL mass flow.
    cp_A0 = float(air_cp(T_Ain_K))
    Q_sim = float(m_air * cp_A0 * (T_Ain_K - float(res.T_out_A_K)))

    err_dP = ((dP_A_sim - dP_A_exp) / dP_A_exp * 100
              if dP_A_exp != 0 else float('nan'))
    err_Q = (Q_sim - Q_exp) / Q_exp * 100 if Q_exp != 0 else float('nan')

    d = res.diagnostics or {}
    cd = d.get('convergence_detail') or {}
    if res.warnings:
        print(f"  [case {case}] pipeline warnings: "
              f"{'; '.join(str(w) for w in res.warnings)}")

    return {
        'Case': case, 'u_air': round(u_A, 2), 'u_water': round(u_B, 4),
        'T_air_in': round(T_Ain_K - 273.15, 1),
        'T_water_in': round(T_Bin_K - 273.15, 1),
        'P_in_abs_kPa': round(P_Ain / 1000.0, 1),
        'dP_air_exp': round(dP_A_exp), 'dP_air_sim': round(dP_A_sim),
        'err_dP%': round(err_dP, 1),
        'Q_exp': round(Q_exp, 1), 'Q_sim': round(Q_sim, 1),
        'Q_native': float(res.Q_W), 'Q_native_unit': 'W/m',
        'Q_legacy_definition': 'measured m_air * cp(T_in) * (T_in - T_out)',
        **{'grid_n' + axis: len(res.fields['d' + axis + '_arr']) for axis in 'xy'},
        'err_Q%': round(err_Q, 1),
        'Q_enthalpy_A': round(Q_sim, 1), 'Q_total_max': round(abs(Q_sim), 1),
        'outer_iters': int(cd.get('outer_iters', -1)),
        'converged': bool(res.converged),
        # 2D water-side outputs the frozen runner could not produce at all.
        'dP_B_sim': float(res.dP_B_Pa),
        'T_water_out_sim': float(res.T_out_B_K) - 273.15,
        'T_water_out_exp': float(df.iloc[ci, 25]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out-dir', help='New run directory; defaults under .cache/validation')
    args = parser.parse_args(argv)
    try:
        out_dir = output_directory('shanghai_2d', args.out_dir)
        path = output_path(out_dir / 'shanghai_validation_aligned.csv')
    except ValueError as exc:
        parser.error(str(exc))
    df = load_cases_df(SHANGHAI_XLSX)
    rows = []
    for index in range(SHANGHAI_N_CASES):
        try:
            row = _run_one_case_pipeline(index, df)
        except Exception as exc:
            row = dict(Case=index + 1, converged=False, error=f'{type(exc).__name__}: {exc}',
                       **{'err_dP%': np.nan, 'err_Q%': np.nan})
        rows.append(row)
        print(f"Case {index + 1}: {row}")
    out = pd.DataFrame(rows)
    write_csv_with_provenance(out, path, __file__)
    errors = out[['err_dP%', 'err_Q%']].to_numpy(dtype=float)
    rms = np.sqrt(np.mean(errors ** 2, axis=0))
    print(f'RMSRE_dP={rms[0]:.2f}%; RMSRE_Q={rms[1]:.2f}% (reported, no accuracy gate)')
    print(f'Saved: {path}')
    return 0 if np.isfinite(errors).all() and out['converged'].all() else 1


if __name__ == '__main__':
    raise SystemExit(main())
