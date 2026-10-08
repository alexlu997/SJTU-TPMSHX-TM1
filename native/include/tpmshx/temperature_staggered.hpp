#pragma once

#include "tpmshx/temperature_driver.hpp"
#include <array>
#include <memory>
#include <vector>

namespace tpmshx {

struct StaggeredTemperatureFluid {
    ArrayView<const double> conductivity, hv, epsilon, rho_cp;
    // Real-coordinate velocities on x/y/z faces, in C order. Shape has one
    // extra entry along its face normal. The caller's faces are never changed.
    std::array<ArrayView<const double>,3> velocity;
    TemperatureBoundary boundary;
    ArrayView<const double> source{};  // optional MMS source, W/m^3
};

struct MacProjectionInfo {
    bool skipped = false, used_bordered_lu = false;
    std::size_t cg_iterations = 0;
    double rhs_mean = 0, residual_relative = 0;
};
struct MacProjectionResult {
    std::array<std::vector<double>,3> velocity;
    std::vector<double> potential;
    MacProjectionInfo info;
};
struct StaggeredFluidResidual {
    bool available = false;
    std::vector<double> cells;  // original conservative equation, W/cell
    double sum = 0, maximum = 0, exchange = 0;
    double global_ratio = 0, cell_ratio = 0;
};
struct StaggeredTemperatureResult {
    TemperatureResult iteration;
    std::array<MacProjectionInfo,2> projection;
    std::array<StaggeredFluidResidual,2> residual;
};

// Original mean-zero Neumann fallback [[L,1],[1^T,0]] [phi,mu]=[D,0].
// L is the unweighted connectivity Laplacian. No cell is pinned. This is
// also callable independently to verify the projection's fallback operator.
std::vector<double> solve_mac_neumann_bordered(
    const GridView& grid, ArrayView<const double> divergence);

// Fixed-coefficient, nz>1 original staggered temperature driver. conservative
// runs the capacity-weighted MAC projection before replacing explicit inlet
// capacity faces. The projection intentionally interpolates epsilon*rhoCp,
// whereas thermal transport interpolates epsilon and rhoCp separately.
// Conservative internal SOU freezes face offsets for five-sweep blocks with
// fluid relaxation capped at .2 and block damping .6. Structurally FOU keeps
// the original single-sweep schedule. Nonconservative serial reconstruction
// reads live temperatures; its RB path freezes start-of-sweep fields.
// Q/field stability is required. For complete conservative boundaries a fresh
// solved-phase L1 and global energy error must also be <=1e-7 relative to
// max(abs(Qa),abs(Qb),1). Incomplete boundaries retain diagnostic Q/field stopping.
// Prescribed B is fixed, contributes reservoir power and has no B certificate.
// Original non-model-h acceleration is unsupported. No EOS or model-h path.
// One instance retains the last grid's AMG hierarchy and is not concurrently
// callable; independent instances have independent mutable solver storage.
class StaggeredTemperatureDriver {
public:
    StaggeredTemperatureDriver();
    ~StaggeredTemperatureDriver();
    StaggeredTemperatureDriver(const StaggeredTemperatureDriver&) = delete;
    StaggeredTemperatureDriver& operator=(const StaggeredTemperatureDriver&) = delete;
    // The independent projection also accepts nz=1 extrusions. Substituting
    // rho for rho_cp gives the original true-h mass-face MAC operation.
    MacProjectionResult project_capacity_faces(
        const GridView& grid, ArrayView<const double> epsilon,
        ArrayView<const double> rho_cp,
        const std::array<ArrayView<const double>,3>& velocity);
    StaggeredTemperatureResult solve(
        const GridView& grid, const StaggeredTemperatureFluid& a,
        const StaggeredTemperatureFluid& b, ArrayView<const double> k_ss,
        TemperatureStateView state, const TemperatureControl& control,
        bool conservative, bool red_black,
        ArrayView<const double> prescribed_b = {},
        ArrayView<const double> source_solid = {});
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tpmshx
