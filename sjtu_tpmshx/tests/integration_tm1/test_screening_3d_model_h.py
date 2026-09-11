"""Approved 3D air screen retains native enthalpy through formal result IO."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.models.screening import DEFAULT_CONFIG
from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.preprocess.api import prepare_screening_3d
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.test_evaluator_frozen_values import _X_NONUNIF


@pytest.mark.slow
@pytest.mark.parametrize('uniform', [True, False])
def test_native_air_enthalpy_3d(tmp_path, uniform):
    x = np.r_[np.full(8,4.),np.full(8,.6)] if uniform else _X_NONUNIF.copy()
    case = prepare_screening_3d(x, dict(DEFAULT_CONFIG), case_id='air-h-3d',
        Nx=10, Ny=6, Nz=3, Lz=.042, max_outer=12, max_iter_simple=800,
        max_iter_energy=2000, convergence_mode='f2', roughness_mode='norris_1a',
        roughness_eps_um=100., verbose=False)
    with pytest.raises(ValueError, match='energy formulation'):
        run_case(replace(case, metadata={**case.metadata,'energy_formulation':'temperature'}))
    result = run_case(case)
    save_result(result, tmp_path/'result.h5')
    result = load_result(tmp_path/'result.h5')
    assert result.run_status['converged']
    assert result.metadata['model_configuration']['energy_formulation']=='conservative_air_model_h'
    transport = result.metadata['thermal_transport']
    assert tuple(transport['model_fluids']) == ('air','air')
    widths = [np.asarray(result.grid['d'+axis]) for axis in 'xyz']
    volume = widths[0][:,None,None]*widths[1][None,:,None]*widths[2][None,None,:]
    a,b,c,origin,reference = model_h_coefficients('air')
    def h(T):
        x,r = T-origin,reference-origin
        return a*(x-r)+b/2*(x*x-r*r)+c/3*(x*x*x-r*r*r)
    for side,name,direction in [('A','Ta',0),('B','Tb',3)]:
        T = result.fields[name]
        mass = transport['mass_flux_'+side]
        Tin = result.metadata['parameters']['T_in'+side]
        outward = 0.
        for axis in range(3):
            for end,sign in [(0,-1),(-1,1)]:
                flux = sign*np.take(mass[axis],end,axis=axis)
                temp = np.take(T,end,axis=axis)
                if axis==direction//2 and end==(0 if direction%2==0 else -1):
                    assert np.all(flux<=0)
                    temp = np.full_like(temp,Tin)
                outward += float(np.sum(flux*h(temp)))
        axis,end = direction//2,0 if direction%2==0 else -1
        other = [i for i in range(3) if i!=axis]
        area = widths[other[0]][:,None]*widths[other[1]][None,:]
        conduction = float(np.sum(2*np.take(result.fields['K_ff'+side+'_arr'],end,axis=axis)
            *area/widths[axis][end]*(np.take(T,end,axis=axis)-Tin)))
        exchange = float(np.sum(result.fields['h_v'+side+'_arr']*(result.fields['Ts']-T)*volume))
        assert abs(outward+conduction-exchange)/max(abs(exchange),1.)<1e-4
