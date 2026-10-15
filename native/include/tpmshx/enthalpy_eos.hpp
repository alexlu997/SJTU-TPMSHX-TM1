#pragma once

#include "tpmshx/side_physics.hpp"

#include <array>
#include <memory>
#include <string>

namespace tpmshx {

struct EnthalpyProperties {
    double cp, conductivity;
};

struct EnthalpyPTState {
    double enthalpy, cp, conductivity;
};

// One evaluator belongs to each run. Direct callers retain HEOS by default.
// An integral relation uses the existing air/water model and phase guards.
class EnthalpyEOS {
public:
    EnthalpyEOS();
    ~EnthalpyEOS();
    EnthalpyEOS(const EnthalpyEOS&) = delete;
    EnthalpyEOS& operator=(const EnthalpyEOS&) = delete;

    void validate(Fluid fluid, double temperature, double pressure,
                  const std::string& where);
    EnthalpyProperties evaluate(Fluid fluid, double temperature, double pressure,
                                EnergyRelation energy=EnergyRelation::eos_h_TP);
    // Actual single-phase PT state, including the project water/CO2 guards.
    // Unlike mathematical bracket evaluation, this can certify a T update.
    EnthalpyPTState evaluate_state(Fluid fluid, double temperature, double pressure,
                                  const std::string& where,
                                  EnergyRelation energy=EnergyRelation::eos_h_TP);
    double conductivity(Fluid fluid, double temperature, double pressure,
                        EnergyRelation energy=EnergyRelation::eos_h_TP);
    double temperature(Fluid fluid, double enthalpy, double pressure,
                       bool use_bicubic, const std::string& where,
                       EnergyRelation energy=EnergyRelation::eos_h_TP);
    // Mathematical scalar bracket evaluation, intentionally outside the
    // actual-state project guard. Caller validates physical inlet/warm states.
    double bracket_enthalpy(Fluid fluid, double temperature, double pressure,
                            EnergyRelation energy=EnergyRelation::eos_h_TP);
    // Called after the first cancellation check. The native library accepts
    // one absolute table path for its lifetime; it cannot be changed per run.
    void enable_bicubic(const std::string& absolute_table_directory);

private:
    CoolProp::AbstractState& heos(Fluid fluid);
    CoolProp::AbstractState& transport_state(Fluid fluid, double temperature, double pressure);
    PropertyEvaluator models_;
    std::array<std::unique_ptr<CoolProp::AbstractState>,4> heos_;
    std::unique_ptr<CoolProp::AbstractState> bicubic_;
};

}  // namespace tpmshx
