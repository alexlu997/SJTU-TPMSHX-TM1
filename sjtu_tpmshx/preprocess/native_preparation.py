"""Share host cache and evidence transport for native preparation stages."""
import ctypes as ct

import numpy as np

from sjtu_tpmshx.shared.domain.compute_config import Sco2NuConfig
from sjtu_tpmshx.shared.domain.run_warnings import (
    RangeRecord, current_warnings, merge_warnings, warning_messages, record_warning, _range_context,
)
from sjtu_tpmshx.shared.models import _native_flow, _native_preparation_case as native
from sjtu_tpmshx.shared.models.tpms_geometry import _TOPOLOGIES, _compute_geometry_cached
from sjtu_tpmshx.shared.models.tpms_calc import _compute_cached, _InletCacheValue


__all__ = [
    'PreparationCacheBridge', 'model_metadata', '_sample', '_range_record', '_records',
    '_geometry_values', '_cache_record_view', '_GEOMETRY_NAMES', '_PROPERTY_NAMES', '_kind', '_flow_kind', '_summary',
]


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


def _summary(value):
    return value.minimum if value.scalar else {'min': value.minimum, 'max': value.maximum}


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
    """Restore ordered source observations without computing their values."""
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
_PROPERTY_COLUMNS = {name: index for index, (name, _) in enumerate(native._Properties._fields_)}


def _geometry_values(value, co2=False):
    return {key: (np.float64(getattr(value, name)) if co2 or key in ('A_0', 'D_h') else getattr(value, name))
            for name, key in _GEOMETRY_NAMES}


def _cache_record_view(records):
    """Keep copied cache evidence alive until the native stage returns."""
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


def _geometry_key(value):
    return (_TOPOLOGIES[value.topology], native._restore(value.cell_length_mm, value.cell_kind),
            native._restore(value.wall_thickness_mm, value.wall_kind), 128)


def _inlet_key(value):
    selection = None
    if value.have_sco2_nu:
        selected = value.sco2_nu
        selection = Sco2NuConfig(
            mode=('cfd_smooth', 'experimental')[selected.mode],
            alpha_D=selected.alpha[0] if selected.have_alpha[0] else None,
            alpha_G=selected.alpha[1] if selected.have_alpha[1] else None,
            **{name: native._text(getattr(selected, name))
               for name in ('parameter_version', 'source', 'applicability')})
    return (*_geometry_key(value.geometry)[:3],
            native._restore(value.velocity_m_s, value.kinds.velocity),
            native._restore(value.temperature_K, value.kinds.temperature),
            native._restore(value.pressure_Pa, value.kinds.pressure),
            native._FLUIDS[value.fluid], selection, bool(value.co2_geometry))


class PreparationCacheBridge:
    """Transport completed native values through the existing scalar caches.

    Keep one bridge for each native call. It owns callback buffers and the
    last geometry observed for each inlet key. The scalar caches own entries.
    """

    def __init__(self, config, chi_error=None):
        self.config = config
        self.chi_error = chi_error
        self.buffers = []
        self.inlet_geometry = {}
        self.extrap_reasons = []
        self._active_inlet_key = None

    def geometry_at(self, action, key, value):
        """Look up or store the actual typed geometry key."""
        cache_key = _geometry_key(key)
        if action:
            _compute_geometry_cached.store(cache_key, None, _geometry_values(value))
            hit = False
        else:
            hit, saved = _compute_geometry_cached.lookup(cache_key)
            if hit:
                for name, field in _GEOMETRY_NAMES:
                    setattr(value, name, saved[field])
        if (action or hit) and self.chi_error is not None:
            raise self.chi_error
        return hit

    def inlet_at(self, action, key, value):
        """Transport inlet values and evidence without a numerical cache call."""
        cache_key = _inlet_key(key)
        self._active_inlet_key = cache_key
        co2 = bool(key.co2_geometry) or native._FLUIDS[key.fluid] == 'co2'
        if not action:
            hit, saved = _compute_cached.lookup(cache_key)
            if not hit:
                return False
            properties, records = saved
            for name, field in _GEOMETRY_NAMES:
                setattr(value.geometry, name, properties[field])
            for name, field in (*_PROPERTY_NAMES, ('cp', None), ('pr', None)):
                scalar = properties[field] if field is not None else getattr(saved, name)
                setattr(value.properties, name, scalar)
                value.kinds[_PROPERTY_COLUMNS[name]] = _kind(scalar)
            value.evidence, buffers = _cache_record_view(records)
            self.buffers.extend(buffers)
            self.inlet_geometry[cache_key] = _geometry_values(value.geometry, co2)
            return True
        properties = _geometry_values(value.geometry, co2)
        for name, field in _PROPERTY_NAMES:
            properties[field] = native._restore(getattr(value.properties, name), value.kinds[_PROPERTY_COLUMNS[name]])
        bound = _records(value.evidence, value.evidence.range_bounds_list)
        records = {key[:-1] if isinstance(record, RangeRecord) else key: record for key, record in bound.items()}
        _compute_cached.store(cache_key, None,
            _InletCacheValue(properties, records, value.properties.cp, value.properties.pr))
        self.inlet_geometry[cache_key] = _geometry_values(value.geometry, co2)
        return False

    def observe_range(self, value, bounds_list, cached, scalar):
        """Replay source records and the original standalone warning filters."""
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
        elif source[0] in ('nu', 'nu_pr') and native._text(value.stage) in ('inlet', 'unbound'):
            fluid, topology = source[1:]
            if fluid == 'air':
                notices = nu_correlations._extrap_notices(topology, scalar, scalar)
                origin = fluid_props._nu_air
            elif fluid == 'water':
                notices = nu_correlations._water_nu_notices(scalar, scalar, topology)
                origin = fluid_props._nu_water
            elif fluid == 'sco2':
                notices = nu_correlations._sco2_nu_notices(scalar, scalar, topology)
                selection = self._active_inlet_key[7] if self._active_inlet_key is not None else self.config.sco2_nu
                origin = (nu_correlations.nu_sco2_selected if selection is not None and selection.mode != 'cfd_smooth'
                          else nu_correlations.nu_sco2_topo)
            else:
                notices = ([co2_correlations._calibration_notice(record.quantity, record.bounds)]
                           if scalar < record.bounds[0] or scalar > record.bounds[1] else [])
                origin = fluid_props._nu_co2
            for notice in notices:
                native._source_warning(origin, notice)

    def observe_notice(self, kind, side, value, message):
        """Use the native notice from the actual inlet topology and fluid."""
        if kind == 1:
            record_warning(('nu_preflight', 'AB'[side]), message)
        elif kind == 2:
            self.extrap_reasons.append(message)
        elif kind == 0:
            if current_warnings() is None and message:
                from sjtu_tpmshx.shared.models import tpms_calc
                native._source_warning(tpms_calc.compute, message, call='_compute_cached')
        else:
            raise RuntimeError(f'unknown preparation notice kind {kind}')


def model_metadata(value, settings, config):
    """Restore model metadata from the shared prepared result views."""
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
