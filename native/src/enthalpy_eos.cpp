#include "tpmshx/enthalpy_eos.hpp"
#include "tpmshx/model_coefficients.hpp"

#include <CoolProp/AbstractState.h>
#include <CoolProp/Exceptions.h>

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
    index(fluid);
    if (fluid == Fluid::water) {
        try { guards_.check_water(temperature,pressure); }
        catch (const WaterStateError& error) {
            std::ostringstream message;
            message << where << ": water T=" << temperature << " K, P_abs=" << pressure
                    << " Pa: " << error.what();
            throw WaterStateError(message.str());
        }
        return;
    }
    positive(temperature,pressure);
    if (fluid == Fluid::co2) guards_.check_co2(temperature,pressure);
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
    // Python _prop_field validates the sCO2 project domain here. Water's
    // physical guard has just run on the inverse T(h,P) field; do not add a
    // second phase/property path to each transport or final-k evaluation.
    if (uses_co2_eos(fluid)) validate(fluid,temperature,pressure,"enthalpy property field");
    else positive(temperature,pressure);
    auto& state = heos(fluid);
    state.update(CoolProp::PT_INPUTS,pressure,temperature);
    return state;
}

EnthalpyProperties EnthalpyEOS::evaluate(Fluid fluid, double temperature, double pressure) {
    auto& state = transport_state(fluid,temperature,pressure);
    const EnthalpyProperties result{state.cpmass(),state.conductivity()};
    if (!std::isfinite(result.cp) || result.cp <= 0.
        || !std::isfinite(result.conductivity) || result.conductivity <= 0.)
        throw std::domain_error("nonfinite or nonpositive true-h EOS property");
    return result;
}

EnthalpyPTState EnthalpyEOS::evaluate_state(Fluid fluid, double temperature, double pressure,
                                          const std::string& where) {
    validate(fluid,temperature,pressure,where);
    auto& state = heos(fluid);
    state.update(CoolProp::PT_INPUTS,pressure,temperature);
    if (state.phase() == CoolProp::iphase_twophase)
        throw std::invalid_argument(where+": conservative energy requires a single-phase state");
    const EnthalpyPTState result{state.hmass(),state.cpmass(),state.conductivity()};
    if (!std::isfinite(result.enthalpy) || !std::isfinite(result.cp) || result.cp <= 0.
        || !std::isfinite(result.conductivity) || result.conductivity <= 0.)
        throw std::domain_error(where+": invalid actual PT energy state");
    return result;
}

double EnthalpyEOS::conductivity(Fluid fluid, double temperature, double pressure) {
    const double result = transport_state(fluid,temperature,pressure).conductivity();
    if (!std::isfinite(result) || result <= 0.)
        throw std::domain_error("nonfinite or nonpositive true-h EOS conductivity");
    return result;
}

double EnthalpyEOS::bracket_enthalpy(Fluid fluid, double temperature, double pressure) {
    positive(temperature,pressure);
    auto& state = heos(fluid);
    state.update(CoolProp::PT_INPUTS,pressure,temperature);
    const double result = state.hmass();
    if (!std::isfinite(result)) throw std::domain_error("nonfinite true-h bracket enthalpy");
    return result;
}

void EnthalpyEOS::enable_bicubic(const std::string& absolute_table_directory) {
    configure_eos_tables_once(absolute_table_directory.c_str());
    if (!bicubic_) bicubic_ = make_eos_state("BICUBIC&HEOS","CO2");
}

double EnthalpyEOS::temperature(Fluid fluid, double enthalpy, double pressure,
                               bool use_bicubic, const std::string& where) {
    double result;
    try {
        if (!std::isfinite(enthalpy) || !std::isfinite(pressure) || pressure <= 0.)
            throw std::invalid_argument("true-h inverse requires finite h and positive Pa(abs)");
        if (use_bicubic && (fluid != Fluid::sco2 || !bicubic_))
            throw std::invalid_argument("true-h BICUBIC state was not configured for CO2");
        auto& state = use_bicubic ? *bicubic_ : heos(fluid);
        state.update(CoolProp::HmassP_INPUTS,enthalpy,pressure);
        result = state.T();
        if (!use_bicubic) {
            // CoolProp 8 HP uses 30-bit T brackets; restore HEOS enthalpy consistency.
            validate(fluid,result,pressure,where);
            state.update(CoolProp::PT_INPUTS,pressure,result);
            result += (enthalpy-state.hmass())/state.cpmass();
        }
    } catch (const std::exception& error) {
        if (fluid != Fluid::water) throw;
        std::ostringstream message;
        message << where << ": water EOS T(h,P) state unconfirmed; input h=" << enthalpy
                << " J/kg, P_abs=" << pressure << " Pa: " << error.what();
        throw WaterStateError(message.str());
    }
    validate(fluid,result,pressure,where);
    return result;
}

}  // namespace tpmshx
