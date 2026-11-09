"""并行枚举与串行结果一致 (joblib loky 跨候选)。

候选独立 → 并行 (n_jobs>1) 与串行 (n_jobs=1) 必须给出相同 feasible 集 + best。
用 2 候选小网格 (逆流, 快) 实跑对比, 同时验证 loky 子进程能 import 求解器栈。
"""
import pytest

from sjtu_tpmshx.applications.design.cases import DesignCase
from sjtu_tpmshx.applications.design.select import enumerate_select


def _cases():
    return [DesignCase(1, "air", 688.23, 1_088_700.0, 0.2855,
                       "air", 320.0, 300_000.0, 0.30, None,
                       0.075, 0.05, dT=100.0)]


@pytest.mark.slow  # ~50 s parallel==serial equivalence; serial path covered elsewhere
def test_parallel_matches_serial():
    cs = _cases()
    nodes = {"topo": ["Diamond"], "l": [5.0, 6.0], "t": [0.5]}   # 2 候选
    feas_s, best_s = enumerate_select(cs, "counter", nodes, n_jobs=1)
    feas_p, best_p = enumerate_select(cs, "counter", nodes, n_jobs=2)

    assert len(feas_s) == len(feas_p)
    vs = sorted(d.V for d in feas_s)
    vp = sorted(d.V for d in feas_p)
    assert all(abs(a - b) < 1e-9 for a, b in zip(vs, vp))

    if best_s is not None:
        assert best_p is not None
        assert best_p.topo == best_s.topo
        assert abs(best_p.l - best_s.l) < 1e-9
        assert abs(best_p.t - best_s.t) < 1e-9
        assert abs(best_p.V - best_s.V) < 1e-9
