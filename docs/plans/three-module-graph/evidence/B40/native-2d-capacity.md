# Native 2D mass/capacity accounting and engineering qualification

2026-09-11, candidate `a32175f`. This corrects the interpretation of the prior
`2d-boundary-diagnostic.md`: its 23–29% gap belongs to the **thermal kernel's
interpolated capacity flux**, not the native SIMPLE mass boundary multiplied
by the original inlet cp. Both diagnostics are retained. The latter native
constant-cp accounting gives the following actual boundary-minus-exchange
residuals; it is not a variable-cp true-enthalpy or experimental certificate.

| Case and phase | Original-budget native gap W/m | Relative to exchange | F2 engineering gap W/m | Relative to exchange |
| --- | ---: | ---: | ---: | ---: |
| uniform A | 89.50665 | 1.10694% | 91.62704 | 1.13321% |
| uniform B | -66.91331 | 0.82753% | -63.96950 | 0.79115% |
| nonuniform A | 73.15099 | 0.96745% | 74.86888 | 0.99020% |
| nonuniform B | -47.74607 | 0.63146% | -45.41495 | 0.60065% |

`native_2d_capacity.py` uses the existing signed native face-mass mapping,
actual saved rho, physical half-porosity, both face velocity components, and
original per-side inlet cp. It includes all four outward advective terms,
inlet half-cell conduction, and the full interphase source. The raw inlet
capacity agrees with the kernel input. Its boundary temperature convention
is restricted to these full-opening forward-inlet cases. The original
thermal capacity instead uses fixed inlet density with interpolated axial
cell velocities and zeros the cross velocity. These are different fields;
a corrected temperature-form equation residual cannot certify native
boundary conservation.

## Independent engineering controls and native exits

The unchanged 73-package lock and pip check pass. The existing observer now
supports `--engineering` to observe the prepared 2D backend. It sets F2,
SIMPLE budget 800, thermal budget 2000 and explicit Q-relative tolerance
1e-4. All original physical inputs, geometry and one density loop remain.
The observed temperature tolerance remains 0.01 K between chunks. No solver
source or frozen reference is changed. Run from the repository root through
`runpy.run_path` with the configured absolute interpreter and local caches.

The uniform run in `.cache/b40-trace/current-2d-uniform-engineering-v2` and
nonuniform run in `.cache/b40-trace/current-2d-nonuniform-engineering` both
complete with **native exit 0**. Their logs are
`.cache/b40-current-2d-{uniform-engineering-v2,nonuniform-engineering}.log`.
The first direct-script invocation failed import resolution (native exit 1).
A subsequent uniform run completed the solver but failed the observer's
legacy `L_field` assertion (native exit 1); that capture and log remain in
the original uniform-engineering directory. The observer assertion now uses
the prepared `eps_arr` field. The corrected run uses a separate directory;
neither failure is overwritten or counted as a successful native run.

| Case | max A/B momentum residual | max A/B local mass residual | max A/B global mass residual | final relative delta Q |
| --- | ---: | ---: | ---: | ---: |
| uniform | 7.76220e-5 | 1.56417e-8 | 2.59765e-8 | 1.17432e-12 |
| nonuniform | 8.72314e-5 | 4.50788e-9 | 1.21417e-10 | 3.65313e-13 |

All measured F2 momentum/mass and thermal criteria pass. Native mass
transport's integrated T div(m cp) is only -0.00095/-0.00355 W/m for uniform
A/B and below 1.7e-5 W/m for nonuniform. Nevertheless the table's boundary
energy discrepancies persist. They are not explained by insufficient SIMPLE
convergence. The engineering objective tuples are retained in
`native-2d-engineering-capacity.json`; they do not replace approved original
budget references.

B40 remains open for the 2D transport handoff/formulation discrepancy.
A remedy must consistently use actual mass transport and the intended cp
model, then receive numerical/boundary validation. Selecting the existing
variable-cp model-h route would be a distinct model choice and is not silently
applied here. No acceptance tolerance or physical scope is relaxed.

## Fixed-flow constant-cp remedy experiment

`constant_cp_faces.py` reuses `_gs_full_chunk`'s existing conservative mass
transport with coefficients `(cp_in,0,0,0,0)`, hence h=cp_in*T. It keeps the
saved F2 flow, geometry, K, hv and original per-side constant cp. Initialization
uses the saved engineering temperatures; this is an independent warm-start
thermal experiment, not a completed public-chain repair. Both cases converge
at 1000 sweeps within the unchanged 2000-sweep experiment budget, native exit
0 (`.cache/b40-constant-cp-faces.log`). The full local result remains in
`.cache/b40-constant-cp-faces.json`, with compact evidence in
`constant-cp-faces.json`.

| Case | Q W/m | A relative boundary residual | B relative boundary residual |
| --- | ---: | ---: | ---: |
| uniform | 8032.3356494823165 | 1.66216e-12 | 2.89637e-14 |
| nonuniform | 7519.101440023398 | 3.40177e-12 | 2.89597e-14 |

The 2026-09-11 01:51:02 UTC user reply explicitly approved relative delta Q
<1e-4 and each-phase complete boundary residual normalized by max(abs(exchange),
1 W) <1e-4. For the unit-depth 2D experiment the quantities are W/m, with the
same one-metre-depth normalization. Both thermal experiments meet these
comparisons. They do not supersede the original-budget references.

Independent static review confirms the constant-cp meaning, native-face
mapping, retained coefficients and sweep-state update. It supports reuse of
the existing conservative kernel for a minimal 2D screening repair. Remaining
work is the complete cold-start public chain, persisted provenance/status,
independent boundary reduction and affected regression. The internal balance
shares helpers with the solver and is not the sole intended final evidence.
