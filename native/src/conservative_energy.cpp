#include "tpmshx/conservative_energy.hpp"
#include "energy_fv_rows.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

namespace tpmshx {
namespace {

std::size_t product(std::size_t a, std::size_t b) {
    if (!a || !b || a > std::numeric_limits<std::size_t>::max() / b)
        throw std::invalid_argument("invalid grid extent");
    return a * b;
}

template <typename T>
void check_array(ArrayView<T> a, std::size_t size) {
    if (!a.data || a.size != size)
        throw std::invalid_argument("array length does not match grid");
    for (std::size_t i = 0; i < size; ++i)
        if (!std::isfinite(a[i]))
            throw std::invalid_argument("nonfinite array value");
}

void check_coefficient(ArrayView<const double> a, std::size_t size, bool positive) {
    check_array(a, size);
    for (std::size_t i = 0; i < size; ++i)
        if (positive ? a[i] <= 0.0 : a[i] < 0.0)
            throw std::invalid_argument("invalid physical coefficient");
}

std::size_t check_grid(const GridView& g) {
    if (g.nx == std::numeric_limits<std::size_t>::max() ||
        g.ny == std::numeric_limits<std::size_t>::max() ||
        g.nz == std::numeric_limits<std::size_t>::max())
        throw std::invalid_argument("invalid grid extent");
    const auto cells = product(product(g.nx, g.ny), g.nz);
    check_coefficient(g.dx, g.nx, true);
    check_coefficient(g.dy, g.ny, true);
    check_coefficient(g.dz, g.nz, true);
    return cells;
}

void check_faces(const std::array<ArrayView<const double>, 3>& mass,
                const GridView& g) {
    check_array(mass[0], product(product(g.nx + 1, g.ny), g.nz));
    check_array(mass[1], product(product(g.nx, g.ny + 1), g.nz));
    check_array(mass[2], product(product(g.nx, g.ny), g.nz + 1));
}

void check_fluid(const FluidView& f, const GridView& g, std::size_t cells) {
    check_coefficient(f.dh, cells, false);
    check_coefficient(f.cp, cells, true);
    check_coefficient(f.hv, cells, false);
    check_array(f.t_star, cells);
    check_array(f.h_star, cells);
    check_faces({f.mass_x, f.mass_y, f.mass_z}, g);
    if (!std::isfinite(f.h_in))
        throw std::invalid_argument("nonfinite inlet enthalpy");
}

void update_temperature(double diagonal, double rhs, double omega, double& t) {
    if (!std::isfinite(diagonal) || !std::isfinite(rhs))
        throw std::domain_error("nonfinite conservative temperature row");
    if (diagonal > 1e-30) {
        const double next = (1. - omega) * t + omega * rhs / diagonal;
        if (!std::isfinite(next))
            throw std::domain_error("nonfinite conservative temperature update");
        t = next;
    }
}

template<class Phase>
void fluid_sweep(const GridView& g,const Phase& f,ArrayView<double> t,
                 ArrayView<double> ts,double omega,ArrayView<const double> numerical,
                 bool reverse) {
    const detail::EnergyMesh mesh(g);
    for(std::size_t ordinal=0;ordinal<mesh.cells();++ordinal) {
        const auto p=reverse ? mesh.cells()-1-ordinal : ordinal;
        const auto row=detail::fluid_energy_row(mesh,f,{t.data,t.size},{ts.data,ts.size},p,
            detail::optional(numerical,p));
        update_temperature(row.diagonal,row.rhs,omega,t[p]);
    }
}

template<class Phase>
void solid_sweep(const GridView& g,const Phase& a,const Phase& b,
                 ArrayView<const double> ks,TemperatureStateView state,
                 double omega,bool reverse,ArrayView<const double> source={}) {
    const detail::EnergyMesh mesh(g);
    for(std::size_t ordinal=0;ordinal<mesh.cells();++ordinal) {
        const auto p=reverse ? mesh.cells()-1-ordinal : ordinal;
        const auto row=detail::solid_energy_row(mesh,ks,detail::exchange(a),detail::exchange(b),
            {state.a.data,state.a.size},{state.b.data,state.b.size},
            {state.solid.data,state.solid.size},source,p);
        update_temperature(row.diagonal,row.rhs,omega,state.solid[p]);
    }
}

double slope(double difference, double distance) {
    const double value = difference / distance;
    if (!std::isfinite(distance) || !std::isfinite(value))
        throw std::domain_error("nonfinite enthalpy reconstruction slope");
    return value;
}

double minmod(double a, double b) {
    if ((a > 0. && b > 0.) || (a < 0. && b < 0.))
        return std::copysign(std::min(std::abs(a), std::abs(b)), a);
    return 0.;
}

std::array<std::vector<double>, 3> enthalpy_gradients(
    const GridView& g, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in) {
    const auto cells = g.nx * g.ny * g.nz;
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1}, extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    std::array<std::vector<double>, 3> gradient{
        std::vector<double>(cells), std::vector<double>(cells), std::vector<double>(cells)};
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                const std::size_t coord[]{i, j, k};
                const std::size_t face[]{p, (i * (g.ny + 1) + j) * g.nz + k,
                    (i * g.ny + j) * (g.nz + 1) + k};
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    if (extent[axis] == 1) continue;
                    const auto c = coord[axis];
                    const double d = width[axis][c];
                    bool have_left = false, have_right = false;
                    double left = 0., right = 0.;
                    if (c > 0) {
                        left = slope(h[p] - h[p - stride[axis]], .5 * (d + width[axis][c - 1]));
                        have_left = true;
                    } else if (mass[axis][face[axis]] > 0.) {
                        left = slope(h[p] - h_in, .5 * d);
                        have_left = true;
                    }
                    if (c + 1 < extent[axis]) {
                        right = slope(h[p + stride[axis]] - h[p], .5 * (d + width[axis][c + 1]));
                        have_right = true;
                    } else if (mass[axis][face[axis] + stride[axis]] < 0.) {
                        right = slope(h_in - h[p], .5 * d);
                        have_right = true;
                    }
                    gradient[axis][p] = have_left && have_right ? minmod(left, right)
                        : (have_left ? left : have_right ? right : 0.);
                }
            }
    return gradient;
}

}  // namespace

void conservative_temperature_sweeps(
    const GridView& g, const FluidView& a, const FluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    std::size_t sweeps, double omega, ArrayView<const double> source_a,
    ArrayView<const double> source_b, double solid_omega) {
    const auto cells = check_grid(g);
    check_fluid(a, g, cells);
    check_fluid(b, g, cells);
    check_coefficient(k_ss, cells, false);
    for (const auto t : {state.a, state.b, state.solid}) check_array(t, cells);
    for (const auto source : {source_a, source_b})
        if (source.size) check_array(source, cells);
    for (const double relaxation : {omega, solid_omega})
        if (!std::isfinite(relaxation) || relaxation <= 0. || relaxation > 1.)
            throw std::invalid_argument("fluid and solid omega must be in (0, 1]");
    // Legacy source parameters retain W/cell numerical RHS semantics.
    // Direction -1 is private to this legacy all-inward-h_in adapter.
    const FrozenEnergyPhase pa{a,{-1,0.}}, pb{b,{-1,0.}};
    for (std::size_t sweep = 0; sweep < sweeps; ++sweep) {
        const bool reverse = sweep % 2 != 0;
        fluid_sweep(g, pa, state.a, state.solid, omega, source_a, reverse);
        fluid_sweep(g, pb, state.b, state.solid, omega, source_b, reverse);
        solid_sweep(g, pa, pb, k_ss, state, solid_omega, reverse);
    }
}

double enthalpy_sou_correction(
    const GridView& g, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in,
    ArrayView<double> correction) {
    const auto cells = check_grid(g);
    check_array(h, cells);
    check_faces(mass, g);
    if (!std::isfinite(h_in)) throw std::invalid_argument("nonfinite inlet enthalpy");
    if (!correction.data || correction.size != cells)
        throw std::invalid_argument("correction array length does not match grid");
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1}, extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    const auto gradient = enthalpy_gradients(g, h, mass, h_in);
    std::fill_n(correction.data, cells, 0.);
    double boundary = 0.;
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                const std::size_t coord[]{i, j, k};
                const std::size_t face[]{p, (i * (g.ny + 1) + j) * g.nz + k,
                    (i * g.ny + j) * (g.nz + 1) + k};
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    const auto c = coord[axis];
                    if (c + 1 < extent[axis]) {
                        const auto q = p + stride[axis];
                        const double m = mass[axis][face[axis] + stride[axis]];
                        const double flux = m * (m >= 0.
                            ? gradient[axis][p] * .5 * width[axis][c]
                            : -gradient[axis][q] * .5 * width[axis][c + 1]);
                        correction[p] -= flux;
                        correction[q] += flux;
                    }
                    if (c == 0 && mass[axis][face[axis]] < 0.) {
                        const double change = mass[axis][face[axis]]
                            * (-.5 * width[axis][c] * gradient[axis][p]);
                        correction[p] += change;
                        boundary += change;
                    }
                    if (c + 1 == extent[axis] && mass[axis][face[axis] + stride[axis]] > 0.) {
                        const double change = -mass[axis][face[axis] + stride[axis]]
                            * (.5 * width[axis][c] * gradient[axis][p]);
                        correction[p] += change;
                        boundary += change;
                    }
                }
            }
    if (!std::isfinite(boundary))
        throw std::domain_error("nonfinite SOU boundary correction");
    for (std::size_t p = 0; p < cells; ++p)
        if (!std::isfinite(correction[p]))
            throw std::domain_error("nonfinite SOU cell correction");
    return boundary;
}

std::array<std::vector<double>, 6> enthalpy_boundary_power(
    const GridView& g, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in,
    bool second_order) {
    const auto cells = check_grid(g);
    check_array(h, cells);
    check_faces(mass, g);
    if (!std::isfinite(h_in)) throw std::invalid_argument("nonfinite inlet enthalpy");
    std::array<std::vector<double>, 3> gradient;
    if (second_order) gradient = enthalpy_gradients(g, h, mass, h_in);
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1}, extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    std::array<std::vector<double>, 6> result;
    for (std::size_t axis = 0; axis < 3; ++axis)
        for (const int sign : {-1, 1}) {
            auto& plane = result[2 * axis + (sign > 0)];
            plane.reserve(cells / extent[axis]);
            for (std::size_t i = 0; i < g.nx; ++i)
                for (std::size_t j = 0; j < g.ny; ++j)
                    for (std::size_t k = 0; k < g.nz; ++k) {
                        const std::size_t coord[]{i, j, k};
                        const auto c = coord[axis];
                        if (c != (sign > 0 ? extent[axis] - 1 : 0)) continue;
                        const auto p = (i * g.ny + j) * g.nz + k;
                        const std::size_t face[]{p, (i * (g.ny + 1) + j) * g.nz + k,
                            (i * g.ny + j) * (g.nz + 1) + k};
                        const double outward = sign * mass[axis][face[axis]
                            + (sign > 0 ? stride[axis] : 0)];
                        double face_h = h_in;
                        if (outward > 0.) {
                            face_h = h[p];
                            if (second_order) face_h += sign * .5 * width[axis][c] * gradient[axis][p];
                        }
                        const double power = outward == 0. ? 0. : outward * face_h;
                        if (!std::isfinite(power)) throw std::domain_error("nonfinite boundary enthalpy power");
                        plane.push_back(power);
                    }
        }
    return result;
}

EnergyAudit thermal_energy_audit_sou(
    const GridView& g, const FluidEnergyView& a, const FluidEnergyView& b,
    ArrayView<const double> ts, ArrayView<const double> k_ss,
    ArrayView<double> ra, ArrayView<double> rb, ArrayView<double> rs) {
    auto result = thermal_energy_audit(g, a, b, ts, k_ss, ra, rb, rs);
    const auto cells = ra.size;
    std::vector<double> correction(cells);
    const FluidEnergyView fluids[]{a, b};
    const ArrayView<double> residuals[]{ra, rb};
    double* duties[]{&result.q_a, &result.q_b};
    for (std::size_t side = 0; side < 2; ++side) {
        const auto& f = fluids[side];
        *duties[side] += enthalpy_sou_correction(g, f.h,
            {f.mass_x, f.mass_y, f.mass_z}, f.h_in, {correction.data(), cells});
        result.fluid_abs_sum[side] = result.fluid_cell_max[side] = 0.;
        for (std::size_t p = 0; p < cells; ++p) {
            residuals[side][p] += correction[p];
            if (!std::isfinite(residuals[side][p]))
                throw std::domain_error("nonfinite SOU energy residual");
            result.fluid_abs_sum[side] += std::abs(residuals[side][p]);
            result.fluid_cell_max[side] = std::max(result.fluid_cell_max[side],
                std::abs(residuals[side][p]));
        }
    }
    result.net = result.q_a + result.q_b;
    result.denominator = std::max({std::abs(result.q_a), std::abs(result.q_b), 1.});
    result.coupled_ratio = std::max(std::abs(result.net), result.solid_abs_sum) / result.denominator;
    result.equation_ratio = std::max({std::abs(result.net), result.solid_abs_sum,
        result.fluid_abs_sum[0], result.fluid_abs_sum[1]}) / result.denominator;
    for (const double value : {result.q_a, result.q_b, result.net,
            result.denominator, result.coupled_ratio, result.equation_ratio,
            result.fluid_abs_sum[0], result.fluid_abs_sum[1]})
        if (!std::isfinite(value)) throw std::domain_error("nonfinite SOU energy budget");
    return result;
}

namespace {

void check_energy_fields(const EnergyPhase& f,const GridView& g,std::size_t n) {
    check_coefficient(f.K,n,false);check_coefficient(f.hv,n,false);
    check_faces(f.faces.capacity,g);
    for(std::size_t axis=0;axis<3;++axis)
        if(f.faces.offset[axis].size) check_array(f.faces.offset[axis],f.faces.capacity[axis].size);
}
void check_energy_fields(const FrozenEnergyPhase& f,const GridView& g,std::size_t n) {
    check_fluid(f.fluid,g,n);
}
void check_energy_fields(const PhysicalEnergyPhase& f,const GridView& g,std::size_t n) {
    check_coefficient(f.K,n,false);check_coefficient(f.hv,n,false);
    check_faces(f.signed_transport,g);check_faces(f.power,g);
}
void check_inlet_h(const EnergyPhase&,std::size_t) {}
void check_inlet_h(const PhysicalEnergyPhase&,std::size_t) {}
void check_inlet_h(const FrozenEnergyPhase& f,std::size_t n) {
    if(f.inlet_h.size) check_array(f.inlet_h,n);
}

template<class Phase>
bool check_energy_phase(const Phase& f,const GridView& g,std::size_t n,bool solved) {
    check_energy_fields(f,g,n);
    if(f.source_W_m3.size) check_array(f.source_W_m3,n);
    const auto& inlet=f.inlet;
    if(inlet.direction<0||inlet.direction>5||!std::isfinite(inlet.inlet_temperature))
        throw std::invalid_argument("invalid physical inlet identity");
    const detail::EnergyMesh mesh(g);
    const auto plane=n/mesh.count[inlet.direction/2];
    if(inlet.profile.size) check_array(inlet.profile,plane);
    if(inlet.opening.size) {
        check_array(inlet.opening,plane);
        for(std::size_t p=0;p<plane;++p)
            if(inlet.opening[p]<0.||inlet.opening[p]>1.)
                throw std::invalid_argument("inlet opening outside [0,1]");
    }
    if(inlet.capacity_flux.size)
        throw std::invalid_argument("prepare signed-axis energy faces before component call");
    check_inlet_h(f,plane);
    if(!solved) return true;
    bool complete=true;
    for(std::size_t p=0;p<n;++p) {
        const auto c=mesh.coord(p);
        for(std::size_t axis=0;axis<3;++axis) for(int sign:{-1,1}) {
            if(mesh.inside(c,axis,sign)) continue;
            if(sign*detail::transport(f,axis,mesh.face(axis,p,sign))>=0.) continue;
            if(!detail::known_inlet(mesh,inlet,c,axis,sign)) complete=false;
        }
    }
    return complete;
}

template<class Phase>
bool check_component(const GridView& g,const Phase& a,const Phase& b,
    ArrayView<const double> ks,TemperatureStateView state,
    ArrayView<const double> ss,ArrayView<const double> prescribed) {
    const auto n=check_grid(g);
    const bool ac=check_energy_phase(a,g,n,true),bc=check_energy_phase(b,g,n,!prescribed.size);
    check_coefficient(ks,n,false);
    for(const auto t:{state.a,state.b,state.solid}) check_array(t,n);
    if(ss.size) check_array(ss,n);
    if(prescribed.size) check_array(prescribed,n);
    return ac&&bc;
}

template<class Phase>
void component_sweeps(const GridView& g,const Phase& a,const Phase& b,
    ArrayView<const double> ks,TemperatureStateView state,std::size_t sweeps,double omega,
    ArrayView<const double> ss,ArrayView<const double> prescribed,
    ArrayView<const double> na,ArrayView<const double> nb,double solid_omega) {
    if(!check_component(g,a,b,ks,state,ss,prescribed))
        throw std::invalid_argument("inward face has no open physical inlet state");
    for(const auto n:{na,nb}) if(n.size) check_array(n,state.a.size);
    for(double r:{omega,solid_omega})
        if(!std::isfinite(r)||r<=0.||r>1.) throw std::invalid_argument("invalid energy relaxation");
    if(!sweeps) return;
    if(prescribed.size) std::copy_n(prescribed.data,prescribed.size,state.b.data);
    for(std::size_t sweep=0;sweep<sweeps;++sweep) {
        const bool reverse=sweep%2!=0;
        fluid_sweep(g,a,state.a,state.solid,omega,na,reverse);
        if(!prescribed.size) fluid_sweep(g,b,state.b,state.solid,omega,nb,reverse);
        solid_sweep(g,a,b,ks,state,solid_omega,reverse,ss);
    }
}

// Full and scalar audits share the same boundary power and arithmetic order.
template<bool Diffusive,class Phase>
double boundary_power(const detail::EnergyMesh& mesh,const Phase& f,
        ArrayView<const double> temperature,std::size_t p,std::size_t axis,int sign) {
    const auto c=mesh.coord(p);
    if constexpr(Diffusive) {
        if(detail::second_order_inlet(f)) {
            const auto inlet=detail::inlet_diffusion(mesh,f,p,axis,sign);
            double power=inlet.boundary>0. ? inlet.boundary*(temperature[p]
                -detail::inlet_temperature(f.inlet,mesh.patch(axis,c))):0.;
            if(inlet.neighbor>0.) power+=inlet.neighbor*(temperature[p]-temperature[inlet.neighbor_cell]);
            return power;
        }
        const double G=detail::inlet_conductance(mesh,f,p,axis,sign);
        return G>0. ? G*(temperature[p]-detail::inlet_temperature(f.inlet,mesh.patch(axis,c))):0.;
    } else {
        const auto face=detail::face_energy(f,mesh,p,axis,sign);
        const double outward=sign*face.C;
        double power=sign*face.B;
        if(outward!=0.) power+=outward*(outward>0.||!detail::known_inlet(mesh,f.inlet,c,axis,sign)
            ? temperature[p]:detail::inlet_temperature(f.inlet,mesh.patch(axis,c)));
        return power;
    }
}

// Keep phase reductions separate to match the complete ledger arithmetic.
struct ReducedAuditScalars {
    std::array<double,3> phase_l1{},source{};
    double outward=0.,sources=0.,reservoir=0.,error=0.;
    bool boundary_complete=true;
};

template<class Phase>
ReducedAuditScalars component_reduced_audit(const GridView& g,const Phase& a,const Phase& b,
    ArrayView<const double> ks,TemperatureStateView state,
    ArrayView<const double> ss,ArrayView<const double> prescribed) {
    ReducedAuditScalars result;
    result.boundary_complete=check_component(g,a,b,ks,state,ss,prescribed);
    if(prescribed.size)
        for(std::size_t p=0;p<prescribed.size;++p)
            if(state.b[p]!=prescribed[p]) throw std::invalid_argument("prescribed B is not applied");
    const detail::EnergyMesh mesh(g);
    const ArrayView<const double> t[]{ {state.a.data,state.a.size},
        {state.b.data,state.b.size},{state.solid.data,state.solid.size} };
    const Phase* phases[]{&a,&b};
    const std::array<bool,3> solved{true,!prescribed.size,true};
    std::array<bool,3> residual_finite{true,true,true},boundary_finite{true,true,true};
    for(std::size_t side=0;side<3;++side) {
        if(!solved[side]) {
            result.source[side]=std::numeric_limits<double>::quiet_NaN();
            continue;
        }
        for(std::size_t p=0;p<mesh.cells();++p) {
            const auto row=side<2 ? detail::fluid_energy_defect_row(mesh,*phases[side],t[side],t[2],p)
                :detail::solid_energy_defect_row(mesh,ks,detail::exchange(a),detail::exchange(b),t[0],t[1],t[2],ss,p);
            result.phase_l1[side]+=std::abs(row.rhs);
            residual_finite[side]=residual_finite[side]&&std::isfinite(row.rhs);
            result.source[side]+=detail::optional(side<2 ? phases[side]->source_W_m3:ss,p)*mesh.volume(mesh.coord(p));
        }
        result.error=std::max(result.error,result.phase_l1[side]);
        result.sources+=result.source[side];
        for(std::size_t face=0;face<6;++face) {
            const std::size_t axis=face/2;const int sign=face%2 ? 1:-1;
            for(int kind=0;kind<2;++kind) for(std::size_t patch=0;patch<mesh.line_count(axis);++patch) {
                const auto p=mesh.line_start(axis,patch)+(sign>0 ? (mesh.count[axis]-1)*mesh.stride[axis]:0);
                const double power=side==2 ? 0. : kind==0
                    ?boundary_power<false>(mesh,*phases[side],t[side],p,axis,sign)
                    :boundary_power<true>(mesh,*phases[side],t[side],p,axis,sign);
                result.outward+=power;
                boundary_finite[side]=boundary_finite[side]&&std::isfinite(power);
            }
        }
    }
    if(prescribed.size)
        for(std::size_t p=0;p<mesh.cells();++p)
            result.reservoir+=detail::exchange(b)[p]*mesh.volume(mesh.coord(p))*(t[1][p]-t[2][p]);
    for(std::size_t side=0;side<3;++side) if(solved[side]) {
        if(!std::isfinite(result.source[side])) throw std::domain_error("nonfinite physical source integral");
        if(!residual_finite[side]) throw std::domain_error("nonfinite physical residual");
        if(!boundary_finite[side]) throw std::domain_error("nonfinite physical boundary power");
    }
    if(!std::isfinite(result.reservoir)) throw std::domain_error("nonfinite prescribed reservoir power");
    result.error=std::max(result.error,std::abs(result.outward-result.sources-result.reservoir));
    return result;
}


template<class Phase>
PhysicalHeatLedger component_audit(const GridView& g,const Phase& a,const Phase& b,
    ArrayView<const double> ks,TemperatureStateView state,
    ArrayView<const double> ss,ArrayView<const double> prescribed) {
    const bool complete=check_component(g,a,b,ks,state,ss,prescribed);
    if(prescribed.size)
        for(std::size_t p=0;p<prescribed.size;++p)
            if(state.b[p]!=prescribed[p]) throw std::invalid_argument("prescribed B is not applied");
    const detail::EnergyMesh mesh(g);
    PhysicalHeatLedger result;result.solved[1]=!prescribed.size;result.boundary_complete=complete;
    const ArrayView<const double> t[]{ {state.a.data,state.a.size},
        {state.b.data,state.b.size},{state.solid.data,state.solid.size} };
    const Phase* phases[]{&a,&b};
    for(std::size_t side=0;side<3;++side) {
        if(!result.solved[side]) {
            result.source_integral[side]=std::numeric_limits<double>::quiet_NaN();
            continue;
        }
        result.residual[side].resize(mesh.cells());
        for(std::size_t face=0;face<6;++face) {
            result.advective_out[side][face].assign(mesh.cells()/mesh.count[face/2],0.);
            result.diffusive_out[side][face].assign(mesh.cells()/mesh.count[face/2],0.);
        }
        for(std::size_t p=0;p<mesh.cells();++p) {
            const auto c=mesh.coord(p);
            // Evaluate the physical difference directly: subtracting two
            // absolute C*T row totals loses low-order balance at large capacity.
            const auto row=side<2 ? detail::fluid_energy_defect_row(mesh,*phases[side],t[side],t[2],p)
                : detail::solid_energy_defect_row(mesh,ks,detail::exchange(a),detail::exchange(b),t[0],t[1],t[2],ss,p);
            result.residual[side][p]=row.rhs;
            result.source_integral[side]+=detail::optional(side<2 ? phases[side]->source_W_m3:ss,p)*mesh.volume(c);
            if(side==2) continue; // all exterior solid Fourier faces are adiabatic
            const auto& f=*phases[side];
            for(std::size_t axis=0;axis<3;++axis) for(int sign:{-1,1}) {
                if(mesh.inside(c,axis,sign)) continue;
                const auto slot=2*axis+(sign>0),patch=mesh.patch(axis,c);
                result.advective_out[side][slot][patch]=boundary_power<false>(mesh,f,t[side],p,axis,sign);
                result.diffusive_out[side][slot][patch]=boundary_power<true>(mesh,f,t[side],p,axis,sign);
            }
        }
    }
    if(prescribed.size)
        for(std::size_t p=0;p<mesh.cells();++p)
            result.prescribed_b_power+=detail::exchange(b)[p]*mesh.volume(mesh.coord(p))*(t[1][p]-t[2][p]);
    for(std::size_t side=0;side<3;++side) if(result.solved[side]) {
        if(!std::isfinite(result.source_integral[side])) throw std::domain_error("nonfinite physical source integral");
        for(double x:result.residual[side]) if(!std::isfinite(x)) throw std::domain_error("nonfinite physical residual");
        for(std::size_t face=0;face<6;++face)
            for(const auto* plane:{&result.advective_out[side][face],&result.diffusive_out[side][face]})
                for(double x:*plane) if(!std::isfinite(x)) throw std::domain_error("nonfinite physical boundary power");
    }
    if(!std::isfinite(result.prescribed_b_power)) throw std::domain_error("nonfinite prescribed reservoir power");
    return result;
}

} // namespace

double energy_balance_error(const PhysicalHeatLedger& ledger) {
    double error=0.,outward=0.,sources=0.;
    for(std::size_t phase=0;phase<3;++phase) if(ledger.solved[phase]) {
        double absolute=0.;
        for(double r:ledger.residual[phase]) absolute+=std::abs(r);
        error=std::max(error,absolute);
        sources+=ledger.source_integral[phase];
        for(std::size_t face=0;face<6;++face)
            for(const auto* powers:{&ledger.advective_out[phase][face],&ledger.diffusive_out[phase][face]})
                for(double power:*powers) outward+=power;
    }
    return std::max(error,std::abs(outward-sources-ledger.prescribed_b_power));
}

void energy_temperature_sweeps(const GridView& g,const EnergyPhase& a,const EnergyPhase& b,
    ArrayView<const double> ks,TemperatureStateView state,std::size_t sweeps,double omega,
    ArrayView<const double> ss,ArrayView<const double> prescribed,
    ArrayView<const double> na,ArrayView<const double> nb,double solid_omega) {
    component_sweeps(g,a,b,ks,state,sweeps,omega,ss,prescribed,na,nb,solid_omega);
}
PhysicalHeatLedger energy_physical_audit(const GridView& g,const EnergyPhase& a,const EnergyPhase& b,
    ArrayView<const double> ks,TemperatureStateView state,ArrayView<const double> ss,
    ArrayView<const double> prescribed) { return component_audit(g,a,b,ks,state,ss,prescribed); }

void energy_temperature_sweeps(const GridView& g,const FrozenEnergyPhase& a,const FrozenEnergyPhase& b,
    ArrayView<const double> ks,TemperatureStateView state,std::size_t sweeps,double omega,
    ArrayView<const double> ss,ArrayView<const double> prescribed,
    ArrayView<const double> na,ArrayView<const double> nb,double solid_omega) {
    component_sweeps(g,a,b,ks,state,sweeps,omega,ss,prescribed,na,nb,solid_omega);
}
PhysicalHeatLedger energy_physical_audit(const GridView& g,const FrozenEnergyPhase& a,const FrozenEnergyPhase& b,
    ArrayView<const double> ks,TemperatureStateView state,ArrayView<const double> ss,
    ArrayView<const double> prescribed) { return component_audit(g,a,b,ks,state,ss,prescribed); }

PhysicalHeatLedger energy_physical_audit(const GridView& g,const PhysicalEnergyPhase& a,const PhysicalEnergyPhase& b,
    ArrayView<const double> ks,TemperatureStateView state,ArrayView<const double> ss,
    ArrayView<const double> prescribed) { return component_audit(g,a,b,ks,state,ss,prescribed); }

}  // namespace tpmshx

namespace tpmshx {
EnergyBalanceAudit energy_balance_audit(const GridView& g,const EnergyPhase& a,const EnergyPhase& b,
    ArrayView<const double> ks,TemperatureStateView state,ArrayView<const double> ss,
    ArrayView<const double> prescribed) {
    const auto r=component_reduced_audit(g,a,b,ks,state,ss,prescribed);
    return {r.error,r.boundary_complete};
}
}
