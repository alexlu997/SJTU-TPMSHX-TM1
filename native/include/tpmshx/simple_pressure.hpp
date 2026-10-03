#pragma once

#include "tpmshx/enthalpy_sweeps.hpp"
#include "tpmshx/pressure_candidate.hpp"

namespace tpmshx {

// Solver coordinates: flow is +y. C-order staggered shapes are
// u(nx+1,ny,nz), v(nx,ny+1,nz), w(nx,ny,nz+1).
// For dimension=2, nz=1 and dz={1 m}; w has size zero. Mass is per unit depth.
template <typename T> struct SimpleFacesView {
    ArrayView<T> u, v, w;
};

struct SimpleBoundaryView {
    // Each inlet/outlet array is (nx,nz), flattened C order.
    // 2D inlet_velocity is multiplied by inlet_fraction; 3D inlet_velocity
    // is already geometrically face-averaged and inlet_fraction is empty.
    ArrayView<const double> inlet_velocity, inlet_fraction;
    ArrayView<const unsigned char> outlet_open;  // exact support: fraction > 0
};

// One canonical CSR pattern per fixed shape and outlet support. The current
// rho_eps, velocities and d coefficients are assembled each call. Degenerate
// aP<1e-30 rows become unit rows but keep the original outlet-only cell_kind.
// This class only assembles. The caller owns its existing PressureCandidate.
class SimplePressureAssembly {
public:
    SimplePressureAssembly(int dimension, const GridView& grid,
                           ArrayView<const unsigned char> outlet_open);
    const PressureSystem& assemble(const GridView& grid,
                                   SimpleFacesView<const double> velocity,
                                   SimpleFacesView<const double> d,
                                   ArrayView<const double> rho_eps);
    const PressureSystem& system() const { return system_; }
    const std::vector<unsigned char>& cell_kind() const { return system_.pin_mask; }
private:
    int dimension_;
    std::size_t nx_, ny_, nz_;
    PressureSystem system_;
};

// These functions preserve the current dimensional algebra and ordering.
// Arrays are borrowed; mutable arrays must not overlap each other or inputs.
// Invalid inputs throw before mutation. Nonfinite arithmetic throws domain_error
// and invalidates the possibly partially updated outputs. No clipping or
// acceptance gate occurs here. rho and eps must be from the intended SAME step.
void close_simple_outlet(int dimension, const GridView& grid,
                         ArrayView<const unsigned char> outlet_open,
                         SimpleFacesView<double> velocity,
                         ArrayView<const double> rho, ArrayView<const double> eps);

// Inlet assignment plus local outlet closure; does not reset side-wall u/w.
// 2D exit closeout calls close_simple_outlet only; 3D uses this function.
void apply_simple_y_boundary(int dimension, const GridView& grid,
                             const SimpleBoundaryView& boundary,
                             SimpleFacesView<double> velocity,
                             ArrayView<const double> rho, ArrayView<const double> eps);

// Correct pressure and all interior face velocities, reset side-wall u/w,
// then apply the current y boundaries. P and Pp are gauge pressure in Pa.
void correct_simple_pressure(int dimension, const GridView& grid,
                             const SimpleBoundaryView& boundary,
                             ArrayView<double> pressure, ArrayView<const double> correction,
                             SimpleFacesView<double> velocity,
                             SimpleFacesView<const double> d,
                             ArrayView<const double> rho, ArrayView<const double> eps,
                             double alpha_p);

struct SimpleMassAudit {
    double local_residual, mass_in, mass_out, global_residual, backflow_fraction;
    std::size_t counted_cells;
};

// excluded_cells is caller-selected 0/1 per cell. During SIMPLE it is the
// outlet-only cell_kind; final 3D certification passes an all-zero selection.
SimpleMassAudit simple_mass_audit(int dimension, const GridView& grid,
                                 SimpleFacesView<const double> velocity,
                                 ArrayView<const double> rho_eps,
                                 ArrayView<const unsigned char> excluded_cells);

struct SimpleLegacyMass { double residual, reference; };

// 2D: plane defect / absolute inlet flow (reference=1).
// 3D: max absolute cell imbalance / inlet absolute flow; reference=1 if <=1e-12.
// Caller supplies the OLD rho_eps; this diagnostic still schedules 3D AMG.
SimpleLegacyMass simple_legacy_mass_residual(int dimension, const GridView& grid,
                                            SimpleFacesView<const double> velocity,
                                            ArrayView<const double> rho_eps);

// Raw solver-axis face mass flow, arithmetic face rho_eps and physical area.
// No physical-axis mapping, thermal projection, balancing or averaging of L/t.
void simple_face_mass_flux(int dimension, const GridView& grid,
                           SimpleFacesView<const double> velocity,
                           ArrayView<const double> rho_eps,
                           SimpleFacesView<double> mass);

}  // namespace tpmshx
