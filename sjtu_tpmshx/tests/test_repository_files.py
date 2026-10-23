"""Keep repository configuration, resources and documented local paths usable."""
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import pytest
import yaml


_ROOT = Path(__file__).resolve().parents[2]


def test_worktree_include_copies_only_the_root_interpreter_pointer(tmp_path):
    subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q'],
                   cwd=tmp_path, check=True)
    patterns = tmp_path / '.git/info/exclude'
    patterns.parent.mkdir(exist_ok=True)
    patterns.write_text((_ROOT / '.worktreeinclude').read_text(encoding='utf-8'),
                        encoding='utf-8')
    names = ['.venv-path', '.cache/archive/.venv-path',
             'nested/project/.venv-path', '.venv-path.backup']
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('local interpreter\n', encoding='utf-8')
    selected = subprocess.run(
        ['git', '-c', 'core.excludesFile=', 'check-ignore', '--no-index', '--stdin'],
        cwd=tmp_path, input='\n'.join(names) + '\n', text=True,
        capture_output=True, check=True)
    assert selected.stdout.splitlines() == ['.venv-path']


@pytest.fixture(scope='module')
def repository_files():
    result = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=_ROOT, check=True, capture_output=True, text=True,
    )
    paths = [_ROOT / name for name in result.stdout.split('\0') if name]
    assert paths, 'repository file inventory is empty'
    return paths


def test_repository_configuration_and_resources_parse(repository_files):
    parsers = {'.json': json.loads, '.toml': tomllib.loads,
               '.yaml': yaml.safe_load, '.yml': yaml.safe_load, '.svg': ET.fromstring}
    for path in repository_files:
        if path.suffix in parsers:
            try:
                parsers[path.suffix](path.read_text(encoding='utf-8'))
            except (ValueError, yaml.YAMLError, ET.ParseError) as error:
                pytest.fail(f'{path.relative_to(_ROOT)}: {error}')


def test_documented_local_files_exist(repository_files):
    missing = []
    for path in repository_files:
        if path.suffix != '.md':
            continue
        source = path.read_text(encoding='utf-8')
        for match in re.finditer(r'\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)', source):
            target = match.group(1).strip('<>')
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            if not (path.parent / unquote(url.path)).exists():
                line = source.count('\n', 0, match.start()) + 1
                missing.append(f'{path.relative_to(_ROOT)}:{line}: {target}')
    assert not missing, 'missing documented local files:\n' + '\n'.join(missing)
