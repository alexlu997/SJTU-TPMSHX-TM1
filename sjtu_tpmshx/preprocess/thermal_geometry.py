"""Fixed native geometry for the existing 2D and 3D heat-transfer closures."""
import numpy as np

from sjtu_tpmshx.shared.models import _native_geometry
from sjtu_tpmshx.shared.models.tpms_props import geometry, geometry_fields, _resolve_chi_s


def prepare_thermal_geometry(tpms, cell_mm, wall_mm, conductivity, *,
                             L_field=None, t_field=None, delta=0., co2_geometry=False):
    geometry_model = geometry
    if co2_geometry:
        from sjtu_tpmshx.shared.models.co2_correlations import geometry as geometry_model
        if delta != 0.:
            raise ValueError('CO2 geometry requires delta=0')
    uniform = geometry_model(tpms, cell_mm, wall_mm, conductivity)
    fields = None
    if L_field is not None:
        if t_field is None or np.shape(L_field) != np.shape(t_field):
            raise ValueError('thermal geometry requires matching cell and wall fields')
        if co2_geometry:
            local = _native_geometry.co2_fields(
                tpms, L_field, t_field, conductivity, chi_s=_resolve_chi_s())
        else:
            local = geometry_fields(tpms, L_field, t_field, conductivity)
        fields = {key: local[key] for key in ('A_0', 'D_h', 'epsilon')}
    sides = _native_geometry.prepare_sides(tpms, cell_mm, wall_mm, delta)
    return dict(uniform=uniform, fields=fields, **sides)
