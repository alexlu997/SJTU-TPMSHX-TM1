# Native dependency notices

The native solver and its component checks use the sources and build options in
[`dependencies-lock.toml`](dependencies-lock.toml). The complete C++ backend links
the applicable dependencies listed below. Source and build artifacts stay in
the ignored `.cache/native-deps` directory. These notices must accompany each
binary distribution that includes the corresponding components.

| Component | Source and notices | Use in this build |
| --- | --- | --- |
| CoolProp 8.0.0 | [MIT notice](licenses/CoolProp.txt); [fixed source](https://github.com/CoolProp/CoolProp/tree/ae81610e7d23efc57f9d051c8e70a4d66e87537f) | Static library; HEOS and BICUBIC qualification. Other default CoolProp backends are compiled, so their included dependencies remain listed. |
| Eigen | [Bundled notices](licenses/CoolProp-bundled.txt); exact source commit in the lock | Compiled with `EIGEN_MPL2_ONLY`; MPL 2.0 and upstream permissive notices are retained. Eigen source is unmodified. Its SparseLU headers also implement the fixed-coefficient temperature line solver; the low-level thermal library does not link the CoolProp runtime. The locked source must remain available with a binary distribution. |
| IF97, REFPROP-headers, fmt 12.0.0, miniz 3.1.1, nlohmann/json 3.12.0, Valijson 1.0.6 | [Bundled notices](licenses/CoolProp-bundled.txt) | Included by CoolProp. REFPROP-headers is the interface code; no proprietary REFPROP library or data is included. JSON headers and Valijson replace the previous RapidJSON dependency. |
| multicomplex | [Original NIST license and attribution](licenses/CoolProp-bundled.txt) | Header dependency used by CoolProp; Python bindings and their pybind11 dependency are not built. |
| msgpack-c and the Boost subset bundled by CoolProp | [Copyright and Boost Software License 1.0](licenses/CoolProp-bundled.txt) | Serialization and headers compiled into CoolProp. Copyright notices remain in the locked source. |
| incbin | [Unlicense](licenses/CoolProp-bundled.txt) | Embedded CoolProp data resources. |
| SuperLU 7.0.1 with selected SciPy 1.18.1 corrections | [Full upstream and COLAMD notices](licenses/SuperLU.txt); [fixed source](https://github.com/xiaoyeli/superlu/tree/83a3c82b9e44c966ca2bc26991ffdb2bf63e1e2b) | Double-precision LU and COLAMD. The Windows build retains bundled C BLAS; macOS uses the system Accelerate framework. The explicit build list excludes ILU/MC64. The upstream notice is retained in full, including the notice for the excluded MC64 routine. The lock identifies the three applied SciPy numerical fixes; Python allocator hooks are excluded. This source is not identical to SciPy's bundled SuperLU revision. |
| Apple Accelerate | System framework supplied by macOS; no Apple binary or source is redistributed | macOS 13.3+ NEWLAPACK LP64 symbols and `USE_VENDOR_BLAS=1`, matching the locked macOS SciPy wheel's pressure BLAS interface. The actual framework comes from the installed operating system. Windows does not use this dependency. |
| AMGCL 1.5.0 | [MIT notice](licenses/AMGCL.txt); [fixed source](https://github.com/ddemidov/amgcl/tree/f4614a7e9ccfe716c4c96df75dc349157229609a) | Staggered-temperature MAC candidate; serial builtin backend with `AMGCL_NO_BOOST`. Pressure uses the original PyAMG/SciPy algorithm excerpts below. |
| PyAMG 5.3.0 algorithm excerpts | [MIT notice](licenses/pyamg-v5.3.0-LICENSE.txt); [source provenance](licenses/classical-amg-sources.md) | Six original strength, coarsening, interpolation and relaxation functions; the pressure solver ports the locked classical hierarchy and V-cycle without a Python runtime dependency. |
| SciPy 1.17.1 CSR excerpts and 1.18.1 pseudo-inverse expression | [BSD-3-Clause notice](licenses/scipy-v1.17.1-LICENSE.txt); [source provenance](licenses/classical-amg-sources.md) | Seven original CSR functions preserve Galerkin product order. The native pressure solver retains the BiCGStab sequence and follows the current locked SciPy coarse pseudo-inverse expression. |

CoolProp 8 declares its dependencies through CPM. The project explicitly fetches
the nine required header dependencies at fixed commits, then supplies their local
paths to an offline CMake build. Optional Catch2, ExcelAddinInstaller and
FindMathematica modules are disabled. Dependency test and wrapper submodules are
not fetched or compiled. Redistributing source requires retaining its notices.

The nlohmann/json 3.12.0 headers carry additional copyright notices;
these are retained with their MIT, Apache and embedded conversion notices in
`CoolProp-bundled.txt`, from the fixed source in the native lock.

CMake 4.4.4 is an isolated build tool, not an application runtime dependency.
Its downloaded package retains `doc/cmake/Copyright.txt` and the third-party
license files beside it. See the upstream
[CMake copyright file](https://github.com/Kitware/CMake/blob/v4.4.4/Copyright.txt).
Do not include the build-tool package in an application bundle.

The macOS include inventory was checked against compiler-generated dependency
files, not merely the downloaded submodule list. Windows build and binary
dependency inspection are still required before claiming Windows distribution
acceptance. The narrow PyAMG/SciPy algorithm excerpts are distributed in
`src/classical_amg_kernels.hpp`; their complete license notices and exact source
revisions accompany them. Other upstream source checkouts remain in ignored cache.

The macOS pressure qualification does not establish cross-platform bitwise
identity. The Windows portable CBLAS build requires its own native numerical
qualification. BLAS thread settings must be recorded for performance runs;
`OPENBLAS_NUM_THREADS` alone does not control Apple's Accelerate framework.
