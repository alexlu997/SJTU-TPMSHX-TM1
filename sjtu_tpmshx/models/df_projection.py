"""Pure geometry-to-drag projection on physical source and solver grids."""
from typing import Optional, Tuple
import numpy as np
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec, SCO2_DF_METHOD
from .tpms_calc import geometry as tpms_geometry


def _cell_centre_fracs(n_target: int,
                       widths: Optional[np.ndarray]) -> np.ndarray:
    """Cell-centre fractional coordinates of a target axis. ``widths``
    None → uniform; else non-uniform cell widths (wall-refined grids)."""
    if widths is None:
        return (np.arange(n_target) + 0.5) / n_target
    w = np.asarray(widths, dtype=np.float64)
    cum = np.concatenate([[0.0], np.cumsum(w)])
    return 0.5 * (cum[:-1] + cum[1:]) / w.sum()


def _nearest_src_idx(fracs: np.ndarray, src_n: int) -> np.ndarray:
    """Nearest-neighbour source indices for fractional probe points."""
    return np.clip((fracs * src_n).astype(int), 0, src_n - 1)


def project_fields_to_streamwise_K_cF(L_field: np.ndarray,
                                       t_field: np.ndarray,
                                       tpms_type: str,
                                       k_s: float,
                                       Ny_sim: int,
                                       direction: int,
                                       streamwise_dx: Optional[np.ndarray] = None,
                                       *, source_grid=None
                                       ) -> Tuple[np.ndarray, np.ndarray]:
    """Project real XY L/t cells onto SIMPLE's inlet-to-outlet drag rows.

    direction is 0=+x, 1=-x, 2=+y or 3=-y. L/t are averaged across the
    physical transverse width before predicting K/cF; this retains the 1D
    row approximation rather than averaging the nonlinear drag coefficients.
    source_grid=(dx, dy) gives actual source widths. Omission means a uniform
    source mesh. streamwise_dx describes target rows in inlet-to-outlet order.
    """
    if direction not in (0, 1, 2, 3):
        raise ValueError(f"direction must be 0, 1, 2 or 3, got {direction!r}")
    stream_axis = 0 if direction in (0, 1) else 1
    cross_axis = 1 - stream_axis
    reverse = direction in (1, 3)
    src_n = L_field.shape[stream_axis]
    if source_grid is None:
        L_1d, t_1d = (f.mean(axis=cross_axis) for f in (L_field, t_field))
        stream_widths = None
    else:
        widths = tuple(np.asarray(w) for w in source_grid)
        L_1d, t_1d = (np.average(f, axis=cross_axis, weights=widths[cross_axis])
                       for f in (L_field, t_field))
        stream_widths = widths[stream_axis]
    if reverse:
        L_1d, t_1d = L_1d[::-1], t_1d[::-1]
        if stream_widths is not None:
            stream_widths = stream_widths[::-1]

    s_fracs = _cell_centre_fracs(Ny_sim, streamwise_dx)
    if stream_widths is None:
        src_idx = _nearest_src_idx(s_fracs, src_n)
    else:
        src_idx = np.minimum(np.searchsorted(np.cumsum(stream_widths),
                                             s_fracs * stream_widths.sum(), side='right'), src_n - 1)

    # Per-cell loop kept loop-form: eps_f derives from tpms_geometry per
    # (L, t) probe and the float evaluation order is gate-pinned.
    L_row = np.empty(Ny_sim, dtype=np.float64)
    t_row = np.empty(Ny_sim, dtype=np.float64)
    eps_f_row = np.empty(Ny_sim, dtype=np.float64)
    for j in range(Ny_sim):
        L_avg = float(L_1d[src_idx[j]]); t_avg = float(t_1d[src_idx[j]])
        g = tpms_geometry(tpms_type, L_avg, t_avg, k_s)
        L_row[j] = L_avg; t_row[j] = t_avg; eps_f_row[j] = g['epsilon'] / 2.0

    K_arr, cF_arr = predict_K_cF_vec(
        tpms_type, L_row, t_row, eps_f_row, method=SCO2_DF_METHOD)
    return K_arr.astype(np.float64), cF_arr.astype(np.float64)
