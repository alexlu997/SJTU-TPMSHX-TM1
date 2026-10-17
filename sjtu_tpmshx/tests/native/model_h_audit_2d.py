"""Read-only model-h residuals for the returned native state."""
import numpy as np

from sjtu_tpmshx.tests.native.thermal_face_audit import _model_h, limited_face_increment


def _model_h_faces(T, mass, coefficients, direction, Tin, ifrac, sou, dx=None, dy=None):
    """Evaluate the face capacity and intercept at the supplied temperatures."""
    dx = np.ones(T.shape[0]) if dx is None else dx
    dy = np.ones(T.shape[1]) if dy is None else dy
    a, b, c, origin, _ = coefficients
    capacity = (np.empty_like(mass[0]), np.empty_like(mass[1]))
    deferred = (np.empty_like(mass[0]), np.empty_like(mass[1]))
    for axis in range(2):
        widths = dx if axis == 0 else dy
        for i in range(mass[axis].shape[0]):
            for j in range(mass[axis].shape[1]):
                pos = i if axis == 0 else j
                count = T.shape[axis]
                m = mass[axis][i, j]
                u = min(max(pos - 1 if m >= 0.0 else pos, 0), count - 1)
                up = (u, j) if axis == 0 else (i, u)
                t = T[up]
                inc = 0.0
                if sou and 0 < pos < count and 0 < u < count - 1:
                    prev = (u-1, j) if axis == 0 else (i, u-1)
                    nxt = (u+1, j) if axis == 0 else (i, u+1)
                    dm = .5*(widths[u-1]+widths[u])
                    dp = .5*(widths[u]+widths[u+1])
                    offset = .5*widths[u]
                    inc = limited_face_increment(T[prev], t, T[nxt], dm, dp,
                                                 offset if m >= 0.0 else -offset)
                if axis == direction // 2 and pos == (0 if direction % 2 == 0 else count):
                    patch = j if axis == 0 else i
                    inward = m if direction % 2 == 0 else -m
                    if ifrac[patch] > 0.0 and inward > 0.0:
                        t = Tin[patch]
                x = t - origin
                cp = a + b*x + c*x*x
                capacity[axis][i, j] = m * cp
                deferred[axis][i, j] = m * (_model_h(t+inc, coefficients) - cp*t)
    return capacity, deferred


def _model_face_values(T, mass, capacity, deferred, direction, Tin, ifrac):
    flux = (np.empty_like(capacity[0]), np.empty_like(capacity[1]))
    for axis in range(2):
        for i in range(capacity[axis].shape[0]):
            for j in range(capacity[axis].shape[1]):
                pos = i if axis == 0 else j
                count = T.shape[axis]
                cap = capacity[axis][i, j]
                m = mass[axis][i, j]
                u = min(max(pos-1 if m >= 0.0 else pos, 0), count-1)
                t = T[u, j] if axis == 0 else T[i, u]
                if axis == direction // 2 and pos == (0 if direction % 2 == 0 else count):
                    patch = j if axis == 0 else i
                    inward = m if direction % 2 == 0 else -m
                    if ifrac[patch] > 0.0 and inward > 0.0:
                        t = Tin[patch]
                flux[axis][i, j] = cap*t + deferred[axis][i, j]
    return flux


def _model_h_balance(Ta, Tb, Ts, K_A, K_B, K_s, hv_A, hv_B, dx, dy,
                     mass_A, mass_B, cp_A, cp_B, dir_A, dir_B,
                     Tin_A, Tin_B, frac_A, frac_B, sou_B, last_Ta, last_Tb):
    """Evaluate final nonlinear raw-state balances without another sweep."""
    area = dx[:, None] * dy[None, :]

    def divergence(face):
        return face[0][1:] - face[0][:-1] + face[1][:, 1:] - face[1][:, :-1]

    def conduction(T, K):
        fx, fy = np.zeros((T.shape[0]+1, T.shape[1])), np.zeros((T.shape[0], T.shape[1]+1))
        rx = .5*(dx[:-1, None]*K[1:] + dx[1:, None]*K[:-1])
        ry = .5*(dy[None, :-1]*K[:, 1:] + dy[None, 1:]*K[:, :-1])
        gx = np.divide(K[:-1]*K[1:], rx, out=np.zeros_like(rx), where=rx > 0)
        gy = np.divide(K[:, :-1]*K[:, 1:], ry, out=np.zeros_like(ry), where=ry > 0)
        fx[1:-1] = gx * dy[None, :] * (T[:-1]-T[1:])
        fy[:, 1:-1] = gy * dx[:, None] * (T[:, :-1]-T[:, 1:])
        return -divergence((fx, fy))

    def boundaries(face):
        return (-face[0][0], face[0][-1], -face[1][:, 0], face[1][:, -1])

    from sjtu_tpmshx.solvers.physical_ledger import FACE_NAMES, boundary_zeros, heat_ledger
    sides = {}
    advection, diffusion = [], []
    residuals = []
    defects = []
    exchanges = []
    for label, T, K, hv, mass, cp, direction, tin, frac, sou, snapshot in (
            ('A', Ta, K_A, hv_A, mass_A, cp_A, dir_A, Tin_A, frac_A, True, last_Ta),
            ('B', Tb, K_B, hv_B, mass_B, cp_B, dir_B, Tin_B, frac_B, sou_B, last_Tb)):
        cap, deferred = _model_h_faces(T, mass, cp, direction, tin, frac, sou, dx, dy)
        flux = _model_face_values(T, mass, cap, deferred, direction, tin, frac)
        old_cap, old_deferred = _model_h_faces(snapshot, mass, cp, direction, tin, frac, sou, dx, dy)
        linear_flux = _model_face_values(T, mass, old_cap, old_deferred, direction, tin, frac)
        defect = divergence(linear_flux) - divergence(flux)
        exchange = hv*(Ts-T)*area
        residual = -divergence(flux) + conduction(T, K) + exchange
        inlet = (0, slice(None)) if direction == 0 else ((-1, slice(None)) if direction == 1
                 else ((slice(None), 0) if direction == 2 else (slice(None), -1)))
        cross = dy if direction <= 1 else dx
        width = (dx[0] if direction == 0 else dx[-1]) if direction <= 1 else (dy[0] if direction == 2 else dy[-1])
        diffusion_in = 2*K[inlet]*cross*frac/width*(tin-T[inlet])
        residual[inlet] += diffusion_in
        outward_mass = boundaries(mass)
        outward_h = boundaries(flux)
        adv, diff = boundary_zeros(T.shape), boundary_zeros(T.shape)
        adv.update({name: face[:, None] for name, face in zip(FACE_NAMES, outward_h)})
        diff[FACE_NAMES[direction]] = -diffusion_in[:, None]
        advection.append(adv)
        diffusion.append(diff)
        unknown = sum(int(np.count_nonzero((m < 0) & (frac <= 0))) if f == direction
                      else int(np.count_nonzero(m < 0)) for f, m in enumerate(outward_mass))
        q = -sum(float(f.sum()) for f in outward_h)
        sides[label] = dict(
            Q_advective_W_per_m=q, inlet_conduction_W_per_m=float(diffusion_in.sum()),
            exchange_W_per_m=float(exchange.sum()), source_W_per_m=0.0,
            residual_sum_W_per_m=float(residual.sum()),
            residual_max_abs_W_per_m=float(np.max(np.abs(residual))),
            linearized_residual_sum_W_per_m=float((residual-defect).sum()),
            linearized_residual_max_abs_W_per_m=float(np.max(np.abs(residual-defect))),
            linearization_defect_sum_W_per_m=float(defect.sum()),
            linearization_defect_max_abs_W_per_m=float(np.max(np.abs(defect))),
            mass_net_out_kg_s_per_m=float(divergence(mass).sum()),
            mass_local_max_abs_kg_s_per_m=float(np.max(np.abs(divergence(mass)))),
            mass_in_kg_s_per_m=sum(float(np.maximum(-m, 0).sum()) for m in outward_mass),
            mass_out_kg_s_per_m=sum(float(np.maximum(m, 0).sum()) for m in outward_mass),
            boundary_mass_out_kg_s_per_m=[f.tolist() for f in outward_mass],
            boundary_h_out_W_per_m=[f.tolist() for f in outward_h],
            mass_faces_kg_s_per_m=[f.tolist() for f in mass],
            h_faces_W_per_m=[f.tolist() for f in flux],
            inlet_conduction_faces_W_per_m=diffusion_in.tolist(),
            cp_coefficients=list(cp), unknown_inflow_faces=unknown,
            physical_boundary_complete=(unknown == 0))
        # Native 2D power is W/m. The 1 W/m floor also defines the
        # near-zero-load absolute scale; this is not a temperature tolerance.
        side_scale = max(abs(float(exchange.sum())), 1.0)
        sides[label]['strict_normalization_W_per_m'] = side_scale
        sides[label]['residual_cellmax_rel'] = float(np.max(np.abs(residual))) * Ta.size / side_scale
        residuals.append(residual)
        defects.append(defect)
        exchanges.append(exchange)
    solid = conduction(Ts, K_s) - exchanges[0] - exchanges[1]
    net = sum(s['Q_advective_W_per_m'] + s['inlet_conduction_W_per_m'] for s in sides.values())
    scale = max(abs(sides['A']['exchange_W_per_m']), abs(sides['B']['exchange_W_per_m']), 1.0)
    solid_sum = float(solid.sum())
    finite = all(np.all(np.isfinite(a)) for a in (
        Ta, Tb, Ts, K_A, K_B, K_s, hv_A, hv_B, dx, dy,
        *mass_A, *mass_B, cp_A, cp_B, last_Ta, last_Tb,
        *residuals, *defects, solid)) and np.isfinite(net)
    complete = all(s['physical_boundary_complete'] for s in sides.values())
    solid_cellmax = float(np.max(np.abs(solid))) * Ta.size / scale
    equations_ok = bool(finite and complete and solid_cellmax <= .01
                        and all(s['residual_cellmax_rel'] <= .01 for s in sides.values()))
    return dict(
        _physical_ledger=heat_ledger((*residuals, solid), advection, diffusion, (0., 0., 0.), complete),
        units='W/m; kg/(s m)', state='raw final thermal return',
        boundary_order=['-x', '+x', '-y', '+y'], A=sides['A'], B=sides['B'],
        sou_A=True, sou_B=bool(sou_B), cell_count=int(Ta.size),
        dx_m=dx.tolist(), dy_m=dy.tolist(), area_m2=float(area.sum()),
        solid_boundary_W_per_m=0.0, solid_source_W_per_m=0.0,
        solid_residual_sum_W_per_m=solid_sum,
        solid_residual_max_abs_W_per_m=float(np.max(np.abs(solid))),
        solid_residual_cellmax_rel=solid_cellmax, equation_tolerance=.01,
        residual_sum_W_per_m=float(sum(r.sum() for r in residuals)+solid_sum),
        telescoping_error_W_per_m=float(sum(r.sum() for r in residuals)+solid_sum-net),
        net_boundary_in_W_per_m=net, D2_W_per_m=scale,
        energy_imbalance_rel=abs(net)/scale, solid_imbalance_rel=abs(solid_sum)/scale,
        physical_boundary_complete=complete, finite=bool(finite),
        energy_ok=bool(finite and complete and abs(net)/scale <= .005),
        solid_ok=bool(finite and complete and abs(solid_sum)/scale <= .01),
        equations_ok=equations_ok,
        passed=bool(equations_ok and abs(net)/scale <= .005 and abs(solid_sum)/scale <= .01))
