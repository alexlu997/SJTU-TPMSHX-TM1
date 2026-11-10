cmake_minimum_required(VERSION 3.31.8)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(tpmshx_geometry LANGUAGES C CXX)
    enable_testing()
endif()

get_filename_component(TPMSHX_GEOMETRY_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
get_filename_component(TPMSHX_GEOMETRY_PROJECT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../.." ABSOLUTE)
set(TPMSHX_MODEL_INCLUDE_DIR "${TPMSHX_GEOMETRY_PROJECT_ROOT}/.cache/native-deps/generated"
    CACHE PATH "Generated model coefficient headers")
if(NOT EXISTS "${TPMSHX_MODEL_INCLUDE_DIR}/tpmshx/model_coefficients.hpp")
    message(FATAL_ERROR "Generate model_coefficients.hpp before configuring geometry")
endif()

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")
endif()

add_library(tpmshx_geometry STATIC
    "${TPMSHX_GEOMETRY_ROOT}/src/geometry.cpp"
    "${TPMSHX_GEOMETRY_ROOT}/src/asym_geometry.cpp"
    "${TPMSHX_GEOMETRY_ROOT}/src/geometry/marching_cubes.cpp")
target_include_directories(tpmshx_geometry PUBLIC "${TPMSHX_GEOMETRY_ROOT}/include"
    PRIVATE "${TPMSHX_MODEL_INCLUDE_DIR}")
target_compile_features(tpmshx_geometry PUBLIC cxx_std_17)
set_target_properties(tpmshx_geometry PROPERTIES
    CXX_EXTENSIONS OFF POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)

add_library(tpmshx_geometry_c STATIC "${TPMSHX_GEOMETRY_ROOT}/src/geometry_c_api.cpp")
add_library(tpmshx_geometry_shared SHARED "${TPMSHX_GEOMETRY_ROOT}/src/geometry_c_api.cpp")
target_compile_definitions(tpmshx_geometry_shared PRIVATE TPMSHX_GEOMETRY_BUILD_SHARED)
foreach(target IN ITEMS tpmshx_geometry_c tpmshx_geometry_shared)
    target_link_libraries(${target} PUBLIC tpmshx_geometry)
    set_target_properties(${target} PROPERTIES
        CXX_EXTENSIONS OFF POSITION_INDEPENDENT_CODE ON
        CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
endforeach()

foreach(target IN ITEMS tpmshx_geometry tpmshx_geometry_c tpmshx_geometry_shared)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX /EHsc /fp:strict /utf-8)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror
            -fno-fast-math -ffp-contract=off -fno-builtin-pow -fno-builtin-sin -fno-builtin-cos)
    endif()
endforeach()

foreach(kind IN ITEMS static shared)
    add_executable(geometry_c_${kind} "${TPMSHX_GEOMETRY_ROOT}/tests/geometry_c_smoke.c")
    target_compile_features(geometry_c_${kind} PRIVATE c_std_11)
    set_target_properties(geometry_c_${kind} PROPERTIES LINKER_LANGUAGE CXX C_EXTENSIONS OFF)
    if(kind STREQUAL static)
        target_link_libraries(geometry_c_${kind} PRIVATE tpmshx_geometry_c)
    else()
        target_link_libraries(geometry_c_${kind} PRIVATE tpmshx_geometry_shared)
        target_compile_definitions(geometry_c_${kind} PRIVATE TPMSHX_GEOMETRY_USE_SHARED)
    endif()
    if(APPLE)
        set_target_properties(geometry_c_${kind} PROPERTIES BUILD_RPATH "@loader_path")
    elseif(UNIX)
        set_target_properties(geometry_c_${kind} PROPERTIES BUILD_RPATH_USE_ORIGIN YES)
    endif()
    add_test(NAME geometry_c_${kind} COMMAND geometry_c_${kind})
endforeach()

add_executable(geometry_kernel_smoke "${TPMSHX_GEOMETRY_ROOT}/tests/geometry_kernel_smoke.cpp")
target_include_directories(geometry_kernel_smoke PRIVATE "${TPMSHX_MODEL_INCLUDE_DIR}")
target_link_libraries(geometry_kernel_smoke PRIVATE tpmshx_geometry)
set_target_properties(geometry_kernel_smoke PROPERTIES CXX_EXTENSIONS OFF)
if(MSVC)
    target_compile_options(geometry_kernel_smoke PRIVATE /W4 /WX /EHsc /fp:strict /utf-8)
else()
    target_compile_options(geometry_kernel_smoke PRIVATE -Wall -Wextra -Wpedantic -Werror -ffp-contract=off)
endif()
add_test(NAME geometry_kernel_smoke COMMAND geometry_kernel_smoke)
