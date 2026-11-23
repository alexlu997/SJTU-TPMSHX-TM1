"""Check shared cache transport without entering a numerical preparation stage."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface._native_values import read_text
from sjtu_tpmshx.cpp_interface import preparation_host as bridge_module
from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig
from sjtu_tpmshx.run_control.run_warnings import RangeRecord, range_context, warning_scope
from sjtu_tpmshx.cpp_interface import _native_preparation_case as native
from sjtu_tpmshx.physical_models.preparation_cache import scalar_cache


@pytest.fixture
def caches(monkeypatch):
    def numerical(*args, **kwargs):
        pytest.fail('The bridge must not enter a numerical cache function')

    geometry = scalar_cache(maxsize=4)(numerical)
    inlet = scalar_cache(maxsize=4)(numerical)
    monkeypatch.setattr(bridge_module, 'geometry_cache', geometry)
    monkeypatch.setattr(bridge_module, 'inlet_cache', inlet)
    return geometry, inlet


def _bridge():
    return bridge_module.PreparationCacheBridge(SimpleNamespace(sco2_nu=Sco2NuConfig()))


def _geometry_key():
    return native._GeometryKey(1, 6., .5)


def _inlet_key():
    return native._InletKey(_geometry_key(), 0, 5., 380., 101325., 0, native._Nu(), 0)


def _inlet_value():
    value = native._InletCache()
    value.geometry = native._GeometryCache(.75, .375, .375, 1200., .002)
    for index, (name, _) in enumerate(native._Properties._fields_):
        setattr(value.properties, name, float(index + 1))
    sample = dict(minimum=(.75, (0, 0, 0)), maximum=(.75, (0, 0, 0)),
                  low=0, high=0, size=1, nonfinite=0)
    record = RangeRecord('air_viscosity', 'T', 'K', [250., 1000.], **sample, last=sample)
    value.evidence, buffers = bridge_module._cache_record_view({('property', 'air_viscosity', (1, 1, 1)): record})
    return value, buffers


def test_geometry_keys_round_trip_float64_entries(caches):
    geometry, _ = caches
    bridge = _bridge()
    source = native._GeometryCache(.75, .375, .375, 1200., .002)
    assert not bridge.geometry_at(0, _geometry_key(), native._GeometryCache())
    assert not bridge.geometry_at(1, _geometry_key(), source)
    restored = native._GeometryCache()
    assert bridge.geometry_at(0, _geometry_key(), restored)
    assert bytes(restored) == bytes(source)
    assert geometry.cache_info() == (1, 1, 4, 1)
    hit, stored = geometry.lookup(('Gyroid', 6., .5, 128))
    assert hit and isinstance(stored['A_0'], np.float64)
    assert not geometry.lookup(('Diamond', 6., .5, 128))[0]


def test_inlet_publication_retains_float64_values_and_current_result_geometry(caches):
    _, inlet = caches
    bridge = _bridge()
    value, buffers = _inlet_value()
    assert not bridge.inlet_at(0, _inlet_key(), native._InletCache())
    assert not bridge.inlet_at(1, _inlet_key(), value)
    restored = native._InletCache()
    assert bridge.inlet_at(0, _inlet_key(), restored)
    assert restored.properties.nu == 7.
    assert inlet.cache_info() == (1, 1, 4, 1)
    del buffers
    assert restored.evidence.range_count == 1 and restored.evidence.ranges[0].rank == 3
    assert read_text(restored.evidence.ranges[0].label) == 'air_viscosity'
    assert bridge_module._records(restored.evidence, restored.evidence.range_bounds_list)
    value.geometry.epsilon = .5
    value.properties.nu = 99.
    value.evidence = restored.evidence
    assert not bridge.inlet_at(1, _inlet_key(), value)
    key = ('Gyroid', 6., .5, 5., 380., 101325., 'air', None, False)
    hit, saved = inlet.lookup(key)
    assert hit and saved[0]['epsilon'] == .75
    assert saved[0]['Nu'] == 7. and isinstance(saved[0]['Nu'], float)
    assert bridge.inlet_geometry[key]['epsilon'] == .5


def test_absent_nu_and_default_nu_keep_separate_inlet_entries(caches):
    _, inlet = caches
    bridge = _bridge()
    value, buffers = _inlet_value()
    zone = _inlet_key()
    nominal = _inlet_key()
    nominal.have_sco2_nu = 1
    for key in (zone, nominal):
        assert not bridge.inlet_at(0, key, native._InletCache())
        assert not bridge.inlet_at(1, key, value)
    assert inlet.cache_info() == (0, 2, 4, 2)
    assert inlet.lookup(('Gyroid', 6., .5, 5., 380., 101325., 'air', None, False))[0]
    assert inlet.lookup(('Gyroid', 6., .5, 5., 380., 101325., 'air', Sco2NuConfig(), False))[0]
    assert buffers


def test_geometry_publication_precedes_later_chi_error(caches):
    geometry, _ = caches
    error = ValueError('synthetic chi error')
    bridge = bridge_module.PreparationCacheBridge(SimpleNamespace(), error)
    with pytest.raises(ValueError) as caught:
        bridge.geometry_at(1, _geometry_key(), native._GeometryCache(.75, .375, .375, 1200., .002))
    assert caught.value is error
    assert geometry.lookup(('Gyroid', 6., .5, 128))[0]


def test_notice_and_unbound_range_use_current_warning_scope(caches):
    import warnings
    bridge = _bridge()
    candidate = 'Gyroid: synthetic notice from the native inlet'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        bridge.observe_notice(0, 0, 99., candidate)
    assert [(item.category, str(item.message)) for item in caught] == [(UserWarning, candidate)]
    value, buffers = _inlet_value()
    collected = {}
    with warnings.catch_warnings(record=True) as scoped_caught:
        warnings.simplefilter('always')
        with warning_scope(collected), range_context(side='B', stage='inlet', layout='scalar'):
            bridge.observe_notice(0, 0, 99., candidate)
            bridge.observe_notice(1, 1, 0., 'preflight')
            bridge.observe_notice(2, 0, 0., 'geometry')
            bridge.observe_notice(2, 1, 0., 'geometry')
            bridge.observe_range(value.evidence.ranges[0], True, True, None)
    assert not scoped_caught
    assert collected[('nu_preflight', 'B')] == 'preflight'
    assert bridge.extrap_reasons == ['geometry', 'geometry']
    assert len(collected) == 2
    assert ('property', 'air_viscosity', (1, 1, 1), ('B', 'inlet', 'scalar')) in collected
    assert buffers
