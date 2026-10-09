#pragma once
#include "tpmshx/enthalpy_driver_c_api.h"
#include "tpmshx/enthalpy_driver.hpp"
#include <CoolProp/CoolProp.h>
#include <cmath>
#include <cstdio>
#include <stdexcept>

namespace tpmshx {
inline EnthalpyAlgorithm energy_algorithm(const tpmshx_energy_options_v1& options) {
    if (options.algorithm > TPMSHX_ENERGY_TEMPERATURE_SOU
        || !std::isfinite(options.temperature_update_tolerance)
        || options.temperature_update_tolerance <= 0.)
        throw std::invalid_argument("invalid conservative energy options");
    return static_cast<EnthalpyAlgorithm>(options.algorithm);
}
inline void apply_energy_options(EnthalpyControl& control, const tpmshx_energy_options_v1& options) {
    control.algorithm = energy_algorithm(options);
    control.temperature_update_tolerance = options.temperature_update_tolerance;
}
inline void apply_energy_options(EnthalpyControl& control, const tpmshx_energy_options_v2& options) {
    if (options.require_enthalpy_update_on_temperature > 1
        || !std::isfinite(options.coupled_energy_tolerance) || options.coupled_energy_tolerance <= 0.
        || !std::isfinite(options.equation_energy_tolerance) || options.equation_energy_tolerance <= 0.
        || !control.max_iterations || !std::isfinite(control.omega) || control.omega <= 0. || control.omega > 1.
        || !std::isfinite(control.update_tolerance) || control.update_tolerance <= 0.)
        throw std::invalid_argument("invalid strict conservative energy options");
    apply_energy_options(control,tpmshx_energy_options_v1{options.algorithm,options.temperature_update_tolerance});
    control.coupled_energy_tolerance = options.coupled_energy_tolerance;
    control.equation_energy_tolerance = options.equation_energy_tolerance;
    control.require_enthalpy_update_on_temperature = options.require_enthalpy_update_on_temperature != 0;
}
inline tpmshx_energy_result_v1 energy_c_view(const EnthalpyResult& result) {
    const bool available = result.stop != EnthalpyStop::cancelled && result.temperature_update.has_value();
    return {static_cast<uint32_t>(result.algorithm), available ? 1u : 0u,
            available ? *result.temperature_update : 0., result.picard_relaxation};
}
inline tpmshx_enthalpy_result_v1 enthalpy_c_view(const EnthalpyResult& native) {
tpmshx_enthalpy_result_v1 output{};
output.stop = static_cast<uint32_t>(native.stop);
output.iterations = native.iterations;
output.last_clips[0] = native.last_clips.a; output.last_clips[1] = native.last_clips.b;
output.total_clips[0] = native.total_clips.a; output.total_clips[1] = native.total_clips.b;
if (native.stop != EnthalpyStop::cancelled) {
    output.residual = native.residual; output.q_a = native.q_a; output.q_b = native.q_b;
    output.energy_imbalance = native.energy_imbalance;
    for (size_t i = 0; i < 2; ++i) {
        output.inlet_enthalpy[i] = native.inlet_enthalpy[i];
        output.used_bicubic[i] = native.used_bicubic[i] ? 1u : 0u;
    }
    output.heos_polish = native.heos_polish ? 1u : 0u;
    output.audit_available = native.final_audit ? 1u : 0u;
    if (native.final_audit) {
        const auto& a = *native.final_audit;
        output.audit = {a.q_a,a.q_b,a.net,a.solid_abs_sum,a.denominator,a.coupled_ratio,
            {a.fluid_abs_sum[0],a.fluid_abs_sum[1]}, {a.fluid_cell_max[0],a.fluid_cell_max[1]},
            a.equation_ratio,a.fluid_equations_computed ? 1u : 0u};
    }
    std::snprintf(output.coolprop_version,sizeof(output.coolprop_version),"%s",
                  CoolProp::get_global_param_string("version").c_str());
}
return output;
}
} // namespace tpmshx
