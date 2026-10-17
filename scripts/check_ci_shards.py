"""Check complete, disjoint CI shard manifests; Python stdlib only."""
import argparse
import json
from pathlib import Path
from xml.etree import ElementTree


def read_manifest(directory, shard, *, serial=False):
    paths = {path.stem: path for path in Path(directory).glob('*.json')}
    expected = {'controller'} if serial else {'gw0', 'gw1'}
    if set(paths) != expected:
        raise ValueError(f'{directory}: expected manifests for {sorted(expected)}')
    records = []
    for worker, path in sorted(paths.items()):
        record = json.loads(path.read_text(encoding='utf-8'))
        if (record.get('schema') != 1 or record.get('worker') != worker
                or record.get('shard') != shard or record.get('exitstatus') != 0
                or record.get('testsfailed') != 0):
            raise ValueError(f'{path}: wrong shard or unsuccessful pytest session')
        for key in ('full_nodeids', 'selected_nodeids'):
            nodes = record.get(key)
            if (not isinstance(nodes, list) or not nodes
                    or any(not isinstance(node, str) for node in nodes)
                    or len(nodes) != len(set(nodes))):
                raise ValueError(f'{path}: empty, duplicate or invalid {key}')
        full, selected = record['full_nodeids'], record['selected_nodeids']
        if not set(selected) <= set(full):
            raise ValueError(f'{path}: selected nodes outside full collection')
        records.append((full, selected))
    if any(record != records[0] for record in records[1:]):
        raise ValueError(f'{directory}: workers collected different nodes')
    return records[0]


def check(shards, baseline=None, *, serial=False, covered_by=(), omitted_modules=()):
    if covered_by and omitted_modules:
        raise ValueError("Cannot combine native coverage with permitted omissions")
    if len(shards) < 2:
        raise ValueError('at least two shards are required')
    records = [read_manifest(path, index, serial=serial) for index, path in enumerate(shards)]
    full0 = records[0][0]
    selected_all = set()
    if covered_by:
        check(covered_by)
        native_full, _ = read_manifest(covered_by[0], 0)
        selected_all.update(set(native_full).intersection(full0))
    selected_all.update(node for node in full0 if node.split("::", 1)[0] in omitted_modules)
    counts = []
    for full, selected in records:
        if full != full0:
            raise ValueError('shards have different full filtered collections')
        if selected_all.intersection(selected):
            raise ValueError('shards must be disjoint and cover the full filtered collection')
        selected_all.update(selected)
        counts.append(len(selected))
    if selected_all != set(full0):
        raise ValueError('shards must be disjoint and cover the full filtered collection')
    if baseline is not None:
        full, selected = read_manifest(baseline, None, serial=serial)
        if full != full0 or selected != full:
            raise ValueError('baseline does not match the full filtered collection')
    return len(full0), counts


def check_report(directory, suite, *, allow_skips=False):
    directory = Path(directory)
    full, selected = read_manifest(directory / f'{suite}-manifest', None, serial=True)
    if selected != full:
        raise ValueError(f'{directory}: report must cover the full collection')
    report = ElementTree.parse(directory / f'{suite}.xml').getroot()
    cases = list(report.iter('testcase'))
    skips = sum(case.find('skipped') is not None for case in cases)
    failed = (any(case.find('failure') is not None or case.find('error') is not None for case in cases)
              or any(int(group.get('failures', 0)) or int(group.get('errors', 0))
                     for group in report.iter('testsuite')))
    if (len(cases) != len(selected) or failed or skips == len(cases)
            or (skips and not allow_skips)):
        raise ValueError(f'{directory}: incomplete or unsuccessful {suite} report')
    return len(cases), skips


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('shards', type=Path, nargs='+')
    parser.add_argument('--baseline', type=Path)
    coverage = parser.add_mutually_exclusive_group()
    coverage.add_argument('--covered-by', type=Path, nargs='+', default=(),
                          help='Two-worker native shards that cover excluded application tests.')
    coverage.add_argument('--omit-modules', type=Path,
                          help='Exact native module list permitted only for the application tier.')
    parser.add_argument('--bo-report', type=Path)
    parser.add_argument('--integration-report', type=Path)
    parser.add_argument('--serial', action='store_true',
                        help='Require one serial pytest manifest per shard.')
    args = parser.parse_args()
    try:
        omitted = set(args.omit_modules.read_text(encoding='utf-8').splitlines()) if args.omit_modules else ()
        total, counts = check(args.shards, args.baseline, serial=args.serial,
                              covered_by=args.covered_by, omitted_modules=omitted)
        if args.bo_report:
            check_report(args.bo_report, 'bo')
        if args.integration_report:
            check_report(args.integration_report, 'integration', allow_skips=True)
    except (OSError, ValueError, TypeError, KeyError, ElementTree.ParseError) as exc:
        parser.exit(1, f'CI shard manifest check failed: {exc}\n')
    mode = 'permitted omissions' if args.omit_modules else 'native coverage' if args.covered_by else 'full selection'
    print(f'CI collection verified: {total} nodes; selected shard counts {counts}; {mode}')


if __name__ == '__main__':
    main()
