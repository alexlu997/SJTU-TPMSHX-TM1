include_guard(GLOBAL)

add_library(tpmshx_pressure_reference STATIC "${TPMSHX_NATIVE_ROOT}/src/pressure_reference.cpp")
target_link_libraries(tpmshx_pressure_reference PUBLIC tpmshx_grid)
target_include_directories(tpmshx_pressure_reference PUBLIC "${TPMSHX_NATIVE_ROOT}/include"
    "${TPMSHX_MODEL_INCLUDE_DIR}")
target_compile_features(tpmshx_pressure_reference PUBLIC cxx_std_17)
set_target_properties(tpmshx_pressure_reference PROPERTIES CXX_EXTENSIONS OFF POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
if(MSVC)
    target_compile_options(tpmshx_pressure_reference PRIVATE /W4 /WX /EHsc /fp:strict)
else()
    target_compile_options(tpmshx_pressure_reference PRIVATE -Wall -Wextra -Wpedantic -Werror -ffp-contract=off)
endif()
