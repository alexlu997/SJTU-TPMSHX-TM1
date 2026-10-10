"""Opt-in CI shards after normal pytest filters, with an automatic complement."""
import json
from pathlib import Path

import pytest

_COLLECTION = pytest.StashKey[dict]()


def pytest_addoption(parser):
    group = parser.getgroup('ci-shard')
    group.addoption('--ci-shard', type=int, default=None,
                    help='Run a listed group or the final automatic complement.')
    group.addoption('--ci-shard-modules', type=Path, action='append',
                    help='Repeat in shard order; each file lists modules or exact test node IDs.')
    group.addoption('--ci-manifest', help='Directory for per-worker collection JSON.')


def pytest_configure(config):
    shard = config.getoption('ci_shard')
    groups = config.getoption('ci_shard_modules') or [Path(__file__).with_name('_ci_shard0.txt')]
    if shard is not None and not 0 <= shard <= len(groups):
        raise pytest.UsageError(f'--ci-shard must be between 0 and {len(groups)}')
    if shard is not None and not config.getoption('ci_manifest'):
        raise pytest.UsageError('--ci-shard requires --ci-manifest')


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(config, items):
    # The outer wrapper resumes after project heavy marking and pytest -m/-k.
    yield
    if not config.getoption('ci_manifest'):
        return
    shard = config.getoption('ci_shard')
    full = [item.nodeid for item in items]
    if shard is not None:
        paths = config.getoption('ci_shard_modules') or [Path(__file__).with_name('_ci_shard0.txt')]
        groups = [{line.strip() for line in path.read_text(encoding='utf-8').splitlines()
                   if line.strip() and not line.lstrip().startswith('#')} for path in paths]
        kept, removed = [], []
        for item in items:
            module = item.path.relative_to(config.rootpath).as_posix()
            owners = [index for index, group in enumerate(groups)
                      if module in group or item.nodeid in group]
            if len(owners) > 1:
                raise pytest.UsageError(f'CI node belongs to multiple shards: {item.nodeid}')
            owner = owners[0] if owners else len(groups)
            (kept if owner == shard else removed).append(item)
        items[:] = kept
        if removed:
            config.hook.pytest_deselected(items=removed)
    config.stash[_COLLECTION] = dict(
        schema=1, shard=shard, full_nodeids=full,
        selected_nodeids=[item.nodeid for item in items])
    if shard is not None and not items:
        raise pytest.UsageError(f'CI shard {shard} is empty after filtering')


def pytest_sessionfinish(session, exitstatus):
    record = session.config.stash.get(_COLLECTION, None)
    if record is None:  # xdist controller does not collect; only workers write.
        return
    from sjtu_tpmshx.tests.ci_metrics import collect_process_metrics

    worker = getattr(session.config, 'workerinput', {}).get('workerid', 'controller')
    record.update(worker=worker, exitstatus=int(exitstatus),
                  testsfailed=session.testsfailed)
    record['process_metrics'] = collect_process_metrics()
    directory = Path(session.config.getoption('ci_manifest'))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{worker}.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
