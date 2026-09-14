"""Manual diagnostic for the historical 2D pipeline refactor cases.

This tracked tool captures two fixed Pipeline2D cases (air-air and air/water-B
cross-flow) and compares supplied snapshots exactly. It originally checked
the retired pipeline stages; the numerical loop now lives under
solvers/backends/python/two_d. It is not a current physical acceptance gate
or a portable cross-platform baseline.

Run from the repository root with the interpreter specified by .venv-path.
Capture to a NEW local file; retain earlier snapshots when investigating:

    python -m sjtu_tpmshx.runs._out._golden_2d .cache/golden-2d-new.json
    python -m sjtu_tpmshx.runs._out._golden_2d --check .cache/golden-2d-new.json

test_asym_porosity_2d imports _air_air_cfg as a configuration helper.
The manual capture/check path is not run by that test.
"""
import os, sys, json, hashlib
import numpy as np

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D


def _air_air_cfg():
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10.0, T_in_K=422.0, P_in_Pa=192362.0),
        fluid_B=FluidConfig(type='air', u_mps=20.0, T_in_K=322.0, P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.182, H_dom_m=0.042),
        solver=SolverConfig(Nx=20, Ny=20),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(),
    )


def _water_b_cfg():
    cc = _air_air_cfg()
    cc.fluid_B = FluidConfig(type='water', u_mps=0.15, T_in_K=300.0,
                             P_in_Pa=101325.0)
    return cc


_SCALARS = ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K')
_FIELDS = ('Ta', 'Tb', 'Ts', 'P_fA', 'P_fB', 'ucA', 'vcA', 'ucB', 'vcB')


def _hash(a):
    if a is None:
        return None
    a = np.ascontiguousarray(np.asarray(a, dtype=np.float64))
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def _capture(cfg):
    res = Pipeline2D(cfg).run()
    out = {'_scalars': {}, '_fields': {}}
    for k in _SCALARS:
        v = getattr(res, k, None)
        out['_scalars'][k] = (None if v is None else float(v))
    f = res.fields
    for k in _FIELDS:
        out['_fields'][k] = _hash(f.get(k))
    return out


def main():
    args = [a for a in sys.argv[1:]]
    check = '--check' in args
    args = [a for a in args if a != '--check']
    path = args[0] if args else None

    cases = {'air_air': _air_air_cfg(), 'water_b': _water_b_cfg()}
    got = {name: _capture(cfg) for name, cfg in cases.items()}

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
        print("GOLDEN-2D: PASS (bit-identical)" if ok else "GOLDEN-2D: FAIL")
        sys.exit(0 if ok else 1)

    blob = json.dumps(got, indent=2)
    print(blob)
    if path:
        with open(path, 'w') as f:
            f.write(blob)
        print(f"[golden-2d] wrote {path}")


if __name__ == '__main__':
    # Pin the convergence criterion (2026-07-13 audit; mirrors _golden_3d.py):
    # The 2D backend resolves convergence_mode as env > cfg > 'f2' — a stray
    # TPMSHX_CONV_MODE in the shell would silently swap the criterion between
    # capture and check. Pinned HERE, not at module level: tests import
    # `_air_air_cfg` from this file, and a module-level env write poisons the
    # whole pytest worker process (measured: 18 unrelated failures).
    os.environ['TPMSHX_CONV_MODE'] = 'f2'
    main()
