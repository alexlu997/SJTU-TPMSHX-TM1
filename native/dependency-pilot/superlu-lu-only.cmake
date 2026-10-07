# Fixed double-real LU subset of the SciPy 1.17.1 upstream baseline.
# Deliberately excludes MC64, ILU drivers, METIS, Fortran and other precisions.
# Shared utility files still contain upstream unused ILU utility functions.
# Private C allocation/ABORT hooks return through the protected C solve boundary.
# Raw vendor calls outside the protected CSC/CSR C solve calls are unsupported.
set(HAVE_METIS 0)
set(HAVE_COLAMD 1)
set(XSDK_INDEX_SIZE 32)
configure_file("${SUPERLU_SOURCE}/SRC/superlu_config.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/tpmshx_superlu_config.h")
set(lu_sources
    superlu_timer.c util.c memory.c get_perm_c.c mmd.c sp_coletree.c
    sp_preorder.c sp_ienv.c relax_snode.c heap_relax_snode.c colamd.c
    mark_relax.c input_error.c dmach.c dgssv.c dsp_blas2.c dsp_blas3.c
    dgstrf.c dgstrs.c dcopy_to_ucol.c dsnode_dfs.c dsnode_bmod.c
    dpanel_dfs.c dpanel_bmod.c dcolumn_dfs.c dcolumn_bmod.c dpivotL.c
    dpruneL.c dmemory.c dutil.c dmyblas2.c)
list(TRANSFORM lu_sources PREPEND "${SUPERLU_SOURCE}/SRC/")
add_library(tpmshx_superlu_lu STATIC ${lu_sources} "${TPMSHX_ROOT}/native/src/superlu_solve.c")
set_target_properties(tpmshx_superlu_lu PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON)
add_library(SuperLU::LU ALIAS tpmshx_superlu_lu)
target_include_directories(tpmshx_superlu_lu SYSTEM PUBLIC
    "${SUPERLU_SOURCE}/SRC" "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_definitions(tpmshx_superlu_lu PRIVATE SCIPY_FIX=1)
target_include_directories(tpmshx_superlu_lu PRIVATE "${TPMSHX_ROOT}/native/include"
    "${TPMSHX_ROOT}/native/src")
# Use a distinct generated name: hooks load it before upstream headers even
# when MSVC processes source-level forced includes before target options.
# Public consumers retain the same 32-bit/no-METIS contract.
if(MSVC)
    target_compile_options(tpmshx_superlu_lu PUBLIC
        "/FI${CMAKE_CURRENT_BINARY_DIR}/tpmshx_superlu_config.h")
    set(superlu_hooks_option
        "/FI${TPMSHX_ROOT}/native/src/superlu_hooks.h")
    set_source_files_properties("${TPMSHX_ROOT}/native/src/superlu_solve.c" PROPERTIES
        COMPILE_OPTIONS "/W4;/WX")
else()
    target_compile_options(tpmshx_superlu_lu PUBLIC
        "SHELL:-include \"${CMAKE_CURRENT_BINARY_DIR}/tpmshx_superlu_config.h\"")
    set(superlu_hooks_option "-include${TPMSHX_ROOT}/native/src/superlu_hooks.h")
    set_source_files_properties("${TPMSHX_ROOT}/native/src/superlu_solve.c" PROPERTIES
        COMPILE_OPTIONS "-Wall;-Wextra;-Wpedantic;-Werror")
endif()
# input_error.c only prints an argument error and has no allocation/ABORT.
# Its upstream void definition conflicts with slu_util.h's int declaration,
# so preserve its original header-free compilation instead of vendor edits.
foreach(source IN LISTS lu_sources)
    if(NOT source STREQUAL "${SUPERLU_SOURCE}/SRC/input_error.c")
        set_property(SOURCE "${source}" APPEND PROPERTY COMPILE_OPTIONS "${superlu_hooks_option}")
    endif()
endforeach()
# Keep upstream machine epsilon/timer routines free of optimization assumptions.
if(MSVC)
    set_property(SOURCE "${SUPERLU_SOURCE}/SRC/dmach.c"
        "${SUPERLU_SOURCE}/SRC/superlu_timer.c" APPEND PROPERTY COMPILE_OPTIONS /Od)
else()
    set_property(SOURCE "${SUPERLU_SOURCE}/SRC/dmach.c"
        "${SUPERLU_SOURCE}/SRC/superlu_timer.c" APPEND PROPERTY COMPILE_OPTIONS -O0)
endif()
if(APPLE)
    if(CMAKE_OSX_DEPLOYMENT_TARGET AND CMAKE_OSX_DEPLOYMENT_TARGET VERSION_LESS "13.3")
        message(FATAL_ERROR "Qualified Accelerate LP64 pressure path requires macOS 13.3 or newer")
    endif()
    find_library(TPMSHX_ACCELERATE_FRAMEWORK Accelerate REQUIRED)
    target_compile_definitions(tpmshx_superlu_lu PRIVATE USE_VENDOR_BLAS=1 TPMSHX_SUPERLU_ACCELERATE=1)
    target_link_libraries(tpmshx_superlu_lu PUBLIC "${TPMSHX_ACCELERATE_FRAMEWORK}")
else()
    # The portable baseline remains explicit until native Windows qualification.
    set(blas_sources idamax.c dasum.c daxpy.c dcopy.c ddot.c dnrm2.c drot.c
        dscal.c dswap.c dgemv.c dsymv.c dtrsv.c dger.c dsyr2.c)
    list(TRANSFORM blas_sources PREPEND "${SUPERLU_SOURCE}/CBLAS/")
    add_library(tpmshx_superlu_blas STATIC ${blas_sources})
    target_include_directories(tpmshx_superlu_blas SYSTEM PRIVATE
        "${SUPERLU_SOURCE}/CBLAS" "${SUPERLU_SOURCE}/SRC" "${CMAKE_CURRENT_BINARY_DIR}")
    target_link_libraries(tpmshx_superlu_lu PUBLIC tpmshx_superlu_blas)
endif()
if(UNIX)
    target_link_libraries(tpmshx_superlu_lu PUBLIC m)
endif()
