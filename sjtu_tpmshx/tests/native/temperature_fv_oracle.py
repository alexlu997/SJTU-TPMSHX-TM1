"""Independent fixed-capacity finite-volume powers; no numerical iteration.

Promoted from the qualified G5 CC/QD face oracle. The only dimensional
correction makes the validated optional w inactive for the 2D operator;
all three input velocity arrays still undergo native validity checks.
"""
import math
import numpy as np

def physical(case, state=None, tin=None, sou=True):
    shape=tuple(case['shape']);width=list(case['widths'])
    if shape[2]==1:width[2]=np.ones(1)
    state=case['state'] if state is None else state
    tin=case['tin'] if tin is None else tin
    vol=width[0][:,None,None]*width[1][None,:,None]*width[2][None,None,:]
    ff=[case['a'],case['b']]
    r=[ff[0][1]*vol*(state[2]-state[0]),ff[1][1]*vol*(state[2]-state[1]),ff[0][1]*vol*(state[0]-state[2])+ff[1][1]*vol*(state[1]-state[2])]
    powers=[[[] for _ in range(6)] for _ in range(3)]
    fluxes=[];complete=True;prescribed=bool(case['prescribed'].size)
    for phase in range(3):
        t=state[phase];K=ff[phase][0] if phase<2 else case['ks']
        if phase==1 and prescribed:
            r[phase]=np.full(shape,np.nan)
            for axis in range(3):
                count=int(np.prod([shape[a] for a in range(3) if a!=axis]))
                for side in (0,1):powers[phase][2*axis+side]=[np.full(count,np.nan),np.full(count,np.nan)]
            fluxes.append([]);continue
        phaseflux=[]
        for axis in range(3):
            fshape=list(shape);fshape[axis]+=1
            flow=np.zeros(fshape);diff=np.zeros(fshape)
            for f in np.ndindex(*fshape):
                pos=f[axis];c=list(f);c[axis]=min(pos,shape[axis]-1);c=tuple(c)
                area=float(vol[c]/width[axis][c[axis]])
                cap=float(ff[phase][2][c]*ff[phase][3][c]*ff[phase][4+axis][c]*area) if phase<2 and not (shape[2]==1 and axis==2) else 0.
                if 0<pos<shape[axis]:
                    left=list(f);left[axis]-=1;left=tuple(left);right=tuple(f)
                    if phase<2:cap=.5*float(ff[phase][2][left]*ff[phase][3][left]*ff[phase][4+axis][left]+ff[phase][2][right]*ff[phase][3][right]*ff[phase][4+axis][right])*area
                    kl,kr=float(K[left]),float(K[right]);g=0. if kl==0 or kr==0 else area/(.5*width[axis][pos-1]/kl+.5*width[axis][pos]/kr)
                    diff[f]=g*(t[left]-t[right]);up=left if cap>=0 else right;delta=0.
                    if phase<2 and sou and (phase==0 or case['sou_b']) and shape[axis]>=3:
                        middle=list(up);middle[axis]=max(1,min(up[axis],shape[axis]-2));j=middle[axis];minus=middle.copy();minus[axis]-=1;plus=middle.copy();plus[axis]+=1
                        sl=(t[tuple(middle)]-t[tuple(minus)])/(.5*(width[axis][j-1]+width[axis][j]));sr=(t[tuple(plus)]-t[tuple(middle)])/(.5*(width[axis][j]+width[axis][j+1]))
                        if sl*sr>0:delta=math.copysign(min(abs(sl),abs(sr)),sl)*.5*width[axis][up[axis]]*(1 if cap>=0 else -1)
                    flow[f]=cap*(t[up]+delta);r[phase][left]-=flow[f]+diff[f];r[phase][right]+=flow[f]+diff[f]
                else:
                    sign=-1 if pos==0 else 1;slot=2*axis+(sign>0)
                    declared=phase<2 and slot==case['directions'][phase]
                    inlet_t=tin[phase] if phase<2 else 0.;opening=1.
                    if declared:
                        patch=tuple(c[a] for a in range(3) if a!=axis);pshape=tuple(shape[a] for a in range(3) if a!=axis)
                        profile,openings,explicit=ff[phase][7:10]
                        if profile.size:inlet_t=float(profile.reshape(pshape)[patch])
                        if openings.size:opening=float(openings.reshape(pshape)[patch])
                        if opening==0:cap=0.
                        elif explicit.size:cap=-sign*float(explicit.reshape(pshape)[patch])
                    known=declared and opening>0.;incoming=sign*cap<0
                    if incoming and not known:complete=False
                    flow[f]=cap*(inlet_t if incoming and known else t[c]) if phase<2 else 0.
                    dout=2*float(K[c])*area*opening/width[axis][c[axis]]*(t[c]-inlet_t) if declared else 0.
                    diff[f]=sign*dout;r[phase][c]-=sign*flow[f]+dout
            phaseflux.append((flow,diff))
            for side in (0,1):
                index=[slice(None)]*3;index[axis]=0 if side==0 else shape[axis]
                sign=-1 if side==0 else 1
                powers[phase][2*axis+side]=[(sign*flow[tuple(index)]).ravel(),(sign*diff[tuple(index)]).ravel()]
        fluxes.append(phaseflux)
    qa=float(np.sum(ff[0][1]*vol*(state[0]-state[2])))
    qb=float(np.sum(ff[1][1]*vol*(state[2]-state[1])))
    flatpowers=np.concatenate([component for phase in powers for face in phase for component in face])
    return dict(residual=np.array(r),powers=flatpowers,qa=qa,qb=qb,volume=vol,denominator=max(abs(qa),abs(qb),1.),boundary_complete=complete,prescribed_b_power=(-qb if prescribed else 0.))
