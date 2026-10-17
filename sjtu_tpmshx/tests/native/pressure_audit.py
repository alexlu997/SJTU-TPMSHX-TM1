"""Independent physical port-pressure and bounded pressure-step checks."""
import numpy as np

from sjtu_tpmshx.models.envelope import PRESSURE_FLOOR_PA
from sjtu_tpmshx.result_math import pressure_face_values

INLET_PRESSURE_REL_TOL = 1e-4


def inlet_pressure_state(solver, specified_Pa):
    """Actual ideal-gas port pressures, using geometric areas in either dimension.

    The pressure anchor pins outlet *cells*. The extrapolated outlet face
    can have nonzero gauge pressure, so anchor + dP is not the inlet pressure.
    """
    if solver is None or solver.fluid_type != 'ideal_gas':
        return None
    if solver.P.ndim == 2:
        area, stream_widths = solver.dx_arr, solver.dy_arr
        inlet, outlet = solver.inlet_geom_frac, solver.outlet_geom_frac
    else:
        area, stream_widths = solver.dx[:, None] * solver.dz[None, :], solver.dy
        inlet, outlet = solver.inlet_frac, solver.outlet_frac
    pin, pout = pressure_face_values(solver.P, stream_widths)
    def mean(values, weights):
        mask = weights > 0.
        return float(np.average(values[mask], weights=weights[mask]))
    inlet_gauge = mean(pin, inlet * area)
    outlet_gauge = mean(pout, outlet * area)
    realized = float(solver.P_ref_abs) + inlet_gauge
    outlet_abs = float(solver.P_ref_abs) + outlet_gauge
    residual = (realized - float(specified_Pa)) / float(specified_Pa)
    return dict(specified_Pa=float(specified_Pa), realized_Pa=realized,
                outlet_Pa=outlet_abs, outlet_gauge_Pa=outlet_gauge,
                minimum_Pa=float(solver.P_ref_abs + np.min(solver.P)),
                iterations=getattr(solver, 'pressure_iterations', []),
                relative_error=residual, relative_tolerance=INLET_PRESSURE_REL_TOL,
                passed=bool(np.isfinite(residual) and abs(residual) < INLET_PRESSURE_REL_TOL),
                definition='geometric open-area mean at physical port faces')


def pressure_shooting_target_sq(state):
    """P² iteration at physical faces; callers convert back to a cell anchor."""
    return (state['specified_Pa'] ** 2
            - (state['realized_Pa'] ** 2 - state['outlet_Pa'] ** 2))


def pressure_initial_reference(P_out_sq, P_in, *, history):
    """Use the 1D estimate when positive; otherwise start from inlet pressure.

    An isothermal straight-flow estimate cannot decide whether the coupled,
    turning, non-isothermal flow has a solution. This is only an initial guess;
    actual inlet-pressure convergence and final-field validity remain required.
    """
    if not np.isfinite((P_out_sq, P_in)).all() or P_in <= PRESSURE_FLOOR_PA:
        raise ValueError('pressure initialization requires finite estimates and inlet pressure above the floor')
    usable = P_out_sq > PRESSURE_FLOOR_PA ** 2
    anchor = float(np.sqrt(P_out_sq) if usable else P_in)
    history.append(dict(stage='initialization', estimate_Pa2=float(P_out_sq),
                        anchor_Pa=anchor, method='1d' if usable else 'inlet-pressure'))
    return anchor


def pressure_shooting_reference(state):
    """Damped P² correction, preserving positive faces and shifted cell fields.

    Limit a downward step to half the remaining squared-pressure distance to
    the existing floor. Ordinary steps retain the original P² update. This
    controls the coupled iteration; it does not certify a physical solution.
    """
    pin, realized, pout, gauge, minimum = (state[k] for k in (
        'specified_Pa', 'realized_Pa', 'outlet_Pa', 'outlet_gauge_Pa', 'minimum_Pa'))
    if not np.isfinite((pin, realized, pout, gauge, minimum)).all():
        raise RuntimeError('pressure iteration received a non-finite pressure state')
    lower = max(PRESSURE_FLOOR_PA, pout - minimum + PRESSURE_FLOOR_PA)
    target = pressure_shooting_target_sq(state)
    delta = target - pout ** 2
    alpha = 1.0
    if delta < 0.0:
        if pout <= lower:
            raise RuntimeError('pressure iteration cannot lower an outlet already at the pressure floor')
        alpha = min(1.0, 0.5 * (pout ** 2 - lower ** 2) / -delta)
    next_sq = pout ** 2 + alpha * delta
    if next_sq <= lower ** 2:
        raise RuntimeError('pressure iteration has no positive admissible update')
    anchor = float(np.sqrt(next_sq) - gauge)
    state['iterations'].append(dict(stage='update', relative_error=state['relative_error'],
                                    target_Pa2=float(target), step_fraction=float(alpha),
                                    anchor_Pa=anchor))
    return anchor
