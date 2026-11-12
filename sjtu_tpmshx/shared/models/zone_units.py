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


def _zone_data_si(value):
    """Convert the existing zone builders' explicit millimetre fields to SI."""
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if key in ('L_mm', 't_mm', 'L_cell_mm', 't_wall_mm', 'L_field', 't_field'):
                result[key.replace('_mm', '_m').replace('_field', '_field_m')] = item * 1e-3
            elif key in ('grid_cells',):
                result[key] = [dict((('L_m' if k == 'L' else 't_m' if k == 't' else k),
                                    v * 1e-3 if k in ('L', 't') else v)
                                   for k, v in cell.items()) for cell in item]
            else:
                result[key] = _zone_data_si(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_zone_data_si(item) for item in value]
    return value
