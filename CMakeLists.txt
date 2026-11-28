cmake_minimum_required(VERSION 3.31.8)
project(tpmshx LANGUAGES C CXX)

include(ExternalProject)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

set(TPMSHX_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
set(component_preparation preprocess)
set(component_result postprocess)
set(component_solver solver)
set(component_geometry geometry)
set(TPMSHX_NATIVE_DEPS_ROOT "${TPMSHX_ROOT}/.cache/native-deps" CACHE PATH "Locked dependency cache")
set(TPMSHX_MODEL_INCLUDE_DIR "${TPMSHX_NATIVE_DEPS_ROOT}/generated" CACHE PATH "Generated model headers")
set(TPMSHX_SOLVER_COOLPROP_LIBRARY "" CACHE FILEPATH "Locked solver CoolProp archive")
set(TPMSHX_PREPARATION_COOLPROP_LIBRARY "" CACHE FILEPATH "Locked preparation CoolProp archive")
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(default_components result)
else()
    set(default_components geometry preparation solver result)
endif()
set(TPMSHX_COMPONENTS "${default_components}" CACHE STRING "Native components to build and install")

if(NOT TPMSHX_COMPONENTS)
    message(FATAL_ERROR "Select at least one native component")
endif()
foreach(component IN LISTS TPMSHX_COMPONENTS)
    if(NOT component MATCHES "^(geometry|preparation|solver|result)$")
        message(FATAL_ERROR "Unknown native component: ${component}")
    endif()
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND NOT component STREQUAL "result")
        message(FATAL_ERROR "Linux supports only the result component")
    endif()
    set(source "${TPMSHX_ROOT}/native/${component_${component}}")
    set(options "-DTPMSHX_NATIVE_DEPS_ROOT:PATH=${TPMSHX_NATIVE_DEPS_ROOT}"
        "-DTPMSHX_MODEL_INCLUDE_DIR:PATH=${TPMSHX_MODEL_INCLUDE_DIR}"
        "-DTPMSHX_BUILD_QUALIFICATION:BOOL=OFF"
        "-DCMAKE_BUILD_TYPE:STRING=Release")
    if(APPLE)
        list(APPEND options "-DCMAKE_OSX_ARCHITECTURES:STRING=arm64")
    endif()
    if(component STREQUAL "solver")
        list(APPEND options "-DTPMSHX_COOLPROP_LIBRARY:FILEPATH=${TPMSHX_SOLVER_COOLPROP_LIBRARY}")
    elseif(component STREQUAL "preparation")
        list(APPEND options "-DTPMSHX_COOLPROP_LIBRARY:FILEPATH=${TPMSHX_PREPARATION_COOLPROP_LIBRARY}")
    endif()
    string(TOUPPER "${component}" upper_component)
    set(TPMSHX_${upper_component}_BUILD_DIR "${CMAKE_BINARY_DIR}/${component}" CACHE PATH
        "Existing or new ${component} component build directory")
    set(component_build "${TPMSHX_${upper_component}_BUILD_DIR}")
    # Separate CMake scopes keep the two CoolProp archives and registries apart.
    ExternalProject_Add(tpmshx_${component}_build
        SOURCE_DIR "${source}" BINARY_DIR "${component_build}"
        DOWNLOAD_COMMAND "" UPDATE_COMMAND ""
        STEP_TARGETS configure
        CMAKE_ARGS ${options}
        BUILD_COMMAND "${CMAKE_COMMAND}" --build <BINARY_DIR> --config Release
            --target tpmshx_${component}_shared --parallel 2
        BUILD_ALWAYS TRUE INSTALL_COMMAND "")
    # A direct qualification build can change the options in the same component directory.
    ExternalProject_Add_Step(tpmshx_${component}_build refresh_sdk_options
        DEPENDERS configure ALWAYS TRUE)
    set(library "${CMAKE_SHARED_LIBRARY_PREFIX}tpmshx_${component}_shared${CMAKE_SHARED_LIBRARY_SUFFIX}")
    if(WIN32)
        install(FILES "${component_build}/${library}" DESTINATION "${CMAKE_INSTALL_BINDIR}")
        install(FILES "${component_build}/Release/tpmshx_${component}_shared.lib"
            DESTINATION "${CMAKE_INSTALL_LIBDIR}")
    else()
        install(FILES "${component_build}/${library}" DESTINATION "${CMAKE_INSTALL_LIBDIR}")
    endif()
endforeach()

set(sdk_headers
    diagnostic_codes.hpp
    closure_evidence_c_api.h
    enthalpy_driver_c_api.h
    field_continuous_c_api.h
    field_lut_c_api.h
    field_sigmoid_c_api.h
    full_2d_c_api.h
    full_2d_run_c_api.h
    full_3d_c_api.h
    full_3d_run_c_api.h
    geometry_c_api.h
    grid_c_api.h
    model_h_c_api.h
    physical_ledger_c_api.h
    preparation_c_api.h
    preparation_case_3d_c_api.h
    preparation_case_c_api.h
    preparation_df_c_api.h
    preparation_flow_c_api.h
    property_c_api.h
    property_sampling_c_api.h
    quick_design_stage_c_api.h
    result_balance_c_api.h
    result_c_api.h
    result_checks_c_api.h
    result_metrics_c_api.h
    result_stage_c_api.h
    run_state_c_api.h
    simple_2d_c_api.h
    simple_3d_c_api.h
    simple_c_api_types.h
    solver_c_api.h
    stage_run_3d_c_api.h
    stage_run_c_api.h
    stages.hpp
    temperature_driver_c_api.h
    temperature_evidence_c_api.h
    thermal_c_api.h
    zones_c_api.h)
list(TRANSFORM sdk_headers PREPEND "${TPMSHX_ROOT}/native/include/tpmshx/")
install(FILES ${sdk_headers} DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/tpmshx")
configure_package_config_file("${TPMSHX_ROOT}/engineering/native_build/cmake/tpmshxConfig.cmake.in"
    "${CMAKE_BINARY_DIR}/tpmshxConfig.cmake"
    INSTALL_DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/tpmshx"
    PATH_VARS CMAKE_INSTALL_INCLUDEDIR CMAKE_INSTALL_BINDIR CMAKE_INSTALL_LIBDIR)
install(FILES "${CMAKE_BINARY_DIR}/tpmshxConfig.cmake"
    DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/tpmshx")
install(FILES "${TPMSHX_ROOT}/LICENSE" DESTINATION "${CMAKE_INSTALL_DATADIR}/tpmshx")
include("${TPMSHX_ROOT}/engineering/native_build/cmake/install-notices.cmake")
