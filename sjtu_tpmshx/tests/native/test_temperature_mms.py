"""Manufactured sources keep the current spatial and boundary accuracy gates."""
import numpy as np
import pytest

from sjtu_tpmshx.tests.native.mms_temperature_fields import prepared
from sjtu_tpmshx.tests.native.test_temperature_staggered import native as native
from sjtu_tpmshx.validation.harness._order_fit import fit_order_loglog


@pytest.mark.parametrize('case',['1d','2d','3d'])
@pytest.mark.parametrize('conservative',[False,True])
def test_native_manufactured_fields(native,case,conservative,record_property):
    c,exact = prepared(case,20,conservative)
    code,status,metrics,_,error = native(c)
    assert code == 0, error
    assert status[0] == 0 and status[1] <= c['maxit']
    l2 = [np.linalg.norm(t-e)/np.linalg.norm(e) for t,e in zip(c['state'],exact)]
    linf = [np.max(np.abs(t-e)) for t,e in zip(c['state'],exact)]
    assert np.isfinite(l2+linf).all()
    assert max(l2) < .02 and max(linf) < 3.
    record_property('relative_l2',[float(value) for value in l2])
    record_property('linf_K',[float(value) for value in linf])
    record_property('iterations',status[1])


@pytest.mark.parametrize('case,conservative',[('1d',False),('2d',False),('3d',False),('3d',True)])
def test_native_manufactured_refinement(native,case,conservative,record_property):
    grids = (10,16,24,32) if conservative else (12,16,20,30,40)
    errors,region_errors = [],[]
    for n in grids:
        c,exact = prepared(case,n,conservative)
        code,status,_,_,error = native(c)
        assert code == 0 and status[0] == 0, (n,status,error)
        errors.append([np.linalg.norm(t-e)/np.linalg.norm(e) for t,e in zip(c['state'],exact)])
        masks = [np.s_[-1,:,:],np.s_[:,-1,:],np.s_[:,:,0],np.s_[1:-1,1:-1,1:-1]]
        region_errors.append([[np.linalg.norm((t-e)[mask])/np.linalg.norm(e[mask])
            for t,e in zip(c['state'],exact)] for mask in masks])
    assert np.isfinite(errors).all() and np.isfinite(region_errors).all()
    orders = [fit_order_loglog(1./np.asarray(grids),np.asarray(errors)[:,phase]) for phase in range(3)]
    limits = (1.8,1.8,1.8) if conservative else (1.5,1.5,1.8)
    for fitted,limit in zip(orders,limits):
        assert np.isfinite([fitted.p,fitted.r2]).all() and fitted.p >= limit
        assert fitted.r2 >= (.99 if conservative else .999)
    assert max(errors[-1]) < .01
    if not conservative:
        assert max(errors[grids.index(30)]) < .01
    if case == '3d' and not conservative:
        # A4 uses the final three grids for each physical boundary region.
        for region,phase,limit in ((0,0,.8),(1,1,.8),(2,2,1.5),*( (3,p,1.8) for p in range(3))):
            data=np.asarray(region_errors)[-3:,region,phase]
            fitted=fit_order_loglog(1./np.asarray(grids[-3:]),data)
            assert np.isfinite(fitted.p) and fitted.p >= limit, (region,phase,fitted)
        assert max(region_errors[-1][3]) < .01
    record_property('grids',grids)
    record_property('relative_l2',np.asarray(errors).tolist())
    record_property('orders',[float(fit.p) for fit in orders])
    record_property('r2',[float(fit.r2) for fit in orders])


@pytest.mark.parametrize('case', ['1d', '2d', '3d'])
@pytest.mark.parametrize('conservative', [False, True])
def test_manufactured_inlet_uses_the_physical_face(native, case, conservative):
    from sjtu_tpmshx.tests.native import mms_temperature_fields as mms
    c, _ = prepared(case, 4, conservative)
    c.update(maxit=1, chunk=1)
    code, _, _, _, error = native(c)
    assert code == 0, error
    dx, dy, dz = (width[0] for width in c['widths'])
    volume = dx*dy*dz
    # Conservative SOU uses its qualified relaxation and block damping.
    damping, relaxation = (.6, .2) if conservative else (1., .7)
    solid_before_damping = mms.T0 + (c['state'][2][0,0,0]-mms.T0)/damping
    for side, area, distance, solid in ((0,dy*dz,dx,mms.T0),
                                      (1,dx*dz,dy,solid_before_damping)):
        phase = c[('a','b')[side]]
        k, hv, eps, rcp = (field[0,0,0] for field in phase[:4])
        speed = (mms.U_A,mms.U_B)[side]
        internal = k*(dy*dz/dx+dx*dz/dy+dx*dy/dz)
        inlet = eps*rcp*speed*area+k*area/(distance/2)
        temperature = phase[7][0,0]
        source = phase[10][0,0,0]
        expected = mms.T0+damping*relaxation*(inlet*(temperature-mms.T0)
            +hv*volume*(solid-mms.T0)+source*volume)/(internal+inlet+hv*volume)
        actual = c['state'][side][0,0,0]
        assert abs(actual-expected)/abs(expected) < 1e-12
        # Cell-center substitution must fail this physical-face response gate.
        wrong = mms._build_mms(case)[('Ta_fn','Tb_fn')[side]](
            dx/2,dy/2,dz/2,mms.L_DOM,mms.H_DOM,mms.LZ)
        wrong_response = expected+damping*relaxation*inlet*(wrong-temperature)/(internal+inlet+hv*volume)
        if wrong != temperature:
            assert abs(actual-wrong_response)/abs(wrong_response) > 1e-12
