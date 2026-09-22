"""
optimization/export_ntop_csv.py — Convert a Pareto solution into nTop-ready
ScalarField CSVs for graded-TPMS body construction.

nTop's "Scalar Field from Grid Data" block ingests a CSV with one column for
each spatial coordinate plus one column for the scalar value. We emit two
CSV files per Pareto pick — one for the cell-size scalar field L(x, y), one
for the wall-thickness field t(x, y) — sampled on a dense regular grid that
covers the HX's (L_domain × H_domain) footprint.

Geometric assumptions (must match the optimizer cfg):
  * (x, y) origin at HX corner; +x = fluid A streamwise, +y = fluid B
    streamwise; depth (z) is uniform — nTop replicates the (x, y) field along
    z when building the lattice
  * Output coordinates in **millimeters** so nTop's default mm units consume
    them natively
  * L_field, t_field values are clamped to [4, 8] mm × [0.3, 0.6] mm — the
    configured geometry window, which also bounds the optimizer (path A in
    the planning history)

CLI usage::

    python -m sjtu_tpmshx.optimization.export_ntop_csv \\
        --pareto opt_runs/production_v1/pareto_final.csv \\
        --config opt_runs/production_v1/config.json \\
        --row    7 \\
        --out    nTop_inputs/case_7 \\
        --grid   100 50

Or invoke the function programmatically::

    from sjtu_tpmshx.optimization.export_ntop_csv import export_decision_vector
    export_decision_vector(x_decision, out_dir='nTop_inputs/best_Q',
                           Nx_export=100, Ny_export=50)

The output directory will contain ``Lfield.csv``, ``tfield.csv``, and a
``provenance.json`` recording the decision vector, cfg, and field statistics
for traceability back to the source Pareto solution.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Optional

import numpy as np

from sjtu_tpmshx.models.continuous_field import (
    DEFAULT_L_BOUNDS,
    DEFAULT_N_CTRL_X,
    DEFAULT_N_CTRL_Y,
    DEFAULT_SYMMETRIC_Y,
    DEFAULT_T_BOUNDS,
)
from sjtu_tpmshx.models.screening import build_field, FIELD_CONFIG_KEYS
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


# ─── Defaults ───────────────────────────────────────────────────────


DEFAULT_GRID_NX = 100        # cells along x_real (fluid A streamwise)
DEFAULT_GRID_NY = 50         # cells along y_real (fluid B streamwise)
DEFAULT_L_DOMAIN_M = 0.10    # m
DEFAULT_H_DOMAIN_M = 0.05    # m
DEFAULT_TPMS = 'Diamond'
DEFAULT_KS = 17.0


# ─── Core conversion ────────────────────────────────────────────────


def _write_scalar_field_csv(path: str,
                             xc_mm: np.ndarray,
                             yc_mm: np.ndarray,
                             field: np.ndarray,
                             value_name: str) -> None:
    """Write a (Nx · Ny, 3) CSV with columns [x_mm, y_mm, value].

    Row order: outer loop on y, inner loop on x. nTop's ScalarField from
    Grid Data block accepts this ordering when both axes are listed
    monotonically — empirically robust across nTop 4.x and 5.x.
    """
    Nx = xc_mm.size; Ny = yc_mm.size
    assert field.shape == (Nx, Ny), \
        f"field shape {field.shape} != ({Nx}, {Ny})"
    rows = []
    for j in range(Ny):
        for i in range(Nx):
            rows.append([xc_mm[i], yc_mm[j], field[i, j]])
    arr = np.asarray(rows, dtype=np.float64)
    np.savetxt(path, arr, delimiter=',',
               header=f"x_mm,y_mm,{value_name}", comments='', fmt='%.6f')


# ─── Public API ─────────────────────────────────────────────────────


def export_decision_vector(x_decision: np.ndarray,
                           out_dir: str,
                           *,
                           Nx_export: int = DEFAULT_GRID_NX,
                           Ny_export: int = DEFAULT_GRID_NY,
                           L_domain_m: float = DEFAULT_L_DOMAIN_M,
                           H_domain_m: float = DEFAULT_H_DOMAIN_M,
                           tpms_type: str = DEFAULT_TPMS,
                           k_s: float = DEFAULT_KS,
                           n_ctrl_x: int = DEFAULT_N_CTRL_X,
                           n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                           symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                           L_bounds: tuple = DEFAULT_L_BOUNDS,
                           t_bounds: tuple = DEFAULT_T_BOUNDS,
                           spline_order: int = 3,
                           extra_metadata: Optional[dict] = None) -> dict:
    """Export L(x, y) + t(x, y) CSVs + provenance JSON for one Pareto pick.

    Returns a dict with the field summary statistics + paths so callers
    (UI, batch scripts) can log the export back to the user.
    """
    os.makedirs(out_dir, exist_ok=True)

    cfg = dict(tpms_type=tpms_type, k_s=k_s, L_domain=L_domain_m, H_domain=H_domain_m,
               n_ctrl_x=n_ctrl_x, n_ctrl_y=n_ctrl_y, symmetric_y=symmetric_y,
               L_bounds=L_bounds, t_bounds=t_bounds, spline_order=spline_order)
    fc = build_field(x_decision, cfg)
    L_field, t_field = fc.evaluate_grid(Nx_export, Ny_export)
    xc_mm = (np.arange(Nx_export) + .5) * L_domain_m / Nx_export * 1000.
    yc_mm = (np.arange(Ny_export) + .5) * H_domain_m / Ny_export * 1000.

    L_path = os.path.join(out_dir, 'Lfield.csv')
    t_path = os.path.join(out_dir, 'tfield.csv')
    _write_scalar_field_csv(L_path, xc_mm, yc_mm, L_field, value_name='L_mm')
    _write_scalar_field_csv(t_path, xc_mm, yc_mm, t_field, value_name='t_mm')

    summary = {
        'Nx_export':   int(Nx_export),
        'Ny_export':   int(Ny_export),
        'L_domain_mm': float(L_domain_m * 1.0e3),
        'H_domain_mm': float(H_domain_m * 1.0e3),
        'tpms_type':   tpms_type,
        'L_min_mm':    float(L_field.min()),
        'L_max_mm':    float(L_field.max()),
        'L_avg_mm':    float(L_field.mean()),
        't_min_mm':    float(t_field.min()),
        't_max_mm':    float(t_field.max()),
        't_avg_mm':    float(t_field.mean()),
        'L_bounds':    list(L_bounds),
        't_bounds':    list(t_bounds),
        'csv_L':       os.path.abspath(L_path),
        'csv_t':       os.path.abspath(t_path),
        'geometry_config': cfg,
        'decision_vector': [float(v) for v in np.asarray(x_decision).ravel()],
    }
    if extra_metadata:
        summary['source'] = extra_metadata

    with open(os.path.join(out_dir, 'provenance.json'), 'w') as f:
        json.dump(summary, f, indent=2)

    return summary


def export_pareto_row(pareto_csv_path: str,
                      row_index: int,
                      out_dir: str,
                      *,
                      decision_dim_expected: int = None,
                      config: dict | None = None,
                      **kwargs) -> dict:
    """Pull one row from a pareto_final.csv (or history.csv), strip the
    trailing (Q, dP) columns, and route through export_decision_vector.

    Both CSV formats follow the convention written by
    ``optimizer_qnehvi._save_pareto_csv``: columns x0..x{D-1}, Q_W_per_m,
    dP_Pa.
    """
    from .pareto_io import read_pareto_csv
    data = read_pareto_csv(pareto_csv_path, decision_dim_expected)
    if row_index < 0 or row_index >= data.shape[0]:
        raise IndexError(
            f"row_index {row_index} out of range [0, {data.shape[0]})")
    row = data[row_index]
    # The reader restores x0..xN order and places the named objectives last.
    decision_dim = row.size - 2

    x_decision = row[:decision_dim]
    Q   = float(row[decision_dim])
    dP  = float(row[decision_dim + 1])
    src = {
        'pareto_csv':    os.path.abspath(pareto_csv_path),
        'pareto_row':    int(row_index),
        'pareto_Q_W_m':  Q,
        'pareto_dP_Pa':  dP,
    }
    status_path = os.path.splitext(pareto_csv_path)[0] + '_status.json'
    if os.path.isfile(status_path):
        with open(status_path, encoding='utf-8') as source:
            statuses = json.load(source)
        if len(statuses) != len(data):
            raise ValueError('history status count does not match CSV rows')
        src['evaluation_status'] = statuses[row_index]
    if config is None:
        config_path = os.path.join(os.path.dirname(pareto_csv_path), 'config.json')
        try:
            with open(config_path, encoding='utf-8') as source:
                config = json.load(source)
        except FileNotFoundError as exc:
            raise ValueError('original config.json is required to restore this Pareto design') from exc
    if not isinstance(config, dict):
        raise ValueError('original Pareto configuration must be a configuration mapping')
    missing = [key for key in FIELD_CONFIG_KEYS if key not in config]
    if missing:
        raise ValueError(f'original geometry configuration is incomplete: {missing}')
    geometry = {key: config[key] for key in FIELD_CONFIG_KEYS}
    geometry['L_domain_m'] = geometry.pop('L_domain')
    geometry['H_domain_m'] = geometry.pop('H_domain')
    if set(kwargs) & geometry.keys():
        raise ValueError('Pareto export geometry must come from its original configuration')
    src['config'] = config
    return export_decision_vector(x_decision, out_dir,
                                   extra_metadata=src, **geometry, **kwargs)


# ─── CLI ────────────────────────────────────────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='export_ntop_csv',
        description='Export Pareto Pareto-pick to nTop ScalarField CSVs.')
    p.add_argument('--pareto', required=True,
                   help='path to pareto_final.csv or history.csv')
    p.add_argument('--row', type=int, default=0,
                   help='row index within the Pareto CSV (0-based)')
    p.add_argument('--out', required=True,
                   help='output directory (will be created)')
    p.add_argument('--grid', type=int, nargs=2,
                   default=[DEFAULT_GRID_NX, DEFAULT_GRID_NY],
                   metavar=('NX', 'NY'),
                   help=f'export grid size (default {DEFAULT_GRID_NX} {DEFAULT_GRID_NY})')
    p.add_argument('--config', help='original run config.json; defaults to the CSV directory')
    return p


def main(argv: Optional[list] = None) -> int:
    args = _build_argparser().parse_args(argv)
    config = None
    if args.config:
        with open(args.config, encoding='utf-8') as source:
            config = json.load(source)
    summary = export_pareto_row(
        pareto_csv_path=args.pareto,
        row_index=args.row,
        out_dir=args.out,
        Nx_export=args.grid[0], Ny_export=args.grid[1],
        config=config,
    )
    print(f"  L range  [{summary['L_min_mm']:.3f}, {summary['L_max_mm']:.3f}] mm "
          f"(avg {summary['L_avg_mm']:.3f})")
    print(f"  t range  [{summary['t_min_mm']:.3f}, {summary['t_max_mm']:.3f}] mm "
          f"(avg {summary['t_avg_mm']:.3f})")
    print(f"  Q       = {summary['source']['pareto_Q_W_m']:.0f} W/m")
    print(f"  dP      = {summary['source']['pareto_dP_Pa']:.0f} Pa")
    print(f"  CSVs    : {summary['csv_L']}")
    print(f"            {summary['csv_t']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
