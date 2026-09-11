# Result-file unit and dimension declarations

2026-09-11, repair on candidate `6e65b7b`. Independent reviewer `b40_review`
identified two formal HDF5 boundary defects: known fields could declare units
that the reducers do not support, and metadata/grid dimensions could disagree.
The former permits a declared Celsius field to be interpreted as Kelvin; the
latter permits a three-dimensional screening integral to be labelled W/m.

The shared result validator now rejects unsupported units on known consumed
fields and mismatches between grid, metadata dimension and the declared
screening/quick-design mode. Existing W/(m3 K) and W/(m^3 K) spellings remain
accepted. Both public save and load use this validator. Unknown additional
fields retain their existing generic metadata contract; no unit conversion
or solver change is introduced.

Three external-producer HDF5 cases reproduce Celsius, dimension and mode
conflicts through the real loader. Before repair: **3 failed, 2 passed,
native exit 1**, `.cache/result-declaration-before.log`. The original failing
log is preserved. After repair, file/metric tests initially passed 13 tests.
The final combined run including real full 2D/3D three-process handoff,
screening, quick design and VTK readback passed **24 tests in 29.51 s,
native exit 0**, `.cache/result-declaration-integration.log`. Changed-file
Ruff and diff whitespace checks pass. All commands use the configured fixed
interpreter and worktree-local caches.

Independent static re-review confirms that the formal file paths reject both
reported inconsistencies. It does not claim comprehensive validation of the
in-memory public API and did not rerun the numerical tests. This repair is
M-A file-contract work; B40 references, convergence and physical acceptance
remain unchanged.

## Direct in-memory postprocessing follow-up

The same declaration checks now run at `postprocess.evaluate()` entry.
Existing partial metric inputs keep their availability behavior; this does
not impose the complete archive contract on them. Three new direct-evaluate
assertions first failed (3 failed, 2 passed, native exit 1;
`.cache/result-memory-declaration-before.log`). After the shared-helper fix,
IO/metric tests pass 13 tests (native exit 0), and the real three-process,
public screening, public quick-design and VTK tests pass 11 tests in 29.57 s
(native exit 0; `.cache/result-memory-declaration-integration.log`).
Independent static review by `b40_review` found no issue in this bounded diff.
The unchanged 73-package lock and pip check pass.
