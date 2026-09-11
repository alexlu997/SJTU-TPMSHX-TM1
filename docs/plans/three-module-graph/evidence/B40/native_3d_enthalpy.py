"""Offline native SIMPLE / air integral enthalpy audit of saved 3D screens."""
import argparse
import json
from pathlib import Path
import numpy as np
from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes

parser = argparse.ArgumentParser()
parser.add_argument('directories', nargs='+', type=Path)
args = parser.parse_args()
ca, cb, cc, origin, reference = model_h_coefficients('air')
def h(t):
    x, r = t-origin, reference-origin
    return ca*(x-r) + cb/2*(x*x-r*r) + cc/3*(x*x*x-r*r*r)

rows = []
for path in args.directories:
    raw = np.load(path/'native.npz')
    meta = json.loads((path/'capture.json').read_text())
    summary = json.loads((path/'summary.json').read_text())
    prefix = f"thermal_{summary['thermal_calls']}/"
    pre = prefix+'return/'
    widths = [raw[pre+n+'_arr'] for n in ('dx','dy','dz')]
    volume = widths[0][:,None,None]*widths[1][None,:,None]*widths[2][None,None,:]
    row = dict(capture=str(path), phases={})
    for side, name in [('A','Ta'),('B','Tb')]:
        flow = prefix+'flow/s'+side+'/'
        u,v,w,rho = [raw[flow+n] for n in ('u','v','w','rho_field')]
        if side == 'A':
            faces = (v.transpose(1,0,2),u.transpose(1,0,2),w.transpose(1,0,2))
            rho = rho.transpose(1,0,2)
        else:
            faces = (u[:,::-1,:],-v[:,::-1,:],w[:,::-1,:])
            rho = rho[:,::-1,:]
        mass = face_mass_fluxes(*faces,rho,raw[pre+'eps_f'+side+'_arr'],*widths)
        T = raw[pre+name]
        direction = meta[pre+'dir_'+side]
        boundary = []
        for axis in range(3):
            for end, sign in [(0,-1),(-1,1)]:
                outward = sign*np.take(mass[axis],end,axis=axis)
                temp = np.take(T,end,axis=axis)
                inlet = axis == direction//2 and end == (0 if direction%2==0 else -1)
                if inlet:
                    assert np.all(outward <= 0), 'audit requires forward inlet'
                    temp = raw[pre+'T_in'+side+'_arr']
                boundary.append(float(np.sum(outward*h(temp))))
        axis,end = direction//2,0 if direction%2==0 else -1
        area = np.prod(np.meshgrid(*(widths[i] for i in range(3) if i!=axis), indexing='ij'),axis=0)
        conduction = float(np.sum(2*np.take(raw[pre+'K_ff'+side+'_arr'],end,axis=axis)
            *area/widths[axis][end]*raw[pre+'ifrac_'+side]
            *(np.take(T,end,axis=axis)-raw[pre+'T_in'+side+'_arr'])))
        source = float(np.sum(raw[pre+'h_v'+side+'_arr']*(raw[pre+'Ts']-T)*volume))
        gap = sum(boundary)+conduction-source
        row['phases'][side] = dict(boundary_h_W=boundary,conduction_W=conduction,
            source_W=source,gap_W=gap,relative_gap=abs(gap)/max(abs(source),1.))
    rows.append(row)
print(json.dumps(rows,indent=2))
