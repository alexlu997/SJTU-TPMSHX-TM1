"""Own the cache, warning, and metadata rules shared by full preparation."""
from dataclasses import replace
from functools import partial
import warnings

import numpy as np

from tm1.data_types.compute_config import Sco2NuConfig
from tm1.physical_models.preparation_cache import geometry_cache, inlet_cache, _InletCacheValue
from tm1.physical_models.preparation_notices import range_notices
from tm1.run_control.logutil import get_logger
from tm1.run_control.run_warnings import RangeRecord, current_warnings, record_warning, warning_messages


GEOMETRY = ('epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h')
PROPERTIES = ('rho', 'mu', 'k_f', 'Re', 'Nu', 'K_df', 'cF_df', 'dP_per_L', 'H_sf', 'K_ff')


def geometry_values(values, co2=False):
    return {key: np.float64(value) if co2 or key in ('A_0', 'D_h') else value
            for key, value in zip(GEOMETRY, values, strict=True)}


def prepared_port(direction, centers, widths):
    """Copy the native float64 port windows."""
    result = {'dir': int(direction)}
    for end, center, width in zip(('in', 'out'), centers, widths):
        result[end + '_ctr'] = float(center)
        result[end + '_w'] = float(width)
    return result


def _summary(value):
    return value.minimum if value.scalar else {'min': value.minimum, 'max': value.maximum}


def _source_records(observations, pending):
    """Restore ordered source observations without computing their values."""
    ranges = []
    for key, record in observations:
        message = next(iter(warning_messages({key: record})), None)
        ranges.append((key, record, message))
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
    return {key[:-1] if isinstance(value, RangeRecord) else key: value for key, value in records.items()}


class PreparationCache:
    """Use the model caches at the native stage's lookup and publication checkpoints."""

    def __init__(self, chi_error=None, nominal_grid_warning=None):
        self.chi_error = chi_error
        self.nominal_grid_warning = nominal_grid_warning
        self.inlet_geometry = {}
        self.extrap_reasons = []

    @staticmethod
    def geometry_key(topology, cell, wall):
        return topology, cell, wall, 128

    @staticmethod
    def inlet_key(geometry, speed, temperature, pressure, fluid, settings, co2):
        selection = None
        if settings is not None:
            selection = Sco2NuConfig(mode=('cfd_smooth', 'experimental')[settings.mode],
                alpha_D=settings.alpha[0] if settings.have_alpha[0] else None,
                alpha_G=settings.alpha[1] if settings.have_alpha[1] else None,
                parameter_version=settings.parameter_version, source=settings.source,
                applicability=settings.applicability)
        return (*geometry, speed, temperature, pressure, fluid, selection, co2)

    def geometry(self, action, key, read, write):
        if action:
            geometry_cache.store(key, None, geometry_values(read()))
            hit = False
        else:
            hit, saved = geometry_cache.lookup(key)
            if hit:
                write(lambda index: saved[GEOMETRY[index]])
        if (action or hit) and self.chi_error is not None:
            raise self.chi_error
        return hit

    def inlet(self, action, key, read, write):
        co2 = key[-1] or key[6] == 'co2'
        if not action:
            hit, saved = inlet_cache.lookup(key)
            if hit:
                properties, records = saved
                values = write(lambda index: properties[GEOMETRY[index]],
                               lambda index: properties[PROPERTIES[index]], partial(getattr, saved), records)
                self.inlet_geometry[key] = geometry_values(values, co2)
            return hit
        geometry, values, cp, pr, ranges, messages = read()
        properties = geometry_values(geometry, co2)
        properties.update(zip(PROPERTIES, values, strict=True))
        records = _source_records(ranges, messages)
        inlet_cache.store(key, None, _InletCacheValue(properties, records, cp, pr))
        self.inlet_geometry[key] = geometry_values(geometry, co2)
        return False

    def observe_range(self, key, record, cached, scalar):
        for message in range_notices(key, record, cached, scalar):
            warnings.warn(message, UserWarning)

    def observe_event(self, kind, logger, message, code, replay):
        if kind == 0:
            get_logger(logger.removeprefix('tpmshx.')).info(message)
        elif kind == 1:
            warnings.warn(message, UserWarning)
        elif kind == 2:
            warn = self.floating_warning
            if self.nominal_grid_warning and message in ('nominal-grid-x', 'nominal-grid-y'):
                warn = partial(self.nominal_grid_warning, message[-1])
            replay([code], warn=warn)
        else:
            raise RuntimeError(f'unknown preparation event kind {kind}')

    @staticmethod
    def floating_warning(message):
        warnings.warn(message, RuntimeWarning)

    def observe_notice(self, kind, side, value, message):
        """Use the native notice from the actual inlet topology and fluid."""
        if kind == 1:
            record_warning(('nu_preflight', 'AB'[side]), message)
        elif kind == 2:
            self.extrap_reasons.append(message)
        elif kind == 0:
            if current_warnings() is None and message:
                warnings.warn(message, UserWarning)
        else:
            raise RuntimeError(f'unknown preparation notice kind {kind}')


def model_metadata(evidence, config):
    """Restore model metadata from the shared prepared result views."""
    settings, co2 = evidence
    nu = dict(mode=config.sco2_nu.mode, model_version=settings.model_version)
    if settings.mode:
        nu.update(alpha_D=settings.alpha[0], alpha_G=settings.alpha[1],
                  interpretation=settings.interpretation)
        nu.update({name: getattr(settings, name)
                   for name in ('parameter_version', 'source', 'applicability')})
    else:
        nu['coefficients'] = {name: dict(zip(('c', 'a', 'd'), values))
                              for name, values in settings.coefficients}
    metadata = {'sco2_nu': nu}
    if co2 is not None:
        details = {name: getattr(co2, name) for name in (
            'version', 'application_version', 'pressure_model', 'correction_source', 'property_model', 'common_geometry')}
        details.update({name: getattr(co2, name) for name in (
            'pressure_multiplier', 'scale_K', 'scale_F', 'nu_multiplier', 'nu_floor_multiplier')})
        details.update(sides=[side for index, side in enumerate('AB') if co2.sides[index]],
                       Re_range=list(co2.re_range), Pr_range=list(co2.pr_range))
        metadata['co2'] = details
    return metadata


def resolved_flow_config(config, speeds, targets):
    """Return a config with the native inlet speeds."""
    fluids = {}
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        if targets is not None or fluid.mass_flow_kg_s is not None:
            fluids['fluid_' + side] = replace(fluid, u_mps=speeds[index],
                mass_flow_kg_s=None if targets is not None else fluid.mass_flow_kg_s)
    return replace(config, **fluids).validate(resolved_inlet_speeds=True) if fluids else config


def drag_application_metadata(evidence, inlet_speed):
    """Read the native D-F application record for a saved case."""
    value, extra, extension = evidence
    metadata = {key: _summary(getattr(value, name)) for name, key in (
        ('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
        ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF'))}
    metadata.update(scale_K=value.scale_permeability, scale_F=value.scale_forchheimer,
                    campaign=value.campaign, scope=value.scope)
    for name in ('application_scope', 'fluid'):
        text = getattr(extra, name)
        if text:
            metadata[name] = text
    if extra.calibration:
        metadata['calibration'] = dict(extra.calibration)
    if extra.selection is not None:
        metadata.update(inlet_u_mps=inlet_speed, extrapolated=bool(extra.selection.flags & 2))
        for name, key in (('application_u', 'velocity_window_mps'),
                          ('calibration_u', 'calibration_velocity_window_mps'),
                          ('runtime_u', 'calibration_runtime_velocity_window_mps')):
            values = getattr(extra.selection, name)
            metadata[key] = {'min': values[0], 'max': values[1]}
    if extension is not None:
        for name in ('transfer_policy', 'geometry_application'):
            text = getattr(extension, name)
            if text:
                metadata[name] = text
        if extension.have_reference_geometry:
            metadata['reference_geometry_mm'] = dict(zip(('L', 't'), extension.reference_geometry_mm))
    return metadata
