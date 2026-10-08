#include "tpmshx/model_h_2d.hpp"
#include "model_h_common.hpp"
#include "energy_fv_rows.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace tpmshx {
namespace {
using namespace model_h_common;
using Vector = std::vector<double>;
using Faces = std::array<Vector, 2>;


struct Mesh {
    const GridView& g;
    std::size_t n;
    Vector zero_z = Vector(2*n);
    std::size_t cell(std::size_t i, std::size_t j) const { return i*g.ny+j; }
    std::size_t face(std::size_t axis, std::size_t i, std::size_t j) const {
        return i*(axis==0 ? g.ny : g.ny+1)+j;
    }
    double volume(std::size_t i, std::size_t j) const { return g.dx[i]*g.dy[j]; }
    double divergence(const Faces& f, std::size_t i, std::size_t j) const {
        return f[0][face(0,i+1,j)]-f[0][face(0,i,j)]
             + f[1][face(1,i,j+1)]-f[1][face(1,i,j)];
    }
};

struct Side {
    const ModelHFluid2D& f;
    const std::array<double,5>* cp;
    bool second_order, strict_boundary;
    Faces capacity, deferred;
    Side(const Mesh&, const ModelHFluid2D& fluid, bool order, bool solved, bool strict)
        : f(fluid), cp(solved ? &coefficients(f.fluid) : nullptr), second_order(order), strict_boundary(strict),
          capacity{Vector(f.mass_x.size),Vector(f.mass_y.size)},
          deferred{Vector(f.mass_x.size),Vector(f.mass_y.size)} {}
    EnergyPhase energy(const Mesh& mesh) const {
        return {f.conductivity,f.hv,{},
            {{view(capacity[0]),view(capacity[1]),view(mesh.zero_z)},
             {view(deferred[0]),view(deferred[1]),{}}},f.boundary,true,strict_boundary};
    }
    PhysicalEnergyPhase physical(const Mesh& mesh) const {
        return {f.conductivity,f.hv,{},
            {view(capacity[0]),view(capacity[1]),view(mesh.zero_z)},
            {view(deferred[0]),view(deferred[1]),view(mesh.zero_z)},f.boundary,true,strict_boundary};
    }
    ArrayView<const double> mass(std::size_t axis) const { return axis==0 ? f.mass_x : f.mass_y; }
    double inlet(std::size_t patch) const { return optional(f.boundary.profile,patch,f.boundary.inlet_temperature); }
    double opening(std::size_t patch) const { return optional(f.boundary.opening,patch,1); }
};

template<bool physical=false>
void faces(const Mesh& mesh, Side& side, ArrayView<const double> t) {
    const auto& g=mesh.g;
    const auto& coefficients=*side.cp;
    const auto dir=static_cast<std::size_t>(side.f.boundary.direction);
    for (std::size_t axis=0; axis<2; ++axis) {
        const auto count=axis==0 ? g.nx : g.ny, ni=g.nx+(axis==0), nj=g.ny+(axis==1);
        const auto width=axis==0 ? g.dx : g.dy;
        for (std::size_t i=0; i<ni; ++i) for (std::size_t j=0; j<nj; ++j) {
            const auto p=mesh.face(axis,i,j), pos=axis==0 ? i : j;
            const double mass=side.mass(axis)[p];
            const auto u=mass>=0 ? (pos==0 ? 0 : pos-1) : std::min(pos,count-1);
            const auto up=axis==0 ? mesh.cell(u,j) : mesh.cell(i,u);
            double temperature=t[up], inc=0;
            if (side.second_order && pos>0 && pos<count && u>0 && u+1<count) {
                const auto stride=axis==0 ? g.ny : 1;
                inc=increment(t[up-stride],temperature,t[up+stride],.5*(width[u-1]+width[u]),
                              .5*(width[u]+width[u+1]),(mass>=0 ? .5 : -.5)*width[u]);
            } else if (side.strict_boundary && side.second_order && count>1
                       && !(pos==0 && mass>0) && !(pos==count && mass<0)) {
                const bool low=u==0;
                const auto neighbor=low ? u+1 : u-1, end=low ? 0 : count;
                const auto patch=axis==0 ? j : i;
                const auto boundary_face=axis==0 ? mesh.face(axis,end,j) : mesh.face(axis,i,end);
                const double boundary_mass=side.mass(axis)[boundary_face];
                const bool known=axis==dir/2 && dir%2==(low ? 0U : 1U)
                    && side.opening(patch)>0 && (low ? boundary_mass : -boundary_mass)>0;
                const auto near=axis==0 ? mesh.cell(neighbor,j) : mesh.cell(i,neighbor);
                inc=boundary_increment(temperature,t[near],.5*(width[u]+width[neighbor]),
                    known ? side.inlet(patch) : 0.,.5*width[u],known,low,
                    (mass>=0 ? .5 : -.5)*width[u]);
            }
            if (axis==dir/2 && pos==(dir%2==0 ? 0 : count)) {
                const auto patch=axis==0 ? j : i;
                if (side.opening(patch)>0 && (dir%2==0 ? mass : -mass)>0) temperature=side.inlet(patch);
            }
            const double x=temperature-coefficients[3], cp=coefficients[0]+coefficients[1]*x+coefficients[2]*x*x;
            side.capacity[axis][p]=mass*cp;
            if constexpr (physical)
                side.deferred[axis][p]=mass*enthalpy(temperature+inc,coefficients);
            else side.deferred[axis][p]=mass*(enthalpy(temperature+inc,coefficients)-cp*temperature);
        }
    }
}

Faces fluxes(const Mesh& mesh, const Side& side, ArrayView<const double> t) {
    Faces flux{Vector(side.f.mass_x.size),Vector(side.f.mass_y.size)};
    const auto& g=mesh.g;
    const auto dir=static_cast<std::size_t>(side.f.boundary.direction);
    for (std::size_t axis=0; axis<2; ++axis) {
        const auto count=axis==0 ? g.nx : g.ny;
        for (std::size_t i=0; i<g.nx+(axis==0); ++i) for (std::size_t j=0; j<g.ny+(axis==1); ++j) {
            const auto p=mesh.face(axis,i,j), pos=axis==0 ? i : j;
            const double mass=side.mass(axis)[p];
            const auto up=mass>=0 ? (pos==0 ? 0 : pos-1) : std::min(pos,count-1);
            double temperature=axis==0 ? t[mesh.cell(up,j)] : t[mesh.cell(i,up)];
            if (axis==dir/2 && pos==(dir%2==0 ? 0 : count)) {
                const auto patch=axis==0 ? j : i;
                if (side.opening(patch)>0 && (dir%2==0 ? mass : -mass)>0) temperature=side.inlet(patch);
            }
            flux[axis][p]=side.capacity[axis][p]*temperature+side.deferred[axis][p];
        }
    }
    return flux;
}

void update(ArrayView<double> t, std::size_t p, double value, double& change) {
    if (!std::isfinite(value)) throw std::domain_error("nonfinite model-h update");
    change=std::max(change,std::abs(value-t[p]));
    t[p]=value;
}

double sweeps(const Mesh& mesh, Side& a, Side& b, ArrayView<const double> ks,
              TemperatureStateView t, Vector& last_a, Vector& last_b,
              std::size_t count, bool red_black, bool solve_b) {
    const auto& g=mesh.g;
    const detail::EnergyMesh energy_mesh(g);
    const auto phase_a=a.energy(mesh),phase_b=b.energy(mesh);
    double change=0;
    for (std::size_t it=0; it<count; ++it) {
        last_a.assign(t.a.data,t.a.data+t.a.size);
        last_b.assign(t.b.data,t.b.data+t.b.size);
        faces(mesh,a,view(last_a));
        if (solve_b) faces(mesh,b,view(last_b));
        change=0;
        for (std::size_t color=0; color<(red_black ? 2U : 1U); ++color)
            for (std::size_t ii=0; ii<g.nx; ++ii) for (std::size_t jj=0; jj<g.ny; ++jj) {
                const auto i=!red_black && a.f.boundary.direction==1 ? g.nx-1-ii : ii;
                const auto j=!red_black && (b.f.boundary.direction==3
                    || (a.f.boundary.direction==3 && b.f.boundary.direction==0)) ? g.ny-1-jj : jj;
                if (red_black && (i+j)%2!=color) continue;
                const auto p=mesh.cell(i,j);
                const auto row_a=detail::fluid_energy_defect_row(energy_mesh,phase_a,view(t.a),view(t.solid),p);
                if (!std::isfinite(row_a.diagonal) || row_a.diagonal<=0)
                    throw std::domain_error("invalid model-h fluid equation");
                update(t.a,p,t.a[p]+model_coefficients::model_h_relaxation*row_a.rhs/row_a.diagonal,change);
                const auto row_s=detail::solid_energy_defect_row(energy_mesh,ks,a.f.hv,b.f.hv,
                    view(t.a),view(t.b),view(t.solid),{},p);
                if (!std::isfinite(row_s.diagonal) || row_s.diagonal<=0)
                    throw std::domain_error("invalid model-h solid equation");
                update(t.solid,p,t.solid[p]+row_s.rhs/row_s.diagonal,change);
                if (solve_b) {
                    const auto row_b=detail::fluid_energy_defect_row(energy_mesh,phase_b,view(t.b),view(t.solid),p);
                    if (!std::isfinite(row_b.diagonal) || row_b.diagonal<=0)
                        throw std::domain_error("invalid model-h fluid equation");
                    update(t.b,p,t.b[p]+model_coefficients::model_h_relaxation*row_b.rhs/row_b.diagonal,change);
                }
            }
        if (change==0.) break;
    }
    return change;
}

std::array<Vector,4> boundaries(const Mesh& mesh, ArrayView<const double> x, ArrayView<const double> y) {
    std::array<Vector,4> out{Vector(mesh.g.ny),Vector(mesh.g.ny),Vector(mesh.g.nx),Vector(mesh.g.nx)};
    for (std::size_t j=0; j<mesh.g.ny; ++j) { out[0][j]=-x[j]; out[1][j]=x[mesh.g.nx*mesh.g.ny+j]; }
    for (std::size_t i=0; i<mesh.g.nx; ++i) {
        out[2][i]=-y[i*(mesh.g.ny+1)]; out[3][i]=y[i*(mesh.g.ny+1)+mesh.g.ny];
    }
    return out;
}
ModelHAudit2D audit(const Mesh& mesh, Side& a, Side& b, ArrayView<const double> ks,
                   TemperatureStateView t, const Vector& last_a, const Vector& last_b) {
    ModelHAudit2D result{};
    faces(mesh,a,view(t.a)); faces(mesh,b,view(t.b));
    auto ledger=energy_physical_audit(mesh.g,a.energy(mesh),b.energy(mesh),ks,t);
    result.finite=true; result.boundary_complete=ledger.boundary_complete;
    result.solid_residual=std::move(ledger.residual[2]);
    Side* sides[]{&a,&b};
    const ArrayView<const double> temperature[]{view(t.a),view(t.b)}, snapshot[]{view(last_a),view(last_b)};
    for (std::size_t index=0; index<2; ++index) {
        auto& s=*sides[index]; auto& out=result.sides[index]; const auto temp=temperature[index];
        out.cp_coefficients=*s.cp;
        faces(mesh,s,temp); out.h_faces=fluxes(mesh,s,temp);
        faces(mesh,s,snapshot[index]); const auto linear=fluxes(mesh,s,temp);
        out.residual=std::move(ledger.residual[index]); out.linearization_defect.resize(mesh.n);
        for (std::size_t i=0; i<mesh.g.nx; ++i) for (std::size_t j=0; j<mesh.g.ny; ++j) {
            const auto p=mesh.cell(i,j);
            const double exchange=s.f.hv[p]*(t.solid[p]-temp[p])*mesh.volume(i,j);
            const double div=mesh.divergence(out.h_faces,i,j);
            out.linearization_defect[p]=mesh.divergence(linear,i,j)-div;
            out.exchange+=exchange;
            const double mass=s.f.mass_x[mesh.face(0,i+1,j)]-s.f.mass_x[mesh.face(0,i,j)]
                             +s.f.mass_y[mesh.face(1,i,j+1)]-s.f.mass_y[mesh.face(1,i,j)];
            out.mass_net+=mass; out.mass_local_max=std::max(out.mass_local_max,std::abs(mass));
        }
        const auto dir=static_cast<std::size_t>(s.f.boundary.direction), npatch=dir<2 ? mesh.g.ny : mesh.g.nx;
        out.inlet_conduction_faces.resize(npatch);
        for (std::size_t patch=0; patch<npatch; ++patch) {
            const double value=-ledger.diffusive_out[index][dir][patch];
            out.inlet_conduction_faces[patch]=value; out.inlet_conduction+=value;
        }
        out.boundary_mass_out=boundaries(mesh,s.f.mass_x,s.f.mass_y);
        for (std::size_t f=0; f<4; ++f)
            out.boundary_h_out[f]=std::move(ledger.advective_out[index][f]);
        for (std::size_t f=0; f<4; ++f) for (std::size_t p=0; p<out.boundary_mass_out[f].size(); ++p) {
            const double mass=out.boundary_mass_out[f][p];
            if (mass<0 && (f!=dir || s.opening(p)<=0)) ++out.unknown_inflow_faces;
            out.mass_in+=std::max(-mass,0.0); out.mass_out+=std::max(mass,0.0);
            out.q_advective-=out.boundary_h_out[f][p];
        }
        for (std::size_t p=0; p<mesh.n; ++p) {
            const double r=out.residual[p], defect=out.linearization_defect[p], lin=r-defect;
            out.residual_sum+=r; out.residual_max=std::max(out.residual_max,std::abs(r));
            out.defect_sum+=defect; out.defect_max=std::max(out.defect_max,std::abs(defect));
            out.linearized_sum+=lin; out.linearized_max=std::max(out.linearized_max,std::abs(lin));
            result.finite=result.finite && std::isfinite(r) && std::isfinite(defect);
        }
        out.normalization=std::max(std::abs(out.exchange),1.0);
        out.cell_ratio=out.residual_max*static_cast<double>(mesh.n)/out.normalization;
        result.net_boundary_in+=out.q_advective+out.inlet_conduction;
        result.residual_sum+=out.residual_sum;
        result.boundary_complete=result.boundary_complete && out.unknown_inflow_faces==0;
    }
    for (double r:result.solid_residual) {
        result.solid_sum+=r; result.solid_max=std::max(result.solid_max,std::abs(r));
        result.finite=result.finite && std::isfinite(r);
    }
    result.finite=result.finite && std::isfinite(result.net_boundary_in);
    result.denominator=std::max({std::abs(result.sides[0].exchange),std::abs(result.sides[1].exchange),1.0});
    result.solid_cell_ratio=result.solid_max*static_cast<double>(mesh.n)/result.denominator;
    result.residual_sum+=result.solid_sum;
    result.telescoping_error=result.residual_sum-result.net_boundary_in;
    result.energy_imbalance=std::abs(result.net_boundary_in)/result.denominator;
    result.solid_imbalance=std::abs(result.solid_sum)/result.denominator;
    const bool valid=result.finite && result.boundary_complete;
    result.energy_ok=valid && result.energy_imbalance<=.005;
    result.solid_ok=valid && result.solid_imbalance<=.01;
    result.equations_ok=valid && result.solid_cell_ratio<=.01
        && result.sides[0].cell_ratio<=.01 && result.sides[1].cell_ratio<=.01;
    result.passed=result.energy_ok && result.solid_ok && result.equations_ok;
    return result;
}


void validate(const GridView& g, const ModelHFluid2D& a, const ModelHFluid2D& b,
              ArrayView<const double> ks, TemperatureStateView t, const ModelHControl2D& c,
              ArrayView<const double> prescribed_b) {
    const auto n=product(g.nx,g.ny);
    if (g.nz!=1 || g.nx==std::numeric_limits<std::size_t>::max() || g.ny==std::numeric_limits<std::size_t>::max())
        throw std::invalid_argument("model-h 2D requires a unit-depth grid");
    product(g.nx+1,g.ny); product(g.nx,g.ny+1);
    if (n>static_cast<std::size_t>(std::numeric_limits<Eigen::Index>::max())/3)
        throw std::invalid_argument("model-h state is too large");
    coefficient(g.dx,g.nx,true); coefficient(g.dy,g.ny,true); coefficient(g.dz,1,true);
    if (g.dz[0]!=1) throw std::invalid_argument("model-h 2D requires dz=1");
    coefficient(ks,n);
    if (!c.chunk_iterations || !std::isfinite(c.q_relative_tolerance) || c.q_relative_tolerance<0)
        throw std::invalid_argument("invalid model-h control");
    const ArrayView<double> states[]{t.a,t.b,t.solid};
    for (auto state:states) check(state,n,c.warm_start);
    if (prescribed_b.size) {
        if (!c.strict_energy_balance)
            throw std::invalid_argument("prescribed model-h B requires strict energy mode");
        check(prescribed_b,n);
        for (auto state:states) disjoint(view(state),prescribed_b);
    }
    for (std::size_t i=0; i<3; ++i) {
        for (std::size_t j=i+1; j<3; ++j) disjoint(view(states[i]),view(states[j]));
        for (auto input:{g.dx,g.dy,g.dz,ks}) disjoint(view(states[i]),input);
    }
    for (const auto* f:{&a,&b}) {
        const bool solved=f==&a || !prescribed_b.size;
        if (solved) coefficients(f->fluid);
        coefficient(f->conductivity,n); coefficient(f->hv,n);
        check(f->mass_x,(g.nx+1)*g.ny,solved); check(f->mass_y,g.nx*(g.ny+1),solved);
        const auto& bc=f->boundary;
        if (bc.direction<0 || bc.direction>3 || !std::isfinite(bc.inlet_temperature)
            || (solved && bc.inlet_temperature<=0) || bc.capacity_flux.size)
            throw std::invalid_argument("invalid model-h boundary");
        const auto count=bc.direction<2 ? g.ny : g.nx;
        if (bc.profile.size) {
            if (solved) coefficient(bc.profile,count,true);
            else check(bc.profile,count);
        }
        if (bc.opening.size) {
            coefficient(bc.opening,count);
            for (std::size_t p=0; p<count; ++p)
                if (bc.opening[p]>1) throw std::invalid_argument("invalid model-h opening fraction");
        }
        for (auto state:states) for (auto input:{f->conductivity,f->hv,f->mass_x,f->mass_y,bc.profile,bc.opening})
            disjoint(view(state),input);
    }
}
}  // namespace

ModelHResult2D solve_model_h_2d(const GridView& g, const ModelHFluid2D& a,
                              const ModelHFluid2D& b, ArrayView<const double> ks,
                              TemperatureStateView t, const ModelHControl2D& c,
                              ArrayView<const double> prescribed_b,
                              PhysicalHeatLedger* physical_audit) {
    validate(g,a,b,ks,t,c,prescribed_b);
    const bool solve_b=!prescribed_b.size;
    ModelHResult2D result{};
    result.stop=TemperatureStop::budget_exhausted;
    result.q_b=std::numeric_limits<double>::quiet_NaN();
    const auto cancelled=[&] { return c.cancel && c.cancel(c.context); };
    if (cancelled()) { result.stop=TemperatureStop::cancelled; return result; }
    if (!c.warm_start) {
        std::fill_n(t.a.data,t.a.size,a.boundary.inlet_temperature);
        if (solve_b) std::fill_n(t.b.data,t.b.size,b.boundary.inlet_temperature);
        std::fill_n(t.solid.data,t.solid.size,.5*(a.boundary.inlet_temperature+b.boundary.inlet_temperature));
    }
    if (!solve_b) std::copy_n(prescribed_b.data,prescribed_b.size,t.b.data);
    result.last_a.assign(t.a.data,t.a.data+t.a.size); result.last_b.assign(t.b.data,t.b.data+t.b.size);
    const Mesh mesh{g,g.nx*g.ny};
    Side side_a(mesh,a,c.second_order_a,true,c.strict_energy_balance),
         side_b(mesh,b,c.second_order_b,solve_b,c.strict_energy_balance);
    auto previous=pack(t,solve_b);
    bool strict_boundary_complete=true;
    const auto strict_audit=[&] {
        // Reuse the deferred buffers for actual m*h, avoiding C*T+B
        // cancellation. Every subsequent numerical sweep rebuilds C/B first.
        faces<true>(mesh,side_a,view(t.a));
        if (solve_b) faces<true>(mesh,side_b,view(t.b));
        auto ledger=energy_physical_audit(g,side_a.physical(mesh),side_b.physical(mesh),ks,t,{},prescribed_b);
        result.energy_error_ratio=energy_balance_error(ledger)/energy_scale(g,a.hv,b.hv,t);
        strict_boundary_complete=ledger.boundary_complete;
        result.physical_audit_available=true;
        const bool passed=ledger.boundary_complete && std::isfinite(result.energy_error_ratio)
            && result.energy_error_ratio<=1e-7;
        if (physical_audit) *physical_audit=std::move(ledger);
        return passed;
    };
    double previous_q=0;
    bool have_q=false;
    // The cancellation exception never escapes the public C++ driver.
    struct Cancelled {};
    const auto step=[&](std::size_t count) {
        if (cancelled()) throw Cancelled{};
        const double change=sweeps(mesh,side_a,side_b,ks,t,result.last_a,result.last_b,count,c.red_black,solve_b);
        if (cancelled()) throw Cancelled{};
        return change;
    };
    try {
        while (result.iterations<c.max_iterations) {
            if (cancelled()) throw Cancelled{};
            const auto count=std::min(c.chunk_iterations,c.max_iterations-result.iterations);
            if (c.accelerate) {
                Anderson accelerator;
                std::size_t done=0;
                while (done<count) {
                    auto before=pack(t,solve_b);
                    const auto n=std::min<std::size_t>(25,count-done);
                    result.residual=step(n); done+=n;
                    auto picard=pack(t,solve_b);
                    accelerator.push(std::move(before),picard);
                    Eigen::VectorXd candidate;
                    if (!accelerator.candidate(picard,candidate) || count-done<2) continue;
                    const double picard_residual=step(1);
                    picard=pack(t,solve_b);
                    const auto saved_a=result.last_a, saved_b=result.last_b;
                    restore(t,candidate,solve_b);
                    const double candidate_residual=step(1); done+=2;
                    if (std::isfinite(candidate_residual) && candidate_residual<=picard_residual)
                        result.residual=candidate_residual;
                    else {
                        restore(t,picard,solve_b); result.last_a=saved_a; result.last_b=saved_b;
                        result.residual=picard_residual;
                    }
                }
            } else result.residual=step(count);
            result.audit_available=false;
            result.physical_audit_available=false;
            result.iterations+=count;
            if (c.progress) c.progress(c.context,result.iterations,c.max_iterations);
            if (cancelled()) throw Cancelled{};
            double q=0;
            for (std::size_t i=0; i<g.nx; ++i) for (std::size_t j=0; j<g.ny; ++j) {
                const auto p=mesh.cell(i,j);
                q+=b.hv[p]*(t.solid[p]-t.b[p])*mesh.volume(i,j);
            }
            result.q_b=q;
            const auto current=pack(t,solve_b);
            if (have_q && std::abs(q-previous_q)/std::max({std::abs(q),std::abs(previous_q),1.0})<c.q_relative_tolerance
                && (current-previous).cwiseAbs().maxCoeff()<.01) {
                if (c.strict_energy_balance) {
                    const bool passed=strict_audit();
                    result.finishing_checks.push_back({result.iterations,passed,passed,result.energy_error_ratio});
                    if (passed) result.stop=TemperatureStop::converged;
                    if (passed || !strict_boundary_complete) break;
                } else {
                    result.audit=audit(mesh,side_a,side_b,ks,t,result.last_a,result.last_b);
                    result.audit_available=true;
                    result.finishing_checks.push_back({result.iterations,result.audit.passed,result.audit.equations_ok});
                    if (result.audit.passed) result.stop=TemperatureStop::converged;
                    if (result.audit.passed || !result.audit.boundary_complete) break;
                }
            }
            previous_q=q; have_q=true; previous=current;
        }
    } catch (const Cancelled&) {
        result.stop=TemperatureStop::cancelled;
        result.audit_available=false; result.q_b=std::numeric_limits<double>::quiet_NaN();
        result.physical_audit_available=false;
        result.energy_error_ratio=std::numeric_limits<double>::quiet_NaN();
        return result;
    }
    if (c.strict_energy_balance) {
        if (!result.physical_audit_available && result.iterations) strict_audit();
    } else if (!result.audit_available) {
        result.audit=audit(mesh,side_a,side_b,ks,t,result.last_a,result.last_b);
        result.audit_available=true;
    }
    return result;
}
}  // namespace tpmshx
