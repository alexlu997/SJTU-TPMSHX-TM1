#pragma once

#include "tpmshx/anderson_state.hpp"
#include "tpmshx/enthalpy_eos.hpp"
#include "tpmshx/enthalpy_sweeps.hpp"
#include "tpmshx/conservative_energy.hpp"

#include <array>
#include <memory>
#include <optional>

namespace tpmshx {

enum class EnthalpyAlgorithm { temperature_sou = 2 };

struct EnthalpySideView {
    Fluid fluid;
    double inlet_temperature, inlet_pressure;
    ArrayView<const double> pressure, epsilon, hv;
    ArrayView<const double> mass_x, mass_y, mass_z;
    // -1 assigns the scalar inlet state to every exterior inflow.
    // Values 0:+x, 1:-x, 2:+y, 3:-y, 4:+z, 5:-z restrict T inflow
    // to that face.
    int inlet_direction = -1;
    EnergyRelation energy = EnergyRelation::eos_h_TP;
    ConductivitySource conductivity_source = ConductivitySource::local_eos;
    ArrayView<const double> effective_conductivity{};
};

struct EnthalpyStateView {
    ArrayView<double> h_a, h_b, a, b, solid;
    // Supplied temperature fields are optional independently, as in Python.
    bool warm_a = false, warm_b = false, warm_solid = false;
};

struct EnthalpyControl {
    std::size_t max_iterations, sweeps;
    double omega, update_tolerance;
    std::optional<double> coupled_energy_tolerance, equation_energy_tolerance;
    bool (*cancel)(void*) = nullptr;
    void* context = nullptr;
    EnthalpyAlgorithm algorithm = EnthalpyAlgorithm::temperature_sou;
    // K, maximum actual A/B/solid update. Full T runs require both energy
    // tolerances; direct components can omit either stop gate.
    // update_tolerance keeps its normalized enthalpy-update meaning.
    double temperature_update_tolerance = 1e-8;
    // Opt-in additional dimensionless h-update gate on T algorithms. This
    // does not replace the K update gate.
    bool require_enthalpy_update_on_temperature = false;
    // Full runs use a scale that does not depend on either enthalpy origin.
    bool reference_independent_update = false;
    std::size_t cpu_threads = 1;
    // Direct C calls retain strict h and relative boundary energy gates.
    bool require_legacy_direct_gates = false;
};

inline EnthalpyControl full_enthalpy_control(std::size_t dimension,
    EnthalpyAlgorithm algorithm = EnthalpyAlgorithm::temperature_sou, bool has_water = false) {
    EnthalpyControl control{dimension == 2 ? (has_water ? 12000u : 5000u) : 1500u,
        5u, .2, 1e-3, .001, .001};
    control.algorithm = algorithm;
    control.cpu_threads = dimension == 2 ? 2u : 1u;
    return control;
}

enum class EnthalpyStop { converged, enthalpy_limited, iteration_limit, cancelled };

struct EnthalpyResult {
    EnthalpyStop stop;
    std::size_t iterations;
    double residual, q_a, q_b, energy_imbalance;
    std::array<double,2> inlet_enthalpy;
    std::array<double,2> enthalpy_update_scale;
    bool reference_independent_update = false;
    ClipCounts last_clips, total_clips;
    // Completed ordinary SOU blocks retain the full unrelaxed audit.
    // The direct C view publishes only the requested audit components.
    std::optional<EnergyAudit> final_audit;
    std::array<bool,2> used_bicubic;
    bool heos_polish;
    EnthalpyAlgorithm algorithm = EnthalpyAlgorithm::temperature_sou;
    std::optional<double> temperature_update;  // K; absent before the first update
    double picard_relaxation = 1.;  // Actual whole-block T increment multiplier
};

enum class EnthalpyPhase { active, completed, cancelled, failed };

struct EnthalpySideState {
    // cp, epsilon*k/cp and epsilon*k.
    std::array<std::vector<double>,3> transport;
};

struct EnthalpyRunState {
    // h_a, h_b, T_a, T_b and T_solid.
    std::array<std::vector<double>,5> fields;
    std::array<EnthalpySideState,2> sides;
    EnthalpyResult result;
    AndersonState acceleration;
};

// Caller arrays remain live. The caller must not change them between calls.
// Restore requires the same input and controls. Snapshots own their arrays.
class EnthalpyRun {
public:
    EnthalpyRun(const GridView&,const EnthalpySideView&,const EnthalpySideView&,
                ArrayView<const double> k_ss,EnthalpyStateView,const EnthalpyControl&,
                PhysicalHeatLedger* physical_audit=nullptr);
    EnthalpyRun(const GridView&,const EnthalpySideView&,const EnthalpySideView&,
                ArrayView<const double> k_ss,EnthalpyStateView,const EnthalpyControl&,
                const EnthalpyRunState&,PhysicalHeatLedger* physical_audit=nullptr);
    ~EnthalpyRun();
    EnthalpyRun(const EnthalpyRun&)=delete;
    EnthalpyRun& operator=(const EnthalpyRun&)=delete;
    // Complete one original Picard iteration, including any SOU proposal.
    EnthalpyPhase advance();
    EnthalpyPhase phase() const;
    EnthalpyRunState snapshot() const;
    EnthalpyResult take_result();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// Shared conservative energy driver for 3D or a unit-depth 2D grid.
// Each side selects its energy relation and conductivity source. Direct calls
// use HEOS unless the caller supplies an integral air or water model.
// The caller supplies mass faces, local pressures and heat exchange terms.
// This driver does not update flow or refresh the heat exchange correlation.
// Actual states retain each fluid's physical guards. Final equation audits
// use the selected relation. SOU uses actual PT states without tables.
// A selected inlet direction rejects inflow on other exterior faces.
// Direction -1 supplies the scalar inlet state at every exterior inflow.
// SOU reconstructs enthalpy at faces and uses a damped Picard update. An
// accepted Anderson proposal still needs an ordinary block to confirm exit.
// The optional ledger receives a completed full equation audit. Cancellation
// does not produce a completed result. Caller arrays must remain live and
// must not alias. An exception can leave these output arrays partly changed.
EnthalpyResult solve_enthalpy(const GridView& grid, const EnthalpySideView& a,
                             const EnthalpySideView& b, ArrayView<const double> k_ss,
                             EnthalpyStateView state, const EnthalpyControl& control,
                             PhysicalHeatLedger* physical_audit = nullptr);

}  // namespace tpmshx
