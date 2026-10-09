#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/model_coefficients.hpp"

#include <CoolProp/AbstractState.h>
#include <CoolProp/CoolProp.h>
#include <CoolProp/Exceptions.h>
#include <CoolProp/Configuration.h>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <mutex>
#include <string>
#include <string_view>

namespace tpmshx {
namespace {
std::mutex factory_mutex;
std::string tables_directory;
}

void configure_eos_tables_once(const char* absolute_directory) {
    if (!absolute_directory || !*absolute_directory)
        throw std::invalid_argument("native EOS tables require an absolute directory");
    const auto requested = std::filesystem::u8path(absolute_directory);
    if (!requested.is_absolute())
        throw std::invalid_argument("native EOS tables require an absolute directory");
    const std::lock_guard<std::mutex> lock(factory_mutex);
    const auto versioned = requested / ("CoolProp-" + CoolProp::get_global_param_string("version"));
    const auto directory = std::filesystem::weakly_canonical(versioned).generic_u8string()+"/";
    if (!tables_directory.empty()) {
        if (tables_directory != directory)
            throw std::invalid_argument("native EOS table directory is already fixed for this library");
        return;
    }
    std::filesystem::create_directories(versioned);
    CoolProp::set_config_string(ALTERNATIVE_TABLES_DIRECTORY,directory);
    tables_directory = directory;
}

std::unique_ptr<CoolProp::AbstractState> make_eos_state(const char* backend, const char* fluid) {
    // CoolProp lazily mutates shared fluid/table libraries during construction;
    // serialize initialization while all subsequent updates stay local.
    // ponytail: one factory lock; split initialization only if startup throughput matters.
    const std::lock_guard<std::mutex> lock(factory_mutex);
    if (!backend || !fluid) throw std::invalid_argument("missing EOS backend or fluid");
    const bool tabular = std::string_view(backend) == "BICUBIC&HEOS";
    if (tabular && tables_directory.empty())
        throw std::invalid_argument("configure native EOS table directory before BICUBIC use");
    auto state = std::unique_ptr<CoolProp::AbstractState>(CoolProp::AbstractState::factory(backend, fluid));
    // The first tabular update mutates CoolProp's dataset library and writes
    // cache files. Finish it under the same lock before independent run use.
    if (tabular) {
        if (std::string_view(fluid) != "CO2")
            throw std::invalid_argument("native tabular EOS is supported only for CO2");
        state->update(CoolProp::PT_INPUTS,8e6,300.);
    }
    return state;
}

namespace {
namespace data = model_coefficients;

void positive_state(double temperature, double pressure) {
    if (!std::isfinite(temperature) || !std::isfinite(pressure)
        || temperature <= 0. || pressure <= 0.)
        throw std::invalid_argument("properties require finite positive K and Pa(abs)");
}

std::size_t topology_row(Topology topology) {
    switch (topology) {
        case Topology::diamond: return 0;
        case Topology::gyroid: return 1;
    }
    throw std::invalid_argument("unsupported property topology");
}

void nu_inputs(double re,double length,double diameter) {
    if (!std::isfinite(re) || re < 0. || !std::isfinite(length) || length <= 0.
        || !std::isfinite(diameter) || diameter <= 0.)
        throw std::invalid_argument("Nu requires finite nonnegative Re and positive cell length/Dh");
}
}  // namespace

PropertyEvaluator::PropertyEvaluator() = default;
PropertyEvaluator::~PropertyEvaluator() = default;

double PropertyEvaluator::check_water(double temperature, double pressure) {
    if (!std::isfinite(temperature) || !std::isfinite(pressure)
        || temperature <= 0. || pressure <= 0.)
        throw WaterStateError("water requires finite positive K and Pa(abs)");
    try {
        if (!water_) water_ = make_eos_state("HEOS", "Water");
        water_->update(CoolProp::PT_INPUTS, pressure, temperature);
        const auto phase = water_->phase();
        if (phase == CoolProp::iphase_supercritical_liquid)
            throw WaterStateError("high-pressure liquid: T-only model applicability unconfirmed");
        if (phase != CoolProp::iphase_liquid)
            throw WaterStateError("only stable single-phase liquid water is supported");
        if (!water_->has_melting_line())
            throw WaterStateError("solid/liquid stability unconfirmed");
        const double melting = water_->melting_line(CoolProp::iT, CoolProp::iP, pressure);
        if (!std::isfinite(melting) || temperature <= melting)
            throw WaterStateError("freezing boundary or solid/metastable water unsupported");
        return melting;
    } catch (const CoolProp::CoolPropBaseError& error) {
        throw WaterStateError(error.what());
    }
}

FluidProperties PropertyEvaluator::evaluate(Fluid fluid, double temperature, double pressure) {
    if (fluid == Fluid::water) check_water(temperature, pressure);
    return transport(fluid,temperature,pressure);
}

FluidProperties PropertyEvaluator::transport(Fluid fluid, double temperature, double pressure) {
    positive_state(temperature, pressure);
    FluidProperties result{};
    switch (fluid) {
        case Fluid::air: {
            const auto& s = data::air_sutherland;
            const auto& k = data::air_conductivity;
            const auto& cp = data::model_h_air;
            const double dt = temperature - cp[3];
            result.rho = pressure * data::air_molar_mass / (data::gas_constant * temperature);
            result.mu = s[1] * std::pow(temperature / s[0], 1.5) * (s[0] + s[2]) / (temperature + s[2]);
            result.k = k[0] * std::pow(temperature / k[1], k[2]);
            result.cp = cp[0] + cp[1] * dt + cp[2] * (dt * dt);
            break;
        }
        case Fluid::water: {
            const auto& r = data::water_density;
            const auto& m = data::water_viscosity;
            const auto& k = data::water_conductivity;
            const double dt = temperature - data::model_h_water[3];
            result.rho = r[0] - r[1] * dt - r[2] * (dt * dt);
            result.mu = m[0] * std::pow(m[1], m[2] / std::max(temperature - m[3], m[4]));
            result.k = k[0] + k[1] * dt;
            result.cp = data::model_h_water[0];
            break;
        }
        case Fluid::sco2: {
            if (temperature < data::sco2_temperature_range[0] || temperature > data::sco2_temperature_range[1])
                throw std::invalid_argument("sCO2 temperature must be within 280..700 K");
            if (pressure < data::sco2_pressure_range[0] || pressure > data::sco2_pressure_range[1])
                throw std::invalid_argument("sCO2 pressure must be within 7.9..16 MPa");
            if (!co2_) co2_ = make_eos_state("HEOS", "CO2");
            co2_->update(CoolProp::PT_INPUTS, pressure, temperature);
            result.rho = co2_->rhomass();
            result.mu = co2_->viscosity();
            result.k = co2_->conductivity();
            result.cp = co2_->cpmass();
            break;
        }
        default: throw std::invalid_argument("unsupported property fluid");
    }
    result.pr = result.mu * result.cp / result.k;
    for (const double value : {result.rho, result.mu, result.k, result.cp, result.pr})
        if (!std::isfinite(value) || value <= 0.)
            throw std::domain_error("nonfinite or nonpositive fluid property");
    return result;
}

double fluid_nusselt(Fluid fluid, Topology topology, double re,double pr,
                     double cell_length_m, double hydraulic_diameter_m,double sco2_multiplier) {
    nu_inputs(re,cell_length_m,hydraulic_diameter_m);
    return fluid_nusselt_ratio(fluid,topology,re,pr,hydraulic_diameter_m/cell_length_m,sco2_multiplier);
}

double fluid_nusselt_ratio(Fluid fluid, Topology topology, double re,double pr,
                           double hydraulic_to_cell_ratio,double sco2_multiplier) {
    nu_inputs(re,1.,hydraulic_to_cell_ratio);
    if (!std::isfinite(pr) || pr<=0. || !std::isfinite(sco2_multiplier) || sco2_multiplier<=0.)
        throw std::invalid_argument("Nu requires finite positive Pr and selected sCO2 multiplier");
    const auto row = topology_row(topology);
    double result;
    switch (fluid) {
        case Fluid::air: {
            const auto& c = data::nu_air[row];
            result = data::nu_roughness_factor * (c[0] * std::pow(data::pr_air, 1. / 3.)
                * std::pow(re, c[1]) * std::pow(hydraulic_to_cell_ratio, c[2]));
            break;
        }
        case Fluid::water: {
            const auto& c = data::nu_water[row];
            result = c[0] * std::pow(std::max(re, 1.), c[1]) * std::pow(pr, 1. / 3.);
            break;
        }
        case Fluid::sco2: {
            const auto& c = data::nu_sco2[row];
            result = c[0] * std::pow(std::max(re, 1.), c[1]) * std::pow(pr, 1. / 3.)
                * std::pow(hydraulic_to_cell_ratio, c[2]);
            result *= sco2_multiplier;
            break;
        }
        default: throw std::invalid_argument("unsupported Nu fluid");
    }
    if (!std::isfinite(result) || result < 0.) throw std::domain_error("nonfinite or negative Nu");
    return result;
}

double PropertyEvaluator::quick_design_nu(Fluid fluid, Topology topology, double re,
                                         double cell_length_m, double hydraulic_diameter_m) {
    nu_inputs(re,cell_length_m,hydraulic_diameter_m);
    double pr=data::pr_air;
    if (fluid==Fluid::water || fluid==Fluid::sco2) {
        const auto& state=fluid==Fluid::water?data::water_nu_reference_state:data::sco2_nu_reference_state;
        pr=evaluate(fluid,state[0],state[1]).pr;
    }
    return fluid_nusselt(fluid,topology,re,pr,cell_length_m,hydraulic_diameter_m);
}

double nu_extra_roughness_factor(double re,RoughnessMode mode,double roughness_m,double diameter) {
    if (mode==RoughnessMode::baseline || mode==RoughnessMode::norris_1a) return 1.;
    if (mode!=RoughnessMode::bhatti_shah_1b) throw std::invalid_argument("unsupported roughness mode");
    if (!std::isfinite(re) || re<0. || !std::isfinite(roughness_m) || roughness_m<0.
        || !std::isfinite(diameter) || diameter<=0.) throw std::invalid_argument("invalid roughness inputs");
    const auto& p=data::roughness_petukhov; const auto& h=data::roughness_haaland;
    const double smooth=std::pow(p[0]*std::log(re)-p[1],-2.);
    // Preserve the caller's m -> micrometre/mm evaluation order.
    const double ratio=(roughness_m*1e6*1e-3)/(diameter*1000.);
    const double rough=std::pow(1./(-h[0]*std::log10(std::pow(ratio/h[1],h[2])+h[3]/re)),2.);
    return std::pow(rough/smooth,data::roughness_nu_power)/data::roughness_nu_baseline;
}

}  // namespace tpmshx
