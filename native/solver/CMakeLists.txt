cmake_minimum_required(VERSION 3.31.8)
project(tpmshx_dependency_pilot LANGUAGES C CXX)
option(TPMSHX_BUILD_QUALIFICATION "Build the native qualification targets" ON)

# Offline only. Downloading is a separate, explicit build-script operation.
get_filename_component(TPMSHX_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
set(TPMSHX_NATIVE_DEPS_ROOT "${TPMSHX_ROOT}/.cache/native-deps" CACHE PATH "Locked dependency cache")
set(TPMSHX_COOLPROP_LIBRARY "" CACHE FILEPATH "Previously built CoolProp 8.0.0 static library")
set(TPMSHX_MODEL_INCLUDE_DIR "${TPMSHX_NATIVE_DEPS_ROOT}/generated" CACHE PATH "Generated model coefficient headers")
set(CP_SOURCE "${TPMSHX_NATIVE_DEPS_ROOT}/src/CoolProp-8.0.0")
set(SUPERLU_SOURCE "${TPMSHX_NATIVE_DEPS_ROOT}/src/superlu-7.0.1")
set(AMGCL_SOURCE "${TPMSHX_NATIVE_DEPS_ROOT}/src/amgcl-1.5.0")
foreach(required IN ITEMS "${TPMSHX_COOLPROP_LIBRARY}" "${CP_SOURCE}/include/AbstractState.h"
        "${TPMSHX_MODEL_INCLUDE_DIR}/tpmshx/model_coefficients.hpp"
        "${SUPERLU_SOURCE}/SRC/slu_ddefs.h" "${AMGCL_SOURCE}/amgcl/amg.hpp")
    if(NOT EXISTS "${required}")
        message(FATAL_ERROR "Missing locked dependency: ${required}; run the explicit fetch/build script")
    endif()
endforeach()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")

add_subdirectory("${TPMSHX_ROOT}/native/geometry" geometry)

include("${TPMSHX_ROOT}/engineering/native_build/cmake/models.cmake")

include("${CMAKE_CURRENT_LIST_DIR}/superlu-lu-only.cmake")
add_library(tpmshx_amgcl INTERFACE)
add_library(AMGCL::AMGCL ALIAS tpmshx_amgcl)
target_include_directories(tpmshx_amgcl SYSTEM INTERFACE "${AMGCL_SOURCE}")
target_compile_definitions(tpmshx_amgcl INTERFACE AMGCL_NO_BOOST)

# EOS-free finite-volume rows, sweeps and physical energy ledgers. Consumers
# link this owner directly; do not obtain shared rows through the EOS driver.
add_library(tpmshx_energy STATIC "${TPMSHX_ROOT}/native/solver/conservative_energy.cpp"
    "${TPMSHX_ROOT}/native/solver/enthalpy_sweeps.cpp")
target_include_directories(tpmshx_energy PUBLIC "${TPMSHX_ROOT}/native/include")
target_link_libraries(tpmshx_energy PUBLIC Threads::Threads)
# Sources that emit common finite-volume rows use one contraction policy.
# Weak-symbol selection must not change the arithmetic.
# Capture keeps the separate rounding steps of the original NumPy operations.
if(MSVC)
    set(TPMSHX_ENERGY_ROW_FP_OPTION /fp:strict)
else()
    set(TPMSHX_ENERGY_ROW_FP_OPTION -ffp-contract=off)
endif()
set_property(SOURCE
    "${TPMSHX_ROOT}/native/solver/conservative_energy.cpp"
    "${TPMSHX_ROOT}/native/solver/enthalpy_sweeps.cpp"
    "${TPMSHX_ROOT}/native/solver/temperature_driver.cpp"
    "${TPMSHX_ROOT}/native/solver/temperature_staggered.cpp"
    "${TPMSHX_ROOT}/native/solver/model_h_2d.cpp"
    "${TPMSHX_ROOT}/native/solver/model_h_3d.cpp"
    "${TPMSHX_ROOT}/native/preprocess/preparation_flow.cpp"
    "${TPMSHX_ROOT}/native/solver/stage_capture_3d.cpp"
    APPEND PROPERTY COMPILE_OPTIONS "${TPMSHX_ENERGY_ROW_FP_OPTION}")

add_library(tpmshx_temperature STATIC "${TPMSHX_ROOT}/native/solver/temperature_driver.cpp")
target_include_directories(tpmshx_temperature PUBLIC "${TPMSHX_ROOT}/native/include")
target_link_libraries(tpmshx_temperature PUBLIC tpmshx_energy)
target_include_directories(tpmshx_temperature SYSTEM PRIVATE "${TPMSHX_NATIVE_DEPS_ROOT}/src/Eigen-5.0.1")
target_compile_definitions(tpmshx_temperature PRIVATE EIGEN_MPL2_ONLY)
add_library(tpmshx_quick_design STATIC "${TPMSHX_ROOT}/native/solver/quick_design_driver.cpp")
target_include_directories(tpmshx_quick_design PUBLIC "${TPMSHX_ROOT}/native/include")
target_link_libraries(tpmshx_quick_design PUBLIC tpmshx_models tpmshx_temperature)
add_library(tpmshx_enthalpy STATIC "${TPMSHX_ROOT}/native/solver/enthalpy_driver.cpp"
    "${TPMSHX_ROOT}/native/solver/enthalpy_eos.cpp")
target_include_directories(tpmshx_enthalpy PUBLIC "${TPMSHX_ROOT}/native/include")
target_link_libraries(tpmshx_enthalpy PUBLIC tpmshx_models tpmshx_energy)
add_library(tpmshx_model_h_2d STATIC "${TPMSHX_ROOT}/native/solver/model_h_2d.cpp")
target_link_libraries(tpmshx_model_h_2d PUBLIC tpmshx_models tpmshx_energy)
if(MSVC)
    target_compile_options(tpmshx_model_h_2d PRIVATE /fp:strict)
else()
    target_compile_options(tpmshx_model_h_2d PRIVATE -ffp-contract=off)
endif()
add_library(tpmshx_model_h_3d STATIC "${TPMSHX_ROOT}/native/solver/model_h_3d.cpp")
target_link_libraries(tpmshx_model_h_3d PUBLIC tpmshx_models tpmshx_energy)
if(MSVC)
    target_compile_options(tpmshx_model_h_3d PRIVATE /fp:strict)
else()
    target_compile_options(tpmshx_model_h_3d PRIVATE -ffp-contract=off)
endif()
add_library(tpmshx_temperature_staggered STATIC "${TPMSHX_ROOT}/native/solver/temperature_staggered.cpp")
target_link_libraries(tpmshx_temperature_staggered PUBLIC tpmshx_models tpmshx_energy SuperLU::LU AMGCL::AMGCL)
include("${TPMSHX_ROOT}/engineering/native_build/cmake/pressure-reference.cmake")
add_custom_target(tpmshx_state_build_identity
    COMMAND "${CMAKE_COMMAND}"
        "-DTPMSHX_STATE_HEADER=${CMAKE_CURRENT_BINARY_DIR}/native_state_build.hpp"
        "-DTPMSHX_STATE_PLATFORM=${CMAKE_SYSTEM_NAME}:${CMAKE_SYSTEM_PROCESSOR}"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/write_state_build_id.cmake"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/native_state_build.hpp"
    VERBATIM)
add_library(tpmshx_run_state STATIC "${TPMSHX_ROOT}/native/solver/full_run_state.cpp")
add_dependencies(tpmshx_run_state tpmshx_state_build_identity)
target_include_directories(tpmshx_run_state PUBLIC "${TPMSHX_ROOT}/native/include" "${TPMSHX_MODEL_INCLUDE_DIR}"
    PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
add_library(tpmshx_full_3d STATIC "${TPMSHX_ROOT}/native/solver/full_3d.cpp"
    "${TPMSHX_ROOT}/native/solver/true_h_preparation.cpp")
target_link_libraries(tpmshx_full_3d PUBLIC tpmshx_run_state tpmshx_simple tpmshx_temperature_staggered
    tpmshx_model_h_2d tpmshx_model_h_3d tpmshx_enthalpy tpmshx_pressure_reference)
if(MSVC)
    target_compile_options(tpmshx_full_3d PRIVATE /fp:strict)
else()
    target_compile_options(tpmshx_full_3d PRIVATE -ffp-contract=off)
endif()

add_library(tpmshx_refinement_2d STATIC "${TPMSHX_ROOT}/native/solver/refinement_2d.cpp")
target_include_directories(tpmshx_refinement_2d PUBLIC "${TPMSHX_ROOT}/native/include")
add_library(tpmshx_full_2d STATIC "${TPMSHX_ROOT}/native/solver/full_2d.cpp")
target_link_libraries(tpmshx_full_2d PUBLIC tpmshx_run_state tpmshx_simple
    tpmshx_model_h_2d tpmshx_enthalpy tpmshx_pressure_reference tpmshx_models tpmshx_refinement_2d)
if(MSVC)
    target_compile_options(tpmshx_refinement_2d PRIVATE /fp:strict)
    target_compile_options(tpmshx_full_2d PRIVATE /fp:strict)
else()
    target_compile_options(tpmshx_refinement_2d PRIVATE -ffp-contract=off)
    target_compile_options(tpmshx_full_2d PRIVATE -ffp-contract=off)
endif()
add_library(tpmshx_solver_shared SHARED "${TPMSHX_ROOT}/native/solver/solver_c_api.cpp"
    "${TPMSHX_ROOT}/native/solver/full_2d_c_api.cpp" "${TPMSHX_ROOT}/native/solver/full_3d_c_api.cpp"
    "${TPMSHX_ROOT}/native/solver/run_state_c_api.cpp" "${TPMSHX_ROOT}/native/solver/temperature_algorithm_c_api.cpp"
    "${TPMSHX_ROOT}/native/solver/model_h_algorithm_c_api.cpp" "${TPMSHX_ROOT}/native/solver/energy_algorithm_c_api.cpp")
target_compile_definitions(tpmshx_solver_shared PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
target_link_libraries(tpmshx_solver_shared PUBLIC tpmshx_quick_design tpmshx_full_2d tpmshx_full_3d)
# Reuse the result arithmetic without a shared result-library dependency.
add_library(tpmshx_capture_math STATIC
    "${TPMSHX_ROOT}/native/numerics/recorded_report.cpp"
    "${TPMSHX_ROOT}/native/solver/execution_report.cpp"
    "${TPMSHX_ROOT}/native/postprocess/result_core.cpp"
    "${TPMSHX_ROOT}/native/postprocess/result_arithmetic.cpp"
    "${TPMSHX_ROOT}/native/postprocess/result_metrics.cpp"
    "${TPMSHX_ROOT}/native/postprocess/result_balance.cpp")
target_include_directories(tpmshx_capture_math PUBLIC "${TPMSHX_ROOT}/native/include")
set_target_properties(tpmshx_capture_math PROPERTIES CXX_VISIBILITY_PRESET hidden
    C_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
if(MSVC)
    target_compile_options(tpmshx_capture_math PRIVATE /W4 /WX /EHsc /fp:strict /utf-8)
else()
    target_compile_options(tpmshx_capture_math PRIVATE -Wall -Wextra -Wpedantic -Werror
        -fno-fast-math -ffp-contract=off -fno-builtin-pow)
endif()
target_link_libraries(tpmshx_solver_shared PRIVATE tpmshx_capture_math)
target_sources(tpmshx_solver_shared PRIVATE "${TPMSHX_ROOT}/native/solver/stage_run.cpp"
    "${TPMSHX_ROOT}/native/solver/prepared_mesh.cpp"
    "${TPMSHX_ROOT}/native/preprocess/preparation_df_corrections.cpp"
    "${TPMSHX_ROOT}/native/preprocess/preparation_flow.cpp"
    "${TPMSHX_ROOT}/native/numerics/df_summary.cpp"
    "${TPMSHX_ROOT}/native/solver/stage_capture_2d.cpp"
    "${TPMSHX_ROOT}/native/solver/stage_run_3d.cpp"
    "${TPMSHX_ROOT}/native/solver/stage_capture_3d.cpp"
    "${TPMSHX_ROOT}/native/solver/quick_design_run.cpp")
set_target_properties(tpmshx_solver_shared PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS OFF)
if(APPLE)
    # Keep each statically linked EOS registry private to its library image.
    target_link_options(tpmshx_solver_shared PRIVATE
        "LINKER:-exported_symbols_list,${CMAKE_CURRENT_LIST_DIR}/solver.exports")
    set_property(TARGET tpmshx_solver_shared APPEND PROPERTY LINK_DEPENDS
        "${CMAKE_CURRENT_LIST_DIR}/solver.exports")
endif()
add_library(tpmshx_pressure STATIC "${TPMSHX_ROOT}/native/solver/pressure_candidate.cpp"
    "${TPMSHX_ROOT}/native/solver/classical_amg.cpp")
if(APPLE)
    target_sources(tpmshx_pressure PRIVATE "${TPMSHX_ROOT}/native/solver/classical_amg_svd_lp64.cpp")
endif()
target_include_directories(tpmshx_pressure PUBLIC "${TPMSHX_ROOT}/native/include")
target_include_directories(tpmshx_pressure SYSTEM PRIVATE "${TPMSHX_NATIVE_DEPS_ROOT}/src/Eigen-5.0.1")
target_compile_definitions(tpmshx_pressure PRIVATE EIGEN_MPL2_ONLY)
target_link_libraries(tpmshx_pressure PUBLIC SuperLU::LU)
if(MSVC)
    target_compile_options(tpmshx_pressure PRIVATE /fp:strict)
else()
    target_compile_options(tpmshx_pressure PRIVATE -ffp-contract=off)
endif()
add_library(tpmshx_simple STATIC "${TPMSHX_ROOT}/native/solver/simple_pressure.cpp"
    "${TPMSHX_ROOT}/native/solver/simple_convergence.cpp" "${TPMSHX_ROOT}/native/solver/simple_2d.cpp"
    "${TPMSHX_ROOT}/native/solver/simple_3d.cpp")
target_link_libraries(tpmshx_simple PUBLIC tpmshx_pressure)
target_include_directories(tpmshx_simple SYSTEM PRIVATE "${TPMSHX_NATIVE_DEPS_ROOT}/src/Eigen-5.0.1")
target_compile_definitions(tpmshx_simple PRIVATE EIGEN_MPL2_ONLY)
if(APPLE)
    target_link_libraries(tpmshx_simple PUBLIC "-framework Accelerate")
endif()
# Python's 2D SIMPLE kernels use strict (non-fastmath) arithmetic. Preserve
# separate multiply/add rounding near the SOU branch's flat-stencil boundary.
if(MSVC)
    target_compile_options(tpmshx_simple PRIVATE /fp:strict)
else()
    target_compile_options(tpmshx_simple PRIVATE -ffp-contract=off)
endif()

set(warning_targets tpmshx_run_state tpmshx_energy tpmshx_models tpmshx_temperature
    tpmshx_quick_design tpmshx_solver_shared tpmshx_enthalpy tpmshx_model_h_2d tpmshx_model_h_3d
    tpmshx_temperature_staggered tpmshx_pressure_reference tpmshx_full_3d tpmshx_refinement_2d
    tpmshx_full_2d tpmshx_pressure tpmshx_simple)
if(TPMSHX_BUILD_QUALIFICATION)
    set_property(SOURCE
        "${TPMSHX_ROOT}/tests/cpp/conservative_energy_smoke.cpp"
        "${TPMSHX_ROOT}/tests/python/native/anderson_candidate_bridge.cpp"
        APPEND PROPERTY COMPILE_OPTIONS "${TPMSHX_ENERGY_ROW_FP_OPTION}")

    add_executable(temperature_driver_smoke "${TPMSHX_ROOT}/tests/cpp/temperature_driver_smoke.cpp")
    target_link_libraries(temperature_driver_smoke PRIVATE tpmshx_temperature)

    add_executable(model_h_2d_smoke "${TPMSHX_ROOT}/tests/cpp/model_h_2d_smoke.cpp")
    target_link_libraries(model_h_2d_smoke PRIVATE tpmshx_model_h_2d)
    add_library(model_h_2d_test SHARED "${TPMSHX_ROOT}/tests/python/native/model_h_2d_bridge.cpp")
    target_compile_definitions(model_h_2d_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(model_h_2d_test PRIVATE tpmshx_model_h_2d)

    add_library(model_h_3d_test SHARED "${TPMSHX_ROOT}/tests/python/native/model_h_3d_bridge.cpp")
    target_compile_definitions(model_h_3d_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(model_h_3d_test PRIVATE tpmshx_model_h_3d)
    add_executable(model_h_3d_smoke "${TPMSHX_ROOT}/tests/cpp/model_h_3d_smoke.cpp")
    target_link_libraries(model_h_3d_smoke PRIVATE tpmshx_model_h_3d)
    add_executable(model_h_chunk_smoke "${TPMSHX_ROOT}/tests/cpp/model_h_chunk_smoke.cpp")
    target_link_libraries(model_h_chunk_smoke PRIVATE tpmshx_models)
    add_executable(model_h_run_smoke "${TPMSHX_ROOT}/tests/cpp/model_h_run_smoke.cpp")
    target_link_libraries(model_h_run_smoke PRIVATE tpmshx_model_h_2d tpmshx_model_h_3d)
    include("${TPMSHX_ROOT}/tests/python/native/model_h_history.cmake")

    add_library(temperature_staggered_test SHARED "${TPMSHX_ROOT}/tests/python/native/temperature_staggered_bridge.cpp")
    target_compile_definitions(temperature_staggered_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(temperature_staggered_test PRIVATE tpmshx_temperature_staggered)
    add_executable(temperature_staggered_smoke "${TPMSHX_ROOT}/tests/cpp/temperature_staggered_smoke.cpp")
    target_link_libraries(temperature_staggered_smoke PRIVATE tpmshx_temperature_staggered)
    add_executable(temperature_run_smoke "${TPMSHX_ROOT}/tests/cpp/temperature_run_smoke.cpp")
    target_link_libraries(temperature_run_smoke PRIVATE tpmshx_temperature tpmshx_temperature_staggered)

    add_library(full_3d_test SHARED "${TPMSHX_ROOT}/tests/python/native/full_3d_bridge.cpp")
    target_compile_definitions(full_3d_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(full_3d_test PRIVATE tpmshx_full_3d)
    target_include_directories(full_3d_test PRIVATE "${TPMSHX_ROOT}/native/solver")

    add_library(refinement_2d_test SHARED "${TPMSHX_ROOT}/tests/python/native/refinement_2d_bridge.cpp")
    target_compile_definitions(refinement_2d_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(refinement_2d_test PRIVATE tpmshx_refinement_2d)

    add_executable(side_physics_smoke "${TPMSHX_ROOT}/tests/cpp/side_physics_smoke.cpp")
    target_link_libraries(side_physics_smoke PRIVATE tpmshx_full_2d tpmshx_full_3d)
    add_library(full_2d_test SHARED "${TPMSHX_ROOT}/tests/python/native/full_2d_bridge.cpp")
    target_compile_definitions(full_2d_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(full_2d_test PRIVATE tpmshx_full_2d)

    add_executable(enthalpy_driver_smoke "${TPMSHX_ROOT}/tests/cpp/enthalpy_driver_smoke.cpp")
    target_link_libraries(enthalpy_driver_smoke PRIVATE tpmshx_enthalpy)
    add_executable(conservative_energy_smoke "${TPMSHX_ROOT}/tests/cpp/conservative_energy_smoke.cpp")
    target_link_libraries(conservative_energy_smoke PRIVATE tpmshx_energy)
    add_executable(conservative_energy_driver_smoke "${TPMSHX_ROOT}/tests/cpp/conservative_energy_driver_smoke.cpp")
    target_link_libraries(conservative_energy_driver_smoke PRIVATE tpmshx_enthalpy)
    add_library(enthalpy_driver_test SHARED "${TPMSHX_ROOT}/tests/python/native/enthalpy_driver_bridge.cpp")
    target_compile_definitions(enthalpy_driver_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(enthalpy_driver_test PRIVATE tpmshx_enthalpy)

    add_executable(quick_design_driver_smoke "${TPMSHX_ROOT}/tests/cpp/quick_design_driver_smoke.cpp")
    target_link_libraries(quick_design_driver_smoke PRIVATE tpmshx_quick_design)
    add_library(quick_design_test SHARED "${TPMSHX_ROOT}/tests/python/native/quick_design_bridge.cpp")
    target_compile_definitions(quick_design_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(quick_design_test PRIVATE tpmshx_quick_design)
    set_target_properties(quick_design_test PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")

    add_executable(eos_smoke "${TPMSHX_ROOT}/tests/cpp/eos_smoke.cpp")
    target_link_libraries(eos_smoke PRIVATE CoolProp::CoolProp Threads::Threads)
    add_executable(fluid_properties_smoke "${TPMSHX_ROOT}/tests/cpp/fluid_properties_smoke.cpp")
    target_link_libraries(fluid_properties_smoke PRIVATE tpmshx_models)

    add_executable(pressure_smoke "${TPMSHX_ROOT}/tests/cpp/pressure_smoke.cpp")
    target_link_libraries(pressure_smoke PRIVATE tpmshx_pressure)

    add_executable(simple_run_smoke "${TPMSHX_ROOT}/tests/cpp/simple_run_smoke.cpp")
    target_link_libraries(simple_run_smoke PRIVATE tpmshx_simple)
    add_executable(simple_2d_smoke "${TPMSHX_ROOT}/tests/cpp/simple_2d_smoke.cpp")
    target_link_libraries(simple_2d_smoke PRIVATE tpmshx_simple)
    add_library(simple_2d_test SHARED "${TPMSHX_ROOT}/tests/python/native/simple_2d_bridge.cpp")
    target_compile_definitions(simple_2d_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(simple_2d_test PRIVATE tpmshx_simple)
    add_library(simple_3d_test SHARED "${TPMSHX_ROOT}/tests/python/native/simple_3d_bridge.cpp")
    target_compile_definitions(simple_3d_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_link_libraries(simple_3d_test PRIVATE tpmshx_simple)
    add_executable(simple_3d_smoke "${TPMSHX_ROOT}/tests/cpp/simple_3d_smoke.cpp")
    target_link_libraries(simple_3d_smoke PRIVATE tpmshx_simple)
    add_library(tpmshx_kernel_test SHARED
        "${TPMSHX_ROOT}/tests/python/native/anderson_candidate_bridge.cpp"
        "${TPMSHX_ROOT}/tests/python/native/enthalpy_bridge.cpp"
        "${TPMSHX_ROOT}/tests/python/native/pressure_reference_bridge.cpp"
        "${TPMSHX_ROOT}/tests/python/native/simple_pressure_bridge.cpp"
        "${TPMSHX_ROOT}/tests/python/native/temperature_bridge.cpp")
    target_compile_definitions(tpmshx_kernel_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED EIGEN_MPL2_ONLY)
    target_include_directories(tpmshx_kernel_test SYSTEM PRIVATE "${TPMSHX_NATIVE_DEPS_ROOT}/src/Eigen-5.0.1")
    target_link_libraries(tpmshx_kernel_test PRIVATE tpmshx_temperature tpmshx_pressure_reference tpmshx_simple)

    add_executable(superlu_error_smoke "${TPMSHX_ROOT}/tests/cpp/superlu_error_smoke.cpp"
        "${TPMSHX_ROOT}/native/solver/superlu_solve.c")
    target_compile_definitions(superlu_error_smoke PRIVATE TPMSHX_SUPERLU_TESTING)
    set_target_properties(superlu_error_smoke PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON)
    target_include_directories(superlu_error_smoke PRIVATE "${TPMSHX_ROOT}/native/include"
        "${TPMSHX_ROOT}/native/solver")
    target_link_libraries(superlu_error_smoke PRIVATE SuperLU::LU Threads::Threads)
    list(APPEND warning_targets temperature_driver_smoke enthalpy_driver_smoke enthalpy_driver_test
        conservative_energy_smoke conservative_energy_driver_smoke model_h_2d_test model_h_2d_smoke
        model_h_3d_test model_h_3d_smoke model_h_chunk_smoke model_h_run_smoke temperature_staggered_test
        temperature_staggered_smoke temperature_run_smoke full_3d_test refinement_2d_test full_2d_test
        side_physics_smoke simple_2d_smoke simple_2d_test simple_3d_test simple_3d_smoke simple_run_smoke
        quick_design_driver_smoke quick_design_test eos_smoke fluid_properties_smoke pressure_smoke
        tpmshx_kernel_test superlu_error_smoke)
endif()
unset(TPMSHX_ENERGY_ROW_FP_OPTION)

foreach(target IN LISTS warning_targets)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX $<$<COMPILE_LANGUAGE:CXX>:/EHsc>)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endforeach()
