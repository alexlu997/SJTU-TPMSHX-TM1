#pragma once

#include "tpmshx/enthalpy_driver.hpp"
#include "tpmshx/model_h_2d.hpp"
#include "tpmshx/pressure_reference.hpp"
#include "tpmshx/simple_2d.hpp"
#include "tpmshx/closure_evidence.hpp"

#include <variant>

namespace tpmshx {

enum class Full2DThermalMode { temperature, model_h, true_h };

struct Full2DSide {
    Fluid fluid;
    int direction;
    double inlet_temperature, inlet_pressure, inlet_velocity, initial_viscosity;
    double seed_permeability, seed_forchheimer;
    // Prepared +y SIMPLE coordinates. Row drag remains authoritative for the
    // original graded pressure seed; optional full fields override momentum.
    ArrayView<const double> row_permeability, row_forchheimer;
    ArrayView<const double> permeability{}, forchheimer{};
    ArrayView<const double> inlet_geometry, outlet_geometry, inlet_profile, outlet_profile;
    ArrayView<const double> outlet_u_fraction;
    double inlet_lo, inlet_hi, outlet_lo, outlet_hi;
    bool uniform_inlet;
    // Original scalar side/reference geometry used only for nonzero offset.
    double side_area_density, side_hydraulic_diameter, reference_area_density, reference_hydraulic_diameter;
};

struct Full2DProblem {
    GridView grid; // physical x/y, nz=1, dz=1
    std::array<Full2DSide,2> sides;
    Topology topology;
    Full2DThermalMode thermal_mode;
    // Already-prepared symmetric Kff; preserve the supplied case's values.
    std::array<ArrayView<const double>,2> fluid_conductivity;
    ArrayView<const double> solid_conductivity, total_porosity;
    // Actual cell geometry. Binding may materialize prepared scalar values.
    ArrayView<const double> area_density, hydraulic_diameter, cell_length;
    // Dimensionless closure input in its original prepared arithmetic:
    // (hydraulic_diameter_m * 1000) / cell_length_mm.
    ArrayView<const double> nu_geometry_ratio;
    double reference_cell_length, reference_porosity, split_a, sco2_nu_multiplier;
    bool asymmetric;
    std::optional<double> initial_solid_temperature;
    bool spatial_geometry=false; // distinguish original scalar inputs from materialized fields
};

struct Full2DControl {
    // Controls are resolved from the existing caller settings. The reference
    // pressure/ideal-gas fields in flow are resolved from each side at runtime.
    Simple2DControl flow;
    std::size_t outer_iterations, thermal_iterations, thermal_chunk;
    double outer_temperature_tolerance, outer_density_tolerance, outer_relaxation;
    double thermal_q_tolerance, enthalpy_update_tolerance;
    bool pressure_shooting, thermal_red_black; // original global RB opt-in; size gate remains native
    std::string envelope_mode, table_directory;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*,std::size_t,std::size_t) = nullptr;
    void (*residual)(void*,std::size_t,std::size_t,double) = nullptr; // side,iter,residual
    void* context = nullptr;
};

struct Full2DFlow {
    std::vector<double> dx,dy;
    // Solver coordinates, matching the complete independent SIMPLE interface.
    std::vector<double> u,v,pressure,pressure_correction,d_u,d_v,density,inlet_velocity;
    std::vector<double> viscosity,effective_viscosity,temperature,epsilon;
    double reference_pressure=std::numeric_limits<double>::quiet_NaN(),taper_flux_scale=1.;
    std::optional<double> massflux_target;
    Simple2DResult result;
    SimpleHistory history;
    std::optional<PressurePortState> pressure_state;
    std::vector<PressureIteration> pressure_iterations;
    // Completed raw physical-axis evidence, before any later property update.
    std::vector<double> uc,vc,absolute_pressure,mass_x,mass_y;
};

struct Full2DThermalState {
    std::array<std::vector<double>,3> temperature;
    std::array<std::vector<double>,2> hv,conductivity,pressure,rho_cp;
    std::array<std::vector<double>,2> mass_x,mass_y;
    std::array<std::vector<double>,2> inlet_capacity;
    std::vector<double> solid_conductivity,h_a,h_b;
    std::variant<TemperatureResult,ModelHResult2D,EnthalpyResult> result;
};

struct Full2DOuterRecord {
    std::size_t iteration,thermal_iterations;
    bool thermal_converged,outer_converged;
    std::array<double,2> relative_density_change;
    std::array<double,3> temperature_change;
};

struct Full2DRefinedState {
    std::vector<double> dx,dy,epsilon;
    std::array<std::vector<double>,2> uc,vc,inlet_profile,outlet_profile;
    Full2DThermalState thermal;
    bool accepted=false,extrapolated=false,warning=true;
    std::array<double,2> duty{},extrapolated_duty{};
};

struct Full2DResult {
    bool cancelled=false,outer_converged=false,post_after_last_thermal=false;
    std::size_t iterations=0;
    std::array<Full2DFlow,2> flow;
    Full2DThermalState thermal;
    std::vector<Full2DOuterRecord> outer_history;
    std::array<EnvelopeAssessment,2> envelope{};
    // Returned outer property state can be post-updated on a capped exit.
    // Thermal inputs above always remain from the actual last thermal call.
    std::array<std::vector<double>,2> density,viscosity,rho_cp;
    std::optional<Full2DRefinedState> refined;
    bool converged=false,simple_ok=false,thermal_ok=false,envelope_ok=false;
    bool pair_balance_ok=false,model_balance_ok=false;
    std::array<double,2> pressure_drop{},outlet_temperature{},inlet_mass{},duty{};
    double q_total=0.,q_solid=0.,energy_imbalance=0.;
    std::array<NuObservation,2> nu_observations;
    std::vector<RangeObservation> range_observations;
};

// Complete coarse-grid 2D flow-first coupling. Native owns initialization,
// pressure shooting, SIMPLE rebuilds, property/local-hv refresh, thermal
// solves, original outer stopping/post-update order and final actual-state
// guards. Geometry/D-F fields are prepared inputs; no Python callbacks do
// numerical work. Richardson refinement is a separate required final phase
// and is not yet represented by this coarse result's outer_converged flag.
// Failed/cancelled states are invalid for accepted-result publication.
Full2DResult solve_full_2d_coarse(const Full2DProblem& problem,const Full2DControl& control);

// Public numerical path also owns mandatory 2x thermal Richardson for
// temperature/model-h. True-h uses its original exact-enthalpy duty instead.
// Refinement budgets and gates retain the current caller's fixed policy.
Full2DResult solve_full_2d(const Full2DProblem& problem,const Full2DControl& control);

} // namespace tpmshx
