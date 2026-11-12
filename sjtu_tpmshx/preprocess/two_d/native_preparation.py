"""Build the existing CaseData contract from the owned native 2D stage."""
from contextlib import ExitStack
from copy import deepcopy
import ctypes as ct
from dataclasses import asdict, replace
import os

import numpy as np

from sjtu_tpmshx.shared.domain.case_data import CaseData
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.shared.domain.model_refs import ModelRef
from sjtu_tpmshx.shared.domain.run_environment import capture_environment
from sjtu_tpmshx.shared.domain.run_warnings import (
    RangeRecord, current_warnings, merge_warnings, warning_messages, record_warning, _range_context,
)
from sjtu_tpmshx.shared.models import _native_preparation_case as native
from sjtu_tpmshx.shared.models import _native_flow, _native_geometry, _native_grid


def supports(config):
    """Keep unported physical modes on their explicit preparation route."""
    return (not config.is_3d and config.geometry.delta_levelset == 0.
            and (not config.zones.enabled or config.zones.axis == 'continuous'))


def _kind(value):
    if isinstance(value, np.ndarray):
        return native._Kind(value.dtype.itemsize * 8 if value.dtype.kind == 'f' else 64, 1, 2)
    if isinstance(value, np.floating):
        return native._Kind(value.dtype.itemsize * 8, 1, 1)
    if isinstance(value, np.integer):
        return native._Kind(64, 1, 1)
    return native._Kind(64, 0, 0)


def _flow_kind(value):
    scalar = _native_flow._scalar(value)
    return native._Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))


def _input(config, targets, operation):
    geometry = config.geometry
    value = native._InputV1(1, ct.sizeof(native._InputV1), geometry.L_dom_m, geometry.H_dom_m,
        config.solver.Nx, config.solver.Ny, config.flags.port_wall_refine,
        _native_geometry._topology(geometry.tpms), geometry.L_cell_mm, geometry.t_wall_mm,
        geometry.k_s_W_mK, geometry.delta_levelset)
    kinds = native._Kinds(_kind(geometry.L_cell_mm), _kind(geometry.t_wall_mm), _kind(geometry.k_s_W_mK))
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        # Capacity queries never consume an obsolete inlet speed.
        speed = 0. if operation == 'prepare_inlet_mass_capacities' or (
            targets is not None or fluid.mass_flow_kg_s is not None) else fluid.u_mps
        value.sides[index] = native._Inlet(native._FLUIDS.index(fluid.type), speed,
            fluid.T_in_K, fluid.P_in_Pa, native._Port(
                port.dir, port.in_ctr, port.in_w, port.out_ctr, port.out_w, port.uniform_inlet_2d),
            fluid.mass_flow_kg_s is not None, fluid.mass_flow_kg_s or 0.)
        kinds.sides[index] = native._InletKinds(*map(_kind, (speed, fluid.T_in_K, fluid.P_in_Pa)))
    value.have_physical_depth = geometry.Lz_m is not None
    value.physical_depth_m = geometry.Lz_m if geometry.Lz_m is not None else 0.
    value.geometry_mode = int(config.zones.enabled)
    value.df_mode = int(config.df_mode == 'experimental')
    typed = native._InputV2(2, ct.sizeof(native._InputV2), value)
    typed.kinds = kinds
    settings = config.sco2_nu
    typed.sco2_nu.mode = int(settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        selected = getattr(settings, name)
        typed.sco2_nu.have_alpha[index] = selected is not None
        typed.sco2_nu.alpha[index] = selected or 0.
    buffers = []
    for name in ('parameter_version', 'source', 'applicability'):
        encoded = getattr(settings, name).encode('utf-8')
        buffer = ct.create_string_buffer(encoded)
        buffers.append(buffer)
        setattr(typed.sco2_nu, name, native._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(encoded)))
    flow = native._FlowInput(3, ct.sizeof(native._FlowInput), typed)
    flow.physical_depth_kind = _flow_kind(geometry.Lz_m if geometry.Lz_m is not None else 0.)
    flow.have_explicit_targets = targets is not None
    for index, side in enumerate('AB'):
        target = targets[index] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
        flow.target_kinds[index] = _flow_kind(target if target is not None else 0.)
        if targets is not None:
            flow.explicit_targets_kg_s[index] = target
    if config.zones.enabled:
        spec = config.zones.config
        decision = np.asarray(spec['x_decision'], dtype=np.float64)
        controls = native._Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['spline_order'], spec['symmetric_y'],
            (native._D * 2)(*spec['L_bounds']), (native._D * 2)(*spec['t_bounds']),
            native._Array(decision.ctypes.data_as(ct.POINTER(native._D)), decision.size))
        source = native._ContinuousInput(4, ct.sizeof(native._ContinuousInput), flow, controls)
        buffers.append(decision)
    else:
        source = flow
    source._grid_error = None

    def grid_kind(value):
        try:
            scalar = _native_grid._scalar(value)
        except TypeError as error:
            if source._grid_error is None:
                source._grid_error = str(error)
            return native._Kind(64, 0, 0)
        return native._Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))

    source._grid_kinds = native._GridKinds(7, ct.sizeof(native._GridKinds),
        (native._Kind * 2)(*map(grid_kind, (geometry.L_dom_m, geometry.H_dom_m))))
    for index, side in enumerate('AB'):
        port = getattr(config, 'bc_' + side)
        source._grid_kinds.ports[index] = (native._Kind * 4)(
            *(grid_kind(getattr(port, name)) if port.in_w > 0. and port.out_w > 0.
              else native._Kind(64, 0, 0) for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w')))
    source._buffers = buffers
    return source


def _sample(value, shape):
    def extreme(name):
        if not value.have_finite:
            return None
        index = tuple(int(item) for item in np.unravel_index(getattr(value, name + '_index'), shape))
        return getattr(value, name), index
    return dict(minimum=extreme('minimum'), maximum=extreme('maximum'),
                **{name: getattr(value, name) for name in ('low', 'high', 'size', 'nonfinite')})


def _range_record(value, bounds_list):
    shape = tuple(value.shape[:value.rank])
    source = tuple(native._text(item) for item in value.source[:value.source_count])
    context = tuple(native._text(getattr(value, name)) for name in ('side', 'stage', 'layout'))
    bounds = list(value.bounds) if bounds_list else tuple(value.bounds)
    record = RangeRecord(native._text(value.label), native._text(value.quantity), native._text(value.unit),
                         bounds, **_sample(value.sample, shape), last=_sample(value.last, shape))
    return (*source, shape, context), record


def _records(evidence, bounds_list):
    """Restore ordered source observations without recomputing their values."""
    ranges = []
    for index in range(evidence.range_count):
        key, record = _range_record(evidence.ranges[index], bounds_list[index])
        message = next(iter(warning_messages({key: record})), None)
        ranges.append((key, record, message))
    pending = [native._text(item) for item in evidence.warnings[:evidence.warning_count]]
    records = {}
    plain = 0
    for key, record, message in ranges:
        if message is not None:
            while pending and pending[0] != message:
                records['native-preparation', plain] = pending.pop(0)
                plain += 1
            if pending:
                pending.pop(0)
        records[key] = record
    for message in pending:
        records['native-preparation', plain] = message
        plain += 1
    return records


_GEOMETRY_NAMES = (('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
                   ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'))
_PROPERTY_NAMES = (('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'),
    ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'), ('pressure_gradient_Pa_m', 'dP_per_L'),
    ('surface_transfer_W_m2K', 'H_sf'), ('fluid_conductivity_W_mK', 'K_ff'))


def _geometry_values(value, co2=False):
    return {key: (np.float64(getattr(value, name)) if co2 or key in ('A_0', 'D_h') else getattr(value, name))
            for name, key in _GEOMETRY_NAMES}


def _cache_record_view(records):
    """Keep copied cache evidence alive until the native stage call returns."""
    buffers, ranges, bounds_list, warnings = [], [], [], []

    def text(value):
        encoded = value.encode('utf-8')
        buffer = ct.create_string_buffer(encoded)
        buffers.append(buffer)
        return native._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(encoded))

    def sample(value, shape):
        finite = value['minimum'] is not None
        def index(name):
            return int(np.ravel_multi_index(value[name][1], shape)) if shape else 0
        return native._Sample(finite, value['minimum'][0] if finite else 0.,
            value['maximum'][0] if finite else 0., index('minimum') if finite else 0,
            index('maximum') if finite else 0, *(value[name] for name in ('low', 'high', 'size', 'nonfinite')))

    for key, record in records.items():
        if not isinstance(record, RangeRecord):
            warnings.append(text(record))
            continue
        shape = key[-1]
        sources = (native._Text * (len(key)-1))(*(text(item) for item in key[:-1]))
        sizes = (native._S * len(shape))(*shape)
        buffers.extend((sources, sizes))
        values = {name: getattr(record, name) for name in ('minimum', 'maximum', 'low', 'high', 'size', 'nonfinite')}
        ranges.append(native._Range(sources, len(sources), text('unbound'), text('unbound'), text('source'),
            text(record.label), text(record.quantity), text(record.unit), (native._D * 2)(*record.bounds),
            sizes, len(shape), sample(values, shape), sample(record.last or values, shape)))
        bounds_list.append(isinstance(record.bounds, list))
    ranges = (native._Range * len(ranges))(*ranges)
    bounds = (native._U * len(bounds_list))(*bounds_list)
    warnings = (native._Text * len(warnings))(*warnings)
    buffers.extend((ranges, bounds, warnings))
    return native._Evidence(ranges, len(ranges), bounds, warnings, len(warnings), None, 0), buffers


def _resolved(config, flow, targets):
    fluids = {}
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        if targets is not None or fluid.mass_flow_kg_s is not None:
            fluids['fluid_' + side] = replace(fluid, u_mps=_native_flow._restore(flow.speeds[index]),
                mass_flow_kg_s=None if targets is not None else fluid.mass_flow_kg_s)
    return replace(config, **fluids).validate(resolved_inlet_speeds=True) if fluids else config


def _summary(value):
    return value.minimum if value.scalar else {'min': value.minimum, 'max': value.maximum}


def _drag(result, index, continuous):
    side, extra = result.prepared.values.sides[index], result.prepared.drag[index]
    value = side.drag_evidence
    metadata = {key: _summary(getattr(value, name)) for name, key in (
        ('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
        ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF'))}
    metadata.update(scale_K=value.scale_permeability, scale_F=value.scale_forchheimer,
                    campaign=native._text(value.campaign), scope=native._text(value.scope))
    for name in ('application_scope', 'fluid'):
        text = native._text(getattr(extra, name))
        if text:
            metadata[name] = text
    if extra.calibration_count:
        metadata['calibration'] = {native._text(item.key): native._text(item.value)
                                   for item in extra.calibration[:extra.calibration_count]}
    if extra.have_selection and extra.selection.scope:
        metadata.update(inlet_u_mps=side.inlet.velocity_m_s, extrapolated=bool(extra.selection.flags & 2))
        for name, key in (('application_u', 'velocity_window_mps'),
                          ('calibration_u', 'calibration_velocity_window_mps'),
                          ('runtime_u', 'calibration_runtime_velocity_window_mps')):
            values = getattr(extra.selection, name)
            metadata[key] = {'min': values[0], 'max': values[1]}
    if continuous:
        extension = result.drag[index]
        for name in ('transfer_policy', 'geometry_application'):
            text = native._text(getattr(extension, name))
            if text:
                metadata[name] = text
        if extension.have_reference_geometry:
            metadata['reference_geometry_mm'] = dict(zip(('L', 't'), extension.reference_geometry_mm))
    return metadata


def _model_metadata(result, config):
    value = result.prepared
    settings = value.sco2_nu
    nu = dict(mode=config.sco2_nu.mode, model_version=native._text(value.sco2_nu_model_version))
    if settings.mode:
        nu.update(alpha_D=settings.alpha[0], alpha_G=settings.alpha[1],
                  interpretation=native._text(value.sco2_nu_interpretation))
        nu.update({name: native._text(getattr(settings, name))
                   for name in ('parameter_version', 'source', 'applicability')})
    else:
        nu['coefficients'] = {name: dict(zip(('c', 'a', 'd'), value.sco2_nu_coefficients[index]))
                              for index, name in enumerate(('Diamond', 'Gyroid'))}
    metadata = {'sco2_nu': nu}
    co2 = value.co2
    if co2.active:
        details = {name: native._text(getattr(co2, name)) for name in (
            'version', 'application_version', 'pressure_model', 'correction_source', 'property_model', 'common_geometry')}
        details.update({name: getattr(co2, name) for name in (
            'pressure_multiplier', 'scale_K', 'scale_F', 'nu_multiplier', 'nu_floor_multiplier')})
        details.update(sides=[side for index, side in enumerate('AB') if co2.sides[index]],
                       Re_range=list(co2.re_range), Pr_range=list(co2.pr_range))
        metadata['co2'] = details
    return metadata


def _case(result, config, case_id, side_geometry=None):
    from .preparation import _zone_data_si
    value = result.prepared.values
    continuous = isinstance(result, native._ContinuousCase)
    shape = value.nx, value.ny
    grid = {name: native._array(getattr(value, name))
            for name in ('dx', 'dy', 'x_edges', 'y_edges', 'x_breaks', 'y_breaks')}
    for name in ('x_breaks', 'y_breaks'):
        grid[name] = grid[name].tolist()
    grid.update(dimension=2, axis_order=('x', 'y'), length_unit='m')
    design = {key: native._array(getattr(value, name), shape, precision=result.prepared.field_kinds[index].precision)
              for index, (name, key) in enumerate((
                  ('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'), ('total_porosity', 'eps_arr'),
                  ('solid_conductivity', 'K_ss_arr'), ('hydraulic_radius', 'r_h_arr')))}
    if continuous:
        design.update(axis='continuous', eps_f_arr=_native_geometry.split_fields(design['eps_arr'], .5)['epsilon_A'])
        for index, side in enumerate('AB'):
            design['K_ff' + side + '_arr'] = native._array(result.fluid_conductivity[index], shape)
    uniform = {key: getattr(value, name) for name, key in (
        ('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
        ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h'), ('uniform_solid_conductivity', 'K_ss'))}
    co2_geometry = bool(result.prepared.co2.active)
    for name in (('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h') if co2_geometry else ('A_0', 'D_h')):
        uniform[name] = np.float64(uniform[name])
    uniform['K_ss'] = native._restore(value.uniform_solid_conductivity, result.prepared.property_kinds[0][12])
    thermal = dict(uniform=uniform, fields=None, split_A=value.split_a, side_geometry=None)
    if continuous:
        thermal['fields'] = dict(A_0=native._array(result.area_density_per_m, shape),
                                D_h=native._array(result.hydraulic_diameter_m, shape), epsilon=design['eps_arr'])
    geometry = config.geometry
    params = dict(L=geometry.L_dom_m, H=geometry.H_dom_m, N_x=value.nx, N_y=value.ny,
        dx=geometry.L_dom_m/config.solver.Nx, dy=geometry.H_dom_m/config.solver.Ny,
        u_A=config.fluid_A.u_mps, u_B=config.fluid_B.u_mps,
        T_inA=config.fluid_A.T_in_K, T_inB=config.fluid_B.T_in_K, T_s_init=config.solver.T_s_init_K,
        envelope_mode=getattr(config, 'envelope_mode', 'raise'), tpms_type=geometry.tpms,
        L_cell_m=native._restore(value.cell_length_m, result.prepared.input_kinds.cell_length),
        t_wall_m=native._restore(value.wall_thickness_m, result.prepared.input_kinds.wall_thickness),
        k_s=geometry.k_s_W_mK, eps=uniform['epsilon'], r_h=np.float64(value.hydraulic_radius_m),
        z_axis='continuous' if continuous else 'y',
        continuous_field=dict(config.zones.config) if continuous else None,
        fluid_A=config.fluid_A.type, fluid_B=config.fluid_B.type, warnings_list=[], extrap_reasons=[],
        _environment=capture_environment(), thermal_geometry=thermal,
        zone_config='continuous' if continuous else None, flow_inputs={}, boundary_openings={}, static_properties={})
    params['run_settings'] = _zone_data_si(config.to_dict())
    params['run_settings'].pop('zones')
    for index, side in enumerate('AB'):
        port = bc_to_dict(getattr(config, 'bc_' + side), geometry.L_dom_m, geometry.H_dom_m, side='A')
        params['cfg' + side], params['dir_' + side] = port, port['dir']
        inlet = value.sides[index]
        flow = {key: native._array(getattr(inlet, name)) for name, key in (
            ('cross_widths', 'dx'), ('stream_widths', 'dy'), ('row_permeability', 'K_m2'), ('row_forchheimer', 'cF_per_m'))}
        seed_type = np.float64 if getattr(config, 'fluid_' + side).type == 'co2' else float
        flow.update(seed_K_m2=seed_type(inlet.seed_permeability_m2),
                    seed_cF_per_m=seed_type(inlet.seed_forchheimer_per_m),
                    metadata=_drag(result, index, continuous))
        if continuous:
            field_shape = inlet.cross_widths.size, inlet.stream_widths.size
            flow.update(K_field_m2=native._array(inlet.permeability, field_shape),
                        cF_field_per_m=native._array(inlet.forchheimer, field_shape))
        params['flow_inputs'][side] = flow
        params['boundary_openings'][side] = {key: native._array(getattr(inlet, name)) for name, key in (
            ('inlet_geometry', 'in_geom_frac'), ('outlet_geometry', 'out_geom_frac'),
            ('inlet_profile', 'in_profile_frac'), ('outlet_profile', 'out_profile_frac'))}
        properties = dict(uniform) if side_geometry is None else dict(side_geometry[index])
        for name, key in (('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'),
                          ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'),
                          ('pressure_gradient_Pa_m', 'dP_per_L'), ('surface_transfer_W_m2K', 'H_sf'),
                          ('fluid_conductivity_W_mK', 'K_ff'), ('solid_conductivity_W_mK', 'K_ss')):
            column = [item[0] for item in native._Properties._fields_].index(name)
            properties[key] = native._restore(getattr(inlet.properties, name), result.prepared.property_kinds[index][column])
        params['static_properties'][side] = properties
    params['static_properties']['geometry'] = uniform
    refs = tuple(ModelRef(native._text(model.name), native._text(model.version),
        {'fluid': getattr(config, 'fluid_' + 'AB'[index]).type, 'sco2_nu': asdict(config.sco2_nu)}
        if index < 2 else {'topology': geometry.tpms} if index == 3 else {},
        applicability='side ' + 'AB'[index] if index < 2 else '') for index, model in enumerate(value.models))
    return CaseData.from_compute_config(case_id, config, grid=grid, design_fields=design, parameters=params,
        model_refs=refs, metadata=dict(preprocessor='two_d_v1', quantity_basis='per_unit_depth',
            model_metadata=_model_metadata(result, config),
            notices=[native._text(item) for item in result.prepared.notices[:result.prepared.notice_count]],
            design_mode='continuous' if continuous else 'uniform',
            model_roles={'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}))


def _execute(config, operation, *, targets=None, case_id=None, own_metadata=False):
    from sjtu_tpmshx.preprocess import api
    from sjtu_tpmshx.shared.models.tpms_props import _resolve_chi_s
    # Preserve the original physical guard before object-key checks.
    from sjtu_tpmshx.shared.models.tpms_calc import validate_fluid_type
    for side in 'AB':
        validate_fluid_type(getattr(config, 'fluid_' + side).type, side)
    source = _input(config, targets, operation)
    chi_error = None
    try:
        chi = _resolve_chi_s()
    except ValueError as problem:
        chi, chi_error = None, problem
    allow = config.extrap.allow or os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes')
    options = native._Options(1, ct.sizeof(native._Options), chi is not None, allow, chi or 0.)
    metadata = {}
    cache_buffers, cache_keys, side_geometry = [], {}, {}
    from sjtu_tpmshx.shared.models.tpms_geometry import _compute_geometry_cached
    from sjtu_tpmshx.shared.models.tpms_calc import _compute_cached, _InletCacheValue
    co2 = 'co2' in (config.fluid_A.type, config.fluid_B.type)
    geometry_key = (config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm, 128)

    def geometry_cache(action, value):
        if action:
            _compute_geometry_cached.store(geometry_key, None, _geometry_values(value))
            hit = False
        else:
            hit, saved = _compute_geometry_cached.lookup(geometry_key)
            if hit:
                for name, key in _GEOMETRY_NAMES:
                    setattr(value, name, saved[key])
        if (action or hit) and chi_error is not None:
            raise chi_error
        return hit

    def inlet_cache(action, side, inlet, speed_kind, value):
        if not action:
            fluid = getattr(config, 'fluid_' + 'AB'[side])
            speed = native._restore(inlet.velocity_m_s, speed_kind) if (
                targets is not None or fluid.mass_flow_kg_s is not None) else fluid.u_mps
            key = (config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm,
                   speed, fluid.T_in_K, fluid.P_in_Pa, fluid.type, config.sco2_nu, co2)
            cache_keys[side] = key
            hit, saved = _compute_cached.lookup(key)
            if not hit:
                return False
            properties, records = saved
            for name, key in _GEOMETRY_NAMES:
                setattr(value.geometry, name, properties[key])
            for name, key in (*_PROPERTY_NAMES, ('cp', None), ('pr', None)):
                scalar = properties[key] if key is not None else getattr(saved, name)
                setattr(value.properties, name, scalar)
                column = [item[0] for item in native._Properties._fields_].index(name)
                value.kinds[column] = _kind(scalar)
            value.evidence, buffers = _cache_record_view(records)
            cache_buffers.extend(buffers)
            side_geometry[side] = _geometry_values(value.geometry, co2)
            return True
        properties = _geometry_values(value.geometry, co2)
        for name, key in _PROPERTY_NAMES:
            column = [item[0] for item in native._Properties._fields_].index(name)
            properties[key] = native._restore(getattr(value.properties, name), value.kinds[column])
        bound = _records(value.evidence, value.evidence.range_bounds_list)
        records = {key[:-1] if isinstance(record, RangeRecord) else key: record for key, record in bound.items()}
        _compute_cached.store(cache_keys[side], None,
            _InletCacheValue(properties, records, value.properties.cp, value.properties.pr))
        side_geometry[side] = _geometry_values(value.geometry, co2)
        return False

    def observe_range(value, bounds_list, cached, scalar):
        key, record = _range_record(value, bounds_list)
        if key[-1] == ('unbound', 'unbound', 'source'):
            key = (*key[:-1], _range_context.get())
        merge_warnings(current_warnings(), [{key: record}])
        if cached or current_warnings() is not None or scalar is None:
            return
        from sjtu_tpmshx.shared.models import tpms_props, fluid_props, nu_correlations, co2_correlations
        source = key[:-2]
        if source[0] == 'property':
            fluid, property_name = source[1].split('_', 1)
            notice = tpms_props._range_notice(source[1], scalar, scalar, *record.bounds)
            if notice is not None:
                attribute = {'density': 'rho', 'viscosity': 'mu', 'conductivity': 'k', 'cp': 'cp'}[property_name]
                native._source_warning(getattr(fluid_props.get(fluid), attribute), notice)
        elif source[0] in ('nu', 'nu_pr') and native._text(value.stage) == 'inlet':
            fluid, topology = source[1:]
            if fluid == 'air':
                notices = nu_correlations._extrap_notices(topology, scalar, scalar)
                origin = fluid_props._nu_air
            elif fluid == 'water':
                notices = nu_correlations._water_nu_notices(scalar, scalar, topology)
                origin = fluid_props._nu_water
            elif fluid == 'sco2':
                notices = nu_correlations._sco2_nu_notices(scalar, scalar, topology)
                origin = (nu_correlations.nu_sco2_selected if config.sco2_nu.mode != 'cfd_smooth'
                          else nu_correlations.nu_sco2_topo)
            else:
                notices = ([co2_correlations._calibration_notice(record.quantity, record.bounds)]
                           if scalar < record.bounds[0] or scalar > record.bounds[1] else [])
                origin = fluid_props._nu_co2
            for notice in notices:
                native._source_warning(origin, notice)

    def observe_notice(kind, side, value, message):
        if kind == 1:
            record_warning(('nu_preflight', 'AB'[side]), message)
        elif kind == 0:
            if current_warnings() is None:
                from sjtu_tpmshx.shared.models import tpms_calc
                fluid = getattr(config, 'fluid_' + 'AB'[side]).type
                notice = tpms_calc._reynolds_notice(config.geometry.tpms, value, fluid)
                if notice is not None:
                    native._source_warning(tpms_calc.compute, notice, call='_compute_cached')
        else:
            raise RuntimeError(f'unknown preparation notice kind {kind}')

    with ExitStack() as scopes:
        def host_input(stage, side):
            if stage == 0:
                if own_metadata:
                    metadata['provenance'] = api.source_context()
                    metadata['records'] = scopes.enter_context(api.warning_scope({}))
            elif stage == 1:
                if 'co2' not in (config.fluid_A.type, config.fluid_B.type):
                    hash((config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm, 128))
                if co2 and chi_error is not None:
                    raise chi_error
            elif stage == 2:
                fluid = getattr(config, 'fluid_' + 'AB'[side])
                speed = 0. if targets is not None or fluid.mass_flow_kg_s is not None else fluid.u_mps
                hash((config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm,
                      speed, fluid.T_in_K, fluid.P_in_Pa, config.sco2_nu,
                      'co2' in (config.fluid_A.type, config.fluid_B.type)))
            elif stage == 3:
                if source._grid_error is not None:
                    raise TypeError(source._grid_error)
            else:
                raise RuntimeError(f'unknown preparation host stage {stage}')

        with native.operation(operation, source, options, host_input, geometry_cache, inlet_cache,
                              observe_range, observe_notice) as result:
            flow = result.flow if hasattr(result, 'flow') else result
            if operation == 'prepare_inlet_mass_capacities':
                return {side: _native_flow._restore(flow.capacities[index]) for index, side in enumerate('AB')}
            resolved = _resolved(config, flow, targets)
            if operation == 'resolve_inlet_flow':
                return resolved
            resolved = ComputeConfig.from_dict(asdict(resolved))
            case = _case(result, resolved, case_id, side_geometry)
            return api._finish_metadata(case, metadata['provenance'], metadata['records']) if own_metadata else case


def prepare_case(config, *, case_id):
    config = ComputeConfig.from_dict(asdict(config))
    return _execute(config, 'prepare_flow_case', case_id=case_id)


def prepare_mass_flow_case(config, targets, *, case_id):
    config = deepcopy(config).validate_static_inputs()
    explicit = (tuple(targets[side] for side in 'AB')
                if all(getattr(config, 'fluid_' + side).mass_flow_kg_s is None for side in 'AB') else None)
    return _execute(config, 'prepare_flow_case', targets=explicit, case_id=case_id, own_metadata=True)


def capacities(config):
    return _execute(config, 'prepare_inlet_mass_capacities')


def resolve(config, *, targets=None):
    return _execute(deepcopy(config).validate_static_inputs(), 'resolve_inlet_flow', targets=targets)
