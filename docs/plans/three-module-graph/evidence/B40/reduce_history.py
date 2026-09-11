"""Six-face temperature-transport diagnostic on saved historical arrays.

This is a common full-domain diagnostic, not the pre-CV interior-only strict
certificate or a real-fluid enthalpy/experimental validation claim.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def solid_residual(T, K, source, widths):
    """Cell-integrated residual, inward conduction plus fluid-to-solid source."""
    residual = source.copy()
    for axis in range(3):
        lo, hi = [slice(None)] * 3, [slice(None)] * 3
        lo[axis], hi[axis] = slice(None, -1), slice(1, None)
        lo, hi = tuple(lo), tuple(hi)
        shape = [1, 1, 1]
        shape[axis] = -1
        distance = (.5 * (widths[axis][:-1] + widths[axis][1:])).reshape(shape)
        area = np.ones([1, 1, 1])
        for other in range(3):
            if other != axis:
                shape = [1, 1, 1]
                shape[other] = -1
                area = area * widths[other].reshape(shape)
        flux = 2*K[lo]*K[hi]/(K[lo]+K[hi]+1e-30)*area/distance*(T[lo]-T[hi])
        residual[lo] -= flux
        residual[hi] += flux
    return residual


def boundary_energy(T, coefficient, velocities, K, widths, direction, Tin, opening):
    faces = {}
    inlet_axis, inlet_end = direction // 2, (0 if direction % 2 == 0 else -1)
    for axis, velocity in enumerate(velocities):
        others = [i for i in range(3) if i != axis]
        area = widths[others[0]][:, None] * widths[others[1]][None, :]
        for end, sign in ((0, -1), (-1, 1)):
            sl = [slice(None)] * 3
            sl[axis] = end
            sl = tuple(sl)
            outward_capacity = sign * coefficient[sl] * velocity[sl] * area
            face_T = T[sl]
            conduction = np.zeros_like(face_T)
            if axis == inlet_axis and end == inlet_end:
                face_T = np.where((outward_capacity < 0) & (opening > 0), Tin, face_T)
                conduction = 2 * K[sl] * area * opening / widths[axis][end] * (T[sl] - Tin)
            faces['xyz'[axis] + ('-' if end == 0 else '+')] = dict(
                outward_advection_W=float(np.sum(outward_capacity * face_T)),
                outward_conduction_W=float(np.sum(conduction)))
    return faces


def flow_summary(raw, metadata, prefix):
    """Unprojected SIMPLE state, in its own coordinates and porosity convention."""
    widths = [raw[prefix + name] for name in ('dx', 'dy', 'dz')]
    coefficient = raw[prefix + 'rho_field'] * raw[prefix + 'eps_field']
    faces = {}
    for axis, name in enumerate(('u', 'v', 'w')):
        others = [i for i in range(3) if i != axis]
        area = widths[others[0]][:, None] * widths[others[1]][None, :]
        for end, sign in ((0, -1), (-1, 1)):
            flux = (sign * np.take(coefficient, end, axis=axis)
                    * np.take(raw[prefix + name], end, axis=axis) * area)
            faces['xyz'[axis] + ('-' if end == 0 else '+')] = dict(
                signed_outward_kg_s=float(flux.sum()),
                inward_kg_s=float(-flux[flux < 0].sum()),
                outward_kg_s=float(flux[flux > 0].sum()))
    P = raw[prefix + 'P']
    area = widths[0][:, None] * widths[2][None, :]
    pin = float(np.average(P[:, 0, :], weights=area * raw[prefix + 'inlet_frac']))
    pout = float(np.average(P[:, -1, :], weights=area * raw[prefix + '_outlet_frac']))
    reference = metadata[prefix + 'P_ref_abs']
    return dict(
        convention='SIMPLE native total porosity; each symmetric physical fluid has half this mass',
        coordinates='solver +y streamwise; A maps to real +x, B maps to real -y',
        faces=faces, net_outward_kg_s=sum(f['signed_outward_kg_s'] for f in faces.values()),
        pressure_gauge_range_Pa=[float(P.min()), float(P.max())],
        pressure_absolute_range_Pa=[float(P.min()+reference), float(P.max()+reference)],
        P_ref_abs_Pa=reference, inlet_cell_area_mean_gauge_Pa=pin,
        outlet_cell_area_mean_gauge_Pa=pout, reported_dP_Pa=pin-pout)


def reduce(directory):
    metadata = json.loads((directory / 'capture.json').read_text(encoding='utf-8'))
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    with np.load(directory / 'native.npz') as raw:
        prefix = f"thermal_{summary['thermal_calls']}/return/"
        widths = [raw[prefix + name + '_arr'] for name in ('dx', 'dy', 'dz')]
        volume = widths[0][:, None, None] * widths[1][None, :, None] * widths[2][None, None, :]
        phases = {}
        for phase, temperature in (('A', 'Ta'), ('B', 'Tb')):
            T = raw[prefix + temperature]
            source = raw[prefix + 'h_v' + phase + '_arr'] * (raw[prefix + 'Ts'] - T) * volume
            coefficient = raw[prefix + 'eps_f' + phase + '_arr'] * raw[prefix + 'rho_cp_f' + phase + '_arr']
            faces = boundary_energy(
                T, coefficient, [raw[prefix + name + phase] for name in ('uf', 'vf', 'wf')],
                raw[prefix + 'K_ff' + phase + '_arr'], widths,
                metadata[prefix + 'dir_' + phase], raw[prefix + 'T_in' + phase + '_arr'],
                raw[prefix + 'ifrac_' + phase])
            net = sum(sum(face.values()) for face in faces.values())
            q = float(source.sum())
            phases[phase] = dict(faces=faces, outward_total_W=net, source_W=q,
                                 residual_W=net-q, relative_residual=abs(net-q)/max(abs(q), 1.))
        summary['native_simple_flow'] = {
            stage: {side: flow_summary(raw, metadata, root + side + '/')
                    for side in ('sA', 'sB')}
            for stage, root in (('last_thermal_input', f"thermal_{summary['thermal_calls']}/flow/"),
                                ('core_return', 'core/'))}
        summary['temperature_transport_boundary'] = phases
        summary['solid_source_sum_W'] = sum(phase['source_W'] for phase in phases.values())
        solid_source = sum(raw[prefix + 'h_v' + side + '_arr']
                           * (raw[prefix + temperature] - raw[prefix + 'Ts']) * volume
                           for side, temperature in (('A', 'Ta'), ('B', 'Tb')))
        residual = solid_residual(raw[prefix + 'Ts'], raw[prefix + 'K_ss_arr'],
                                  solid_source, widths)
        scale = max(*(abs(phase['source_W']) for phase in phases.values()), 1.)
        summary['solid_temperature_diagnostic'] = dict(
            units='W', exterior_boundary_W=0., external_source_W=0.,
            residual_sum_W=float(residual.sum()),
            residual_max_abs_cell_W=float(np.abs(residual).max()),
            residual_l1_W=float(np.abs(residual).sum()), normalization_W=scale,
            relative_global=abs(float(residual.sum()))/scale,
            relative_l1=float(np.abs(residual).sum())/scale,
            acceptance='diagnostic; no new threshold applied')
        summary['boundary_energy_status'] = 'diagnostic_only_no_acceptance_threshold_applied'
    return summary


def self_check():
    solid = solid_residual(np.array([310., 320.]).reshape(2, 1, 1),
                           np.full((2, 1, 1), 4.), np.zeros((2, 1, 1)),
                           [np.ones(2), np.ones(1), np.ones(1)])
    assert np.array_equal(solid.ravel(), [40., -40.])
    assert solid.sum() == 0.
    T = np.array([310., 320.]).reshape(2, 1, 1)
    faces = boundary_energy(T, np.full_like(T, 2.),
                            (np.full((3, 1, 1), 3.), np.zeros((2, 2, 1)), np.zeros((2, 1, 2))),
                            np.full_like(T, 4.), [np.ones(2), np.ones(1), np.ones(1)],
                            0, np.full((1, 1), 300.), np.ones((1, 1)))
    assert sum(x['outward_advection_W'] for x in faces.values()) == 120.
    assert sum(x['outward_conduction_W'] for x in faces.values()) == 80.
    raw = dict(dx=np.ones(1), dy=np.ones(2), dz=np.ones(1),
               rho_field=np.full((1, 2, 1), 2.), eps_field=np.full((1, 2, 1), .5),
               u=np.zeros((2, 2, 1)), v=np.full((1, 3, 1), 3.), w=np.zeros((1, 2, 2)),
               P=np.array([5., 2.]).reshape(1, 2, 1),
               inlet_frac=np.ones((1, 1)), _outlet_frac=np.ones((1, 1)))
    flow = flow_summary(raw, {'P_ref_abs': 100.}, '')
    assert flow['faces']['y-']['signed_outward_kg_s'] == -3.
    assert flow['net_outward_kg_s'] == 0.
    assert flow['reported_dP_Pa'] == 3.
    assert flow['pressure_absolute_range_Pa'] == [102., 105.]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directories', nargs='*', type=Path)
    args = parser.parse_args()
    self_check()
    print(json.dumps([reduce(path) for path in args.directories], indent=2))
