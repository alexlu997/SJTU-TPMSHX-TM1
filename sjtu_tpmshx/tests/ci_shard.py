"""Opt-in, module-preserving CI shards after the normal pytest filters."""
import json
from pathlib import Path

import pytest

_COLLECTION = pytest.StashKey[dict]()


def pytest_addoption(parser):
    group = parser.getgroup('ci-shard')
    group.addoption('--ci-shard', type=int, choices=(0, 1), default=None,
                    help='Run listed modules (0) or their automatic complement (1).')
    group.addoption('--ci-manifest', help='Directory for per-worker collection JSON.')


def pytest_configure(config):
    if config.getoption('ci_shard') is not None and not config.getoption('ci_manifest'):
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
        modules = {line.strip() for line in
                   Path(__file__).with_name('_ci_shard0.txt').read_text().splitlines()
                   if line.strip() and not line.lstrip().startswith('#')}
        kept, removed = [], []
        for item in items:
            listed = item.path.relative_to(config.rootpath).as_posix() in modules
            (kept if listed == (shard == 0) else removed).append(item)
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
