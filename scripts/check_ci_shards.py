"""Check two complete, disjoint CI shard manifests; Python stdlib only."""
import argparse
import json
from pathlib import Path


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


def check(shard0, shard1, baseline=None, *, serial=False):
    full0, selected0 = read_manifest(shard0, 0, serial=serial)
    full1, selected1 = read_manifest(shard1, 1, serial=serial)
    if full0 != full1:
        raise ValueError('shards have different full filtered collections')
    a, b = set(selected0), set(selected1)
    if a & b or a | b != set(full0):
        raise ValueError('shards must be disjoint and cover the full filtered collection')
    if baseline is not None:
        full, selected = read_manifest(baseline, None, serial=serial)
        if full != full0 or selected != full:
            raise ValueError('baseline does not match the full filtered collection')
    return len(full0), len(a), len(b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('shard0', type=Path)
    parser.add_argument('shard1', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--serial', action='store_true',
                        help='Require one serial pytest manifest per shard.')
    args = parser.parse_args()
    try:
        total, zero, one = check(args.shard0, args.shard1, args.baseline, serial=args.serial)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f'CI shard manifest check failed: {exc}\n')
    print(f'CI shards verified: {total} nodes = {zero} + {one}; collection manifests agree')


if __name__ == '__main__':
    main()
