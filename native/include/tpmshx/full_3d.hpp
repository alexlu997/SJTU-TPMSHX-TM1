#pragma once

#include "tpmshx/enthalpy_driver.hpp"
#include "tpmshx/closure_evidence.hpp"
#include "tpmshx/model_h_3d.hpp"
#include "tpmshx/outer_anderson.hpp"
#include "tpmshx/pressure_reference.hpp"
#include "tpmshx/simple_3d.hpp"
#include "tpmshx/temperature_staggered.hpp"

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace tpmshx {

inline constexpr std::size_t bootstrap_auto_cell_threshold=2000;
inline constexpr std::size_t bootstrap_recursive_iterations=200;
inline constexpr std::size_t bootstrap_min_coarse_axis=4;

// All geometric fields are the prepared physical (x,y,z) fields, in C order.
// D-F correction factors are resolved preparation inputs, applied exactly once
// by this driver. No surrogate, geometry fit or model-file lookup occurs here.
struct Full3DGeometry {
    GridView grid;
    ArrayView<const double> epsilon, epsilon_a, epsilon_b;
    ArrayView<const double> permeability, forchheimer, solid_conductivity;
    ArrayView<const double> cell_length, area_density, hydraulic_diameter;
    double reference_cell_length, reference_hydraulic_diameter;
    bool spatial = false, asymmetric = false;
};

struct Full3DSide {
    Fluid fluid;
    int direction;  // physical +x,-x,+y,-y,+z,-z (0..5)
    // Solver axes are physical (cross1,stream,cross2). This is the prepared
    // axis map, not an inferred exchange of inlet and outlet for reverse flow.
    std::array<int,3> solver_axes;
    double inlet_temperature, inlet_pressure, inlet_velocity;
    std::array<double,4> inlet_rectangle, outlet_rectangle;  // solver x,z edges
    ArrayView<const double> inlet_opening, outlet_opening;   // solver (nx,nz)
    double permeability_scale = 1., forchheimer_scale = 1.;
    double dispersion = 0., sco2_nusselt_multiplier = 1.;
    // Prepared asymmetric side and its own symmetric reference A0,Dh.
    std::array<double,4> heat_transfer_geometry{1.,1.,1.,1.};
};

enum class Full3DThermalMode { temperature, model_h, true_h };
enum class Full3DStop { converged, iteration_limit, cancelled };

struct Full3DControl {
    std::size_t max_outer = 12, initial_simple_iterations = 2000;
    std::size_t warm_simple_iterations = 600, thermal_iterations = 10000;
    double outer_temperature_tolerance = .5, thermal_relaxation = .7;
    bool pressure_shooting = true, variable_rho_cp = true;
    bool conservative = true, strict_mass_balance = true, force_cell_centered = true;
    bool refined_port_energy = false, red_black_energy = false;
    bool sco2_local_pressure_a = false, coarse_bootstrap = false;
    bool outer_anderson = false;
    std::size_t coarse_iterations = bootstrap_recursive_iterations, anderson_history = 3, anderson_patience = 3;
    double anderson_trust = 5.;
    // Full execution resolves the current options; no environment lookup is
    // performed in native code. Until each option is qualified it is rejected.
    int roughness_mode = 0;  // 0 baseline, 1 retained norris_1a, 2 bhatti_shah_1b
    double roughness_height = 1e-4;
    int envelope_mode = 0;   // 0 raise, 1 warn, 2 off; all retain gate truth
    Simple3DControl simple{2000,1,100,.5,.2,.3,0.,287.05,.05,
        true,true,false,true,false,Simple3DOrdering::natural,
        {1e-4,1e-6,1e-6,.01,1e-4,1e-3,2,5,60},nullptr,nullptr,nullptr};
    EnthalpyControl enthalpy{1500,25,.6,1e-3,.001,.001,"",nullptr,nullptr};
    std::optional<double> initial_solid_temperature;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*,double percent) = nullptr;
    void (*outer_iteration)(void*,std::size_t completed,std::size_t total) = nullptr;
    void* context = nullptr;
};

struct Full3DInput {
    Full3DGeometry geometry;
    Topology topology;
    Full3DSide a, b;
    bool solve_b = true;
    std::array<ArrayView<const double>,3> sources{};  // optional A,B,solid W/m3
};

struct Full3DFlowState {
    // Complete final solver-coordinate SIMPLE state and immutable geometry.
    std::array<std::vector<double>,3> widths;
    std::vector<double> epsilon, permeability, forchheimer, temperature;
    std::vector<double> viscosity, effective_viscosity, density;
    std::vector<double> u,v,w,pressure,pressure_correction,d_u,d_v,d_w,inlet_velocity;
    std::vector<double> inlet_opening,outlet_opening,outlet_u_fraction,outlet_w_fraction;
    std::vector<double> fixed_inlet_massflux;
    double pressure_reference = 0.;
    Simple3DResult last;
    SimpleHistory history;
    std::vector<PressureIteration> pressure_iterations;
    std::optional<PressurePortState> inlet_pressure;
    struct Bootstrap {
        bool applied = false, converged = false;
        std::size_t iterations = 0;
        double residual = std::numeric_limits<double>::quiet_NaN();
        std::array<std::size_t,3> shape{};
        std::string reason;
    };
    std::optional<Bootstrap> bootstrap;
    struct BootstrapLevel {
        std::size_t depth = 0, iteration_cap = 0, charged_iterations = 0;
        std::array<std::size_t,3> fine_shape{}, coarse_shape{};
        bool solve_started = false, applied = false, converged = false, child_selected = false;
        std::string stop = "not-started";
    };
    struct BootstrapTrace {
        bool available = false, selected = false;
        std::array<std::size_t,3> fine_shape{};
        std::size_t coarse_iteration_cap = 0;
        std::string policy, decision;
        std::vector<BootstrapLevel> levels;
    } bootstrap_trace;
    // Display/report fields are always the final flow, even on outer-cap exit.
    std::vector<double> pressure_real, density_real;
    std::vector<double> speed_real;
    std::array<std::vector<double>,3> velocity_real, face_velocity_real;
};

struct Full3DThermalEvidence {
    // Detached before the subsequent post update, including the final capped
    // post. These fields cannot be reconstructed from the later final flow.
    Full3DThermalMode mode = Full3DThermalMode::temperature;
    std::size_t outer_index = 0;
    std::array<std::vector<double>,3> temperature;
    std::array<std::vector<double>,2> pressure,hv,rho_cp,conductivity;
    std::array<std::array<std::vector<double>,3>,2> mass,face_velocity;
    std::array<std::vector<double>,2> inlet_capacity,enthalpy;
    // Candidate-only final EOS conductivity and outward m*h_face power.
    // Original conductivity above remains the prepared outer property state.
    std::array<std::vector<double>,2> actual_conductivity;
    std::array<std::array<std::vector<double>,6>,2> enthalpy_boundary_power;
    std::optional<ModelHResult3D> model_h;
    std::optional<EnthalpyResult> true_h;
    std::optional<StaggeredTemperatureResult> staggered;
};

struct Full3DOuterRecord {
    std::size_t outer_index = 0, thermal_iterations = 0;
    double thermal_residual = 0.;
    std::array<double,3> temperature_change{};
    std::array<std::optional<PressurePortState>,2> inlet_pressure;
    std::array<double,2> pressure_reference{};
    std::array<std::array<double,2>,2> pressure_range{};
    bool thermal_converged = false, coupling_converged = false;
    std::vector<std::size_t> rejected_startup_iterations;
    std::vector<std::string> rejected_startup_reasons;
    std::size_t startup_total_iterations = 0;
    std::optional<ModelHResult3D> model_h; // scalar history; no retained cell/face arrays
    std::optional<EnthalpyResult> true_h;
};

struct Full3DResult {
    Full3DStop stop = Full3DStop::iteration_limit;
    bool converged = false, simple_ok = false, thermal_ok = false;
    bool outer_ok = false, finite_fields = false, envelope_ok = false;
    bool post_after_last_thermal = false;
    std::array<Full3DFlowState,2> flow;
    Full3DThermalEvidence thermal;
    std::vector<Full3DOuterRecord> outer;
    std::vector<std::string> simple_failures, warnings,envelope_reasons;
    std::array<std::vector<double>,2> final_conductivity,final_rho_cp;
    std::array<double,2> inlet_cp{};
    std::array<NuObservation,2> nu_observations;
    std::vector<RangeObservation> range_observations;
    std::array<double,2> pressure_drop{},outlet_temperature{},inlet_mass{},duty{};
    std::array<double,2> maximum_mach{},minimum_pressure{};
    std::array<double,2> solid_exchange{},interior_exchange{},physical_mass_in{},physical_mass_out{},mass_imbalance{};
    double energy_imbalance=0.,interior_duty=0.,interior_imbalance=0.;
    double enthalpy_imbalance=std::numeric_limits<double>::quiet_NaN();
    std::array<std::optional<OuterAndersonStats>,2> anderson;
};

// Numerical execution from prepared physical fields. Owns initial SIMPLE,
// local closure/property refresh, the thermal-first outer loop, pressure
// shooting/anchoring, native thermal evidence and final convergence gates.
// It calls existing numerical drivers directly; there is no Python callback
// for a numerical phase. Cancellation is cooperative and never certifies a
// partial result. Exceptions invalidate partial output. Independent calls own
// separate flow solvers, property evaluators and MAC hierarchies.
Full3DResult solve_full_3d(const Full3DInput& input, const Full3DControl& control);

}  // namespace tpmshx
