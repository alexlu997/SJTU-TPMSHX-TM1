"""Check the ComputeConfig JSON archive writer."""
import json

import pytest

from tm1.file_io import config_io, text_file


DATA = {'name': '噜噜', 'values': [1, 2.5, None], 'nested': {'flag': True}}


def test_write_json_keeps_text_format(tmp_path):
    path, reference = tmp_path / 'config.json', tmp_path / 'reference.json'
    config_io.write_json(path, DATA)
    # The previous in-place writer gives the reference bytes, with the platform newline.
    reference.write_text(json.dumps(DATA, indent=2, ensure_ascii=False), encoding='utf-8')
    assert path.read_bytes() == reference.read_bytes()
    assert config_io.read_json(path) == DATA


@pytest.mark.parametrize('stage', ['write', 'replace'])
def test_failed_write_json_keeps_previous_file(tmp_path, monkeypatch, stage):
    path = tmp_path / 'config.json'
    config_io.write_json(path, {'old': 1})
    previous = path.read_bytes()

    close = text_file.os.close

    def fail(target, *args, **kwargs):
        if stage == 'write':
            close(target)
        raise OSError('write failed')

    monkeypatch.setattr(text_file.os, 'fdopen' if stage == 'write' else 'replace', fail)
    with pytest.raises(OSError, match='write failed'):
        config_io.write_json(path, {'new': 2})
    assert path.read_bytes() == previous
    assert [item.name for item in tmp_path.iterdir()] == ['config.json']
