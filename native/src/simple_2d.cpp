#include "tpmshx/simple_2d.hpp"
#include "tpmshx/simple_momentum.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>

namespace tpmshx {
namespace {
template <typename T> ArrayView<const T> read(ArrayView<T> a) { return {a.data, a.size}; }
SimpleFacesView<const double> velocities(Simple2DStateView s) { return {read(s.u), read(s.v), {}}; }
SimpleFacesView<double> mutable_velocities(Simple2DStateView s) { return {s.u, s.v, {}}; }
SimpleFacesView<const double> corrections(Simple2DStateView s) { return {read(s.d_u), read(s.d_v), {}}; }

template <typename T> void extent(ArrayView<T> a, std::size_t size, const char* name) {
    if (a.size != size || (size && !a.data))
        throw std::invalid_argument(std::string("invalid SIMPLE 2D extent: ") + name);
}
template <typename T> bool finite(ArrayView<T> a) {
    for (std::size_t i = 0; i < a.size; ++i) if (!std::isfinite(a[i])) return false;
    return true;
}
bool state_finite(const Simple2DMaterialView& m, Simple2DStateView s) {
    return finite(s.u) && finite(s.v) && finite(s.pressure) && finite(s.density) && finite(m.temperature);
}
void positive(ArrayView<const double> a, const char* name, bool zero_allowed = false) {
    for (std::size_t i = 0; i < a.size; ++i)
        if (!std::isfinite(a[i]) || (zero_allowed ? a[i] < 0. : a[i] <= 0.))
            throw std::invalid_argument(std::string("invalid SIMPLE 2D coefficient: ") + name);
}
void fraction(ArrayView<const double> a, const char* name) {
    for (std::size_t i = 0; i < a.size; ++i)
        if (!std::isfinite(a[i]) || a[i] < 0. || a[i] > 1.)
            throw std::invalid_argument(std::string("invalid SIMPLE 2D opening: ") + name);
}
bool overlap(ArrayView<const double> a, ArrayView<const double> b) {
    const auto x = reinterpret_cast<std::uintptr_t>(a.data), y = reinterpret_cast<std::uintptr_t>(b.data);
    return a.size && b.size && (x <= y ? y-x < a.size*sizeof(double) : x-y < b.size*sizeof(double));
}
void validate(const GridView& g, const Simple2DMaterialView& m,
    const Simple2DBoundaryView& b, Simple2DStateView s, bool initial=true) {
    if (!g.nx || !g.ny || g.nz != 1 || g.nx > static_cast<std::size_t>(std::numeric_limits<int>::max())/g.ny)
        throw std::invalid_argument("SIMPLE 2D requires a nonempty 32-bit cell grid and nz=1");
    extent(g.dx, g.nx, "dx"); extent(g.dy, g.ny, "dy"); extent(g.dz, 1, "dz");
    positive(g.dx, "dx"); positive(g.dy, "dy");
    if (g.dz[0] != 1.) throw std::invalid_argument("SIMPLE 2D uses unit depth");
    const auto n = g.nx*g.ny;
    extent(m.epsilon, n, "epsilon"); extent(m.viscosity, n, "viscosity");
    extent(m.effective_viscosity, n, "effective_viscosity"); extent(m.permeability, n, "permeability");
    extent(m.forchheimer, n, "forchheimer"); extent(m.temperature, n, "temperature");
    extent(s.u, (g.nx+1)*g.ny, "u"); extent(s.v, g.nx*(g.ny+1), "v");
    extent(s.pressure, n, "pressure"); extent(s.pressure_correction, n, "pressure_correction");
    extent(s.d_u, s.u.size, "d_u"); extent(s.d_v, s.v.size, "d_v"); extent(s.density, n, "density");
    extent(s.inlet_velocity, g.nx, "inlet_velocity");
    extent(b.inlet_fraction, g.nx, "inlet_fraction"); extent(b.outlet_u_fraction, g.nx+1, "outlet_u_fraction");
    positive(m.epsilon, "epsilon"); positive(m.viscosity, "viscosity");
    positive(m.effective_viscosity, "effective_viscosity"); positive(m.permeability, "permeability");
    positive(m.forchheimer, "forchheimer", true);
    fraction(m.epsilon, "epsilon"); fraction(b.inlet_fraction, "inlet_fraction");
    fraction(b.outlet_u_fraction, "outlet_u_fraction");
    if ((initial && !finite(s.inlet_velocity)) || !std::isfinite(b.reference_inlet_velocity)
        || !std::isfinite(b.taper_flux_scale) || b.taper_flux_scale <= 0.
        || (b.inlet_density_reference && (!std::isfinite(*b.inlet_density_reference) || *b.inlet_density_reference <= 0.)))
        throw std::invalid_argument("invalid SIMPLE 2D inlet reference");
    const ArrayView<const double> outputs[] = {read(s.u), read(s.v), read(s.pressure), read(s.pressure_correction),
        read(s.d_u), read(s.d_v), read(s.density), read(s.inlet_velocity)};
    const ArrayView<const double> inputs[] = {g.dx, g.dy, g.dz, m.epsilon, m.viscosity,
        m.effective_viscosity, m.permeability, m.forchheimer, m.temperature,
        b.inlet_fraction, b.outlet_u_fraction};
    for (std::size_t i = 0; i < 8; ++i) {
        for (std::size_t j = 0; j < i; ++j)
            if (overlap(outputs[i], outputs[j])) throw std::invalid_argument("SIMPLE mutable arrays overlap");
        for (auto input : inputs)
            if (overlap(outputs[i], input)) throw std::invalid_argument("SIMPLE mutable state overlaps an input");
    }
}

double eps_ratio(double value, double centre) { return value == centre ? 1. : value/centre; }
using detail::sou_axis;
using detail::sou_bound;

struct Transport { double de, dw, dn, ds, fe, fw, fn, fs; };
struct Equation { double diagonal, rhs, compensation; };
struct Kernel {
    const GridView& g;
    const Simple2DMaterialView& m;
    const Simple2DBoundaryView& b;
    Simple2DStateView s;
    const int nx, ny;
    const double anisotropy;
    Kernel(const GridView& grid, const Simple2DMaterialView& material,
        const Simple2DBoundaryView& boundary, Simple2DStateView state, double cf)
        : g(grid), m(material), b(boundary), s(state), nx(static_cast<int>(grid.nx)),
          ny(static_cast<int>(grid.ny)), anisotropy(cf) {}
    std::size_t c(int i, int j) const { return static_cast<std::size_t>(i)*g.ny+static_cast<std::size_t>(j); }
    std::size_t vindex(int i, int j) const { return static_cast<std::size_t>(i)*(g.ny+1)+static_cast<std::size_t>(j); }
    double u(int i, int j) const { return s.u[c(i,j)]; }
    double v(int i, int j) const { return s.v[vindex(i,j)]; }
    double ep(int i, int j) const { return m.epsilon[c(i,j)]; }
    double rho(int i, int j) const { return s.density[c(i,j)]; }
    double effective_mu(int i, int j, double ec) const { return m.effective_viscosity[c(i,j)]*eps_ratio(ep(i,j),ec); }
    double mass_x(int i, int j, double ec) const {
        if (i == 0 || i == nx) return 0.;
        return .5*(rho(i-1,j)*eps_ratio(ep(i-1,j),ec)+rho(i,j)*eps_ratio(ep(i,j),ec))*u(i,j);
    }
    double mass_y(int i, int j, double ec) const {
        const int lo = std::max(j-1,0), hi = std::min(j,ny-1);
        return .5*(rho(i,lo)*eps_ratio(ep(i,lo),ec)+rho(i,hi)*eps_ratio(ep(i,hi),ec))*v(i,j);
    }
    Transport transport_u(int i, int j) const {
        Transport t{};
        const double ec = .5*(ep(i-1,j)+ep(i,j)), wl = .5*g.dx[i-1], wr = .5*g.dx[i];
        t.de = effective_mu(i,j,ec)*g.dy[j]/g.dx[i];
        t.fe = .5*(mass_x(i,j,ec)+mass_x(i+1,j,ec))*g.dy[j];
        t.dw = effective_mu(i-1,j,ec)*g.dy[j]/g.dx[i-1];
        t.fw = .5*(mass_x(i,j,ec)+mass_x(i-1,j,ec))*g.dy[j];
        if (j < ny-1) {
            t.dn = wl*detail::diffusion_conductance(effective_mu(i-1,j,ec), effective_mu(i-1,j+1,ec), .5*g.dy[j], .5*g.dy[j+1])
                 + wr*detail::diffusion_conductance(effective_mu(i,j,ec), effective_mu(i,j+1,ec), .5*g.dy[j], .5*g.dy[j+1]);
        } else {
            t.dn = 2.*(wl*effective_mu(i-1,j,ec)+wr*effective_mu(i,j,ec))/g.dy[j];
            t.dn *= 1.-b.outlet_u_fraction[i];
        }
        t.fn = wl*mass_y(i-1,j+1,ec)+wr*mass_y(i,j+1,ec);
        if (j > 0) {
            t.ds = wl*detail::diffusion_conductance(effective_mu(i-1,j,ec), effective_mu(i-1,j-1,ec), .5*g.dy[j], .5*g.dy[j-1])
                 + wr*detail::diffusion_conductance(effective_mu(i,j,ec), effective_mu(i,j-1,ec), .5*g.dy[j], .5*g.dy[j-1]);
        } else t.ds = 2.*(wl*effective_mu(i-1,j,ec)+wr*effective_mu(i,j,ec))/g.dy[j];
        t.fs = wl*mass_y(i-1,j,ec)+wr*mass_y(i,j,ec);
        return t;
    }
    Transport transport_v(int i, int j) const {
        Transport t{};
        const double ec = .5*(ep(i,j-1)+ep(i,j)), wl = .5*g.dy[j-1], wr = .5*g.dy[j];
        if (i < nx-1) {
            t.de = wl*detail::diffusion_conductance(effective_mu(i,j-1,ec), effective_mu(i+1,j-1,ec), .5*g.dx[i], .5*g.dx[i+1])
                 + wr*detail::diffusion_conductance(effective_mu(i,j,ec), effective_mu(i+1,j,ec), .5*g.dx[i], .5*g.dx[i+1]);
        } else t.de = 2.*(wl*effective_mu(i,j-1,ec)+wr*effective_mu(i,j,ec))/g.dx[i];
        t.fe = wl*mass_x(i+1,j-1,ec)+wr*mass_x(i+1,j,ec);
        if (i > 0) {
            t.dw = wl*detail::diffusion_conductance(effective_mu(i,j-1,ec), effective_mu(i-1,j-1,ec), .5*g.dx[i], .5*g.dx[i-1])
                 + wr*detail::diffusion_conductance(effective_mu(i,j,ec), effective_mu(i-1,j,ec), .5*g.dx[i], .5*g.dx[i-1]);
        } else t.dw = 2.*(wl*effective_mu(i,j-1,ec)+wr*effective_mu(i,j,ec))/g.dx[i];
        t.fw = wl*mass_x(i,j-1,ec)+wr*mass_x(i,j,ec);
        t.dn = effective_mu(i,j,ec)*g.dx[i]/g.dy[j];
        t.fn = .5*(mass_y(i,j,ec)+mass_y(i,j+1,ec))*g.dx[i];
        t.ds = effective_mu(i,j-1,ec)*g.dx[i]/g.dy[j-1];
        t.fs = .5*(mass_y(i,j,ec)+mass_y(i,j-1,ec))*g.dx[i];
        return t;
    }
    Equation equation_u(int i, int j, bool predictor) const {
        const auto t = transport_u(i,j);
        const double ue = i+1 < nx ? u(i+1,j) : 0., uw = i > 1 ? u(i-1,j) : 0.;
        const double un = j < ny-1 ? u(i,j+1) : 0., us = j > 0 ? u(i,j-1) : 0.;
        const double rl = .5*(rho(i-1,j)+rho(i,j));
        const double ml = .5*(m.viscosity[c(i-1,j)]+m.viscosity[c(i,j)]);
        const double va = .25*(v(i-1,j)+v(i,j)+v(i-1,j+1)+v(i,j+1));
        const double speed = std::sqrt(u(i,j)*u(i,j)+va*va);
        const double permeability = .5*(m.permeability[c(i-1,j)]+m.permeability[c(i,j)]);
        double cf = .5*(m.forchheimer[c(i-1,j)]+m.forchheimer[c(i,j)]);
        if (anisotropy != 0. && speed > 1e-10) {
            const double ux2 = u(i,j)*u(i,j), uy2 = va*va;
            const double xi4 = 4.*ux2*uy2/(speed*speed*speed*speed);
            cf *= 1.+anisotropy*xi4;
        }
        const double volume = .5*(g.dx[i-1]+g.dx[i])*g.dy[j];
        const double drag = (speed < 1e-10 ? ml/permeability : ml/permeability+rl*cf*speed)*volume;
        const double source = (s.pressure[c(i-1,j)]-s.pressure[c(i,j)])*g.dy[j];
        const double sou = sou_axis(u(std::max(i-2,0),j),u(i-1,j),u(i,j),u(std::min(i+1,nx),j),u(std::min(i+2,nx),j),
            i>2, i>1 && i+1<nx, i+2<=nx, i>1, t.fw,t.fe,g.dx,i,true)
            + sou_axis(u(i,std::max(j-2,0)),u(i,std::max(j-1,0)),u(i,j),u(i,std::min(j+1,ny-1)),u(i,std::min(j+2,ny-1)),
            j>1, j>0 && j<ny-1, j<ny-2, j>0 && j<ny-1, t.fs,t.fn,g.dy,j,false);
        Equation e{t.de+t.dw+t.dn+t.ds+drag+std::max(t.fe,0.)+std::max(-t.fw,0.)+std::max(t.fn,0.)+std::max(-t.fs,0.),
            (t.de+std::max(-t.fe,0.))*ue+(t.dw+std::max(t.fw,0.))*uw
            +(t.dn+std::max(-t.fn,0.))*un+(t.ds+std::max(t.fs,0.))*us+source+sou, 0.};
        if (predictor) {
            e.compensation = std::max(-(t.fe-t.fw+t.fn-t.fs),0.);
            e.compensation += sou_bound(u(i-1,j),u(i,j),u(i+1,j),i>1,i>1 && i+1<nx,t.fw,t.fe,g.dx,i,true)
                +sou_bound(u(i,std::max(j-1,0)),u(i,j),u(i,std::min(j+1,ny-1)),
                    j>0 && j<ny-1,j>0 && j<ny-1,t.fs,t.fn,g.dy,j,false);
        }
        return e;
    }
    Equation equation_v(int i, int j, bool predictor) const {
        const auto t = transport_v(i,j);
        const double ve = i < nx-1 ? v(i+1,j) : 0., vw = i > 0 ? v(i-1,j) : 0.;
        const double vn = v(i,j+1), vs = v(i,j-1);
        const double rl = .5*(rho(i,j-1)+rho(i,j));
        const double ml = .5*(m.viscosity[c(i,j-1)]+m.viscosity[c(i,j)]);
        const double ua = .25*(u(i,j-1)+u(i+1,j-1)+u(i,j)+u(i+1,j));
        const double speed = std::sqrt(ua*ua+v(i,j)*v(i,j));
        double cf = m.forchheimer[c(i,j)];
        if (anisotropy != 0. && speed > 1e-10) {
            const double ux2 = ua*ua, uy2 = v(i,j)*v(i,j);
            const double xi4 = 4.*ux2*uy2/(speed*speed*speed*speed);
            cf *= 1.+anisotropy*xi4;
        }
        const double volume = g.dx[i]*.5*(g.dy[j-1]+g.dy[j]);
        const double drag = (speed < 1e-10 ? ml/m.permeability[c(i,j)] : ml/m.permeability[c(i,j)]+rl*cf*speed)*volume;
        const double source = (s.pressure[c(i,j-1)]-s.pressure[c(i,j)])*g.dx[i];
        const double sou = sou_axis(v(std::max(i-2,0),j),v(std::max(i-1,0),j),v(i,j),v(std::min(i+1,nx-1),j),v(std::min(i+2,nx-1),j),
            i>1,i>0 && i<nx-1,i<nx-2,i>0 && i<nx-1,t.fw,t.fe,g.dx,i,false)
            +sou_axis(v(i,std::max(j-2,0)),v(i,j-1),v(i,j),v(i,std::min(j+1,ny)),v(i,std::min(j+2,ny)),
            j>2,j>1 && j+1<=ny,j+2<=ny,j>1,t.fs,t.fn,g.dy,j,true);
        Equation e{t.de+t.dw+t.dn+t.ds+drag+std::max(t.fe,0.)+std::max(-t.fw,0.)+std::max(t.fn,0.)+std::max(-t.fs,0.),
            (t.de+std::max(-t.fe,0.))*ve+(t.dw+std::max(t.fw,0.))*vw
            +(t.dn+std::max(-t.fn,0.))*vn+(t.ds+std::max(t.fs,0.))*vs+source+sou, 0.};
        if (predictor) {
            e.compensation = std::max(-(t.fe-t.fw+t.fn-t.fs),0.);
            e.compensation += sou_bound(v(std::max(i-1,0),j),v(i,j),v(std::min(i+1,nx-1),j),
                i>0 && i<nx-1,i>0 && i<nx-1,t.fw,t.fe,g.dx,i,false)
                +sou_bound(v(i,j-1),v(i,j),v(i,j+1),j>1,j>1,t.fs,t.fn,g.dy,j,true);
        }
        return e;
    }
    void predict(ArrayView<const unsigned char> outlet_open, double alpha, std::size_t sweeps) const {
        for (std::size_t sweep = 0; sweep < sweeps; ++sweep)
            for (int i = 1; i < nx; ++i) for (int j = 0; j < ny; ++j) {
                const auto e = equation_u(i,j,true);
                const double ap = e.diagonal+e.compensation;
                double rhs = e.rhs+e.compensation*u(i,j);
                rhs += (1.-alpha)/alpha*ap*u(i,j);
                s.u[c(i,j)] = rhs/(ap/alpha);
                s.d_u[c(i,j)] = g.dy[j]/ap;
            }
        for (int j = 0; j < ny; ++j) { s.u[c(0,j)] = 0.; s.u[c(nx,j)] = 0.; }
        for (std::size_t sweep = 0; sweep < sweeps; ++sweep)
            for (int i = 0; i < nx; ++i) for (int j = 1; j < ny; ++j) {
                const auto e = equation_v(i,j,true);
                const double ap = e.diagonal+e.compensation;
                double rhs = e.rhs+e.compensation*v(i,j);
                rhs += (1.-alpha)/alpha*ap*v(i,j);
                s.v[vindex(i,j)] = rhs/(ap/alpha);
                s.d_v[vindex(i,j)] = g.dx[i]/ap;
            }
        for (int i = 0; i < nx; ++i) s.v[vindex(i,0)] = s.inlet_velocity[i]*b.inlet_fraction[i];
        if (!finite(s.u) || !finite(s.v) || !finite(s.d_u) || !finite(s.d_v))
            throw std::domain_error("nonfinite SIMPLE momentum arithmetic");
        close_simple_outlet(2,g,outlet_open,mutable_velocities(s),read(s.density),m.epsilon);
    }
    SimpleMomentumResidual residual() const {
        SimpleMomentumResidual r;
        for (int i = 1; i < nx; ++i) for (int j = 0; j < ny; ++j) {
            const auto e = equation_u(i,j,false); const double lhs = e.diagonal*u(i,j);
            r.numerator[0] += std::abs(lhs-e.rhs); r.denominator[0] += .5*(std::abs(lhs)+std::abs(e.rhs));
        }
        for (int i = 0; i < nx; ++i) for (int j = 1; j < ny; ++j) {
            const auto e = equation_v(i,j,false); const double lhs = e.diagonal*v(i,j);
            r.numerator[1] += std::abs(lhs-e.rhs); r.denominator[1] += .5*(std::abs(lhs)+std::abs(e.rhs));
        }
        normalize_simple_momentum(r,2);
        return r;
    }
};

void nonfinite_result(Simple2DResult& r) {
    const auto invalidate = [](double& v) { if (std::isfinite(v)) v = std::numeric_limits<double>::quiet_NaN(); };
    r.stop = SimpleStop::nonfinite; r.converged = false; r.post_closure_certified = false;
    r.legacy_residual = std::numeric_limits<double>::quiet_NaN();
    invalidate(r.momentum.maximum); invalidate(r.mass.local_residual);
    invalidate(r.mass.global_residual); invalidate(r.mass.backflow_fraction);
}
void validate_solve(const GridView& g,const Simple2DMaterialView& m,
    const Simple2DBoundaryView& b,Simple2DStateView s,const Simple2DControl& control,bool initial=true) {
    validate(g,m,b,s,initial);
    if (!control.max_iterations || !control.inner_sweeps)
        throw std::invalid_argument("SIMPLE iteration budgets must be positive");
    for (double alpha : {control.alpha_velocity,control.alpha_pressure,control.alpha_density})
        if (!std::isfinite(alpha) || alpha <= 0. || alpha > 1.)
            throw std::invalid_argument("invalid SIMPLE relaxation");
    if (!std::isfinite(control.pressure_reference_absolute) || control.pressure_reference_absolute <= 0.
        || !std::isfinite(control.gas_constant) || control.gas_constant <= 0. || !std::isfinite(control.cf_anisotropy))
        throw std::invalid_argument("invalid SIMPLE pressure/density controls");
}

}

void simple_2d_predictor(const GridView& g, ArrayView<const unsigned char> outlet_open,
    const Simple2DMaterialView& m, const Simple2DBoundaryView& b, Simple2DStateView s,
    double alpha, std::size_t sweeps, double cf) {
    validate(g,m,b,s); extent(outlet_open,g.nx,"outlet_open");
    if (!std::isfinite(alpha) || alpha <= 0. || alpha > 1. || !std::isfinite(cf))
        throw std::invalid_argument("invalid SIMPLE momentum controls");
    if (!state_finite(m,s)) throw std::invalid_argument("nonfinite SIMPLE predictor input");
    Kernel(g,m,b,s,cf).predict(outlet_open,alpha,sweeps);
    if (!state_finite(m,s) || !finite(s.d_u) || !finite(s.d_v))
        throw std::domain_error("nonfinite SIMPLE momentum arithmetic");
}

SimpleMomentumResidual simple_2d_momentum_residual(const GridView& g,
    const Simple2DMaterialView& m, const Simple2DBoundaryView& b, Simple2DStateView s, double cf) {
    validate(g,m,b,s);
    if (!std::isfinite(cf)) throw std::invalid_argument("invalid SIMPLE anisotropy");
    return Kernel(g,m,b,s,cf).residual();
}

struct Simple2DSolver::Impl {
    struct Active {
        Simple2DMaterialView material;
        Simple2DBoundaryView boundary;
        Simple2DStateView state;
        Simple2DControl control;
        SimpleF2Monitor monitor;
        Simple2DResult result;
        Active(const Simple2DMaterialView& m,const Simple2DBoundaryView& b,
            Simple2DStateView s,const Simple2DControl& c)
            :material(m),boundary(b),state(s),control(c),monitor(velocities(s),c.convergence,20) {}
        Active(const Simple2DMaterialView& m,const Simple2DBoundaryView& b,
            Simple2DStateView s,const Simple2DControl& c,const Simple2DRunState& saved)
            :material(m),boundary(b),state(s),control(c),monitor(saved.convergence,c.convergence),result(saved.result) {}
    };
    std::unique_ptr<Active> active;
    SimplePhase phase=SimplePhase::idle;
    bool boundary=true,taken=false;
    bool initialize();
    bool step();
    Simple2DOwnerState owner_state() const;
    std::vector<double> dx, dy, old_rho_eps, fresh_rho_eps;
    double depth = 1.;
    std::vector<unsigned char> outlet;
    GridView grid;
    SimplePressureAssembly assembly;
    PressureCandidate pressure;
    SimpleHistory history;
    std::optional<double> target;
    std::size_t pressure_clip_hits = 0;
    Impl(const GridView& g, ArrayView<const unsigned char> open)
        : dx(g.dx.data,g.dx.data+g.dx.size), dy(g.dy.data,g.dy.data+g.dy.size),
          old_rho_eps(g.nx*g.ny), fresh_rho_eps(g.nx*g.ny), outlet(open.data,open.data+open.size),
          grid{g.nx,g.ny,1,{dx.data(),dx.size()},{dy.data(),dy.size()},{&depth,1}}, assembly(2,grid,{outlet.data(),outlet.size()}) {}
    ArrayView<const unsigned char> opening() const { return {outlet.data(),outlet.size()}; }
    ArrayView<const unsigned char> excluded() const { return {assembly.cell_kind().data(),assembly.cell_kind().size()}; }
    void rho_eps(std::vector<double>& out, const Simple2DMaterialView& m, Simple2DStateView s) {
        for (std::size_t k = 0; k < out.size(); ++k) out[k] = s.density[k]*m.epsilon[k];
    }
    void inlet(Simple2DStateView s, bool enabled) const {
        if (enabled && target)
            for (std::size_t i = 0; i < grid.nx; ++i)
                s.inlet_velocity[i] = *target/std::max(s.density[i*grid.ny],1e-9);
    }
};

Simple2DSolver::Simple2DSolver(const GridView& g, ArrayView<const unsigned char> open) {
    if (!g.nx || !g.ny || g.nz != 1 || g.nx > static_cast<std::size_t>(std::numeric_limits<int>::max())/g.ny)
        throw std::invalid_argument("invalid SIMPLE 2D grid");
    extent(g.dx,g.nx,"dx"); extent(g.dy,g.ny,"dy"); extent(g.dz,1,"dz"); extent(open,g.nx,"outlet_open");
    positive(g.dx,"dx"); positive(g.dy,"dy");
    if (g.dz[0] != 1.) throw std::invalid_argument("SIMPLE 2D uses unit depth");
    for (std::size_t i = 0; i < open.size; ++i) if (open[i] > 1) throw std::invalid_argument("invalid outlet support");
    impl_ = std::make_unique<Impl>(g,open);
}
Simple2DOwnerState Simple2DSolver::Impl::owner_state() const {
    return {{dx,dy},depth,outlet,pressure.snapshot(),history,target,pressure_clip_hits};
}
Simple2DOwnerState Simple2DSolver::snapshot() const {
    if(impl_->phase==SimplePhase::active || !impl_->boundary)
        throw std::logic_error("use an active SIMPLE snapshot during a solve");
    return impl_->owner_state();
}
void Simple2DSolver::restore(const Simple2DOwnerState& state) {
    const auto& p=*impl_;
    if(p.phase==SimplePhase::active || !p.boundary)
        throw std::logic_error("cannot replace an active SIMPLE call");
    if(state.widths[0]!=p.dx || state.widths[1]!=p.dy || state.depth!=p.depth || state.outlet!=p.outlet
        || state.history.legacy.size()!=state.history.local_mass.size()
        || state.history.legacy.size()!=state.history.global_mass.size()
        || (state.massflux_target && !std::isfinite(*state.massflux_target))
        || (state.pressure.construction && state.pressure.construction->rhs.size()!=p.grid.nx*p.grid.ny))
        throw std::invalid_argument("saved SIMPLE 2D owner differs from its grid or history");
    for(const auto* values:{&state.history.legacy,&state.history.local_mass,&state.history.global_mass})
        for(double value:*values)
            if(!std::isfinite(value) || value<0.)throw std::invalid_argument("invalid saved SIMPLE 2D residual");
    for(const auto& record:state.history.momentum) {
        if(!record.iteration || !std::isfinite(record.residual.maximum) || record.residual.maximum<0.)
            throw std::invalid_argument("invalid saved SIMPLE 2D momentum record");
        for(const auto* values:{&record.residual.numerator,&record.residual.denominator,&record.residual.component})
            for(double value:*values)
                if(!std::isfinite(value) || value<0.)throw std::invalid_argument("invalid saved SIMPLE 2D momentum value");
    }
    auto restored=std::make_unique<Impl>(p.grid,p.opening());
    restored->pressure.restore(state.pressure);restored->history=state.history;
    restored->target=state.massflux_target;restored->pressure_clip_hits=state.pressure_clip_hits;
    impl_=std::move(restored);
}
Simple2DSolver::~Simple2DSolver() = default;
const SimpleHistory& Simple2DSolver::history() const { return impl_->history; }
std::optional<double> Simple2DSolver::massflux_target() const { return impl_->target; }

bool Simple2DSolver::Impl::initialize() {
    auto& impl=*this;const auto& g=grid;auto& call=*active;
    const auto& m=call.material;const auto& b=call.boundary;auto s=call.state;
    const auto& control=call.control;auto& result=call.result;
    result.pressure_clip_hits = impl.pressure_clip_hits;
    if (!state_finite(m,s)) { nonfinite_result(result); return true; }
    positive(read(s.density),"density"); positive(m.temperature,"temperature");
    if (control.massflux_inlet && (control.ideal_gas || b.inlet_density_reference) && !impl.target) {
        double reference = 0.;
        if (b.inlet_density_reference) reference = *b.inlet_density_reference;
        else {
            for (std::size_t i = 0; i < g.nx; ++i) reference += s.density[i*g.ny];
            reference /= static_cast<double>(g.nx);
        }
        impl.target = b.reference_inlet_velocity*reference*b.taper_flux_scale;
        if (!control.ideal_gas) impl.inlet(s,control.massflux_inlet);
    }
    return false;
}

bool Simple2DSolver::Impl::step() {
    auto& impl=*this;const auto& g=grid;auto& call=*active;
    const auto& m=call.material;const auto& b=call.boundary;auto s=call.state;
    const auto& control=call.control;auto& result=call.result;
    auto& monitor=call.monitor;
    Kernel kernel(g,m,b,s,control.cf_anisotropy);
    const SimpleBoundaryView velocity_boundary{read(s.inlet_velocity),b.inlet_fraction,impl.opening()};
    const auto close_outlet = [&] {
        if (control.close_outlet_on_exit)
            close_simple_outlet(2,g,impl.opening(),mutable_velocities(s),read(s.density),m.epsilon);
    };
    const auto mass_audit = [&] {
        impl.rho_eps(impl.fresh_rho_eps,m,s);
        return simple_mass_audit(2,g,velocities(s),{impl.fresh_rho_eps.data(),impl.fresh_rho_eps.size()},impl.excluded());
    };
    const auto it=result.iterations+1;
    if (control.cancel && control.cancel(control.context)) { result.stop = SimpleStop::cancelled; return true; }
    result.iterations = it;
    impl.rho_eps(impl.old_rho_eps,m,s);
    try { kernel.predict(impl.opening(),control.alpha_velocity,control.inner_sweeps); }
    catch (const std::domain_error&) { nonfinite_result(result); return true; }
    if (!state_finite(m,s) || !finite(s.d_u) || !finite(s.d_v)) { nonfinite_result(result); return true; }
    const auto& system = impl.assembly.assemble(g,velocities(s),corrections(s),{impl.old_rho_eps.data(),impl.old_rho_eps.size()});
    PressureControl linear_control; linear_control.dimension = 2;
    result.linear = impl.pressure.solve(system,linear_control);
    if (!result.linear.success) { result.stop = SimpleStop::pressure_failure; return true; }
    std::copy(result.linear.x.begin(),result.linear.x.end(),s.pressure_correction.data);
    result.linear.x.clear();
    try {
        correct_simple_pressure(2,g,velocity_boundary,s.pressure,read(s.pressure_correction),mutable_velocities(s),
            corrections(s),read(s.density),m.epsilon,control.alpha_pressure);
    } catch (const std::domain_error&) { nonfinite_result(result); return true; }
    if (control.ideal_gas) {
        if (!state_finite(m,s)) { nonfinite_result(result); return true; }
        for (std::size_t k = 0; k < s.pressure.size; ++k) {
            double absolute = s.pressure[k]+control.pressure_reference_absolute;
            const bool clipped = absolute < 1e3 || absolute > 10e6;
            absolute = std::clamp(absolute,1e3,10e6);
            if (clipped) { ++impl.pressure_clip_hits; s.pressure[k] = absolute-control.pressure_reference_absolute; }
            const double new_density = absolute/(m.temperature[k]*control.gas_constant);
            s.density[k] = control.alpha_density*new_density+(1.-control.alpha_density)*s.density[k];
        }
        impl.inlet(s,control.massflux_inlet);
    }
    result.pressure_clip_hits = impl.pressure_clip_hits;
    if (!state_finite(m,s)) { nonfinite_result(result); return true; }
    result.legacy_residual = simple_legacy_mass_residual(2,g,velocities(s),
        {impl.old_rho_eps.data(),impl.old_rho_eps.size()}).residual;
    impl.history.legacy.push_back(result.legacy_residual);
    if (control.progress && (it % 20 == 0 || it == 1)) control.progress(control.context,it,result.legacy_residual);
    const double delta = monitor.velocity_delta(velocities(s));
    result.mass = mass_audit();
    impl.history.local_mass.push_back(result.mass.local_residual);
    impl.history.global_mass.push_back(result.mass.global_residual);
    if (!std::isfinite(result.legacy_residual) || !std::isfinite(delta)
        || !std::isfinite(result.mass.local_residual) || !std::isfinite(result.mass.global_residual)
        || !std::isfinite(result.mass.backflow_fraction)) { nonfinite_result(result); return true; }
    if (monitor.should_evaluate_momentum(it,delta)) {
        result.momentum = kernel.residual();
        impl.history.momentum.push_back({it,result.momentum});
        const auto reason = monitor.submit(it,result.momentum.maximum,result.mass,delta);
        if (reason == SimpleStop::nonfinite) { nonfinite_result(result); return true; }
        if (reason != SimpleStop::ongoing) {
            try { close_outlet(); } catch (const std::domain_error&) { nonfinite_result(result); return true; }
            if (!state_finite(m,s)) { nonfinite_result(result); return true; }
            result.mass = mass_audit(); result.momentum = kernel.residual();
            result.post_closure_measured = true;
            if (!std::isfinite(result.momentum.maximum) || !std::isfinite(result.mass.local_residual)
                || !std::isfinite(result.mass.global_residual) || !std::isfinite(result.mass.backflow_fraction)) {
                nonfinite_result(result); return true;
            }
            result.post_closure_certified = monitor.gates_hold(result.momentum.maximum,result.mass);
            result.stop = reason;
            result.converged = reason == SimpleStop::tol && result.post_closure_certified;
            return true;
        }
    }
    if(it<control.max_iterations)return false;
    try { close_outlet(); } catch (const std::domain_error&) { nonfinite_result(result); return true; }
    if (!state_finite(m,s)) { nonfinite_result(result); return true; }
    // Keep Python 2D's max-budget contract: closure does not replace its last
    // measured F2 values or invent a returned-field certificate.
    result.stop = SimpleStop::max_iterations;
    return true;
}

SimplePhase Simple2DSolver::start(const Simple2DMaterialView& m,const Simple2DBoundaryView& b,
    Simple2DStateView s,const Simple2DControl& control) {
    auto& impl=*impl_;
    if(impl.phase==SimplePhase::active || !impl.boundary)
        throw std::logic_error("SIMPLE call is already active");
    impl.boundary=false;impl.phase=SimplePhase::failed;impl.taken=false;
    try {
        validate_solve(impl.grid,m,b,s,control);
        impl.active=std::make_unique<Impl::Active>(m,b,s,control);
        impl.phase=SimplePhase::active;
        const bool done=impl.initialize();
        impl.phase=!done?SimplePhase::active:(impl.active->result.stop==SimpleStop::cancelled?SimplePhase::cancelled:SimplePhase::completed);
        impl.boundary=true;return impl.phase;
    } catch(...) { impl.phase=SimplePhase::failed;impl.boundary=true;throw; }
}

SimplePhase Simple2DSolver::advance() {
    auto& impl=*impl_;
    if(!impl.boundary)throw std::logic_error("SIMPLE step is already advancing");
    if(impl.phase==SimplePhase::failed)throw std::logic_error("failed SIMPLE call cannot advance");
    if(impl.phase!=SimplePhase::active)return impl.phase;
    impl.boundary=false;
    try {
        if(impl.step())impl.phase=impl.active->result.stop==SimpleStop::cancelled?SimplePhase::cancelled:SimplePhase::completed;
        impl.boundary=true;return impl.phase;
    } catch(...) { impl.phase=SimplePhase::failed;impl.boundary=true;throw; }
}
SimplePhase Simple2DSolver::phase() const { return impl_->phase; }
Simple2DResult Simple2DSolver::take_result() {
    auto& impl=*impl_;
    if(impl.taken || !impl.boundary || (impl.phase!=SimplePhase::completed && impl.phase!=SimplePhase::cancelled))
        throw std::logic_error("SIMPLE result is not available");
    impl.taken=true;return std::move(impl.active->result);
}

Simple2DRunState Simple2DSolver::snapshot_active() const {
    const auto& impl=*impl_;
    if(impl.phase!=SimplePhase::active || !impl.boundary)
        throw std::logic_error("SIMPLE has no active save boundary");
    const auto s=impl.active->state;
    const ArrayView<double> fields[]{s.u,s.v,s.pressure,s.pressure_correction,s.d_u,s.d_v,s.density,s.inlet_velocity};
    Simple2DRunState saved;
    saved.owner=impl.owner_state();saved.convergence=impl.active->monitor.snapshot();saved.result=impl.active->result;
    for(std::size_t i=0;i<8;++i)saved.fields[i].assign(fields[i].data,fields[i].data+fields[i].size);
    return saved;
}
void Simple2DSolver::restore_active(const Simple2DMaterialView& m,const Simple2DBoundaryView& b,
    Simple2DStateView s,const Simple2DControl& control,const Simple2DRunState& saved) {
    const auto& impl=*impl_;
    if(impl.phase==SimplePhase::active || !impl.boundary)
        throw std::logic_error("cannot replace an active SIMPLE call");
    validate_solve(impl.grid,m,b,s,control,false);positive(m.temperature,"temperature");
    const ArrayView<double> fields[]{s.u,s.v,s.pressure,s.pressure_correction,s.d_u,s.d_v,s.density,s.inlet_velocity};
    const auto& r=saved.result;
    if(r.converged || r.iterations>=control.max_iterations || !r.linear.x.empty()
        || r.pressure_clip_hits!=saved.owner.pressure_clip_hits
        || saved.owner.history.legacy.size()<r.iterations
        || saved.convergence.minimum_iterations!=20
        || saved.convergence.window_start_iteration>r.iterations
        || saved.convergence.streak>=control.convergence.confirmations)
        throw std::invalid_argument("invalid saved SIMPLE iteration position");
    if(r.stop!=SimpleStop::ongoing || r.post_closure_measured || r.post_closure_certified)
        throw std::invalid_argument("saved SIMPLE 2D call has a final certificate");
    for(std::size_t i=0;i<8;++i) {
        const auto& values=saved.fields[i];
        if(values.size()!=fields[i].size)throw std::invalid_argument("saved SIMPLE field extent differs");
        // Initial correction arrays are unused until the first complete step.
        const bool initialized=r.iterations || i<=2 || i>=6;
        if(initialized)for(double value:values)
            if(!std::isfinite(value))throw std::invalid_argument("nonfinite saved SIMPLE field");
    }
    positive({saved.fields[6].data(),saved.fields[6].size()},"saved density");
    const std::size_t sizes[]{s.u.size,s.v.size,0};
    for(std::size_t i=0;i<3;++i)
        if(saved.convergence.previous[i].size()!=sizes[i])
            throw std::invalid_argument("saved SIMPLE F2 extent differs");
    if(r.iterations) {
        for(double value:{r.legacy_residual,r.mass.local_residual,r.mass.global_residual,r.mass.backflow_fraction})
            if(!std::isfinite(value) || value<0.)throw std::invalid_argument("invalid saved SIMPLE residual");
        if(!std::isfinite(r.mass.mass_in) || !std::isfinite(r.mass.mass_out) || !r.linear.success)
            throw std::invalid_argument("invalid saved SIMPLE step evidence");
    }
    if(!std::isnan(r.momentum.maximum) && (!std::isfinite(r.momentum.maximum) || r.momentum.maximum<0.))
        throw std::invalid_argument("invalid saved SIMPLE momentum");
    for(const auto* values:{&r.momentum.numerator,&r.momentum.denominator,&r.momentum.component})
        for(double value:*values)
            if(!std::isfinite(value) || value<0.)throw std::invalid_argument("invalid saved SIMPLE momentum component");
    Simple2DSolver restored(impl.grid,impl.opening());
    restored.restore(saved.owner);
    restored.impl_->active=std::make_unique<Impl::Active>(m,b,s,control,saved);
    restored.impl_->phase=SimplePhase::active;
    for(std::size_t i=0;i<8;++i)
        std::copy(saved.fields[i].begin(),saved.fields[i].end(),fields[i].data);
    impl_=std::move(restored.impl_);
}

Simple2DResult Simple2DSolver::solve(const Simple2DMaterialView& m,const Simple2DBoundaryView& b,
    Simple2DStateView s,const Simple2DControl& control) {
    start(m,b,s,control);
    while(phase()==SimplePhase::active)advance();
    return take_result();
}

}  // namespace tpmshx
