"""Profiling outputs are isolated without changing the measured call counts."""
from benchmarks.profiling import profile_evaluator


def test_profile_runs_use_separate_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_evaluator, 'OUT_DIR', tmp_path / '.cache' / 'profiling')
    field = object()
    calls = []
    monkeypatch.setattr(profile_evaluator, 'build_field', lambda *args: field)

    def evaluate(x, cfg, cached_field):
        calls.append(cached_field)
        return -100.0, 50.0, None

    monkeypatch.setattr(profile_evaluator, 'evaluate_design', evaluate)
    for _ in range(2):
        profile_evaluator.profile_workload({}, 'eval', repeats=3, wall_repeats=3, callees=5)
    assert calls == [field] * 14  # each run: 1 warmup + 3 profiled + 3 wall-time calls
    outputs = list(profile_evaluator.OUT_DIR.iterdir())
    assert len(outputs) == 2
    for output in outputs:
        assert {path.name for path in output.iterdir()} == {
            'eval_baseline.prof', 'eval_baseline_top30.txt',
            'eval_baseline_tottime.txt', 'eval_baseline_callees.txt',
        }
