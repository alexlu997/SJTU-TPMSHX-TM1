"""Check real document targets, anchors and command examples."""
import pytest

from scripts.check_docs import check


def test_local_links_anchors_and_module_commands(tmp_path):
    (tmp_path / 'target.md').write_text(
        '# Duplicate\n# Duplicate\n<a id="中文入口"></a>\n# A named heading\n', encoding='utf-8')
    (tmp_path / 'sjtu_tpmshx').mkdir()
    (tmp_path / 'sjtu_tpmshx' / 'cli.py').write_text('pass\n')
    (tmp_path / 'README.md').write_text(
        '[file](target.md)\n[duplicate](target.md#duplicate-1)\n'
        '[unicode](target.md#%E4%B8%AD%E6%96%87%E5%85%A5%E5%8F%A3)\n'
        '[heading](target.md#a-named-heading)\n'
        '[external](https://example.org/not-a-local-file)\n'
        '~~~md\n[example](not-a-real-file.md)\n~~~\n'
        'python -m sjtu_tpmshx.cli\npython -m sjtu_tpmshx.runs.<tool>\n', encoding='utf-8')
    assert check(tmp_path, ['README.md']) == (4, 1)


@pytest.mark.parametrize('body', [
    '[bad](missing.md)',
    '[bad](target.md#missing-anchor)',
    'python -m sjtu_tpmshx.missing_command',
])
def test_invalid_document_reference_fails(tmp_path, body):
    (tmp_path / 'README.md').write_text(body)
    (tmp_path / 'target.md').write_text('# Present\n')
    with pytest.raises(ValueError):
        check(tmp_path, ['README.md'])


def test_inline_code_is_not_a_document_link(tmp_path):
    (tmp_path / 'README.md').write_text('`[sample](missing.md)`')
    assert check(tmp_path, ['README.md']) == (0, 0)
