"""Analytical fields and volumetric sources for native temperature tests."""
import numpy as np
import sympy as sp


L_DOM, H_DOM, LZ = 0.182, 0.042, 0.042

# Uniform material — chosen to be physically representative of Air-Air HX,
# but free of TPMS porosity zoning so kernel face-mean / harmonic-K reduce
# to constants and MMS source derivation is exact.
EPS_F     = 0.85                 # fluid fraction (eps_f in kernel)
RHO_CP_A  = 1.10 * 1006.0        # rho*cp ~ 1107 J/m3K (P=1atm, T=350K air)
RHO_CP_B  = 1.10 * 1006.0
K_FFA     = 0.030                # W/mK eff (~ eps * k_air)
K_FFB     = 0.030
K_SS      = (1.0 - EPS_F) * 16.0 # ~ 2.4 W/mK steel * (1-eps)
H_VA      = 5.0e4                # W/m3K LTNE volumetric coupling (moderate)
H_VB      = 5.0e4
U_A       = 5.0                  # m/s axial (A flows in +x)
U_B       = 5.0                  # m/s cross-stream (B flows in +y)

# Manufactured solution amplitudes
T0   = 350.0                     # K reference
DA   = 30.0                      # K amplitude for T_a
DB   = 20.0                      # K amplitude for T_b
DS   = 25.0                      # K amplitude for T_s


# ─────────────────────────────────────────────────────────────────────────
# Sympy: build T_alpha and analytical S_alpha
# ─────────────────────────────────────────────────────────────────────────
def _build_mms(case='3d'):
    """sympy-derive analytical T_alpha and PDE residual S_alpha.

    Returns dict of np.lambdified callables:
        Ta_fn(x,y,z,Lx,Ly,Lz), Tb_fn, Ts_fn,
        SA_fn, SB_fn, SS_fn   (all volumetric, W/m3)
    """
    x, y, z, Lx_, Ly_, Lz_ = sp.symbols('x y z Lx Ly Lz', positive=True)
    PI = sp.pi

    if case == '1d':
        # Axial only; lateral walls trivially adiabatic (T constant in y, z).
        # Outlet at x=L: cos(pi) sine = 0 -> Neumann auto.
        Ta = T0 + DA * sp.cos(PI * x / Lx_)
        Tb = T0 + DB * sp.cos(PI * x / Lx_)
        Ts = T0 + DS * sp.cos(PI * x / Lx_)

    elif case == '2d':
        # x,y; z-independent. Cosines give zero gradient at all 4 in-plane walls.
        Ta = T0 + DA * sp.cos(PI * x / Lx_) * sp.cos(PI * y / Ly_)
        Tb = T0 + DB * sp.cos(2 * PI * x / Lx_) * sp.cos(PI * y / Ly_)
        Ts = T0 + DS * sp.cos(PI * x / Lx_) * sp.cos(2 * PI * y / Ly_)

    elif case == '3d':
        # Full 3D trig — different shape per phase to make h_v coupling non-trivial.
        Ta = T0 + DA * sp.cos(PI * x / Lx_) * sp.cos(PI * y / Ly_) * sp.cos(PI * z / Lz_)
        Tb = T0 + DB * sp.cos(2 * PI * x / Lx_) * sp.cos(PI * y / Ly_) * sp.cos(PI * z / Lz_)
        Ts = T0 + DS * sp.cos(PI * x / Lx_) * sp.cos(2 * PI * y / Ly_) * sp.cos(PI * z / Lz_)

    else:
        raise ValueError(f"Unknown MMS case {case!r}")

    def lap(T):
        return sp.diff(T, x, 2) + sp.diff(T, y, 2) + sp.diff(T, z, 2)

    # PDE residual (volumetric source, W/m3) — kernel-consistent sign convention
    S_A = (EPS_F * RHO_CP_A * U_A * sp.diff(Ta, x)
           - K_FFA * lap(Ta)
           - H_VA * (Ts - Ta))
    S_B = (EPS_F * RHO_CP_B * U_B * sp.diff(Tb, y)
           - K_FFB * lap(Tb)
           - H_VB * (Ts - Tb))
    S_s = (-K_SS * lap(Ts)
           - H_VA * (Ta - Ts)
           - H_VB * (Tb - Ts))

    args = (x, y, z, Lx_, Ly_, Lz_)
    return dict(
        Ta_fn=sp.lambdify(args, Ta, 'numpy'),
        Tb_fn=sp.lambdify(args, Tb, 'numpy'),
        Ts_fn=sp.lambdify(args, Ts, 'numpy'),
        SA_fn=sp.lambdify(args, S_A, 'numpy'),
        SB_fn=sp.lambdify(args, S_B, 'numpy'),
        SS_fn=sp.lambdify(args, S_s, 'numpy'),
    )


def _eval_grid(fn, X, Y, Z):
    """Evaluate lambdified function on grid; broadcast scalars to grid shape."""
    val = fn(X, Y, Z, L_DOM, H_DOM, LZ)
    val = np.asarray(val, dtype=np.float64)
    if val.shape != X.shape:
        val = np.broadcast_to(val, X.shape).copy()
    return np.ascontiguousarray(val)


def prepared(case='3d', n=20, conservative=True):
    shape = (n,n,n)
    widths = [np.full(n,length/n) for length in (L_DOM,H_DOM,LZ)]
    coordinates = [np.cumsum(w)-.5*w for w in widths]
    xyz = np.meshgrid(*coordinates,indexing='ij')
    symbolic = _build_mms(case)
    exact = [_eval_grid(symbolic[key],*xyz) for key in ('Ta_fn','Tb_fn','Ts_fn')]
    sources = [_eval_grid(symbolic[key],*xyz) for key in ('SA_fn','SB_fn','SS_fn')]
    sides = []
    for side,axis in enumerate((0,1)):
        face_coordinates = list(coordinates)
        face_coordinates[axis] = np.array([0.])
        face = np.meshgrid(*face_coordinates,indexing='ij')
        profile = _eval_grid(symbolic[('Ta_fn','Tb_fn')[side]],*face).squeeze(axis=axis).copy()
        # Each velocity has one extra face in its own normal direction.
        velocities = [np.full(tuple(n+(j==k) for k in range(3)),(U_A,U_B)[side] if j==axis else 0.) for j in range(3)]
        sides.append([np.full(shape,(K_FFA,K_FFB)[side]),np.full(shape,(H_VA,H_VB)[side]),
            np.full(shape,EPS_F),np.full(shape,(RHO_CP_A,RHO_CP_B)[side]),*velocities,
            profile,np.ones(profile.shape),np.empty(0),sources[side]])
    return dict(shape=shape,widths=widths,state=[np.full(shape,T0) for _ in range(3)],
        ks=np.full(shape,K_SS),a=sides[0],b=sides[1],source_s=sources[2],prescribed=np.empty(0),
        tin=(T0,T0),directions=(0,2),maxit=400000,chunk=50,warm=True,conservative=conservative,
        rb=False,alpha=(.7,1.,.7),qtol=1e-10), exact
