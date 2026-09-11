# 3D native-mass integral-enthalpy audit

Subsequent decision: the user explicitly approved applying the existing native
mass/air integral-enthalpy model only to this 3D air-air screening path, retaining
original results and requiring separate reference disposition. The audit below
describes the pre-repair model; approval alone does not pass acceptance.

Offline supplement to saved `054dc96` engineering-budget captures, no new PDE.
Reproducer: `native_3d_enthalpy.py`, invoked with the two directories from
`current-engineering-budget.md`. Full reduction is `native-3d-enthalpy.json`.

The reducer maps the retained raw SIMPLE staggered faces and density into real
coordinates, uses the existing face-mass convention and evaluates the existing
air cp(T) integral directly. It includes physical inlet half-cell conduction
and compares the outward energy with signed solid-to-fluid exchange. These
cases have forward full-face inlets and zero flow at other exterior walls.

| Case | A gap W | A relative gap | B gap W | B relative gap |
| --- | ---: | ---: | ---: | ---: |
| uniform | 9.945710426287349 | 0.03671659891882218 | -13.594608202069026 | 0.050187242079417195 |
| nonuniform | 16.008629589319924 | 0.049298235270588464 | -13.456097242948431 | 0.04143776605023485 |

All four exceed the approved 1e-4 boundary-energy threshold. These are total W
for actual 0.042 m depth, not the optimizer's W/m objective. Earlier temperature
capacity balance remains valid as an equation diagnostic but does not establish
this native-mass/enthalpy boundary balance. Both historical engineering runs
remain preserved with their native exits and convergence flags.

The current screen passes relaxed rho*cp(T) and staggered velocities to its
temperature-form kernel. The production kernel already has a native-mass air
integral-enthalpy route, but this screening call does not select it. Applying
that model to 3D requires a clear model decision; the previous explicit choice
was made for 2D. No 3D solver or frozen reference is changed by this audit.

Separately, `native-model-h-solid.json` completes the new 2D candidate's solid
calculation: global signed residuals are -5.8171e-8 / -6.8296e-8 W/m and L1
relative residuals 7.3157e-12 / 9.1300e-12 for uniform/nonuniform. Those results
do not fill the remaining 3D fluid-energy gap.
