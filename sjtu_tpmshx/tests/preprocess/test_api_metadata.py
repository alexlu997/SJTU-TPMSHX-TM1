"""Public preparation preserves case-owned metadata and warning scope."""
from importlib import import_module
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.run_warnings import (
    current_warnings, record_warning, warning_messages, warning_scope,
)
from sjtu_tpmshx.preprocess import api


@pytest.mark.parametrize('entry,module,is_3d', [
    ('prepare_case', 'two_d.preparation', False),
    ('prepare_case', 'three_d.preparation', True),
    ('prepare_quick_design', 'app_modes.quick_design', False),
    ('prepare_screening_2d', 'app_modes.screening_2d', False),
    ('prepare_screening_3d', 'app_modes.screening_3d', True),
])
def test_public_preparation_keeps_metadata_and_warning_ownership(monkeypatch, entry, module, is_3d):
    # Stub only physical preparation; exercise each real public boundary.
    argument = SimpleNamespace(is_3d=is_3d)
    args = (argument,) if entry == 'prepare_case' else (argument, object())
    kwargs = {'case_id': 'boundary'}
    original = CaseData('boundary', metadata={
        'mode_data': {'owned': 7}, 'provenance': {'origin': 'old'},
        'warnings': ('existing', 'duplicate'),
    })
    provenance = {'origin': 'this preparation'}
    events = []
    failure = ValueError('physical preparation failed')
    fail = False
    parent = {('parent',): 'parent notice'}
    enclosing = current_warnings()

    def source_context():
        assert current_warnings() is parent
        events.append('source')
        return provenance

    def prepare(*received_args, **received_kwargs):
        assert received_args == args and received_kwargs == kwargs
        assert current_warnings() is not parent
        assert not current_warnings()
        events.append('prepare')
        record_warning(('first',), 'new first')
        record_warning(('duplicate',), 'duplicate')
        record_warning(('last',), 'new last')
        if fail:
            raise failure
        return original

    monkeypatch.setattr(api, 'source_context', source_context)
    monkeypatch.setattr(import_module('sjtu_tpmshx.preprocess.' + module), entry, prepare)
    with warning_scope(parent):
        result = getattr(api, entry)(*args, **kwargs)
        assert current_warnings() is parent
        assert list(warning_messages(parent)) == ['parent notice']
        assert events == ['source', 'prepare']
        assert result.metadata['mode_data'] == {'owned': 7}
        assert result.metadata['provenance'] == provenance
        assert result.metadata['warnings'] == ('existing', 'duplicate', 'new first', 'new last')
        assert original.metadata['provenance'] == {'origin': 'old'}
        assert original.metadata['warnings'] == ('existing', 'duplicate')

        # A failed preparation must restore its caller's scope and exception.
        fail = True
        events.clear()
        with pytest.raises(ValueError) as caught:
            getattr(api, entry)(*args, **kwargs)
        assert caught.value is failure
        assert events == ['source', 'prepare']
        assert current_warnings() is parent
        assert list(warning_messages(parent)) == ['parent notice']
    assert current_warnings() is enclosing
