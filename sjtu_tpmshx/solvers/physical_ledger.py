"""Store existing physical audits for two fluids and an adiabatic solid."""
import numpy as np


FACE_NAMES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')


def boundary_zeros(shape):
    shape = tuple(shape) + ((1,) if len(shape) == 2 else ())
    return {name: np.zeros(tuple(n for d, n in enumerate(shape) if d != face // 2))
            for face, name in enumerate(FACE_NAMES)}


def heat_ledger(residuals, advection, diffusion, sources, complete):
    """Retain RHS minus diagonal times state, in native power units."""
    dimension = residuals[0].ndim
    labels = ('A', 'B', 'solid')
    return dict(definition='physical_heat_ledger_v1', physical_dimension=dimension,
        power_units='W/m' if dimension == 2 else 'W',
        physical_boundary_complete=complete,
        solved=dict.fromkeys(labels, True),
        residual=dict(zip(labels, residuals)),
        advective_out=dict(zip(labels, (*advection, boundary_zeros(residuals[0].shape)))),
        diffusive_out=dict(zip(labels, (*diffusion, boundary_zeros(residuals[0].shape)))),
        source_integral=dict(zip(labels, map(float, sources))), prescribed_b_power=0.)


def ports_complete(mass, direction, inlet, outlet):
    """Check actual boundary mass against the prepared physical ports."""
    for axis, faces in enumerate(mass):
        for end, sign in ((0, -1), (-1, 1)):
            outward = sign * np.take(faces, end, axis=axis)
            if axis != direction // 2:
                if np.any(outward != 0.):
                    return False
                continue
            is_inlet = end == (0 if direction % 2 == 0 else -1)
            opening = np.asarray(inlet if is_inlet else outlet)
            if opening.shape != outward.shape:
                raise ValueError('physical port mask shape disagrees with mass faces')
            if np.any((opening == 0.) & (outward != 0.)) or (not is_inlet and np.any(outward < 0.)):
                return False
    return True
