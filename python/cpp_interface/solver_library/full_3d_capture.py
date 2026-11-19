"""Map detached full native 3D evidence to the portable result contract."""

import numpy as np

from ..full_3d_stage import capture_result
from sjtu_tpmshx.data_types.model_refs import freeze_value


def _legacy_fields(case, p, r):
    from sjtu_tpmshx.postprocess.result_display import describe_fields
    fields=dict(zip(('Ta','Tb','Ts'), map(freeze_value, r['temperature'])))
    fields.update(h_vA=r['hv'][0],h_vB=r['hv'][1],K_ss=np.asarray(p['design']['K_ss']))
    for s,label in enumerate('AB'):
        if r['thermal_pressure'][s] is not None:
            fields['P_thermal_'+label]=r['thermal_pressure'][s]
    for name in ('Ta','Tb','Ts'):
        fields[name+'_display']=fields[name]
    for s,label in enumerate('AB'):
        f=r['flow'][s]
        if f is None:
            continue
        axis=case.parameters['prepared']['axes'][label]
        gauge = f['pressure'].transpose(axis['solver_to_real_perm'])
        if axis['is_reverse']:
            gauge = np.flip(gauge, axis=axis['stream_real_axis'])
        fields['P_gauge_'+label] = np.ascontiguousarray(gauge)
        fields['P_report_'+label]=freeze_value(f['pressure_real'])
        fields['P_f'+label+'_display']=fields['P_report_'+label]
        for name,value in zip(('uc','vc','wc'),f['velocity_real']):
            fields[name+label]=value
        fields['vmag_'+label]=f['speed_real']
    return fields, describe_fields(fields, 3)


def _legacy_drag(cfg, p, r):
    from sjtu_tpmshx.physical_models.df_surrogate.experimental_correction import cfd_metadata
    df_metadata=dict(mode=cfg.get('df_mode','cfd_smooth'))
    for label,f in zip('AB',r['flow']):
        if f is None:
            df_metadata[label]=None
        else:
            base=cfd_metadata(p['design']['K_m2'],p['design']['cF_per_m'])
            applied=cfd_metadata(f['permeability'],f['forchheimer'])
            df_metadata[label]=dict((cfg.get('df_application') or {}).get(label,{}) if df_metadata['mode']=='experimental' else base,
                base_K=base['base_K'],base_cF=base['base_cF'],applied_K=applied['applied_K'],applied_cF=applied['applied_cF'])
    return df_metadata


def _legacy_ratios(r):
    strict={}
    for s,label in enumerate('AB'):
        for suffix in ('','_cellmax'):
            value=None
            if r['model_h'] is not None:
                value=r['model_h']['eps_'+label+'_strict'+suffix]
            elif r['mode']=='temperature' and r['staggered'][s] is not None and r['staggered'][s]['residual_available']:
                value=r['staggered'][s]['cell_ratio' if suffix else 'global_ratio']
            strict['eps_'+label+'_strict'+suffix]=value
    return strict


def _build_outlet_frac_taper(Nx, Nz, n_taper=8, min_frac=0.2):
    """Build the numerical outlet taper near the x and z walls."""
    arr = np.ones((Nx, Nz), dtype=np.float64)
    for i in range(min(n_taper, Nx // 2)):
        d = i + 1
        taper = 1.0 - 0.8 * np.exp(-1.0 * d)
        if taper < min_frac:
            taper = min_frac
        arr[i, :] = np.minimum(arr[i, :], taper)
        arr[Nx - 1 - i, :] = np.minimum(arr[Nx - 1 - i, :], taper)
    for k in range(min(n_taper, Nz // 2)):
        d = k + 1
        taper = 1.0 - 0.8 * np.exp(-1.0 * d)
        if taper < min_frac:
            taper = min_frac
        arr[:, k] = np.minimum(arr[:, k], taper)
        arr[:, Nz - 1 - k] = np.minimum(arr[:, Nz - 1 - k], taper)
    return arr
