"""Regenerate the fast-tier heavy-test manifest from a durations census log.

P3.1 (2026-07-20). The manifest (`sjtu_tpmshx/tests/_fast_tier_manifest.txt`)
lists test node-ids whose measured `call` duration is >= the threshold;
`tests/conftest.py` marks them `heavy` at collection time and
`scripts/run_tests_fast.ps1` excludes them (`-m "not heavy"`). CI fast tests
exclude both slow and heavy and run public-module integration separately.

Census input = a full-suite log produced with `--durations=0
--durations-min=0.05` under the target environment.

Usage (repo root)::

    python sjtu_tpmshx/runs/tools/build_fast_tier_manifest.py \
        --log path/to/census.log --threshold 30

The fast tier is a DEVELOPER inner-loop convenience. It is NOT the
verification gate — "before claiming done" remains the FULL suite
(scripts/run_tests_server.ps1). Do not lower the threshold to chase
wall-clock; regenerate only from a fresh census and commit manifest +
census log reference together.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

_DEF_OUT = Path(__file__).resolve().parents[2] / 'tests' / '_fast_tier_manifest.txt'


def parse_call_durations(log_path: Path) -> list[tuple[float, str]]:
    txt = log_path.read_text(encoding='utf-8', errors='replace').replace('\x00', '')
    rows = []
    for m in re.finditer(r'^\s*([0-9.]+)s\s+(call|setup|teardown)\s+(\S+)$', txt, re.M):
        if m.group(2) == 'call':
            rows.append((float(m.group(1)), m.group(3)))
    return sorted(rows, reverse=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='build fast-tier heavy manifest')
    ap.add_argument('--log', required=True, help='durations census log')
    ap.add_argument('--threshold', type=float, default=30.0,
                    help='seconds; call-duration >= this → heavy (default 30)')
    ap.add_argument('--out', default=str(_DEF_OUT))
    args = ap.parse_args(argv)

    rows = parse_call_durations(Path(args.log))
    if not rows:
        raise SystemExit(f'no duration rows parsed from {args.log} — '
                         f'was it produced with --durations=0?')
    heavy = [(t, n) for t, n in rows if t >= args.threshold]
    total = sum(t for t, _ in rows)
    hsum = sum(t for t, _ in heavy)

    lines = [
        '# fast-tier heavy manifest — GENERATED, do not hand-edit.',
        f'# regen: python sjtu_tpmshx/runs/tools/build_fast_tier_manifest.py '
        f'--log <census.log> --threshold {args.threshold:g}',
        f'# census: {args.log} · threshold {args.threshold:g}s · '
        f'{len(heavy)} heavy of {len(rows)} timed tests · '
        f'{hsum:.0f}s of {total:.0f}s call-compute ({100 * hsum / total:.0f}%)',
        '# semantics: conftest marks these nodeids `heavy` at collection; the',
        '# full suite still runs them. Local fast excludes heavy; CI fast excludes',
        '# slow/heavy and runs public-module integration separately. Neither is the full suite.',
    ]
    lines += [n for _, n in heavy]
    Path(args.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'wrote {args.out}: {len(heavy)} heavy nodeids '
          f'(>= {args.threshold:g}s; {100 * hsum / total:.0f}% of call-compute)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
