"""Prepare a Quick Design case and query its inlet pressure fractions."""
from dataclasses import asdict
from functools import partial
import inspect
from types import SimpleNamespace
import warnings

import numpy as np

from tm1.cpp_interface.quick_preparation import run_preparation
from tm1.data_types.model_refs import ModelRef
from tm1.model_configs.model_parameters import MODEL_VERSIONS, fixed_geometry_error, load_quick_design_parameters
from tm1.physical_models import fluid_props as registry, tpms_geometry
from tm1.physical_models.df_surrogate.backend import resolve_method
from tm1.run_control.run_environment import _resolve_chi_s, capture_environment
from tm1.run_control.run_warnings import range_context, record_range


_Parameters = load_quick_design_parameters()
K_STEEL, LTNE_TOL = _Parameters['k_s'], _Parameters['tol']
_FLUIDS = ('air', 'water', 'sco2', 'co2')


def _bind_pressure_options(compressible, options):
    from tm1.physical_models.df_surrogate import predict as df

    function = df.predict_dP_compressible if compressible else df.predict_dP
    try:
        bound = inspect.signature(function).bind(*([None] * (9 if compressible else 8)), **options)
    except TypeError as problem:
        message = str(problem)
        if message.startswith('multiple values for argument'):
            message = 'got ' + message
        raise TypeError(f'{function.__name__}() {message}') from None
    bound.apply_defaults()
    return bound.arguments['method'], bound.arguments.get('strict', False)


def _fluid_name(fluid):
    name = fluid.strip().lower() if type(fluid) is str else None
    return name if name in _FLUIDS else registry.get(fluid).name


def _record_inlet(state, fluid, pressure, replay_events):
    events, limited, outlet_squared = pressure
    replay_events(events)
    if fluid == 'air' and limited:
        from tm1.physical_models.df_surrogate.predict import _record_pressure_limit
        _record_pressure_limit(state.topo, state.l, state.t, outlet_squared, state.strict)


def _observe(state, warn, ranges, events, pressures, collect, replay_events):
    from tm1.physical_models.tpms_props import _range_notice

    for label, side, bounds, temperature in ranges:
        name = label.decode('utf-8')
        values = np.asarray(temperature, dtype=float)
        with range_context(side='AB'[side], stage='design-dp-inlet', layout='scalar'):
            if record_range(('property', name), values, bounds, label=name, quantity='T', unit='K', collect=collect):
                continue
        message = _range_notice(name, temperature, temperature, *bounds)
        if message is not None:
            warn(message, UserWarning)
    replay = partial(replay_events, warn=warn)
    replay(events)
    for fluid, pressure in zip(state.fluids, pressures):
        _record_inlet(state, fluid, pressure, replay)


def _operation(state, warn):
    return run_preparation(state, observe=partial(_observe, state, warn))


def _state(case, topo, l, t, s, length, arrangement, height, *, init, conductivity, prop_model,
           tolerance, df_options, full):
    if topo not in tpms_geometry.TOPOLOGIES:
        raise ValueError(f"tpms_type must be 'Diamond' or 'Gyroid', got '{topo}'")
    try:
        float(l), float(t)
    except (TypeError, ValueError) as problem:
        raise ValueError(fixed_geometry_error()) from problem
    if init is not None:
        registry.check_finite_temperatures(*init, where='design external warm start')
    fluids = tuple(_fluid_name(getattr(case, name)) for name in ('hot_fluid', 'cold_fluid'))
    for fluid, pressure in zip(fluids, (case.P_in_h, case.P_in_c)):
        if fluid == 'sco2':
            registry._require_sco2_pressure(pressure)
        elif fluid == 'co2' and pressure is None:
            raise ValueError('CO2 requires absolute pressure P in Pa')
    strict = False
    if full:
        df_options = dict(method=resolve_method())
    else:
        options = dict(df_options or {})
        for fluid in fluids:
            method, selected = _bind_pressure_options(fluid == 'air', options)
            resolve_method(method)
            strict = strict or (fluid == 'air' and bool(selected))
    height = s if height is None else height
    values = (l, t, s, length, height, conductivity if full else K_STEEL, tolerance,
              case.mdot_h, case.mdot_c, case.T_in_h, case.T_in_c, case.P_in_h, case.P_in_c)
    return SimpleNamespace(case=case, topo=topo, l=l, t=t, s=s, length=length, height=height,
        arrangement=arrangement, prop_model=prop_model, init=init, fluids=fluids, values=values,
        chi=_resolve_chi_s(), strict=strict, df_options=df_options, full=full)


def prepare_values(case, topo, l, t, s, Lx, arrangement='cross', *, init=None,
                   k_s=K_STEEL, prop_model='const', tol=LTNE_TOL, height=None):
    """Return copied native fields and detached host snapshots for CaseData."""
    state = _state(case, topo, l, t, s, Lx, arrangement, height, init=init, conductivity=k_s,
                   prop_model=prop_model, tolerance=tol, df_options=None, full=True)
    output = _operation(state, lambda message, category=RuntimeWarning: warnings.warn(message, category))
    grid = dict(dimension=3, length_unit='m', axis_order=('x', 'y', 'z'))
    for axis, (widths, edges) in zip('xyz', output.axes):
        grid['d' + axis] = widths
        grid[axis + '_edges'] = edges
    fields = dict(eps=output.epsilon, eps_A=output.epsilon_a, K_ss=output.solid_conductivity)
    c = output.controls
    controls = dict(dirB=c.dir_b, alpha=c.alpha, maxit=c.max_iterations,
                    qtol=c.q_relative_tolerance if c.have_q_relative_tolerance else None,
                    chunk=c.chunk_iterations if c.have_chunk_iterations else None)
    fractions = output.fractions
    state.units = output.cell_length_m, output.wall_thickness_m
    state.geometry = dict(A_0=np.float64(output.area_density_per_m),
                          D_h=np.float64(output.hydraulic_diameter_m))
    state.config = asdict(case)
    state.operating = {name: getattr(case, name) for name in
        ('hot_fluid', 'cold_fluid', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c', 'mdot_h', 'mdot_c')}
    state.environment = capture_environment()
    state.model_refs = (ModelRef('quick_design', MODEL_VERSIONS['quick_design']),
        ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.hot_fluid}),
        ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.cold_fluid}))
    return state, grid, fields, controls, fractions


def pressure_fractions(case, topo, l, t, s, Lx, arrangement='cross', height=None, *, df_options=None):
    """Query analytical inlet pressure fractions without allocating thermal fields."""
    state = _state(case, topo, l, t, s, Lx, arrangement, height, init=None, conductivity=K_STEEL,
                   prop_model='const', tolerance=LTNE_TOL, df_options=df_options, full=False)
    return _operation(state, lambda message, category=RuntimeWarning: warnings.warn(message, category))


def prepare_quick_design(case, topo, l, t, s, Lx, arrangement='cross', *,
                         case_id, init=None, k_s=K_STEEL, prop_model='const',
                         tol=LTNE_TOL, height=None):
    from tm1.data_types.case_data import CaseData
    state, grid, fields, controls, fractions = prepare_values(
        case, topo, l, t, s, Lx, arrangement, init=init, k_s=k_s,
        prop_model=prop_model, tol=tol, height=height)
    return CaseData(
        case_id=case_id, config_snapshot=state.config, grid=grid, design_fields=fields,
        parameters=dict(operating_point=state.operating, topology=topo,
                        L_cell_m=state.units[0], t_wall_m=state.units[1], Lx=Lx,
                        s=s, height=state.height, k_s=k_s,
                        A_0=state.geometry['A_0'], D_h=state.geometry['D_h'],
                        arrangement=arrangement, prop_model=prop_model, tol=tol,
                        controls=controls, initial_fields=init, df_options=state.df_options,
                        _environment=state.environment,
                        inlet_pressure_fractions=dict(zip(('A', 'B'), fractions))),
        model_refs=state.model_refs,
        metadata=dict(mode='quick_design', model='plug_ltne_analytic_dp_v1',
                      quantity_basis='total', geometry_resolution=_Parameters['geometry_resolution'],
                      thermal_kernel=('2d_delegation' if fields['eps'].shape[2] == 1 else '3d'),
                      applicability='Sizing approximation; prescribed velocity, analytical inlet-state dP; not full SIMPLE or experimental validation.'))
