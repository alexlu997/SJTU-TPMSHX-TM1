Source provenance for the native classical AMG implementation.

- [PyAMG v5.3.0](https://github.com/pyamg/pyamg/tree/074024b792a7024a68b2b3028aae256a60acf043),
  commit `074024b792a7024a68b2b3028aae256a60acf043`, MIT.
- [SciPy v1.17.1](https://github.com/scipy/scipy/tree/527eb7fd7953a1de068f94bf8b322f249b9405ae),
  commit `527eb7fd7953a1de068f94bf8b322f249b9405ae`, BSD-3-Clause.
- [SciPy v1.18.1](https://github.com/scipy/scipy/tree/e4e854eaa8f18d807cd3496028e257e36caa93cc),
  commit `e4e854eaa8f18d807cd3496028e257e36caa93cc`, BSD-3-Clause, for the updated `pinv` expression.

Only the following existing algorithm functions are included, from the pinned
versions listed below. This is no runtime Python binding
or new binary dependency. Full upstream files were inspected in ignored cache;
the distributed header contains only these functions. Binding-only size
parameters are marked maybe_unused, numerical operation order is unchanged,
and NumPy's integer aliases use standard C++ equivalents.

- `classical_strength_of_connection_abs`: `pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:63-111`
- `rs_cf_splitting`: `pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:284-463`
- `rs_classical_interpolation_pass1`: `pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:1082-1103`
- `remove_strong_FF_connections`: `pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:1132-1181`
- `rs_classical_interpolation_pass2`: `pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:1238-1383`
- `gauss_seidel`: `pyamg-v5.3.0/pyamg/amg_core/relaxation.h:48-76`
- `csr_has_canonical_format`: `scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:325-340`
- `csr_tocsc`: `scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:418-462`
- `csr_matmat_maxnnz`: `scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:562-601`
- `csr_matmat`: `scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:607-669`
- `csr_binop_csr_general`: `scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:691-763`
- `csr_binop_csr_canonical`: `scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:781-855`
- `csr_binop_csr`: `scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:889-907`

`src/classical_amg.cpp` translates the orchestration in PyAMG's
`classical/classical.py`, `classical/interpolate.py`, `classical/split.py`,
`strength.py`, and `multilevel.py`, plus SciPy's
`sparse/linalg/_isolve/iterative.py:bicgstab`. Coarse solves retain SciPy
1.18.1 `linalg/_basic.py:pinv`'s rank threshold and expression order,
`Vh.T @ ((1/s)[:, None] * U.T)`, with the inverse stored in C order. The sparse
excerpts above retain their original 1.17.1 provenance. On macOS the
existing system Accelerate dependency supplies the locked SciPy wheel's LP64
DGESDD through `src/classical_amg_svd_lp64.cpp` and the locked NumPy wheel's
ILP64 BLAS dot/matmul/matvec calls through `src/classical_amg.cpp`. These ABI
choices concern integer arguments; both paths retain double arithmetic. The original sparse
excerpts retain that wheel's multiply/add contraction; the wrapper's CSR
matvec explicitly uses FMA while NumPy-style vector updates remain strict.
Other platforms retain the already locked Eigen Jacobi SVD and their existing
arithmetic path. These platform paths require independent qualification;
macOS agreement does not establish Windows or cross-platform bitwise identity.
