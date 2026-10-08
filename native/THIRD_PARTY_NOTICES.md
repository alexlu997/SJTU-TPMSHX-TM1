# Native dependency notices

The native solver and its component checks use the sources and build options in
[`dependencies-lock.toml`](dependencies-lock.toml). The complete C++ backend links
the applicable dependencies listed below. Source and build artifacts stay in
the ignored `.cache/native-deps` directory. These notices must accompany each
binary distribution that includes the corresponding components.

| Component | Source and notices | Use in this build |
| --- | --- | --- |
| CoolProp 7.2.0 | [MIT notice](licenses/CoolProp.txt); [fixed source](https://github.com/CoolProp/CoolProp/tree/98b3523d5daa98454618d381d2ae53f7471d216b) | Static library; HEOS and BICUBIC qualification. Other default CoolProp backends are compiled, so their included dependencies remain listed. |
| Eigen | [Bundled notices](licenses/CoolProp-bundled.txt); exact source commit in the lock | Compiled with `EIGEN_MPL2_ONLY`; MPL 2.0 and upstream permissive notices are retained. Eigen source is unmodified. Its SparseLU headers also implement the fixed-coefficient temperature line solver; the low-level thermal library does not link the CoolProp runtime. The locked source must remain available with a binary distribution. |
| IF97, REFPROP-headers, fmt, miniz, nlohmann/json | [Bundled notices](licenses/CoolProp-bundled.txt) | Included by CoolProp. REFPROP-headers is the interface code; no proprietary REFPROP library or data is included. |
| RapidJSON | [Full upstream notice](licenses/CoolProp-bundled.txt) | Only library headers are used. `bin/jsonchecker` and third-party test programs are excluded. The complete upstream notice retains their separate terms without making them build inputs. |
| msgpack-c and the Boost subset bundled by CoolProp | [Copyright and Boost Software License 1.0](licenses/CoolProp-bundled.txt) | Serialization and headers compiled into CoolProp. Copyright notices remain in the locked source. |
| incbin | [Unlicense](licenses/CoolProp-bundled.txt) | Embedded CoolProp data resources. |
| SuperLU 6.0.1, fixed SciPy source commit | [Full upstream and COLAMD notices](licenses/SuperLU.txt); [fixed source](https://github.com/xiaoyeli/superlu/tree/18958c35006c63071813df6808d7809247caac89) | Double-precision LU and COLAMD. The Windows build retains bundled C BLAS; macOS uses the system Accelerate framework. The explicit build list excludes ILU/MC64. The upstream notice is retained in full, including the notice for the excluded MC64 routine. The lock identifies the three applied SciPy numerical fixes; Python allocator hooks are excluded. |
| Apple Accelerate | System framework supplied by macOS; no Apple binary or source is redistributed | macOS 13.3+ NEWLAPACK LP64 symbols and `USE_VENDOR_BLAS=1`, matching the locked macOS SciPy wheel's pressure BLAS interface. The actual framework comes from the installed operating system. Windows does not use this dependency. |
| AMGCL 1.4.4 | [MIT notice](licenses/AMGCL.txt); [fixed source](https://github.com/ddemidov/amgcl/tree/42ee9da2057153b1aef734e8e462c846a33aa805) | Staggered-temperature MAC candidate; serial builtin backend with `AMGCL_NO_BOOST`. Pressure uses the original PyAMG/SciPy algorithm excerpts below. |
| PyAMG 5.3.0 algorithm excerpts | [MIT notice](licenses/pyamg-v5.3.0-LICENSE.txt); [source provenance](licenses/classical-amg-sources.md) | Six original strength, coarsening, interpolation and relaxation functions; the pressure solver ports the locked classical hierarchy and V-cycle without a Python runtime dependency. |
| SciPy 1.17.1 algorithm excerpts | [BSD-3-Clause notice](licenses/scipy-v1.17.1-LICENSE.txt); [source provenance](licenses/classical-amg-sources.md) | Seven original CSR functions preserve Galerkin product order. The native pressure solver also translates the locked BiCGStab sequence and coarse pseudo-inverse convention. |

CoolProp's full source checkout also includes test and wrapper submodules
(Catch2, multicomplex, pybind11, GoogleTest, ExcelAddinInstaller and
FindMathematica). These are pinned for reproducibility but are not linked into
the pilot executables. Their original licenses remain with their source;
redistributing the complete source checkout requires retaining those files.

The nlohmann/json 3.11.3 single header carries additional copyright notices;
these are retained after its MIT and Apache texts in `CoolProp-bundled.txt`.
Those two license texts come from the upstream
[3.11.3 tag](https://github.com/nlohmann/json/tree/v3.11.3).

CMake 3.31.8 is an isolated build tool, not an application runtime dependency.
Its downloaded package retains `doc/cmake/Copyright.txt` and the third-party
license files beside it. See the upstream
[CMake copyright file](https://github.com/Kitware/CMake/blob/v3.31.8/Copyright.txt).
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
