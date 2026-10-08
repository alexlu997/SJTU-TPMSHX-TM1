#include "legacy_single_a_temperature.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace tpmshx {
namespace {

std::size_t product(std::size_t a, std::size_t b) {
    if (!a || !b || a > std::numeric_limits<std::size_t>::max() / b)
        throw std::invalid_argument("invalid temperature grid extent");
    return a * b;
}

template <typename T>
void check_array(ArrayView<T> x, std::size_t size, bool finite = true) {
    if (!x.data || x.size != size)
        throw std::invalid_argument("temperature array length does not match grid");
    if (finite)
        for (std::size_t i = 0; i < size; ++i)
            if (!std::isfinite(x[i])) throw std::invalid_argument("nonfinite temperature input");
}

void coefficient(ArrayView<const double> x, std::size_t n, bool positive = false) {
    check_array(x, n);
    for (std::size_t i = 0; i < n; ++i)
        if (positive ? x[i] <= 0.0 : x[i] < 0.0)
            throw std::invalid_argument("invalid temperature coefficient");
}

template <typename T, typename U>
void disjoint(ArrayView<T> a, ArrayView<U> b) {
    if (!a.size || !b.size) return;
    const auto ap = reinterpret_cast<std::uintptr_t>(a.data);
    const auto bp = reinterpret_cast<std::uintptr_t>(b.data);
    const auto maximum = std::numeric_limits<std::uintptr_t>::max();
    if (a.size > (maximum-ap)/sizeof(double) || b.size > (maximum-bp)/sizeof(double)
        || (ap < bp+b.size*sizeof(double) && bp < ap+a.size*sizeof(double)))
        throw std::invalid_argument("temperature input/output arrays overlap");
}

struct Mesh {
    const GridView& g;
    bool two_d;
    std::array<std::size_t, 3> count, stride;
    std::array<ArrayView<const double>, 3> width;
    std::size_t axes;
    Mesh(const GridView& grid, bool plane)
        : g(grid), two_d(plane), count{grid.nx, grid.ny, grid.nz},
          stride{grid.ny*grid.nz, grid.nz, 1}, width{grid.dx,grid.dy,grid.dz},
          axes(plane ? 2U : 3U) {}
    double volume(const std::array<std::size_t,3>& c) const {
        const double area = g.dx[c[0]] * g.dy[c[1]];
        return two_d ? area : area * g.dz[c[2]];
    }
    double face_area(std::size_t axis, const std::array<std::size_t,3>& c) const {
        if (two_d) return axis == 0 ? g.dy[c[1]] : g.dx[c[0]];
        if (axis == 0) return g.dy[c[1]] * g.dz[c[2]];
        if (axis == 1) return g.dx[c[0]] * g.dz[c[2]];
        return g.dx[c[0]] * g.dy[c[1]];
    }
    std::size_t patch(int direction, const std::array<std::size_t,3>& c) const {
        if (direction <= 1) return c[1]*g.nz+c[2];
        if (direction <= 3) return c[0]*g.nz+c[2];
        return c[0]*g.ny+c[1];
    }
};

double optional(ArrayView<const double> x, std::size_t p, double fallback) {
    return x.size ? x[p] : fallback;
}

double increment(double tm, double t, double tp, double dm, double dp, double offset) {
    const double left = (t-tm)/dm, right = (tp-t)/dp;
    if (left*right <= 0.0) return 0.0;
    return (left < 0.0 ? -std::min(std::abs(left),std::abs(right))
                       : std::min(std::abs(left),std::abs(right))) * offset;
}

double cell_capacity(const Mesh& mesh, const TemperatureFluidView& f,
                     std::size_t p, std::size_t axis,
                     const std::array<std::size_t,3>& c) {
    const auto velocity = axis == 0 ? f.u : (axis == 1 ? f.v : f.w);
    return (f.epsilon[p]*f.rho_cp[p]) * velocity[p] * mesh.face_area(axis,c);
}

double sou_axis(const Mesh& mesh, const TemperatureFluidView& f,
                ArrayView<const double> t, std::size_t p, std::size_t axis,
                const std::array<std::size_t,3>& c) {
    double correction = 0.0;
    const auto pos = c[axis], count = mesh.count[axis], stride = mesh.stride[axis];
    const auto width = mesh.width[axis];
    const double local = cell_capacity(mesh,f,p,axis,c);
    for (std::size_t side = 0; side < 2; ++side) {
        const auto face = pos+side;
        if (face == 0 || face == count) continue;
        const auto left = p-(side == 0 ? stride : 0);
        const auto right = left+stride;
        const double flow = mesh.two_d
            ? 0.5*(cell_capacity(mesh,f,left,axis,c)+cell_capacity(mesh,f,right,axis,c))
            : local;
        const auto upos = flow >= 0.0 ? face-1 : face;
        if (upos == 0 || upos+1 == count) continue;
        const auto up = flow >= 0.0 ? left : right;
        const double dm = 0.5*(width[upos-1]+width[upos]);
        const double dp = 0.5*(width[upos]+width[upos+1]);
        const double offset = 0.5*width[upos]*(flow >= 0.0 ? 1.0 : -1.0);
        correction += (side == 0 ? 1.0 : -1.0)*flow*
            increment(t[up-stride],t[up],t[up+stride],dm,dp,offset);
    }
    return correction;
}

void update(ArrayView<double> t, std::size_t p, double value, double alpha, double& change) {
    const double next = alpha == 1.0 ? value : t[p]+alpha*(value-t[p]);
    if (!std::isfinite(next)) throw std::domain_error("nonfinite temperature row update");
    change = std::max(change,std::abs(next-t[p]));
    t[p] = next;
}

void fluid_row(const Mesh& mesh, const TemperatureFluidView& f,
               ArrayView<double> t, ArrayView<double> solid, std::size_t p,
               const std::array<std::size_t,3>& c, bool sou, double alpha,
               double& change, ArrayView<const double> reconstruction = {}) {
    std::array<double,6> a{}, neighbor{};
    const auto direction = static_cast<std::size_t>(f.boundary.direction);
    for (std::size_t axis = 0; axis < mesh.axes; ++axis) {
        const auto pos = c[axis], count = mesh.count[axis], stride = mesh.stride[axis];
        const auto width = mesh.width[axis];
        const double area = mesh.face_area(axis,c);
        const double local = cell_capacity(mesh,f,p,axis,c);
        for (std::size_t side = 0; side < 2; ++side) {
            const auto face = 2*axis+side;
            const bool inside = side == 0 ? pos > 0 : pos+1 < count;
            const auto nb = inside ? (side == 0 ? p-stride : p+stride) : p;
            const auto npos = inside ? (side == 0 ? pos-1 : pos+1) : pos;
            const double diffusion = inside ? detail::diffusion_conductance(
                f.conductivity[p],f.conductivity[nb],0.5*width[pos],0.5*width[npos])*area : 0.0;
            const double flow = mesh.two_d
                ? (side == 0 ? 0.5*(cell_capacity(mesh,f,nb,axis,c)+local)
                             : 0.5*(local+cell_capacity(mesh,f,nb,axis,c))) : local;
            a[face] = diffusion + std::max(side == 0 ? flow : -flow,0.0);
            neighbor[face] = t[nb];
            if (!inside && face == direction) {
                const auto patch = mesh.patch(f.boundary.direction,c);
                const double frac = optional(f.boundary.opening,patch,1.0);
                const double incoming = optional(f.boundary.capacity_flux,patch,
                                                  side == 0 ? flow : -flow);
                if (mesh.two_d || frac > 0.0) {
                    // The 3D CC closed patch retains its old self-neighbour
                    // convection. In 2D the physical inlet coefficient is zero.
                    a[face] = 2.0*f.conductivity[p]*area*frac/width[pos]
                        + (frac > 0.0 ? std::max(incoming,0.0) : 0.0);
                    neighbor[face] = optional(f.boundary.profile,patch,
                                              f.boundary.inlet_temperature);
                }
            }
        }
    }
    const double hv = f.hv[p]*mesh.volume(c);
    double diagonal = a[1]+a[0]+a[3]+a[2];
    double rhs = a[1]*neighbor[1]+a[0]*neighbor[0]+a[3]*neighbor[3]+a[2]*neighbor[2];
    if (!mesh.two_d) {
        diagonal += a[5]+a[4];
        rhs += a[5]*neighbor[5]+a[4]*neighbor[4];
    }
    diagonal += hv;
    double correction = 0.0;
    if (!reconstruction.size) reconstruction = {t.data,t.size};
    if (sou)
        for (std::size_t axis = 0; axis < mesh.axes; ++axis)
            correction += sou_axis(mesh,f,reconstruction,p,axis,c);
    rhs += hv*solid[p];
    rhs += correction;
    if (!std::isfinite(diagonal) || !std::isfinite(rhs) || diagonal <= 0.0)
        throw std::domain_error("invalid temperature fluid equation");
    if (mesh.two_d && alpha != 1.0) {
        const auto axis = direction/2;
        const bool outlet = direction%2 == 0 ? c[axis]+1 == mesh.count[axis] : c[axis] == 0;
        if (outlet) alpha = 1.0;
    }
    update(t,p,rhs/diagonal,alpha,change);
}

void solid_row(const Mesh& mesh, const TemperatureFluidView& a, const TemperatureFluidView& b,
               ArrayView<const double> ks, TemperatureStateView state, std::size_t p,
               const std::array<std::size_t,3>& c, double alpha, double& change) {
    std::array<double,6> conductance{}, neighbor{};
    for (std::size_t axis = 0; axis < mesh.axes; ++axis) {
        const auto pos = c[axis], count = mesh.count[axis], stride = mesh.stride[axis];
        const auto width = mesh.width[axis];
        const double area = mesh.face_area(axis,c);
        for (std::size_t side = 0; side < 2; ++side) {
            const auto face = 2*axis+side;
            const bool inside = side == 0 ? pos > 0 : pos+1 < count;
            const auto nb = inside ? (side == 0 ? p-stride : p+stride) : p;
            const auto npos = inside ? (side == 0 ? pos-1 : pos+1) : pos;
            conductance[face] = inside ? detail::diffusion_conductance(
                ks[p],ks[nb],0.5*width[pos],0.5*width[npos])*area : ks[p]*area/width[pos];
            neighbor[face] = state.solid[nb];
        }
    }
    const double ha = a.hv[p]*mesh.volume(c), hb = b.hv[p]*mesh.volume(c);
    double diagonal = conductance[1]+conductance[0]+conductance[3]+conductance[2];
    double rhs = conductance[1]*neighbor[1]+conductance[0]*neighbor[0]
        +conductance[3]*neighbor[3]+conductance[2]*neighbor[2];
    if (!mesh.two_d) {
        diagonal += conductance[5]+conductance[4];
        rhs += conductance[5]*neighbor[5]+conductance[4]*neighbor[4];
    }
    diagonal += ha+hb;
    rhs += ha*state.a[p]+hb*state.b[p];
    if (!std::isfinite(diagonal) || !std::isfinite(rhs) || diagonal <= 0.0)
        throw std::domain_error("invalid temperature solid equation");
    update(state.solid,p,rhs/diagonal,alpha,change);
}

double chunk(const Mesh& mesh, const TemperatureFluidView& a, const TemperatureFluidView& b,
             ArrayView<const double> ks, TemperatureStateView state,
             const TemperatureControl& control, bool frozen, std::size_t sweeps,
             bool red_black) {
    double change = 0.0;
    const bool reverse_x = !red_black && a.boundary.direction == 1;
    const bool reverse_y = !red_black && (b.boundary.direction == 3
        || (mesh.two_d && a.boundary.direction == 3 && b.boundary.direction == 0));
    const bool reverse_z = !red_black && a.boundary.direction == 5;
    std::vector<double> snapshot_a(red_black ? state.a.size : 0);
    std::vector<double> snapshot_b(red_black ? state.b.size : 0);
    for (std::size_t iteration = 0; iteration < sweeps; ++iteration) {
        change = 0.0;
        if (red_black) {
            std::copy(state.a.data,state.a.data+state.a.size,snapshot_a.begin());
            std::copy(state.b.data,state.b.data+state.b.size,snapshot_b.begin());
        }
        for (std::size_t color = 0; color < (red_black ? 2U : 1U); ++color)
          for (std::size_t ii = 0; ii < mesh.g.nx; ++ii)
            for (std::size_t jj = 0; jj < mesh.g.ny; ++jj)
                for (std::size_t kk = 0; kk < mesh.g.nz; ++kk) {
                    const std::array<std::size_t,3> c{
                        reverse_x ? mesh.g.nx-1-ii : ii,
                        reverse_y ? mesh.g.ny-1-jj : jj,
                        reverse_z ? mesh.g.nz-1-kk : kk};
                    if (red_black && (c[0]+c[1])%2 != color) continue;
                    const auto p = (c[0]*mesh.g.ny+c[1])*mesh.g.nz+c[2];
                    fluid_row(mesh,a,state.a,state.solid,p,c,true,control.alpha_a,change,
                              {snapshot_a.data(),snapshot_a.size()});
                    solid_row(mesh,a,b,ks,state,p,c,control.alpha_solid,change);
                    if (!frozen) fluid_row(mesh,b,state.b,state.solid,p,c,
                                          control.second_order_b,control.alpha_b,change,
                                          {snapshot_b.data(),snapshot_b.size()});
                }
        if (change < 1e-10) break;
    }
    return change;
}

double duty(const Mesh& mesh, const TemperatureFluidView& b, TemperatureStateView state) {
    double q = 0.0;
    for (std::size_t i = 0; i < mesh.g.nx; ++i)
        for (std::size_t j = 0; j < mesh.g.ny; ++j)
            for (std::size_t k = 0; k < mesh.g.nz; ++k) {
                const auto p = (i*mesh.g.ny+j)*mesh.g.nz+k;
                q += b.hv[p]*(state.solid[p]-state.b[p])*mesh.volume({i,j,k});
            }
    if (!std::isfinite(q)) throw std::domain_error("nonfinite temperature duty");
    return q;
}

}  // namespace

TemperatureResult solve_legacy_single_a_temperature(TemperatureScheme scheme, const GridView& grid,
    const TemperatureFluidView& a, const TemperatureFluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    const TemperatureControl& control, ArrayView<const double> prescribed_b, bool red_black) {
    if (scheme != TemperatureScheme::cell_centered_2d && scheme != TemperatureScheme::cell_centered_3d)
        throw std::invalid_argument("unsupported temperature scheme");
    const bool two_d = scheme == TemperatureScheme::cell_centered_2d;
    if (red_black && !two_d)
        throw std::invalid_argument("cell-centred RB requires a 2D temperature scheme");
    const auto cells = product(product(grid.nx,grid.ny),grid.nz);
    if ((two_d && grid.nz != 1) || (!two_d && grid.nz <= 1))
        throw std::invalid_argument("temperature dimension does not match scheme");
    coefficient(grid.dx,grid.nx,true); coefficient(grid.dy,grid.ny,true);
    coefficient(grid.dz,grid.nz,true); coefficient(k_ss,cells);
    if (!control.chunk_iterations || !std::isfinite(control.q_relative_tolerance)
        || control.q_relative_tolerance <= 0.0)
        throw std::invalid_argument("invalid temperature chunk or stopping tolerance");
    for (const double alpha : {control.alpha_a,control.alpha_solid,control.alpha_b})
        if (!std::isfinite(alpha) || alpha <= 0.0 || alpha > 1.0)
            throw std::invalid_argument("invalid temperature relaxation");
    if ((two_d && (control.alpha_a != .7 || control.alpha_solid != 1. || control.alpha_b != 1.))
        || (!two_d && !control.second_order_b))
        throw std::invalid_argument("unsupported temperature phase policy");
    const std::array<ArrayView<double>,3> outputs{state.a,state.b,state.solid};
    for (auto out : outputs) check_array(out,cells,control.warm_start);
    if (prescribed_b.size) check_array(prescribed_b,cells);
    for (std::size_t i = 0; i < outputs.size(); ++i) {
        for (std::size_t j = 0; j < i; ++j) disjoint(outputs[i],outputs[j]);
        for (auto input : {grid.dx,grid.dy,grid.dz,k_ss,prescribed_b}) disjoint(outputs[i],input);
    }
    for (const auto* f : {&a,&b}) {
        coefficient(f->conductivity,cells); coefficient(f->hv,cells);
        coefficient(f->epsilon,cells); coefficient(f->rho_cp,cells,true);
        check_array(f->u,cells); check_array(f->v,cells);
        if (!two_d || f->w.size) check_array(f->w,cells);
        const auto& bc = f->boundary;
        if (bc.direction < 0 || bc.direction >= (two_d ? 4 : 6)
            || !std::isfinite(bc.inlet_temperature))
            throw std::invalid_argument("invalid temperature inlet direction or value");
        const auto face_size = bc.direction < 2 ? product(grid.ny,grid.nz)
            : (bc.direction < 4 ? product(grid.nx,grid.nz) : product(grid.nx,grid.ny));
        for (auto input : {bc.profile,bc.opening,bc.capacity_flux})
            if (input.size) check_array(input,face_size);
        for (std::size_t i = 0; i < bc.opening.size; ++i)
            if (bc.opening[i] < 0. || bc.opening[i] > 1.)
                throw std::invalid_argument("inlet opening must lie in [0,1]");
        for (auto out : outputs)
            for (auto input : {f->conductivity,f->hv,f->epsilon,f->rho_cp,f->u,f->v,f->w,
                               bc.profile,bc.opening,bc.capacity_flux}) disjoint(out,input);
    }
    if (!control.warm_start) {
        std::fill_n(state.a.data,cells,a.boundary.inlet_temperature);
        std::fill_n(state.b.data,cells,b.boundary.inlet_temperature);
        std::fill_n(state.solid.data,cells,.5*(a.boundary.inlet_temperature+b.boundary.inlet_temperature));
    }
    if (prescribed_b.size) std::copy_n(prescribed_b.data,cells,state.b.data);
    const Mesh mesh(grid,two_d);
    std::array<std::vector<double>,3> previous;
    for (std::size_t phase = 0; phase < outputs.size(); ++phase)
        previous[phase].assign(outputs[phase].data,outputs[phase].data+cells);
    TemperatureResult result{TemperatureStop::budget_exhausted,0,0.,
                             std::numeric_limits<double>::quiet_NaN()};
    bool have_previous_q = false;
    double previous_q = 0.0;
    while (result.iterations < control.max_iterations) {
        if (control.cancel && control.cancel(control.context)) {
            result.stop = TemperatureStop::cancelled;
            result.q_b = std::numeric_limits<double>::quiet_NaN();
            return result;
        }
        const auto n = std::min(control.chunk_iterations,control.max_iterations-result.iterations);
        result.residual = chunk(mesh,a,b,k_ss,state,control,prescribed_b.size != 0,n,red_black);
        result.iterations += n;
        if (control.progress) control.progress(control.context,result.iterations,control.max_iterations);
        if (control.cancel && control.cancel(control.context)) {
            result.stop = TemperatureStop::cancelled;
            result.q_b = std::numeric_limits<double>::quiet_NaN();
            return result;
        }
        result.q_b = duty(mesh,b,state);
        double delta = 0.0;
        for (std::size_t phase = 0; phase < outputs.size(); ++phase)
            for (std::size_t p = 0; p < cells; ++p)
                delta = std::max(delta,std::abs(outputs[phase][p]-previous[phase][p]));
        const double scale = std::max({std::abs(result.q_b),std::abs(previous_q),1.0});
        if (have_previous_q && std::abs(result.q_b-previous_q)/scale < control.q_relative_tolerance
            && delta < .01) {
            result.stop = TemperatureStop::converged;
            return result;
        }
        previous_q = result.q_b;
        have_previous_q = true;
        for (std::size_t phase = 0; phase < outputs.size(); ++phase)
            std::copy_n(outputs[phase].data,cells,previous[phase].data());
    }
    return result;
}

}  // namespace tpmshx
