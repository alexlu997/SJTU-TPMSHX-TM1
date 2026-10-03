#include "tpmshx/model_h_2d.hpp"
#include "model_h_common.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace tpmshx {
namespace {
using namespace model_h_common;
using Vector = std::vector<double>;
using Faces = std::array<Vector, 2>;
using Rows = std::vector<std::array<double, 4>>;


struct Mesh {
    const GridView& g;
    std::size_t n;
    std::size_t cell(std::size_t i, std::size_t j) const { return i*g.ny+j; }
    std::size_t face(std::size_t axis, std::size_t i, std::size_t j) const {
        return i*(axis==0 ? g.ny : g.ny+1)+j;
    }
    std::size_t neighbor(std::size_t i, std::size_t j, std::size_t f) const {
        if (f==0 && i>0) return cell(i-1,j);
        if (f==1 && i+1<g.nx) return cell(i+1,j);
        if (f==2 && j>0) return cell(i,j-1);
        if (f==3 && j+1<g.ny) return cell(i,j+1);
        return cell(i,j);
    }
    double volume(std::size_t i, std::size_t j) const { return g.dx[i]*g.dy[j]; }
    double divergence(const Faces& f, std::size_t i, std::size_t j) const {
        return f[0][face(0,i+1,j)]-f[0][face(0,i,j)]
             + f[1][face(1,i,j+1)]-f[1][face(1,i,j)];
    }
};

Rows diffusion_rows(const Mesh& mesh, ArrayView<const double> k,
                    const TemperatureBoundary* boundary) {
    const auto& g=mesh.g;
    Rows rows(mesh.n);
    for (std::size_t i=0; i<g.nx; ++i) for (std::size_t j=0; j<g.ny; ++j) {
        const auto p=mesh.cell(i,j);
        for (std::size_t f=0; f<4; ++f) {
            const auto nb=mesh.neighbor(i,j,f), axis=f/2, pos=axis==0 ? i : j;
            const auto widths=axis==0 ? g.dx : g.dy;
            const double area=axis==0 ? g.dy[j] : g.dx[i];
            if (nb!=p) {
                const auto next=f%2==0 ? pos-1 : pos+1;
                rows[p][f]=detail::diffusion_conductance(k[p],k[nb],.5*widths[pos],.5*widths[next])*area;
            } else if (!boundary) rows[p][f]=k[p]*area/widths[pos];
            else if (static_cast<int>(f)==boundary->direction) {
                const auto patch=axis==0 ? j : i;
                rows[p][f]=2*k[p]*area*optional(boundary->opening,patch,1)/widths[pos];
            }
        }
    }
    return rows;
}

struct Side {
    const ModelHFluid2D& f;
    const std::array<double,5>& cp;
    Rows diffusion;
    Vector exchange;
    Faces capacity, deferred;
    Side(const Mesh& mesh, const ModelHFluid2D& fluid)
        : f(fluid), cp(coefficients(f.fluid)), diffusion(diffusion_rows(mesh,f.conductivity,&f.boundary)),
          exchange(mesh.n), capacity{Vector(f.mass_x.size),Vector(f.mass_y.size)},
          deferred{Vector(f.mass_x.size),Vector(f.mass_y.size)} {
        for (std::size_t i=0; i<mesh.g.nx; ++i) for (std::size_t j=0; j<mesh.g.ny; ++j) {
            const auto p=mesh.cell(i,j);
            exchange[p]=f.hv[p]*mesh.volume(i,j);
        }
    }
    ArrayView<const double> mass(std::size_t axis) const { return axis==0 ? f.mass_x : f.mass_y; }
    double inlet(std::size_t patch) const { return optional(f.boundary.profile,patch,f.boundary.inlet_temperature); }
    double opening(std::size_t patch) const { return optional(f.boundary.opening,patch,1); }
};

void faces(const Mesh& mesh, Side& side, ArrayView<const double> t) {
    const auto& g=mesh.g;
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
            if (pos>0 && pos<count && u>0 && u+1<count) {
                const auto stride=axis==0 ? g.ny : 1;
                inc=increment(t[up-stride],temperature,t[up+stride],.5*(width[u-1]+width[u]),
                              .5*(width[u]+width[u+1]),(mass>=0 ? .5 : -.5)*width[u]);
            }
            if (axis==dir/2 && pos==(dir%2==0 ? 0 : count)) {
                const auto patch=axis==0 ? j : i;
                if (side.opening(patch)>0 && (dir%2==0 ? mass : -mass)>0) temperature=side.inlet(patch);
            }
            const double x=temperature-side.cp[3], cp=side.cp[0]+side.cp[1]*x+side.cp[2]*x*x;
            side.capacity[axis][p]=mass*cp;
            side.deferred[axis][p]=mass*(enthalpy(temperature+inc,side.cp)-cp*temperature);
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

double fluid_row(const Mesh& mesh, const Side& s, ArrayView<double> t,
                 ArrayView<double> solid, std::size_t i, std::size_t j) {
    const auto p=mesh.cell(i,j);
    double diagonal=s.exchange[p], rhs=diagonal*solid[p];
    for (std::size_t f=0; f<4; ++f) {
        const auto axis=f/2, nb=mesh.neighbor(i,j,f);
        const auto fp=mesh.face(axis,i+(f==1),j+(f==3));
        const double sign=f%2==0 ? -1 : 1, cap=sign*s.capacity[axis][fp], outward=sign*s.mass(axis)[fp];
        rhs-=sign*s.deferred[axis][fp];
        double neighbor=t[nb], conductance=s.diffusion[p][f];
        if (nb==p && static_cast<int>(f)==s.f.boundary.direction) {
            const auto patch=axis==0 ? j : i;
            rhs+=conductance*s.inlet(patch);
            diagonal+=conductance;
            conductance=0;
            if (s.opening(patch)>0 && outward<0) neighbor=s.inlet(patch);
        }
        diagonal+=conductance+(outward>=0 ? cap : 0);
        rhs+=(conductance-(outward<0 ? cap : 0))*neighbor;
    }
    if (!std::isfinite(diagonal) || diagonal<=0 || !std::isfinite(rhs))
        throw std::domain_error("invalid model-h fluid equation");
    return t[p]+model_coefficients::model_h_relaxation*(rhs/diagonal-t[p]);
}
void update(ArrayView<double> t, std::size_t p, double value, double& change) {
    if (!std::isfinite(value)) throw std::domain_error("nonfinite model-h update");
    change=std::max(change,std::abs(value-t[p]));
    t[p]=value;
}

double sweeps(const Mesh& mesh, Side& a, Side& b, const Rows& ds,
              TemperatureStateView t, Vector& last_a, Vector& last_b,
              std::size_t count, bool red_black) {
    const auto& g=mesh.g;
    double change=0;
    for (std::size_t it=0; it<count; ++it) {
        last_a.assign(t.a.data,t.a.data+t.a.size);
        last_b.assign(t.b.data,t.b.data+t.b.size);
        faces(mesh,a,view(last_a)); faces(mesh,b,view(last_b));
        change=0;
        for (std::size_t color=0; color<(red_black ? 2U : 1U); ++color)
            for (std::size_t ii=0; ii<g.nx; ++ii) for (std::size_t jj=0; jj<g.ny; ++jj) {
                const auto i=!red_black && a.f.boundary.direction==1 ? g.nx-1-ii : ii;
                const auto j=!red_black && (b.f.boundary.direction==3
                    || (a.f.boundary.direction==3 && b.f.boundary.direction==0)) ? g.ny-1-jj : jj;
                if (red_black && (i+j)%2!=color) continue;
                const auto p=mesh.cell(i,j);
                update(t.a,p,fluid_row(mesh,a,t.a,t.solid,i,j),change);
                const auto& d=ds[p];
                const double diagonal=d[1]+d[0]+d[3]+d[2]+a.exchange[p]+b.exchange[p];
                const double rhs=d[1]*t.solid[mesh.neighbor(i,j,1)]+d[0]*t.solid[mesh.neighbor(i,j,0)]
                    +d[3]*t.solid[mesh.neighbor(i,j,3)]+d[2]*t.solid[mesh.neighbor(i,j,2)]
                    +a.exchange[p]*t.a[p]+b.exchange[p]*t.b[p];
                if (!std::isfinite(diagonal) || diagonal<=0 || !std::isfinite(rhs))
                    throw std::domain_error("invalid model-h solid equation");
                update(t.solid,p,rhs/diagonal,change);
                update(t.b,p,fluid_row(mesh,b,t.b,t.solid,i,j),change);
            }
        if (change<1e-10) break;
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
Vector conduction(const Mesh& mesh, ArrayView<const double> t, ArrayView<const double> k) {
    Faces flow{Vector((mesh.g.nx+1)*mesh.g.ny),Vector(mesh.g.nx*(mesh.g.ny+1))};
    const auto& g=mesh.g;
    for (std::size_t i=0; i<g.nx; ++i) for (std::size_t j=0; j<g.ny; ++j) {
        const auto p=mesh.cell(i,j);
        if (i+1<g.nx) {
            const auto nb=mesh.cell(i+1,j);
            const double r=.5*(g.dx[i]*k[nb]+g.dx[i+1]*k[p]);
            flow[0][mesh.face(0,i+1,j)]=(r>0 ? k[p]*k[nb]/r : 0)*g.dy[j]*(t[p]-t[nb]);
        }
        if (j+1<g.ny) {
            const auto nb=mesh.cell(i,j+1);
            const double r=.5*(g.dy[j]*k[nb]+g.dy[j+1]*k[p]);
            flow[1][mesh.face(1,i,j+1)]=(r>0 ? k[p]*k[nb]/r : 0)*g.dx[i]*(t[p]-t[nb]);
        }
    }
    Vector result(mesh.n);
    for (std::size_t i=0; i<g.nx; ++i) for (std::size_t j=0; j<g.ny; ++j)
        result[mesh.cell(i,j)]=-mesh.divergence(flow,i,j);
    return result;
}

ModelHAudit2D audit(const Mesh& mesh, Side& a, Side& b, ArrayView<const double> ks,
                   TemperatureStateView t, const Vector& last_a, const Vector& last_b) {
    ModelHAudit2D result{};
    result.finite=true; result.boundary_complete=true;
    result.solid_residual=conduction(mesh,view(t.solid),ks);
    Side* sides[]{&a,&b};
    const ArrayView<const double> temperature[]{view(t.a),view(t.b)}, snapshot[]{view(last_a),view(last_b)};
    for (std::size_t index=0; index<2; ++index) {
        auto& s=*sides[index]; auto& out=result.sides[index]; const auto temp=temperature[index];
        out.cp_coefficients=s.cp;
        faces(mesh,s,temp); out.h_faces=fluxes(mesh,s,temp);
        faces(mesh,s,snapshot[index]); const auto linear=fluxes(mesh,s,temp);
        out.residual=conduction(mesh,temp,s.f.conductivity); out.linearization_defect.resize(mesh.n);
        for (std::size_t i=0; i<mesh.g.nx; ++i) for (std::size_t j=0; j<mesh.g.ny; ++j) {
            const auto p=mesh.cell(i,j);
            const double exchange=s.f.hv[p]*(t.solid[p]-temp[p])*mesh.volume(i,j);
            const double div=mesh.divergence(out.h_faces,i,j);
            out.residual[p]=(-div+out.residual[p])+exchange;
            out.linearization_defect[p]=mesh.divergence(linear,i,j)-div;
            result.solid_residual[p]-=exchange; out.exchange+=exchange;
            const double mass=s.f.mass_x[mesh.face(0,i+1,j)]-s.f.mass_x[mesh.face(0,i,j)]
                             +s.f.mass_y[mesh.face(1,i,j+1)]-s.f.mass_y[mesh.face(1,i,j)];
            out.mass_net+=mass; out.mass_local_max=std::max(out.mass_local_max,std::abs(mass));
        }
        const auto dir=static_cast<std::size_t>(s.f.boundary.direction), npatch=dir<2 ? mesh.g.ny : mesh.g.nx;
        out.inlet_conduction_faces.resize(npatch);
        for (std::size_t patch=0; patch<npatch; ++patch) {
            const auto i=dir<2 ? (dir==0 ? 0 : mesh.g.nx-1) : patch;
            const auto j=dir>=2 ? (dir==2 ? 0 : mesh.g.ny-1) : patch;
            const auto p=mesh.cell(i,j);
            const double cross=dir<2 ? mesh.g.dy[j] : mesh.g.dx[i], width=dir<2 ? mesh.g.dx[i] : mesh.g.dy[j];
            const double value=2*s.f.conductivity[p]*cross*s.opening(patch)/width*(s.inlet(patch)-temp[p]);
            out.inlet_conduction_faces[patch]=value; out.residual[p]+=value; out.inlet_conduction+=value;
        }
        out.boundary_mass_out=boundaries(mesh,s.f.mass_x,s.f.mass_y);
        out.boundary_h_out=boundaries(mesh,view(out.h_faces[0]),view(out.h_faces[1]));
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
              ArrayView<const double> ks, TemperatureStateView t, const ModelHControl2D& c) {
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
    for (std::size_t i=0; i<3; ++i) {
        for (std::size_t j=i+1; j<3; ++j) disjoint(view(states[i]),view(states[j]));
        for (auto input:{g.dx,g.dy,g.dz,ks}) disjoint(view(states[i]),input);
    }
    for (const auto* f:{&a,&b}) {
        coefficients(f->fluid);
        coefficient(f->conductivity,n); coefficient(f->hv,n);
        check(f->mass_x,(g.nx+1)*g.ny); check(f->mass_y,g.nx*(g.ny+1));
        const auto& bc=f->boundary;
        if (bc.direction<0 || bc.direction>3 || !std::isfinite(bc.inlet_temperature)
            || bc.inlet_temperature<=0 || bc.capacity_flux.size)
            throw std::invalid_argument("invalid model-h boundary");
        const auto count=bc.direction<2 ? g.ny : g.nx;
        if (bc.profile.size) coefficient(bc.profile,count,true);
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
                              TemperatureStateView t, const ModelHControl2D& c) {
    validate(g,a,b,ks,t,c);
    ModelHResult2D result{};
    result.stop=TemperatureStop::budget_exhausted;
    result.q_b=std::numeric_limits<double>::quiet_NaN();
    const auto cancelled=[&] { return c.cancel && c.cancel(c.context); };
    if (cancelled()) { result.stop=TemperatureStop::cancelled; return result; }
    if (!c.warm_start) {
        std::fill_n(t.a.data,t.a.size,a.boundary.inlet_temperature);
        std::fill_n(t.b.data,t.b.size,b.boundary.inlet_temperature);
        std::fill_n(t.solid.data,t.solid.size,.5*(a.boundary.inlet_temperature+b.boundary.inlet_temperature));
    }
    result.last_a.assign(t.a.data,t.a.data+t.a.size); result.last_b.assign(t.b.data,t.b.data+t.b.size);
    const Mesh mesh{g,g.nx*g.ny};
    Side side_a(mesh,a), side_b(mesh,b);
    const auto ds=diffusion_rows(mesh,ks,nullptr);
    auto previous=pack(t);
    double previous_q=0;
    bool have_q=false;
    // The cancellation exception never escapes the public C++ driver.
    struct Cancelled {};
    const auto step=[&](std::size_t count) {
        if (cancelled()) throw Cancelled{};
        const double change=sweeps(mesh,side_a,side_b,ds,t,result.last_a,result.last_b,count,c.red_black);
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
                    auto before=pack(t);
                    const auto n=std::min<std::size_t>(25,count-done);
                    result.residual=step(n); done+=n;
                    auto picard=pack(t);
                    accelerator.push(std::move(before),picard);
                    Eigen::VectorXd candidate;
                    if (!accelerator.candidate(picard,candidate) || count-done<2) continue;
                    const double picard_residual=step(1);
                    picard=pack(t);
                    const auto saved_a=result.last_a, saved_b=result.last_b;
                    restore(t,candidate);
                    const double candidate_residual=step(1); done+=2;
                    if (std::isfinite(candidate_residual) && candidate_residual<=picard_residual)
                        result.residual=candidate_residual;
                    else {
                        restore(t,picard); result.last_a=saved_a; result.last_b=saved_b;
                        result.residual=picard_residual;
                    }
                }
            } else result.residual=step(count);
            result.audit_available=false;
            result.iterations+=count;
            if (c.progress) c.progress(c.context,result.iterations,c.max_iterations);
            if (cancelled()) throw Cancelled{};
            double q=0;
            for (std::size_t i=0; i<g.nx; ++i) for (std::size_t j=0; j<g.ny; ++j) {
                const auto p=mesh.cell(i,j);
                q+=b.hv[p]*(t.solid[p]-t.b[p])*mesh.volume(i,j);
            }
            result.q_b=q;
            const auto current=pack(t);
            if (have_q && std::abs(q-previous_q)/std::max({std::abs(q),std::abs(previous_q),1.0})<c.q_relative_tolerance
                && (current-previous).cwiseAbs().maxCoeff()<.01) {
                result.audit=audit(mesh,side_a,side_b,ks,t,result.last_a,result.last_b);
                result.audit_available=true;
                result.finishing_checks.push_back({result.iterations,result.audit.passed,result.audit.equations_ok});
                if (result.audit.passed) result.stop=TemperatureStop::converged;
                if (result.audit.passed || !result.audit.boundary_complete) break;
            }
            previous_q=q; have_q=true; previous=current;
        }
    } catch (const Cancelled&) {
        result.stop=TemperatureStop::cancelled;
        result.audit_available=false; result.q_b=std::numeric_limits<double>::quiet_NaN();
        return result;
    }
    if (!result.audit_available) {
        result.audit=audit(mesh,side_a,side_b,ks,t,result.last_a,result.last_b);
        result.audit_available=true;
    }
    return result;
}
}  // namespace tpmshx
