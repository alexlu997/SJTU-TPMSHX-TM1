"""Manual reproduction of the historical 3D refactor reference (three cases).

The root golden_3d.json and golden_3d.meta.json retain their original values
and environment. This historical bitwise comparison is not a current physical
acceptance gate or a portable cross-platform baseline. Do not rebaseline it
as part of cleanup or performance work.

    python -m sjtu_tpmshx.runs._out._golden_3d --check golden_3d.json

Current tests import configuration from tests.cases_3d, independently of this
tracked historical diagnostic. Capture to a NEW local file when investigating.
"""
import os, sys, json, hashlib
import numpy as np

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


from sjtu_tpmshx.tests.cases_3d import air_air_cfg as _air_air_cfg


def _water_b_cfg(**ov):
    # Full-face air-A + water-B cross-flow (exercises water _build_hv_local_3d).
    return _air_air_cfg(
        u_B=0.5, fluid_type_B='water',
        fluid_B_cfg=dict(dir=3, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        **ov)


def _asym_cfg(**ov):
    # δ≠0 offset-isosurface: ε_A ≠ ε_B via asym_split (audit T5, 2026-07-07 —
    # the asym path previously had behavioural tests but no numeric pin; the
    # old runs/_out/_asym_baseline_3d.json was an orphan with no checker).
    return _air_air_cfg(delta_levelset=0.6, **ov)


_SCALARS = ('Q', 'dP', 'dP_B', 'T_A_out', 'T_B_out',
            'Q_enthalpy_A', 'Q_enthalpy_B', 'Q_sA', 'Q_sB')
_FIELDS = ('Ta', 'Tb', 'Ts', 'vmag', 'vmag_B', 'P_kPa', 'P_Pa_B', 'chi_B')


def _hash(a):
    if a is None:
        return None
    a = np.ascontiguousarray(np.asarray(a, dtype=np.float64))
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def _capture(label, cfg):
    r = _run_3d_stack(cfg)
    out = {'_scalars': {}, '_fields': {}}
    for k in _SCALARS:
        v = r.get(k)
        out['_scalars'][k] = (None if v is None else float(v))
    for k in _FIELDS:
        out['_fields'][k] = _hash(r.get(k))
    return out


def main():
    args = [a for a in sys.argv[1:]]
    check = '--check' in args
    args = [a for a in args if a != '--check']
    path = args[0] if args else None

    cases = {'air_air': _air_air_cfg(), 'water_b': _water_b_cfg(),
             'asym_b': _asym_cfg()}
    got = {name: _capture(name, cfg) for name, cfg in cases.items()}

    if check and path:
        with open(path) as f:
            gold = json.load(f)
        ok = True
        for name in cases:
            for k, v in got[name]['_scalars'].items():
                gv = gold[name]['_scalars'][k]
                if v != gv:
                    print(f"  SCALAR DIFF {name}.{k}: {gv} -> {v}")
                    ok = False
            for k, v in got[name]['_fields'].items():
                gv = gold[name]['_fields'][k]
                if v != gv:
                    print(f"  FIELD HASH DIFF {name}.{k}: {gv} -> {v}")
                    ok = False
        print("GOLDEN: PASS (bit-identical)" if ok else "GOLDEN: FAIL")
        sys.exit(0 if ok else 1)

    blob = json.dumps(got, indent=2)
    print(blob)
    if path:
        with open(path, 'w') as f:
            f.write(blob)
        print(f"[golden] wrote {path}")


if __name__ == '__main__':
    # Pin the convergence criterion (2026-07-13 audit): the pipeline resolves
    # convergence_mode as env > cfg > 'f2' — a stray TPMSHX_CONV_MODE in the
    # shell would silently swap the criterion between capture and check, and
    # a future default flip would silently re-baseline. Pinned HERE, not at
    # module level: importing a historical diagnostic must not write process-wide settings.
    os.environ['TPMSHX_CONV_MODE'] = 'f2'
    main()
