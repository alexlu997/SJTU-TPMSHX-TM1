#pragma once

#include "tpmshx/model_h_2d.hpp"

namespace tpmshx {

struct ModelHFluid3D {
    Fluid fluid;
    ArrayView<const double> conductivity, hv, mass_x, mass_y, mass_z;
    TemperatureBoundary boundary;  // no capacity_flux: use raw signed mass
    ArrayView<const double> source{};  // optional manufactured source, W/m3
};

struct ModelHBoundaryAudit3D {
    double mass_out, enthalpy_out, unknown_mass_in, inlet_reverse_mass_out;
    std::size_t unknown_inflow_count;
    std::vector<double> enthalpy_faces;
};

struct ModelHSideAudit3D {
    std::array<ModelHBoundaryAudit3D,6> boundaries;  // x-,x+,y-,y+,z-,z+
    std::array<double,5> cp_coefficients;
    double temperature_min, temperature_max, mass_net;
    double advective_in, diffusion_in, numerical_external_in, exchange, source;
    double residual_sum, residual_max, normalization, global_ratio, cell_ratio;
    bool boundary_complete;
    std::vector<double> residual, inlet_diffusion;
};

struct ModelHAudit3D {
    std::array<ModelHSideAudit3D,2> sides;
    std::vector<double> solid_residual;
    double volume, numerical_external_in, explicit_source;
    double solid_sum, solid_max, full_residual_sum, telescoping_error, ltne_source_ratio;
    bool boundary_complete;
    // Exactly compute_phase2a's existing gates: A global/cell, B global/cell,
    // LTNE exchange balance, complete physical inflow data. No new solid gate.
    std::array<bool,6> gates;
    bool passed;
};

struct ModelHControl3D {
    std::size_t max_iterations, chunk_iterations;
    double q_relative_tolerance, alpha_a, alpha_solid, alpha_b;
    bool warm_start=false, accelerate=false, red_black=false;
    bool (*cancel)(void*)=nullptr;
    void (*progress)(void*,std::size_t,std::size_t)=nullptr;
    void* context=nullptr;
    bool second_order_a=true, second_order_b=true;
    bool strict_energy_balance=false;
};

struct ModelHFinishingCheck3D {
    std::size_t iterations;
    std::array<bool,6> gates;
    bool physical_passed=false;
    double energy_error_ratio=std::numeric_limits<double>::quiet_NaN();
};

struct ModelHResult3D {
    TemperatureStop stop;
    std::size_t iterations;
    double residual, q_b;
    bool audit_available, has_sources;
    ModelHAudit3D audit;
    std::vector<ModelHFinishingCheck3D> finishing_checks;
    bool physical_audit_available=false;
    double energy_error_ratio=std::numeric_limits<double>::quiet_NaN();
};

// Complete fixed-flow symmetric AA/AW/WA model-h thermal driver, nz>1.
// The caller supplies real-axis completed SIMPLE raw mass faces; this call
// performs no MAC projection, mass correction, EOS or outer property refresh.
// Both fluids use minmod SOU, original capped fluid relaxation, serial or
// two-color GS and optional existing Anderson acceleration. Explicit sources
// retain their original field/Q stopping policy, with a final audit returned
// separately; a manufactured-source solve is not a source-free certificate.
// Borrowed inputs remain immutable through callbacks. State must not alias.
// Exceptions invalidate partial state; cancelled returns have no final audit.
// FullCC strict mode and prescribed B follow the 2D control/ledger contract.
// Strict fullCC additionally supports its existing water-water consumer;
// the original non-strict model-h entry still rejects water-water.
// A prescribed B is never part of the iteration/Anderson vector or equation
// certificate; its exchange with the solid is external reservoir power.
ModelHResult3D solve_model_h_3d(const GridView& grid, const ModelHFluid3D& a,
                              const ModelHFluid3D& b, ArrayView<const double> k_ss,
                              ArrayView<const double> solid_source,
                              TemperatureStateView state, const ModelHControl3D& control,
                              ArrayView<const double> prescribed_b = {},
                              PhysicalHeatLedger* physical_audit = nullptr);

}  // namespace tpmshx
