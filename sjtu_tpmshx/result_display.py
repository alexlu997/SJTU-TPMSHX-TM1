"""Derive display fields and describe recorded result fields without Qt."""
import numpy as np


def display_fields_2d(temperature, pressure, velocity, boundary_openings):
    """Keep raw velocities and smooth display fields at partial ports."""
    fields = dict(zip(('Ta_display', 'Tb_display', 'Ts_display'), temperature))
    partial = []
    for side, label in enumerate('AB'):
        openings = boundary_openings[label]
        partial.append(bool(np.any(openings['out_profile_frac'] < .99) or
                            np.any(openings['in_profile_frac'] < .99)))
        fields.update({'P_f' + label + '_display': pressure[side],
                       'uc' + label: velocity[side][0], 'vc' + label: velocity[side][1]})
    if any(partial):
        from scipy.ndimage import gaussian_filter
        for key in ('Ta_display', 'Tb_display', 'Ts_display'):
            fields[key] = gaussian_filter(fields[key], sigma=1.5)
        for side, label in enumerate('AB'):
            if partial[side]:
                key = 'P_f' + label + '_display'
                fields[key] = gaussian_filter(fields[key], sigma=1.5)
                for prefix in ('uc', 'vc'):
                    fields[prefix + label + '_display'] = gaussian_filter(
                        fields[prefix + label], sigma=2.)
    return fields


def describe_fields(fields, dimension):
    """Return the existing units, axes and states for 2D or 3D fields."""
    metadata = {}
    axes = ('x', 'y') if dimension == 2 else ('x', 'y', 'z')
    for key in fields:
        unit = ('K' if key.startswith(('Ta', 'Tb', 'Ts')) else
                'Pa' if key.startswith('P_') else
                'W/(m3 K)' if key.startswith('h_v') else
                'W/(m K)' if key == 'K_ss' else
                'm/s' if dimension == 2 or key.startswith(('uc', 'vc', 'wc', 'vmag_')) else
                'W/(m K)')
        if key.endswith('_display'):
            state = 'display'
        elif dimension == 2:
            state = ('last thermal input' if key.startswith(('P_thermal', 'h_v')) or key == 'K_ss' else
                     'final flow/report' if key.startswith(('P_report', 'uc', 'vc')) else
                     'raw last main thermal return')
        else:
            state = ('final flow/report' if key.startswith(('uc', 'vc', 'wc', 'vmag_')) else
                     'final SIMPLE flow' if key.startswith(('P_report', 'P_gauge')) else
                     'last thermal solve')
        metadata[key] = dict(unit=unit, axes=axes, location='cell', state=state)
    return metadata


def zone_statistics_2d(z_axis, zone_config, za, L, H,
                       energy_dx, energy_dy, Ta, Tb, Ts):
    """Return area-weighted zone statistics and physical boundary positions."""
    if zone_config is None or za is None:
        return None
    if z_axis == 'continuous':
        return dict(axis_dir=z_axis, boundaries=[], boundaries_x=[], boundaries_y=[], stats=[])
    from sjtu_tpmshx.models.zone_config import Zone, compute_zone_statistics, format_zone_report
    from sjtu_tpmshx.logutil import get_logger
    zones = dict(axis_dir=z_axis)
    if z_axis == 'grid':
        zones.update(boundaries=[], boundaries_x=[b * L for b in za.get('x_bounds', [])],
                     boundaries_y=[b * H for b in za.get('y_bounds', [])])
        definitions = [Zone(f'g{r}', gc['y0'], gc['y1'], gc['L'], gc['t'])
                       for r, gc in enumerate(za.get('grid_cells', []))]
    else:
        definitions = zone_config.zones
        zones.update(boundaries_x=None, boundaries_y=None,
                     boundaries=[z.y_frac_end * (H if z_axis == 'y' else L)
                                 for z in definitions[:-1]])
    zones['stats'] = compute_zone_statistics(
        Ta, Tb, Ts, za['zone_id'], definitions,
        cell_area=energy_dx[:, None] * energy_dy[None, :])
    # Keep the zone-report logger for timestamped output.
    log = get_logger('sjtu_tpmshx.solvers.backends.capture_2d')
    log.info("\n[ZONE STATISTICS]")
    log.info(format_zone_report(zones['stats']))
    return zones
