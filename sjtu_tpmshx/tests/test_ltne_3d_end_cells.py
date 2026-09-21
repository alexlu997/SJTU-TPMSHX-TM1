"""Independent two-CV balances: physical inlet faces and complete end cells."""
import numpy as np
import pytest
from numba import get_num_threads, set_num_threads

from sjtu_tpmshx.solvers import _kernels_ltne_3d as kernels
from sjtu_tpmshx.solvers.ltne_energy_3d import _conservation_residual_sum


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('fraction', [0.0, 0.4, 1.0])
@pytest.mark.parametrize('mode', ['cc', 'stag', 'cons', 'rb', 'rb_cons'])
def test_two_complete_end_cells(direction, fraction, mode):
    _check_two_cells(direction, fraction, mode, False)


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('mode', ['cc', 'stag', 'cons', 'rb', 'rb_cons'])
def test_unequal_transport_keeps_original_discretisation(direction, mode):
    _check_two_cells(direction, 0.4, mode, True)


@pytest.mark.parametrize('direction', range(6))
def test_cc_uses_actual_inlet_transport(direction):
    _check_two_cells(direction, 0.4, 'cc_face', True)


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('fraction', [0.0, 0.4, 1.0])
@pytest.mark.parametrize('mode', ['cc', 'stag', 'cons', 'rb', 'rb_cons'])
@pytest.mark.parametrize('inlet_scale', [1.0, 1.25])
def test_explicit_capacity_in_complete_end_cell_equations(direction, fraction, mode, inlet_scale):
    # Unequal synthetic inlet/internal capacities check wiring, not physical
    # admissibility or a constant-temperature invariant for divergent F.
    _check_two_cells(direction, fraction, mode, True, inlet_scale)


def _check_two_cells(direction, fraction, mode, unequal, inlet_scale=None):
    # Two unequal streamwise cells; transverse copies keep Nz>1 for every axis.
    cc_mode = mode.startswith('cc')
    axis = direction // 2
    lengths = np.array([0.3, 0.7])
    widths = [np.array([0.4, 0.4]) for _ in range(3)]
    widths[axis] = lengths[::-1].copy() if direction % 2 else lengths.copy()
    area = 0.16
    volume = area * lengths
    one = np.ones((2, 2, 2))
    def field(values):
        vals = np.asarray(values)[::-1] if direction % 2 else np.asarray(values)
        shape = [1, 1, 1]; shape[axis] = 2
        return np.broadcast_to(vals.reshape(shape), one.shape).copy()
    ka, kb, ks = (np.array([0.2, 0.5]), np.array([0.3, 0.4]), np.array([0.7, 0.9]))
    ha, hb = np.array([2.0, 3.0])*volume, np.array([4.0, 2.5])*volume
    fa = fraction*np.array([1.0, 1.3, 1.1] if unequal else [1.0]*3)
    fb = np.array([0.8]*3)
    inlet_fluxes = None if inlet_scale is None else np.array([fa[0], fb[0]]) * inlet_scale
    balance_fa, balance_fb = fa.copy(), fb.copy()
    if inlet_fluxes is not None:
        balance_fa[0], balance_fb[0] = inlet_fluxes
    conservative = mode in ('cons', 'rb_cons')
    # Assemble six coupled unknowns A0,A1,B0,B1,S0,S1 from heat balances.
    matrix = np.zeros((6, 6)); rhs = np.zeros(6)
    for base, kval, exchange, flux, tin, frac in (
        (0, ka, ha, balance_fa, 360.0, fraction), (2, kb, hb, balance_fb, 300.0, 1.0)
    ):
        diffusion = 2*kval[0]*kval[1]/kval.sum()*area/(lengths.sum()/2)
        inlet_d = 2*kval[0]*area*frac/lengths[0]
        f0, fm, f2 = flux
        # CC uses its own local coefficient in each row, including the end CV.
        downstream = f2 if cc_mode else fm
        matrix[base, base] = diffusion + inlet_d + f0 + exchange[0]
        matrix[base, base+1] = -diffusion
        matrix[base+1, base] = -diffusion-downstream
        matrix[base+1, base+1] = diffusion+downstream+exchange[1]
        if conservative:
            matrix[base, base] += fm-f0
            matrix[base+1, base+1] += f2-fm
        matrix[base, 4] = -exchange[0]; matrix[base+1, 5] = -exchange[1]
        rhs[base] = (inlet_d+f0)*tin
    ds = 2*ks[0]*ks[1]/ks.sum()*area/(lengths.sum()/2)
    for cell in range(2):
        matrix[4+cell, 4+cell] = ds+ha[cell]+hb[cell]
        matrix[4+cell, 5-cell] = -ds
        matrix[4+cell, cell] = -ha[cell]
        matrix[4+cell, 2+cell] = -hb[cell]
    expected = np.linalg.solve(matrix, rhs)
    fields = [one*340, one*310, one*325]
    eps = np.array([0.3, 0.5]); rcp = np.array([4.0, 6.0])
    face_coef = np.array([eps[0]*rcp[0], eps.mean()*rcp.mean(), eps[1]*rcp[1]])
    if direction % 2: face_coef = face_coef[::-1]
    faces = []
    cc = []
    for flux in (fa, fb):
        ff = [np.zeros((3,2,2)), np.zeros((2,3,2)), np.zeros((2,2,3))]
        vals = flux[::-1] if direction % 2 else flux
        shape = [1,1,1]; shape[axis] = 3
        ff[axis][:] = vals.reshape(shape)/(face_coef.reshape(shape)*area)*(-1 if direction % 2 else 1)
        faces.extend(ff)
        vel = [np.zeros_like(one) for _ in range(3)]
        local = flux[[0,2]].copy()
        if mode == 'cc_face': local[0] *= 1.8
        vel[axis] = field(local)/(field(eps*rcp)*area)*(-1 if direction % 2 else 1)
        cc.extend(vel)
    args = (*fields, 2,2,2, *widths, field(ka),field(kb),field(ks),
            field(ha/volume),field(hb/volume), field(eps),field(eps),field(rcp),field(rcp),
            *(cc if cc_mode else faces), direction,direction,
            np.full((2,2),360.0),np.full((2,2),300.0),
            np.full((2,2),fraction),np.ones((2,2)), 4000,0,0.7,0.7,0.7)
    if cc_mode:
        if mode == 'cc_face':
            args += (np.full((2,2),fa[0]),np.full((2,2),fb[0]))
        elif inlet_fluxes is not None:
            args += tuple(np.full((2,2), flux) for flux in inlet_fluxes)
        kernels._gs_full_chunk_3d(*args)
    else:
        fn = kernels._gs_full_chunk_3d_stag_rb if mode.startswith('rb') else kernels._gs_full_chunk_3d_stag
        old_threads = get_num_threads()
        try:
            set_num_threads(2)
            extra = () if inlet_fluxes is None else tuple(
                np.full((2,2), flux) for flux in inlet_fluxes)
            fn(*args, one*0,one*0,one*0,int(conservative), *extra)
        finally:
            set_num_threads(old_threads)
    for actual, pair in zip(fields, expected.reshape(3,2)):
        np.testing.assert_allclose(actual, field(pair), atol=2e-8, rtol=0)
    # Independent whole-core external balance plus the original scheme defect.
    ta,tb,ts = expected.reshape(3,2)
    total = 0.0
    for t,kval,flux,tin,frac in ((ta,ka,balance_fa,360,fraction),(tb,kb,balance_fb,300,1)):
        f0,fm,f2 = flux
        total += f0*tin-f2*t[1]+2*kval[0]*area*frac/lengths[0]*(tin-t[0])
        if cc_mode:
            total += (f2-f0)*t[0]
        elif not conservative:
            total += t[0]*(fm-f0)+t[1]*(f2-fm)
    assert abs(total) < 2e-10
    assert abs(np.sum(ha*(ts-ta)+hb*(ts-tb))) < 2e-10
    if conservative:
        residual, source, cellmax = _conservation_residual_sum(
            fields[0],fields[2],*faces[:3],field(eps),field(ka),field(rcp),
            field(ha/volume),*widths,direction,np.full((2,2),360.0),
            np.full((2,2),fraction),one*0,
            None if inlet_fluxes is None else np.full((2,2),inlet_fluxes[0]))
        assert abs(residual) < 2e-8
        assert cellmax < 2e-8
        np.testing.assert_allclose(source,4*np.sum(ha*(ts-ta)),atol=2e-8,rtol=0)
        if inlet_fluxes is not None:
            perturbed = expected.copy()
            perturbed[:2] += [0.1, -0.2]
            oracle = matrix[:2] @ perturbed - rhs[:2]
            residual, _, cellmax = _conservation_residual_sum(
                field(perturbed[:2]),fields[2],*faces[:3],field(eps),field(ka),field(rcp),
                field(ha/volume),*widths,direction,np.full((2,2),360.0),
                np.full((2,2),fraction),one*0,np.full((2,2),inlet_fluxes[0]))
            np.testing.assert_allclose(residual,4*oracle.sum(),atol=2e-8,rtol=0)
            np.testing.assert_allclose(cellmax,np.max(np.abs(oracle)),atol=2e-8,rtol=0)


@pytest.mark.parametrize('direction', range(6))
def test_actual_inlet_transport_has_no_second_area_factor(direction):
    from sjtu_tpmshx.solvers.ltne_energy_3d import _inlet_transport_3d
    widths = (np.array([0.2,0.5]),np.array([0.3,0.6]),np.array([0.4,0.7]))
    eps = np.arange(8).reshape(2,2,2)*0.02+0.25
    rho = np.arange(8).reshape(2,2,2)+4.0
    cp_in = 1007.0
    faces = [np.ones((3,2,2))*0.8,np.ones((2,3,2))*1.2,np.ones((2,2,3))*1.6]
    # Values already represent face averages over the rectangular mesh face.
    actual = _inlet_transport_3d(faces,eps,rho,cp_in,*widths,direction)
    axis = direction//2; index = 0 if direction%2 == 0 else 1
    transverse = [dim for dim in range(3) if dim != axis]
    for a,b in np.ndindex(2,2):
        cell = [0,0,0]; cell[axis] = index
        cell[transverse[0]] = a; cell[transverse[1]] = b
        expected = (eps[tuple(cell)]*rho[tuple(cell)]*cp_in*(0.8,1.2,1.6)[axis]
                    *widths[transverse[0]][a]*widths[transverse[1]][b]
                    *(1 if direction%2 == 0 else -1))
        assert actual[a,b] == pytest.approx(expected)


@pytest.mark.parametrize('inlet_scale', [None, 1.0, 1.25])
def test_prescribed_b_is_external_reservoir_and_not_a_certificate(inlet_scale):
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
    shape = (2,1,2); one = np.ones(shape); zero = one*0
    dx = np.array([0.3,0.7]); dy = np.array([0.4]); dz = np.array([0.4,0.4])
    area = 0.16; ha = 2*area*dx; hb = 3*area*dx
    d = 0.2*area/0.5; din = 2*0.2*area/0.3; ds = 0.7*area/0.5
    flux = 0.4*5*2*area
    incoming = flux if inlet_scale is None else flux*inlet_scale
    # A and solid equations, with B maintained externally at 300 K.
    matrix = np.array([[d+din+flux+ha[0],-d,-ha[0],0],
                       [-d-flux,d+flux+ha[1],0,-ha[1]],
                       [-ha[0],0,ds+ha[0]+hb[0],-ds],
                       [0,-ha[1],-ds,ds+ha[1]+hb[1]]])
    expected = np.linalg.solve(matrix,[(din+incoming)*360,0,hb[0]*300,hb[1]*300])
    ta,tb,ts,info = solve_full_domain_3d(
        1.0,0.4,0.8,*shape,360,300,0.2,0.3,0.7,2.0,3.0,5.0,5.0,0.8,
        one*2,zero,zero,zero,zero,zero,0,0,
        dx_arr=dx,dy_arr=dy,dz_arr=dz,Tb_prescribed=one*300,
        ufA=np.ones((3,1,2))*2,vfA=np.zeros((2,2,2)),wfA=np.zeros((2,1,3)),
        ufB=np.zeros((3,1,2)),vfB=np.zeros((2,2,2)),wfB=np.zeros((2,1,3)),
        inlet_flux_A=None if inlet_scale is None else np.full((1,2),incoming),
        conservative_ltne=True,max_iter=4000,tol=1e-10,return_info=True)
    np.testing.assert_allclose(ta[:,0,0],expected[:2],atol=2e-8,rtol=0)
    np.testing.assert_allclose(ts[:,0,0],expected[2:],atol=2e-8,rtol=0)
    np.testing.assert_array_equal(tb,one*300)
    assert info['converged'] and info['eps_A_strict'] < 1e-8
    assert info['eps_B_strict'] is None and info['eps_B_strict_cellmax'] is None
    external_b = 2*np.sum(hb*(300-expected[2:]))
    a_boundary = 2*(incoming*360-flux*expected[1]+din*(360-expected[0]))
    assert external_b < 0
    assert abs(a_boundary+external_b) < 1e-10


@pytest.mark.parametrize('directions', [(0, 3), (3, 0)])
def test_nz1_passes_integrated_inlet_flux_per_unit_depth(directions):
    from sjtu_tpmshx.tests.test_ltne_energy_3d import _toy_case
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
    from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain
    cfg = _toy_case(Nx=3,Ny=2,Nz=1)
    cfg.update(max_iter=10,inlet_flux_A=np.array([[0.3],[0.5]]),
               inlet_flux_B=np.array([[0.1],[0.2],[0.4]]))
    if directions == (3, 0):
        cfg.update(dir_A=3, dir_B=0,
                   ucA=cfg['vcA'], vcA=-cfg['ucA'],
                   ucB=-cfg['vcB'], vcB=cfg['ucB'],
                   inlet_flux_A=cfg['inlet_flux_B'], inlet_flux_B=cfg['inlet_flux_A'])
    actual = solve_full_domain_3d(**cfg)
    flat = dict(cfg)
    for key in ('D','Nz','wcA','wcB'): flat.pop(key)
    for key in ('ucA','vcA','ucB','vcB'): flat[key] = flat[key][...,0]
    for key in ('inlet_flux_A','inlet_flux_B'): flat[key] = flat[key][:,0]/cfg['D']
    expected = solve_full_domain(**flat)
    for a,e in zip(actual,expected): np.testing.assert_array_equal(a[...,0],e)


@pytest.mark.parametrize('nz',[1,2])
def test_rejects_wrong_inlet_transport_shape(nz):
    from sjtu_tpmshx.tests.test_ltne_energy_3d import _toy_case
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
    cfg = _toy_case(Nx=3,Ny=2,Nz=nz)
    with pytest.raises(ValueError,match='inlet_flux_A.*shape'):
        solve_full_domain_3d(**cfg,inlet_flux_A=np.ones((1,nz)))
