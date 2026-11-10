#pragma once

#include <array>
#include <memory>
#include <stdexcept>
#include <string>

namespace CoolProp { class AbstractState; }

namespace tpmshx {

// EOS consumers in one library image share this factory lock. Each statically
// linked CoolProp image owns its mutable fluid registry. States belong to callers.
std::unique_ptr<CoolProp::AbstractState> make_eos_state(const char* backend, const char* fluid);
enum class Fluid { air, water, sco2, co2 };
constexpr bool uses_co2_eos(Fluid fluid) {
    return fluid == Fluid::sco2 || fluid == Fluid::co2;
}
const std::array<double,5>& model_h_coefficients(Fluid fluid);
inline double model_enthalpy(double t,const std::array<double,5>& cp) {
    const double x=t-cp[3],x0=cp[4]-cp[3];
    return cp[0]*(x-x0)+0.5*cp[1]*(x*x-x0*x0)+cp[2]/3.0*(x*x*x-x0*x0*x0);
}
inline double model_heat_capacity(double t,const std::array<double,5>& cp) {
    const double x=t-cp[3];
    return cp[0]+cp[1]*x+cp[2]*(x*x);
}
double nusselt_floor(Fluid fluid);
enum class Topology { diamond, gyroid };
enum class RoughnessMode { baseline, norris_1a, bhatti_shah_1b };

struct FluidProperties {
    double rho, mu, k, cp, pr;  // kg/m3, Pa s, W/(m K), J/(kg K), dimensionless
};

// Existing empirical Nu at the caller's actual Pr. Air keeps its fixed Pr;
// water/sCO2 keep max(Re,1). No local laminar floor is applied here. The
// explicitly selected total sCO2 C_eff multiplies the CFD base exactly once,
// before a full-driver caller applies the shared generated Nu floor.
double fluid_nusselt(Fluid fluid, Topology topology, double re, double pr,
                     double cell_length_m, double hydraulic_diameter_m,
                     double sco2_multiplier = 1.);
// Preserve a prepared closure's original D_h/L arithmetic, including its
// source units, without converting a rounded SI length back to millimetres.
double fluid_nusselt_ratio(Fluid fluid, Topology topology, double re, double pr,
                          double hydraulic_to_cell_ratio, double sco2_multiplier = 1.);
// Optional original air-side addition. The caller preserves the registry's
// air-only applicability and inlet-scalar Re sampling. Modes baseline/norris
// are exact identity. Nonfinite numerical results remain visible to the
// subsequent field guards, including the original Re==0 singular behavior.
double nu_extra_roughness_factor(double re, RoughnessMode mode,
                                 double roughness_m, double hydraulic_diameter_m);

class WaterStateError : public std::invalid_argument {
public:
    using std::invalid_argument::invalid_argument;
    WaterStateError(const std::string& text,bool eos_failure)
        :std::invalid_argument(text),eos_failure(eos_failure) {}
    bool eos_failure=false;
};

namespace detail {
// Each guard updates the caller's HEOS state for the next property read.
double check_water_pt(std::unique_ptr<CoolProp::AbstractState>& state,
                      double temperature, double pressure);
void check_co2_pt(std::unique_ptr<CoolProp::AbstractState>& state,
                  double temperature, double pressure);
}  // namespace detail

// One instance per run. Mutable EOS states are not shared between runs or
// threads. Air/water retain the project's empirical transport correlations;
// HEOS checks water's stable liquid phase and supplies sCO2 properties.
// Coefficients are generated from shared model data resources at build time.
// Neither Python nor a model-file parser is required at runtime.
class PropertyEvaluator {
public:
    PropertyEvaluator();
    ~PropertyEvaluator();
    PropertyEvaluator(const PropertyEvaluator&) = delete;
    PropertyEvaluator& operator=(const PropertyEvaluator&) = delete;

    FluidProperties evaluate(Fluid fluid, double temperature, double pressure);
    // Original full-driver property primitive. Water's empirical T-only
    // sampling is separate from a paired actual-state phase check: callers
    // must invoke check_water at the original physical guard points. sCO2
    // still uses the same HEOS/domain checks; QD uses evaluate above.
    FluidProperties transport(Fluid fluid, double temperature, double pressure);
    // Returns the melting-line temperature, K. Rejects uncertain/unsupported
    // water states; it does not certify the T-only fit's pressure accuracy.
    double check_water(double temperature, double pressure);
    void check_co2(double temperature, double pressure);
    // Existing QD Nu policy: fixed air Pr; representative water/sCO2 Pr;
    // no local laminar floor, experimental C_eff or geometry recalculation.
    double quick_design_nu(Fluid fluid, Topology topology, double re,
                           double cell_length_m, double hydraulic_diameter_m);

private:
    std::unique_ptr<CoolProp::AbstractState> co2_, water_;
};

}  // namespace tpmshx
