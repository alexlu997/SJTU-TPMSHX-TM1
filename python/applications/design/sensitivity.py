"""Air-only sensitivity estimates for TPMS design screening."""
import numpy as np


# Available sweep parameters: (key, label, unit, default_min, default_max)
SWEEP_PARAMS = [
    ('L_cell', 'TPMS cell L', 'mm', 4.0, 8.0),
    ('t',     'Wall thickness t', 'mm', 0.3, 0.6),
    ('u_A',   'Fluid A velocity', 'm/s', 1.0, 30.0),
]

# Metrics the heatmap can display
METRICS = [
    ('Q_per_vol',   'Q / volume',       'W / m³'),
    ('dP_per_L',    'ΔP / length',      'Pa / m'),
    ('h_v',         'Volumetric h_v',   'W/m³·K'),
    ('ratio',       'h_v / (ΔP/L)',     'W/(m²·K·Pa)'),
]

SCOPE_NOTE = (
    "Fluid A only: air correlations. Blank Fluid A pressure uses 101325 Pa. "
    "Pressure loss uses the CFD baseline "
    "without experimental correction. Q/volume = h_v × 40 K is a ranking "
    "estimate. Click a valid cell to load parameters into the main inputs.")


def _eval_surrogate(tpms, L_cell_mm, t_mm, u, T_in_K, P_in_Pa):
    """Calculate the screening metrics for one Fluid A air state."""
    from tm1.physical_models.tpms_calc import compute as _tpms_compute
    # Solid conductivity affects only the unused K_ss result.
    r = _tpms_compute(tpms, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, 16.0)
    h_v = r['H_sf'] * r['A_0']
    dT = 40.0  # Assumed fluid-to-solid temperature difference for the heat ranking.
    Q_vol = h_v * dT
    return {
        'Q_per_vol': Q_vol,
        'dP_per_L': r['dP_per_L'],
        'h_v': h_v,
        'ratio': h_v / max(r['dP_per_L'], 1e-9),
        'Re': r['Re'],
        'Nu': r['Nu'],
    }


def sweep_axis(key, steps):
    """Return the sample values of one sweep parameter."""
    for name, _, _, low, high in SWEEP_PARAMS:
        if name == key:
            return np.linspace(low, high, steps)
    raise KeyError(key)


def sweep_row(fixed, key_x, x, key_y, ys, metric):
    """Return values at one x, the number of failed points, and the first failure message."""
    values = np.empty(len(ys))
    failures = 0
    first_error = ""
    params = dict(fixed)
    params[key_x] = float(x)
    for j, y in enumerate(ys):
        params[key_y] = float(y)
        try:
            result = _eval_surrogate(
                params['tpms'], params['L_cell'], params['t'],
                params['u_A'], params['T_in'], params['P_in'])
        except Exception as error:
            values[j] = np.nan
            failures += 1
            if not first_error:
                first_error = str(error)
        else:
            values[j] = result[metric]
    return values, failures, first_error
