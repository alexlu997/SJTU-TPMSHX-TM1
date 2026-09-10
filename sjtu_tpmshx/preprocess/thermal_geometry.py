"""Fixed geometry consumed by the existing 2D and 3D heat-transfer closures."""
import numpy as np
from sjtu_tpmshx.models.tpms_props import geometry
from sjtu_tpmshx.models.asym_split import _asym_split_A


def prepare_thermal_geometry(tpms, cell_mm, wall_mm, conductivity, *,
                             L_field=None, t_field=None, delta=0.):
    uniform = geometry(tpms, cell_mm, wall_mm, conductivity)
    fields = None
    if L_field is not None:
        if t_field is None or np.shape(L_field) != np.shape(t_field):
            raise ValueError('thermal geometry requires matching cell and wall fields')
        fields = {key: np.empty(np.shape(L_field)) for key in ('A_0', 'D_h', 'epsilon')}
        for index in np.ndindex(np.shape(L_field)):
            local = geometry(tpms, float(L_field[index]), float(t_field[index]), conductivity)
            for key in fields:
                fields[key][index] = local[key]
    split = _asym_split_A({'delta_levelset': delta}, tpms, cell_mm, wall_mm)
    sides = None
    if delta != 0.:
        from sjtu_tpmshx.models.tpms_geometry import _phi_grid, _C_from_tL
        from sjtu_tpmshx.models import asym_geometry
        n = 128
        phi = _phi_grid(tpms, n)
        level = _C_from_tL(tpms, float(wall_mm) / float(cell_mm))
        length = float(cell_mm) / 1000.
        area = asym_geometry.a0_sides(phi, level, delta, length, n)
        diameter = asym_geometry.dh_sides(phi, level, delta, length, n, mc=True)
        reference_area = asym_geometry.a0_sides(phi, level, 0., length, n)
        reference_diameter = asym_geometry.dh_sides(phi, level, 0., length, n, mc=True)
        sides = {side: (area[i], diameter[i], reference_area[i], reference_diameter[i])
                 for i, side in enumerate(('A', 'B'))}
    return dict(uniform=uniform, fields=fields, split_A=split, side_geometry=sides)
