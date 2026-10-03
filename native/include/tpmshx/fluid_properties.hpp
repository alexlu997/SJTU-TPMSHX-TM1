#pragma once

#include <memory>
#include <stdexcept>

namespace CoolProp { class AbstractState; }

namespace tpmshx {

// All native EOS consumers share this construction lock: CoolProp's lazy
// process-wide fluid library is mutable. Returned states belong to the caller.
std::unique_ptr<CoolProp::AbstractState> make_eos_state(const char* backend, const char* fluid);
// Configure this native library's tabular storage once, before BICUBIC use.
// An absolute UTF-8 directory is required. Repeating the same path is allowed;
// switching it after initialization is rejected to protect concurrent runs.
void configure_eos_tables_once(const char* absolute_directory);

enum class Fluid { air, water, sco2 };
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
};

// One instance per run. Mutable EOS states are not shared between runs or
// threads. Air/water retain the project's empirical transport correlations;
// HEOS checks water's stable liquid phase and supplies sCO2 properties.
// Coefficients are generated at build time from the existing Python model
// owners; neither Python nor a model-file parser is required at runtime.
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
    // Existing QD Nu policy: fixed air Pr; representative water/sCO2 Pr;
    // no local laminar floor, experimental C_eff or geometry recalculation.
    double quick_design_nu(Fluid fluid, Topology topology, double re,
                           double cell_length_m, double hydraulic_diameter_m);

private:
    std::unique_ptr<CoolProp::AbstractState> co2_, water_;
};

}  // namespace tpmshx
