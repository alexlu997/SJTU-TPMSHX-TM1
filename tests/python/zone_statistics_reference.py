"""Frozen zone statistics before the native result migration."""
import numpy as np

def compute_zone_statistics(Ta, Tb, Ts, zone_id, zones,
                            u=None, v=None, P=None,
                            cell_area=None):
    """Compute per-zone statistics from solution fields.

    Parameters
    ----------
    Ta, Tb, Ts : arrays — temperature fields (1D or 2D)
    zone_id    : array — zone index per cell (same shape as Ta)
    zones      : list of Zone objects
    u, v       : velocity arrays (optional)
    P          : pressure array (optional)
    cell_area  : array (same shape as Ta) — per-cell area for weighted stats

    Returns
    -------
    list of dicts, one per zone.
    """
    Ta_flat = np.ravel(Ta)
    Tb_flat = np.ravel(Tb)
    Ts_flat = np.ravel(Ts)
    zid_flat = np.ravel(zone_id)
    w_flat = np.ravel(cell_area) if cell_area is not None else None

    def _wmean(arr, w):
        if w is not None:
            return float(np.average(arr, weights=w))
        return float(arr.mean())

    def _wstd(arr, w):
        if w is not None:
            m = np.average(arr, weights=w)
            return float(np.sqrt(np.average((arr - m)**2, weights=w)))
        return float(arr.std())

    stats = []
    for zi, z in enumerate(zones):
        mask = zid_flat == zi
        n = mask.sum()
        if n == 0:
            stats.append({'name': z.name, 'n_cells': 0})
            continue

        w = w_flat[mask] if w_flat is not None else None
        s = {
            'name':    z.name,
            'n_cells': int(n),
            'L_mm':    z.L_mm,
            't_mm':    z.t_mm,
            'Ta_mean': _wmean(Ta_flat[mask], w),
            'Ta_std':  _wstd(Ta_flat[mask], w),
            'Ta_min':  float(Ta_flat[mask].min()),
            'Ta_max':  float(Ta_flat[mask].max()),
            'Tb_mean': _wmean(Tb_flat[mask], w),
            'Tb_std':  _wstd(Tb_flat[mask], w),
            'Tb_min':  float(Tb_flat[mask].min()),
            'Tb_max':  float(Tb_flat[mask].max()),
            'Ts_mean': _wmean(Ts_flat[mask], w),
            'Ts_std':  _wstd(Ts_flat[mask], w),
        }

        if u is not None and v is not None:
            u_flat = np.ravel(u)
            v_flat = np.ravel(v)
            umag = np.sqrt(u_flat[mask]**2 + v_flat[mask]**2)
            s['u_mean']    = _wmean(u_flat[mask], w)
            s['v_mean']    = _wmean(v_flat[mask], w)
            s['umag_mean'] = _wmean(umag, w)
            s['umag_cv']   = float(_wstd(umag, w) / max(_wmean(umag, w), 1e-10))

        if P is not None:
            P_flat = np.ravel(P)
            s['P_mean']    = _wmean(P_flat[mask], w)
            s['P_min']     = float(P_flat[mask].min())
            s['P_max']     = float(P_flat[mask].max())
            s['P_spread']  = float(P_flat[mask].max() - P_flat[mask].min())

        stats.append(s)

    return stats


