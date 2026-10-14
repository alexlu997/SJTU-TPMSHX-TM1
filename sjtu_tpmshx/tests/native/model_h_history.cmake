# Qualification-only copies, using the same observation approach as N4.
# The original numerical source and production targets are left unchanged.
function(_model_h_observer_replace needle replacement)
    string(FIND "${observed_source}" "${needle}" first)
    if(first LESS 0)
        message(FATAL_ERROR "Model-h observation anchor is absent: ${needle}")
    endif()
    string(LENGTH "${needle}" length)
    math(EXPR end "${first}+${length}")
    string(SUBSTRING "${observed_source}" ${end} -1 remaining)
    string(FIND "${remaining}" "${needle}" duplicate)
    if(NOT duplicate EQUAL -1)
        message(FATAL_ERROR "Model-h observation anchor is not unique: ${needle}")
    endif()
    string(REPLACE "${needle}" "${replacement}" observed_source "${observed_source}")
    set(observed_source "${observed_source}" PARENT_SCOPE)
endfunction()

function(_model_h_history_target dimension)
    set(original "${TPMSHX_ROOT}/native/src/model_h_${dimension}d.cpp")
    set(observed "${CMAKE_CURRENT_BINARY_DIR}/model_h_${dimension}d_history.cpp")
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${original}")
    file(READ "${original}" observed_source)
    if(dimension EQUAL 2)
        set(validation "    validate(g,a,b,ks,t,c,prescribed_b);")
        set(sweep "        const double change=sweeps(mesh,side_a,side_b,ks,t,result.last_a,result.last_b,count,c.red_black,solve_b);")
        set(fields "t,result.last_a,result.last_b")
    else()
        set(validation "    validate(grid,a,b,ks,source_s,t,control,prescribed_b);")
        set(sweep "        const double change=sweeps(mesh,side_a,side_b,ks,source_s,t,control,count,line_axis,line_work,carry,diffusion,solve_b);")
        set(fields "t")
        _model_h_observer_replace(
            "    const auto reset_carry=[&] { for(auto& field:carry) std::fill(field.begin(),field.end(),0.); };"
            "    const auto reset_carry=[&] {\n        double before=0.;\n        for(const auto& field:carry) for(double value:field) before=std::max(before,std::abs(value));\n        for(auto& field:carry) std::fill(field.begin(),field.end(),0.);\n        observe_model_h_carry(carry,before);\n    };")
    endif()
    _model_h_observer_replace("${validation}"
        "    model_h_trace.clear();\n    std::size_t observed_steps=0;\n${validation}")
    _model_h_observer_replace("${sweep}"
        "${sweep}\n        observed_steps+=count;\n        observe_model_h(0,count,change,${fields});")
    _model_h_observer_replace("                    const double ordinary=step(1);"
        "                    const double ordinary=step(1);\n                    observe_model_h(1,observed_steps,ordinary,${fields});")
    _model_h_observer_replace("                    const double proposed=step(1);"
        "                    const double proposed=step(1);\n                    observe_model_h(2,observed_steps,proposed,${fields});")
    _model_h_observer_replace("                    return accepted?proposed:ordinary;"
        "                    observe_model_h(3,observed_steps,accepted?proposed:ordinary,${fields});\n                    return accepted?proposed:ordinary;")
    file(WRITE "${observed}" "#include \"model_h_history.hpp\"\n${observed_source}")
    add_library(tpmshx_model_h_${dimension}d_history STATIC "${observed}")
    target_include_directories(tpmshx_model_h_${dimension}d_history PRIVATE
        "${TPMSHX_ROOT}/native/src" "${TPMSHX_ROOT}/sjtu_tpmshx/tests/native")
    target_compile_definitions(tpmshx_model_h_${dimension}d_history PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_compile_options(tpmshx_model_h_${dimension}d_history PRIVATE
        "$<TARGET_PROPERTY:tpmshx_model_h_${dimension}d,COMPILE_OPTIONS>")
    target_link_libraries(tpmshx_model_h_${dimension}d_history PUBLIC tpmshx_models tpmshx_energy)
    add_library(model_h_${dimension}d_history_test SHARED
        "${TPMSHX_ROOT}/sjtu_tpmshx/tests/native/model_h_${dimension}d_bridge.cpp")
    target_compile_definitions(model_h_${dimension}d_history_test PRIVATE TPMSHX_THERMAL_BUILD_SHARED)
    target_compile_options(model_h_${dimension}d_history_test PRIVATE
        "$<TARGET_PROPERTY:model_h_${dimension}d_test,COMPILE_OPTIONS>")
    target_link_libraries(model_h_${dimension}d_history_test PRIVATE tpmshx_model_h_${dimension}d_history)
endfunction()

_model_h_history_target(2)
_model_h_history_target(3)
