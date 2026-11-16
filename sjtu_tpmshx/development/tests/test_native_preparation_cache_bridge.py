"""Check shared cache transport without entering a numerical preparation stage."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.preprocess import native_preparation as bridge_module
from sjtu_tpmshx.shared.domain.compute_config import Sco2NuConfig
from sjtu_tpmshx.shared.domain.run_warnings import RangeRecord, range_context, warning_scope
from sjtu_tpmshx.shared.models import _native_preparation_case as native
from sjtu_tpmshx.shared.models.preparation_cache import scalar_cache


@pytest.fixture
def caches(monkeypatch):
    def numerical(*args, **kwargs):
        pytest.fail('The bridge must not enter a numerical cache function')

    geometry = scalar_cache(maxsize=4)(numerical)
    inlet = scalar_cache(maxsize=4)(numerical)
    monkeypatch.setattr(bridge_module, '_compute_geometry_cached', geometry)
    monkeypatch.setattr(bridge_module, '_compute_cached', inlet)
    return geometry, inlet


def _bridge():
    return bridge_module.PreparationCacheBridge(SimpleNamespace(sco2_nu=Sco2NuConfig()))


def _geometry_key(narrow=False):
    return native._GeometryKey(1, 6., .5,
        native._Kind(32, 1, 1) if narrow else native._Kind(64, 0, 0),
        native._Kind(16, 1, 1) if narrow else native._Kind(64, 0, 0))


def _inlet_key(narrow=False):
    weak = native._Kind(64, 0, 0)
    speed = native._Kind(32, 1, 1) if narrow else weak
    return native._InletKey(_geometry_key(narrow), 0, 5., 380., 101325.,
        native._InletKinds(speed, weak, weak), 0, native._Nu(), 0)


def _inlet_value():
    value = native._InletCache()
    value.geometry = native._GeometryCache(.75, .375, .375, 1200., .002)
    for index, (name, _) in enumerate(native._Properties._fields_):
        setattr(value.properties, name, float(index + 1))
        value.kinds[index] = native._Kind(64, 0, 0)
    value.kinds[bridge_module._PROPERTY_COLUMNS['nu']] = native._Kind(32, 1, 1)
    sample = dict(minimum=(.75, (0, 0, 0)), maximum=(.75, (0, 0, 0)),
                  low=0, high=0, size=1, nonfinite=0)
    record = RangeRecord('air_viscosity', 'T', 'K', [250., 1000.], **sample, last=sample)
    value.evidence, buffers = bridge_module._cache_record_view({('property', 'air_viscosity', (1, 1, 1)): record})
    return value, buffers


def test_geometry_keys_preserve_equal_types_and_unhashable_arrays(caches):
    geometry, _ = caches
    bridge = _bridge()
    source = native._GeometryCache(.75, .375, .375, 1200., .002)
    assert not bridge.geometry_at(0, _geometry_key(True), native._GeometryCache())
    assert not bridge.geometry_at(1, _geometry_key(True), source)
    restored = native._GeometryCache()
    assert bridge.geometry_at(0, _geometry_key(), restored)
    assert bytes(restored) == bytes(source)
    assert geometry.cache_info() == (1, 1, 4, 1)
    key = _geometry_key()
    key.cell_kind = native._Kind(64, 1, 2)
    with pytest.raises(TypeError, match='unhashable'):
        bridge.geometry_at(0, key, native._GeometryCache())
    assert geometry.cache_info() == (1, 1, 4, 1)
    hit, stored = geometry.lookup(('Gyroid', 6., .5, 128))
    assert hit and isinstance(stored['A_0'], np.float64)
    assert not geometry.lookup(('Diamond', 6., .5, 128))[0]


def test_inlet_publication_retains_first_types_and_current_result_geometry(caches):
    _, inlet = caches
    bridge = _bridge()
    value, buffers = _inlet_value()
    assert not bridge.inlet_at(0, _inlet_key(True), native._InletCache())
    assert not bridge.inlet_at(1, _inlet_key(True), value)
    restored = native._InletCache()
    assert bridge.inlet_at(0, _inlet_key(), restored)
    kind = restored.kinds[bridge_module._PROPERTY_COLUMNS['nu']]
    assert (kind.precision, kind.strong, kind.layout) == (32, 1, 1)
    assert inlet.cache_info() == (1, 1, 4, 1)
    del buffers
    assert restored.evidence.range_count == 1 and restored.evidence.ranges[0].rank == 3
    assert native._text(restored.evidence.ranges[0].label) == 'air_viscosity'
    assert bridge_module._records(restored.evidence, restored.evidence.range_bounds_list)
    value.geometry.epsilon = .5
    value.properties.nu = 99.
    value.evidence = restored.evidence
    assert not bridge.inlet_at(1, _inlet_key(), value)
    key = ('Gyroid', 6., .5, 5., 380., 101325., 'air', None, False)
    hit, saved = inlet.lookup(key)
    assert hit and saved[0]['epsilon'] == .75
    assert saved[0]['Nu'] == 7. and isinstance(saved[0]['Nu'], np.float32)
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


def test_notice_and_unbound_range_use_current_warning_scope(monkeypatch, caches):
    bridge = _bridge()
    messages = []
    monkeypatch.setattr(native, '_source_warning',
                        lambda function, message, **kwargs: messages.append((message, kwargs)))
    candidate = 'Gyroid: synthetic notice from the native inlet'
    bridge.observe_notice(0, 0, 99., candidate)
    assert messages == [(candidate, {'call': '_compute_cached'})]
    value, buffers = _inlet_value()
    collected = {}
    with warning_scope(collected), range_context(side='B', stage='inlet', layout='scalar'):
        bridge.observe_notice(0, 0, 99., candidate)
        bridge.observe_notice(1, 1, 0., 'preflight')
        bridge.observe_notice(2, 0, 0., 'geometry')
        bridge.observe_notice(2, 1, 0., 'geometry')
        bridge.observe_range(value.evidence.ranges[0], True, True, None)
    assert len(messages) == 1
    assert collected[('nu_preflight', 'B')] == 'preflight'
    assert bridge.extrap_reasons == ['geometry', 'geometry']
    assert len(collected) == 2
    assert ('property', 'air_viscosity', (1, 1, 1), ('B', 'inlet', 'scalar')) in collected
    assert buffers
