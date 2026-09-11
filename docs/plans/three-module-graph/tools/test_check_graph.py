"""Unit tests for the package's read-only graph checker; no CFD/project imports."""
from __future__ import annotations

import unittest

import check_graph as cg


def graph_of(*nodes):
    return {'nodes': list(nodes)}


def node(ident, deps=(), paths=()):
    return {'id': ident, 'depends_on': list(deps), 'write_paths': list(paths)}


class GraphCheckerTests(unittest.TestCase):
    def test_diamond_is_acyclic(self):
        nodes = cg.index_nodes(graph_of(node('A'), node('B', ['A']), node('C', ['A']), node('D', ['B', 'C'])))
        order, children, level = cg.topology(nodes)
        self.assertEqual(order[0], 'A')
        self.assertEqual(order[-1], 'D')
        self.assertEqual(level['D'], 2)
        self.assertEqual(cg.descendants('B', children), {'D'})

    def test_missing_dependency_rejected(self):
        with self.assertRaisesRegex(cg.GraphError, 'unknown dependency'):
            cg.index_nodes(graph_of(node('A', ['MISSING'])))

    def test_duplicate_id_rejected(self):
        with self.assertRaisesRegex(cg.GraphError, 'Duplicate'):
            cg.index_nodes(graph_of(node('A'), node('A')))

    def test_cycle_rejected(self):
        nodes = cg.index_nodes(graph_of(node('A', ['B']), node('B', ['A'])))
        with self.assertRaisesRegex(cg.GraphError, 'Cycle'):
            cg.topology(nodes)

    def test_parallel_writer_conflict(self):
        nodes = cg.index_nodes(graph_of(node('A', paths=['src/**']), node('B', paths=['src/core.py'])))
        _, children, _ = cg.topology(nodes)
        self.assertEqual(len(cg.independent_write_conflicts(nodes, children)), 1)

    def test_ordered_handover_allowed(self):
        nodes = cg.index_nodes(graph_of(node('A', paths=['src/**']), node('B', ['A'], ['src/core.py'])))
        _, children, _ = cg.topology(nodes)
        self.assertEqual(cg.independent_write_conflicts(nodes, children), [])

    def test_path_prefix_is_not_directory(self):
        self.assertFalse(cg.patterns_overlap('src/pre/**', 'src/preprocess/api.py'))
        self.assertTrue(cg.patterns_overlap('src/pre/**', 'src/pre/api.py'))

    def test_unsafe_pattern_rejected(self):
        for pattern in ('/root/**', '../src/file.py', 'src/**/api.py'):
            with self.subTest(pattern=pattern), self.assertRaises(cg.GraphError):
                cg.pattern_parts(pattern)


if __name__ == '__main__':
    unittest.main(verbosity=2)
