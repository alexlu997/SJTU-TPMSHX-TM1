cmake_minimum_required(VERSION 3.31.8)
project(tpmshx_result LANGUAGES C CXX)
enable_testing()

get_filename_component(TPMSHX_NATIVE_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")

add_library(tpmshx_result STATIC
    "${TPMSHX_NATIVE_ROOT}/src/result_core.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_arithmetic.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_metrics.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_balance.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_checks.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_stage.cpp")
target_include_directories(tpmshx_result PUBLIC "${TPMSHX_NATIVE_ROOT}/include")
if(APPLE)
    target_sources(tpmshx_result PRIVATE "${TPMSHX_NATIVE_ROOT}/src/result_complex_sqrt.c")
    target_compile_features(tpmshx_result PRIVATE c_std_11)
    set_source_files_properties("${TPMSHX_NATIVE_ROOT}/src/result_complex_sqrt.c" PROPERTIES
        COMPILE_OPTIONS "-fno-builtin-csqrt;-fno-builtin-csqrtf;-fno-builtin-csqrtl")
endif()
set(TPMSHX_RESULT_C_SOURCES
    "${TPMSHX_NATIVE_ROOT}/src/result_c_api.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_metrics_c_api.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_balance_c_api.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_checks_c_api.cpp"
    "${TPMSHX_NATIVE_ROOT}/src/result_stage_c_api.cpp")
add_library(tpmshx_result_c STATIC ${TPMSHX_RESULT_C_SOURCES})
add_library(tpmshx_result_shared SHARED ${TPMSHX_RESULT_C_SOURCES})
target_compile_definitions(tpmshx_result_shared PRIVATE TPMSHX_RESULT_BUILD_SHARED)
foreach(target IN ITEMS tpmshx_result_c tpmshx_result_shared)
    target_link_libraries(${target} PUBLIC tpmshx_result)
endforeach()
foreach(target IN ITEMS tpmshx_result tpmshx_result_c tpmshx_result_shared)
    target_compile_features(${target} PUBLIC cxx_std_17)
    set_target_properties(${target} PROPERTIES CXX_EXTENSIONS OFF C_EXTENSIONS OFF POSITION_INDEPENDENT_CODE ON
        CXX_VISIBILITY_PRESET hidden C_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES WINDOWS_EXPORT_ALL_SYMBOLS OFF)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX /EHsc /fp:strict /utf-8)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror
            -fno-fast-math -ffp-contract=off -fno-builtin-pow)
    endif()
endforeach()
if(APPLE)
    target_link_options(tpmshx_result_shared PRIVATE "LINKER:-exported_symbols_list,${CMAKE_CURRENT_LIST_DIR}/result.exports")
    set_property(TARGET tpmshx_result_shared APPEND PROPERTY LINK_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/result.exports")
elseif(UNIX)
    target_link_options(tpmshx_result_shared PRIVATE "LINKER:--version-script,${CMAKE_CURRENT_LIST_DIR}/result.map")
    set_property(TARGET tpmshx_result_shared APPEND PROPERTY LINK_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/result.map")
endif()

foreach(kind IN ITEMS static shared)
    add_executable(result_c_${kind} "${TPMSHX_NATIVE_ROOT}/tests/result_c_smoke.c")
    target_compile_features(result_c_${kind} PRIVATE c_std_11)
    set_target_properties(result_c_${kind} PROPERTIES LINKER_LANGUAGE CXX C_EXTENSIONS OFF)
    if(kind STREQUAL static)
        target_link_libraries(result_c_${kind} PRIVATE tpmshx_result_c)
    else()
        target_link_libraries(result_c_${kind} PRIVATE tpmshx_result_shared)
        target_compile_definitions(result_c_${kind} PRIVATE TPMSHX_RESULT_USE_SHARED)
    endif()
    if(APPLE)
        set_target_properties(result_c_${kind} PROPERTIES BUILD_RPATH "@loader_path")
    elseif(UNIX)
        set_target_properties(result_c_${kind} PROPERTIES BUILD_RPATH_USE_ORIGIN YES)
    endif()
    add_test(NAME result_c_${kind} COMMAND result_c_${kind})
endforeach()

add_executable(result_kernel_smoke "${TPMSHX_NATIVE_ROOT}/tests/result_smoke.cpp")
target_link_libraries(result_kernel_smoke PRIVATE tpmshx_result)
target_compile_features(result_kernel_smoke PRIVATE cxx_std_17)
add_test(NAME result_kernel_smoke COMMAND result_kernel_smoke)

add_executable(result_stage_smoke "${TPMSHX_NATIVE_ROOT}/tests/result_stage_smoke.cpp")
target_link_libraries(result_stage_smoke PRIVATE tpmshx_result_c)
target_compile_features(result_stage_smoke PRIVATE cxx_std_17)
add_test(NAME result_stage_smoke COMMAND result_stage_smoke)
