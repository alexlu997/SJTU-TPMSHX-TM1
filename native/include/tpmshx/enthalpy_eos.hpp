#pragma once

#include "tpmshx/fluid_properties.hpp"

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

// Real-fluid HEOS used only by the existing true-h equation. In particular,
// true-h Air/Water h, cp and k are EOS quantities; QD/model-h keep their
// separate empirical PropertyEvaluator route. One evaluator belongs to a run.
class EnthalpyEOS {
public:
    EnthalpyEOS();
    ~EnthalpyEOS();
    EnthalpyEOS(const EnthalpyEOS&) = delete;
    EnthalpyEOS& operator=(const EnthalpyEOS&) = delete;

    void validate(Fluid fluid, double temperature, double pressure,
                  const std::string& where);
    EnthalpyProperties evaluate(Fluid fluid, double temperature, double pressure);
    // Actual single-phase PT state, including the project water/CO2 guards.
    // Unlike mathematical bracket evaluation, this can certify a T update.
    EnthalpyPTState evaluate_state(Fluid fluid, double temperature, double pressure,
                                  const std::string& where);
    double conductivity(Fluid fluid, double temperature, double pressure);
    double temperature(Fluid fluid, double enthalpy, double pressure,
                       bool use_bicubic, const std::string& where);
    // Mathematical scalar bracket evaluation, intentionally outside the
    // actual-state project guard. Caller validates physical inlet/warm states.
    double bracket_enthalpy(Fluid fluid, double temperature, double pressure);
    // Called after the first cancellation check. The native library accepts
    // one absolute table path for its lifetime; it cannot be changed per run.
    void enable_bicubic(const std::string& absolute_table_directory);

private:
    CoolProp::AbstractState& heos(Fluid fluid);
    CoolProp::AbstractState& transport_state(Fluid fluid, double temperature, double pressure);
    std::array<std::unique_ptr<CoolProp::AbstractState>,4> heos_;
    std::unique_ptr<CoolProp::AbstractState> bicubic_;
    PropertyEvaluator guards_;
};

}  // namespace tpmshx
