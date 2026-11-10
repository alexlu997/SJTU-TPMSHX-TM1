"""Native offset-isosurface split with the symmetric array identity contract."""
from . import _native_geometry


def _asym_split_A(cfg, tpms_type, Lcell, t_wall):
    """Return the fraction of total porosity assigned to side A."""
    delta = float(cfg.get('delta_levelset', 0.0))
    if delta == 0.0:
        return 0.5
    return float(_native_geometry.split_from_index(tpms_type, Lcell, t_wall, delta))


def _eps_sides_for_run(cfg, tpms_type, Lcell, t_wall, eps_arr, eps_f_arr):
    """Split the supplied total porosity; retain both zero-offset aliases."""
    if float(cfg.get('delta_levelset', 0.0)) == 0.0:
        return eps_f_arr, eps_f_arr
    fraction = _asym_split_A(cfg, tpms_type, Lcell, t_wall)
    fields = _native_geometry.split_fields(eps_arr, fraction)
    return fields['epsilon_A'], fields['epsilon_B']
