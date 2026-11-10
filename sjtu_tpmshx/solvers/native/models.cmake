include_guard(GLOBAL)

set(CP_SOURCE "${TPMSHX_NATIVE_DEPS_ROOT}/src/CoolProp-8.0.0")
foreach(required IN ITEMS "${TPMSHX_COOLPROP_LIBRARY}" "${CP_SOURCE}/include/AbstractState.h"
        "${TPMSHX_MODEL_INCLUDE_DIR}/tpmshx/model_coefficients.hpp")
    if(NOT EXISTS "${required}")
        message(FATAL_ERROR "Missing locked model input: ${required}; run the explicit fetch/build script")
    endif()
endforeach()
add_library(CoolProp::CoolProp STATIC IMPORTED)
set_target_properties(CoolProp::CoolProp PROPERTIES IMPORTED_LOCATION "${TPMSHX_COOLPROP_LIBRARY}")
target_include_directories(CoolProp::CoolProp SYSTEM INTERFACE
    "${CP_SOURCE}" "${CP_SOURCE}/include" "${CP_SOURCE}/src" "${TPMSHX_NATIVE_DEPS_ROOT}/src/Eigen-5.0.1"
    "${TPMSHX_NATIVE_DEPS_ROOT}/src/fmt-12.0.0/include" "${TPMSHX_NATIVE_DEPS_ROOT}/src/json-3.12.0/include")
target_compile_definitions(CoolProp::CoolProp INTERFACE EIGEN_MPL2_ONLY)
if(MSVC)
    target_compile_options(CoolProp::CoolProp INTERFACE "$<$<COMPILE_LANGUAGE:CXX>:/utf-8>")
endif()
find_package(Threads REQUIRED)

add_library(tpmshx_models STATIC "${TPMSHX_NATIVE_ROOT}/src/fluid_properties.cpp")
target_include_directories(tpmshx_models PUBLIC "${TPMSHX_NATIVE_ROOT}/include" "${TPMSHX_MODEL_INCLUDE_DIR}")
target_link_libraries(tpmshx_models PUBLIC CoolProp::CoolProp Threads::Threads tpmshx_grid)
target_compile_features(tpmshx_models PUBLIC cxx_std_17)
set_target_properties(tpmshx_models PROPERTIES CXX_EXTENSIONS OFF POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES C_VISIBILITY_PRESET hidden)
if(MSVC)
    target_compile_options(tpmshx_models PRIVATE /W4 /WX /EHsc /fp:strict)
else()
    # Keep separate operators and the original libm pow calls.
    target_compile_options(tpmshx_models PRIVATE -Wall -Wextra -Wpedantic -Werror
        -ffp-contract=off -fno-builtin-pow)
endif()
if(APPLE)
    target_sources(tpmshx_models PRIVATE "${TPMSHX_NATIVE_ROOT}/src/model_complex_log.c")
    target_compile_features(tpmshx_models PRIVATE c_std_11)
    set_target_properties(tpmshx_models PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF)
    find_library(TPMSHX_MODEL_ACCELERATE_FRAMEWORK Accelerate REQUIRED)
    target_link_libraries(tpmshx_models PUBLIC "${TPMSHX_MODEL_ACCELERATE_FRAMEWORK}")
endif()
