"""Independent face heat powers and final-state residuals; no solver iteration."""
import numpy as np


def uniform_face_mass_flux(shape, mass, direction):
    faces = [np.zeros(tuple(n + (axis == k) for k, n in enumerate(shape))) for axis in range(3)]
    axis = direction // 2
    cross_cells = np.prod([n for k, n in enumerate(shape) if k != axis])
    faces[axis].fill((1. if direction % 2 == 0 else -1.) * abs(mass) / cross_cells)
    return tuple(faces)


def advection(h, inlet, mass):
    residual = np.zeros_like(h)
    duty = 0.
    for axis, flow in enumerate(mass):
        cells = np.moveaxis(h, axis, 0)
        flux = np.moveaxis(flow, axis, 0)
        power = flux * np.where(flux >= 0.,
            np.concatenate((np.full_like(cells[:1], inlet), cells)),
            np.concatenate((cells, np.full_like(cells[:1], inlet))))
        residual -= np.moveaxis(np.diff(power, axis=0), 0, axis)
        duty += float(power[0].sum() - power[-1].sum())
    return residual, duty


def sou_advection(h, inlet, mass, widths):
    """Reconstruct limited shared face powers with scalar exterior inflow."""
    residual = np.zeros_like(h)
    duty = 0.
    for axis, width in enumerate(widths):
        cells, flux = [np.moveaxis(x, axis, 0) for x in (h, mass[axis])]
        gradient = np.zeros_like(cells)
        if len(width) > 1:
            distance = .5 * (width[:-1] + width[1:])[:, None, None]
            interior = np.diff(cells, axis=0) / distance
            left, right = np.full_like(cells, np.nan), np.full_like(cells, np.nan)
            left[1:], right[:-1] = interior, interior
            left[0] = np.where(flux[0] > 0., (cells[0] - inlet) / (.5 * width[0]), np.nan)
            right[-1] = np.where(flux[-1] < 0., (inlet - cells[-1]) / (.5 * width[-1]), np.nan)
            both = np.isfinite(left) & np.isfinite(right)
            limited = np.where(left * right > 0.,
                               np.sign(left) * np.minimum(np.abs(left), np.abs(right)), 0.)
            one_sided = np.where(np.isfinite(left), left, np.where(np.isfinite(right), right, 0.))
            gradient = np.where(both, limited, one_sided)
        increment = gradient * np.asarray(width)[:, None, None] / 2
        exterior = np.full_like(cells[:1], inlet)
        from_left = np.concatenate((exterior, cells + increment))
        from_right = np.concatenate((cells - increment, exterior))
        power = flux * np.where(flux >= 0., from_left, from_right)
        residual -= np.moveaxis(np.diff(power, axis=0), 0, axis)
        duty += float(power[0].sum() - power[-1].sum())
    return residual, duty


def conduction(temperature, conductivity, widths):
    residual = np.zeros_like(temperature)
    for axis, width in enumerate(widths):
        t, k, r = [np.moveaxis(a, axis, 0) for a in (temperature, conductivity, residual)]
        transverse = [w for other, w in enumerate(widths) if other != axis]
        area = transverse[0][:, None] * transverse[1][None, :]
        for face in range(1, len(width)):
            left, right = k[face-1], k[face]
            valid = (left > 0.) & (right > 0.)
            heat = np.zeros_like(left)
            heat[valid] = area[valid] * (t[face][valid]-t[face-1][valid]) / (
                .5*width[face-1]/left[valid] + .5*width[face]/right[valid])
            r[face-1] += heat
            r[face] -= heat
    return residual


def energy(widths, enthalpy, temperature, solid, conductivity, hv, ks, mass, inlet, *, sou=False):
    volume = widths[0][:,None,None] * widths[1][None,:,None] * widths[2][None,None,:]
    residuals, duties = [], []
    solid_residual = conduction(solid, ks, widths)
    for h, t, k, transfer, faces, hin in zip(enthalpy, temperature, conductivity, hv, mass, inlet):
        flow, duty = sou_advection(h, hin, faces, widths) if sou else advection(h, hin, faces)
        exchange = transfer * (solid-t) * volume
        residuals.append(flow + conduction(t, k, widths) + exchange)
        solid_residual -= exchange
        duties.append(duty)
    net = sum(duties)
    denominator = max(*(abs(q) for q in duties), 1.)
    solid_abs = np.abs(solid_residual).sum()
    fluid_abs = [np.abs(r).sum() for r in residuals]
    metrics = [*duties, net, solid_abs, denominator, max(abs(net),solid_abs)/denominator,
        *fluid_abs, *(np.abs(r).max() for r in residuals),
        max(abs(net),solid_abs,*fluid_abs)/denominator]
    return [*residuals, solid_residual], np.array(metrics)
