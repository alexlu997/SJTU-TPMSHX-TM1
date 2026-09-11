#!/usr/bin/env python3
"""Read-only validation and inspection of the TM1 project task graph.

Uses only the Python standard library. Does not run project code, change state,
launch agents, invoke git/GitHub, or implement a native Codex graph interface.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


class GraphError(ValueError):
    """An invalid or incomplete task graph."""


def load_graph(root: Path) -> dict[str, Any]:
    path = root / 'graph.json'
    try:
        graph = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GraphError(f'Cannot read {path}: {exc}') from exc
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list):
        raise GraphError('graph.json must be an object containing a nodes array')
    return graph


def index_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for node in graph['nodes']:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str):
            raise GraphError('Each node must be an object with a string id')
        ident = node['id']
        if ident in nodes:
            raise GraphError(f'Duplicate node id: {ident}')
        deps = node.get('depends_on')
        if not isinstance(deps, list) or any(not isinstance(x, str) for x in deps):
            raise GraphError(f'{ident}: depends_on must be a string array')
        if len(deps) != len(set(deps)):
            raise GraphError(f'{ident}: duplicate dependencies')
        nodes[ident] = node
    for ident, node in nodes.items():
        for dep in node['depends_on']:
            if dep not in nodes:
                raise GraphError(f'{ident}: unknown dependency {dep}')
            if dep == ident:
                raise GraphError(f'{ident}: self dependency')
    return nodes


def topology(nodes: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, list[str]], dict[str, int]]:
    children: dict[str, list[str]] = {ident: [] for ident in nodes}
    indegree = {ident: len(node['depends_on']) for ident, node in nodes.items()}
    level = {ident: 0 for ident in nodes}
    for ident, node in nodes.items():
        for dep in node['depends_on']:
            children[dep].append(ident)
    queue = deque(sorted(x for x in nodes if not indegree[x]))
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for child in sorted(children[current]):
            level[child] = max(level[child], level[current] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(nodes):
        rest = ', '.join(sorted(x for x in nodes if indegree[x]))
        raise GraphError(f'Cycle or cycle-dependent nodes: {rest}')
    return order, children, level


def descendants(ident: str, children: dict[str, list[str]]) -> set[str]:
    found: set[str] = set()
    todo = list(children[ident])
    while todo:
        child = todo.pop()
        if child not in found:
            found.add(child)
            todo.extend(children[child])
    return found


def pattern_parts(pattern: str) -> tuple[str, bool]:
    """Only exact relative paths or an explicitly owned terminal /** tree."""
    if not pattern or pattern.startswith('/') or '\\' in pattern or '..' in pattern.split('/'):
        raise GraphError(f'Unsafe ownership pattern: {pattern!r}')
    subtree = pattern.endswith('/**')
    literal = pattern[:-3] if subtree else pattern
    if any(x in literal for x in '*?[]'):
        raise GraphError(f'Unsupported ownership glob (use exact or terminal /**): {pattern}')
    return literal.rstrip('/'), subtree


def patterns_overlap(first: str, second: str) -> bool:
    a, tree_a = pattern_parts(first)
    b, tree_b = pattern_parts(second)
    if a == b:
        return True
    if tree_a and b.startswith(a + '/'):
        return True
    if tree_b and a.startswith(b + '/'):
        return True
    return False


def independent_write_conflicts(nodes: dict[str, dict[str, Any]], children: dict[str, list[str]]) -> list[str]:
    downstream = {ident: descendants(ident, children) for ident in nodes}
    problems: list[str] = []
    ids = sorted(nodes)
    for pos, a in enumerate(ids):
        for b in ids[pos + 1:]:
            # Predecessor->successor overlaps are explicit handovers, not concurrent ownership.
            if b in downstream[a] or a in downstream[b]:
                continue
            for pa in nodes[a]['write_paths']:
                for pb in nodes[b]['write_paths']:
                    if patterns_overlap(pa, pb):
                        problems.append(f'{a} <-> {b}: {pa} overlaps {pb}')
    return problems


def within_root(root: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise GraphError('Artifact paths must be strings')
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise GraphError(f'Artifact outside package: {relative}') from exc
    return path


def load_states(root: Path, nodes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for ident, node in nodes.items():
        path = within_root(root, node['status_file'])
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GraphError(f'{ident}: cannot read state: {exc}') from exc
        if not isinstance(state, dict) or state.get('node_id') != ident:
            raise GraphError(f'{ident}: mismatched state id')
        states[ident] = state
    return states


def validate(root: Path, graph: dict[str, Any]) -> dict[str, Any]:
    nodes = index_nodes(graph)
    required = ('title', 'scope', 'write_paths', 'work_items', 'acceptance',
                'required_evidence', 'resource_needs', 'branch', 'card', 'status_file')
    branches: set[str] = set()
    for ident, node in nodes.items():
        for key in required:
            if not node.get(key):
                raise GraphError(f'{ident}: missing/empty {key}')
        if node['branch'] in branches:
            raise GraphError(f'Duplicate node branch: {node["branch"]}')
        branches.add(node['branch'])
        for pattern in node['write_paths']:
            pattern_parts(pattern)
        card = within_root(root, node['card'])
        if not card.is_file():
            raise GraphError(f'{ident}: missing card {card}')
        text = card.read_text(encoding='utf-8')
        if not text.startswith(f'# {ident}｜'):
            raise GraphError(f'{ident}: card header mismatch')
        # Exact ownership and acceptance must agree between graph and task card.
        for item in node['write_paths'] + node['acceptance']:
            if item not in text:
                raise GraphError(f'{ident}: card and graph disagree on {item!r}')
    order, children, levels = topology(nodes)
    conflicts = independent_write_conflicts(nodes, children)
    if conflicts:
        raise GraphError('Unordered writer conflicts:\n' + '\n'.join(conflicts))
    states = load_states(root, nodes)
    allowed = set(graph['scheduling']['node_states'])
    for ident, state in states.items():
        if state.get('status') not in allowed:
            raise GraphError(f'{ident}: unknown status {state.get("status")!r}')
        if state.get('status') == 'done':
            missing = [d for d in nodes[ident]['depends_on'] if states[d]['status'] != 'done']
            if missing:
                raise GraphError(f'{ident}: done before required dependencies: {missing}')
            if not state.get('evidence'):
                raise GraphError(f'{ident}: done without evidence references')
    # Initial distribution includes one card and state per graph node; no stale cards.
    card_ids = {p.stem for p in (root / 'nodes').glob('*.md')}
    state_ids = {p.stem for p in (root / 'state').glob('*.json')}
    if card_ids != set(nodes) or state_ids != set(nodes):
        raise GraphError('Task card/state files do not match graph node ids')
    return {'nodes': nodes, 'order': order, 'children': children, 'levels': levels, 'states': states}


def print_summary(graph: dict[str, Any], data: dict[str, Any]) -> None:
    nodes, states = data['nodes'], data['states']
    print(f'Goal {graph["goal_id"]} | plan {graph["plan_version"]} | reference {graph["reference_commit"]}')
    print(f'Nodes: {len(nodes)}; dependency edges: {sum(len(n["depends_on"]) for n in nodes.values())}')
    print('Scopes: ' + ', '.join(f'{k}={v}' for k, v in sorted(Counter(n['scope'] for n in nodes.values()).items())))
    print('States: ' + ', '.join(f'{k}={v}' for k, v in sorted(Counter(s['status'] for s in states.values()).items())))
    layers: dict[int, list[str]] = defaultdict(list)
    for ident, depth in data['levels'].items():
        layers[depth].append(ident)
    print('Topological layers (illustrative, not synchronized execution waves):')
    for depth in sorted(layers):
        print(f'  {depth}: {", ".join(sorted(layers[depth]))}')
    print('This is plan metadata only: no numerical or integration test is performed.')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('command', choices=('validate', 'summary', 'ready', 'impact'))
    parser.add_argument('node_id', nargs='?')
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        graph = load_graph(root)
        data = validate(root, graph)
        if args.command == 'validate':
            print('PASS: JSON/schema essentials, unique ids/branches, dependency references, DAG,')
            print('      task card/state parity, declared acceptance parity, independent write ranges, state names.')
            print_summary(graph, data)
        elif args.command == 'summary':
            print_summary(graph, data)
        elif args.command == 'ready':
            ready = [ident for ident in data['order']
                     if data['states'][ident]['status'] not in ('done', 'cancelled', 'running', 'reviewing',
                                                              'ci_pending', 'merge_ready', 'merged_pending_verification')
                     and all(data['states'][d]['status'] == 'done' for d in data['nodes'][ident]['depends_on'])]
            print('Topologically ready (resources, permissions and ownership leases still need checking):')
            for ident in ready:
                node = data['nodes'][ident]
                print(f'  {ident}: {node["title"]} | needs: {", ".join(node["resource_needs"])}')
            if not ready:
                print('  (none)')
        else:
            if args.node_id not in data['nodes']:
                raise GraphError(f'impact requires a valid node id; got {args.node_id!r}')
            affected = descendants(args.node_id, data['children'])
            ordered = [x for x in data['order'] if x in affected]
            print(f'{args.node_id}: hard-dependency descendants ({len(ordered)}): {", ".join(ordered) or "(none)"}')
            print('Unrelated nodes remain schedulable; a shared resource or contract incident may have additional scope.')
        return 0
    except (GraphError, KeyError, TypeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
