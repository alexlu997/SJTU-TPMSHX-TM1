"""Unit spelling adapter for existing zone model and display consumers."""

def _legacy_zone_units(value):
    """Adapt prepared SI data to existing kernel/model parameter spellings."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ('L_m', 't_m', 'L_cell_m', 't_wall_m', 'L_field_m', 't_field_m'):
                result[key[:-2] + ('_mm' if '_field_' not in key else '')] = item * 1e3
            elif key == 'grid_cells':
                result[key] = [dict((('L' if k == 'L_m' else 't' if k == 't_m' else k),
                                     v * 1e3 if k in ('L_m', 't_m') else v)
                                    for k, v in cell.items()) for cell in item]
            else:
                result[key] = _legacy_zone_units(item)
        return result
    if isinstance(value, list):
        return [_legacy_zone_units(item) for item in value]
    return value
