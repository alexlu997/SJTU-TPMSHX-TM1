#include "tpmshx/enthalpy_eos.hpp"
#include "tpmshx/model_coefficients.hpp"

#include <CoolProp/AbstractState.h>
#include <CoolProp/Exceptions.h>

#include <algorithm>
#include <cmath>
#include <sstream>

namespace tpmshx {
namespace {

std::size_t index(Fluid fluid) {
    switch (fluid) {
        case Fluid::air: return 0;
        case Fluid::water: return 1;
        case Fluid::sco2: return 2;
        case Fluid::co2: return 3;
    }
    throw std::invalid_argument("unsupported true-h fluid");
}

bool integral(Fluid fluid,EnergyRelation energy) {
    if(energy==EnergyRelation::eos_h_TP)return false;
    if(energy!=EnergyRelation::integral_cp_T)
        throw std::invalid_argument("unsupported energy relation");
    model_h_coefficients(fluid);
    return true;
}


void positive(double temperature, double pressure) {
    if (!std::isfinite(temperature) || !std::isfinite(pressure)
        || temperature <= 0. || pressure <= 0.)
        throw std::invalid_argument("true-h EOS requires finite positive K and Pa(abs)");
}
}  // namespace

EnthalpyEOS::EnthalpyEOS() = default;
EnthalpyEOS::~EnthalpyEOS() = default;

CoolProp::AbstractState& EnthalpyEOS::heos(Fluid fluid) {
    const auto i = index(fluid);
    const char* names[] = {"Air","Water","CO2","CO2"};
    if (!heos_[i]) heos_[i] = make_eos_state("HEOS",names[i]);
    return *heos_[i];
}

void EnthalpyEOS::validate(Fluid fluid, double temperature, double pressure,
                         const std::string& where) {
    const auto slot = index(fluid);
    if (fluid == Fluid::water) {
        try { detail::check_water_pt(heos_[slot],temperature,pressure); }
        catch (const WaterStateError& error) {
            std::ostringstream message;
            message << where << ": water T=" << temperature << " K, P_abs=" << pressure
                    << " Pa: " << error.what();
            throw WaterStateError(message.str());
        }
        return;
    }
    positive(temperature,pressure);
    if (fluid == Fluid::co2) detail::check_co2_pt(heos_[slot],temperature,pressure);
    if (fluid == Fluid::sco2) {
        const auto& tr = model_coefficients::sco2_temperature_range;
        const auto& pr = model_coefficients::sco2_pressure_range;
        if (temperature < tr[0] || temperature > tr[1])
            throw std::invalid_argument(where+": sCO2 temperature must be within 280..700 K");
        if (pressure < pr[0] || pressure > pr[1])
            throw std::invalid_argument(where+": sCO2 pressure must be within 7.9..16 MPa");
    }
}

CoolProp::AbstractState& EnthalpyEOS::transport_state(Fluid fluid, double temperature, double pressure) {
    // The actual-state caller has checked water phase. Keep transport on
    // that property path and check the CO2 project domain here.
    if (uses_co2_eos(fluid)) validate(fluid,temperature,pressure,"enthalpy property field");
    else positive(temperature,pressure);
    auto& state = heos(fluid);
    if (fluid != Fluid::co2) state.update(CoolProp::PT_INPUTS,pressure,temperature);
    return state;
}

EnthalpyProperties EnthalpyEOS::evaluate(Fluid fluid, double temperature, double pressure,
                                       EnergyRelation energy) {
    if(integral(fluid,energy)) {
        const auto properties=models_.transport(fluid,temperature,pressure);
        return {properties.cp,properties.k};
    }
    auto& state = transport_state(fluid,temperature,pressure);
    const EnthalpyProperties result{state.cpmass(),state.conductivity()};
    if (!std::isfinite(result.cp) || result.cp <= 0.
        || !std::isfinite(result.conductivity) || result.conductivity <= 0.)
        throw std::domain_error("nonfinite or nonpositive true-h EOS property");
    return result;
}

EnthalpyPTState EnthalpyEOS::evaluate_state(Fluid fluid, double temperature, double pressure,
                                          const std::string& where,EnergyRelation energy) {
    const bool model=integral(fluid,energy);
    validate(fluid,temperature,pressure,where);
    if(model) {
        const auto properties=models_.transport(fluid,temperature,pressure);
        const double h=model_enthalpy(temperature,model_h_coefficients(fluid));
        if(!std::isfinite(h))throw std::domain_error(where+": invalid integral enthalpy state");
        return {h,properties.cp,properties.k};
    }
    auto& state = heos(fluid);
    if (fluid != Fluid::water && fluid != Fluid::co2)
        state.update(CoolProp::PT_INPUTS,pressure,temperature);
    if (state.phase() == CoolProp::iphase_twophase)
        throw std::invalid_argument(where+": conservative energy requires a single-phase state");
    const EnthalpyPTState result{state.hmass(),state.cpmass(),state.conductivity()};
    if (!std::isfinite(result.enthalpy) || !std::isfinite(result.cp) || result.cp <= 0.
        || !std::isfinite(result.conductivity) || result.conductivity <= 0.)
        throw std::domain_error(where+": invalid actual PT energy state");
    return result;
}

double EnthalpyEOS::conductivity(Fluid fluid, double temperature, double pressure,EnergyRelation energy) {
    if(integral(fluid,energy))return models_.transport(fluid,temperature,pressure).k;
    const double result = transport_state(fluid,temperature,pressure).conductivity();
    if (!std::isfinite(result) || result <= 0.)
        throw std::domain_error("nonfinite or nonpositive true-h EOS conductivity");
    return result;
}

double EnthalpyEOS::bracket_enthalpy(Fluid fluid, double temperature, double pressure,EnergyRelation energy) {
    positive(temperature,pressure);
    if(integral(fluid,energy)) {
        const double result=model_enthalpy(temperature,model_h_coefficients(fluid));
        if(!std::isfinite(result))throw std::domain_error("nonfinite model bracket enthalpy");
        return result;
    }
    auto& state = heos(fluid);
    state.update(CoolProp::PT_INPUTS,pressure,temperature);
    const double result = state.hmass();
    if (!std::isfinite(result)) throw std::domain_error("nonfinite true-h bracket enthalpy");
    return result;
}
}  // namespace tpmshx
