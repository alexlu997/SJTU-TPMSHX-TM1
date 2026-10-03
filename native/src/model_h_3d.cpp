#include "tpmshx/model_h_3d.hpp"
#include "model_h_common.hpp"

namespace tpmshx {
namespace {
using namespace model_h_common;
using Vector=std::vector<double>;
using Coordinate=std::array<std::size_t,3>;
using Faces=std::array<Vector,3>;
using Rows=std::vector<std::array<double,6>>;
// The independent audit traverses equations in E,W,N,S,T,B order.
// The sweep below preserves the original Numba fastmath operation order with
// explicit FMA. Compile this translation unit without implicit contraction:
// changing last-bit rounding can change Anderson candidates on refined grids.
constexpr std::array<std::size_t,6> order{1,0,3,2,5,4};

struct Mesh {
    const GridView& g;
    std::size_t n;
    Coordinate counts, strides;
    std::array<ArrayView<const double>,3> widths;
    explicit Mesh(const GridView& grid):g(grid),n(grid.nx*grid.ny*grid.nz),
        counts{g.nx,g.ny,g.nz},strides{g.ny*g.nz,g.nz,1},widths{g.dx,g.dy,g.dz} {}
    std::size_t cell(const Coordinate& c) const { return (c[0]*g.ny+c[1])*g.nz+c[2]; }
    std::size_t face(std::size_t axis, const Coordinate& c) const {
        return (c[0]*(g.ny+(axis==1))+c[1])*(g.nz+(axis==2))+c[2];
    }
    Coordinate point(std::size_t p) const { return {p/(g.ny*g.nz),(p/g.nz)%g.ny,p%g.nz}; }
    std::size_t neighbor(const Coordinate& c, std::size_t f) const {
        const auto p=cell(c),axis=f/2;
        if (f%2==0) return c[axis]>0 ? p-strides[axis] : p;
        return c[axis]+1<counts[axis] ? p+strides[axis] : p;
    }
    std::size_t patch(std::size_t axis, const Coordinate& c) const {
        if (axis==0) return c[1]*g.nz+c[2];
        if (axis==1) return c[0]*g.nz+c[2];
        return c[0]*g.ny+c[1];
    }
    double volume(const Coordinate& c) const { return g.dx[c[0]]*g.dy[c[1]]*g.dz[c[2]]; }
    double area(std::size_t axis, const Coordinate& c) const {
        if (axis==0) return g.dy[c[1]]*g.dz[c[2]];
        if (axis==1) return g.dx[c[0]]*g.dz[c[2]];
        return g.dx[c[0]]*g.dy[c[1]];
    }
    double divergence(const Faces& faces, const Coordinate& c) const {
        Coordinate east=c,north=c,top=c; ++east[0]; ++north[1]; ++top[2];
        // Numba's array-expression kernel accumulates z, x, y by sign.
        return (faces[2][face(2,top)]+faces[0][face(0,east)]+faces[1][face(1,north)])
             - (faces[2][face(2,c)]+faces[0][face(0,c)]+faces[1][face(1,c)]);
    }
};

Rows diffusion_rows(const Mesh& mesh, ArrayView<const double> k, bool solid, bool fluid_b=false) {
    Rows rows(mesh.n);
    for (std::size_t p=0; p<mesh.n; ++p) {
        const auto c=mesh.point(p);
        for (std::size_t f=0; f<6; ++f) {
            const auto axis=f/2,nb=mesh.neighbor(c,f),pos=c[axis];
            if (nb!=p) {
                const auto next=f%2==0 ? pos-1 : pos+1;
                const double width=mesh.widths[axis][pos],neighbor_width=mesh.widths[axis][next];
                // The retained A/solid and B kernels contract opposite products
                // on positive faces. Keep those original rounding decisions.
                const double resistance=f%2 && !fluid_b
                    ? std::fma(neighbor_width,k[p],k[nb]*width)
                    : std::fma(width,k[nb],k[p]*neighbor_width);
                rows[p][f]=(k[p]<=0 || k[nb]<=0 ? 0.0 : k[p]*k[nb]/(.5*resistance))*mesh.area(axis,c);
            } else if (solid) rows[p][f]=k[p]*mesh.area(axis,c)/mesh.widths[axis][pos];
        }
    }
    return rows;
}
struct Side {
    const ModelHFluid3D& f;
    const bool fluid_b;
    const std::array<double,5>& cp;
    std::array<ArrayView<const double>,3> mass;
    Rows diffusion;
    Faces capacity,deferred;
    Side(const Mesh& mesh, const ModelHFluid3D& fluid, bool fluid_b=false):f(fluid),fluid_b(fluid_b),cp(coefficients(f.fluid)),
        mass{f.mass_x,f.mass_y,f.mass_z},diffusion(diffusion_rows(mesh,f.conductivity,false,fluid_b)),
        capacity{Vector(f.mass_x.size),Vector(f.mass_y.size),Vector(f.mass_z.size)},
        deferred{Vector(f.mass_x.size),Vector(f.mass_y.size),Vector(f.mass_z.size)} {}
    double inlet(std::size_t patch) const { return optional(f.boundary.profile,patch,f.boundary.inlet_temperature); }
    double opening(std::size_t patch) const { return optional(f.boundary.opening,patch,1); }
};

void faces(const Mesh& mesh, Side& side, ArrayView<const double> temperature) {
    const auto dir=static_cast<std::size_t>(side.f.boundary.direction);
    for (std::size_t axis=0; axis<3; ++axis) {
        auto extent=mesh.counts; ++extent[axis];
        const auto widths=mesh.widths[axis];
        for (std::size_t i=0; i<extent[0]; ++i) for (std::size_t j=0; j<extent[1]; ++j)
            for (std::size_t k=0; k<extent[2]; ++k) {
                const Coordinate c{i,j,k}; const auto p=mesh.face(axis,c),pos=c[axis],count=mesh.counts[axis];
                const double mass=side.mass[axis][p];
                const auto u=mass>=0 ? (pos==0 ? 0 : pos-1) : std::min(pos,count-1);
                auto up=c; up[axis]=u; const auto up_index=mesh.cell(up);
                double t=temperature[up_index],inc=0;
                if (pos>0 && pos<count && u>0 && u+1<count) {
                    inc=increment(temperature[up_index-mesh.strides[axis]],t,
                        temperature[up_index+mesh.strides[axis]],.5*(widths[u-1]+widths[u]),
                        .5*(widths[u]+widths[u+1]),(mass>=0 ? .5 : -.5)*widths[u]);
                }
                if (axis==dir/2 && pos==(dir%2==0 ? 0 : count)) {
                    const auto patch=mesh.patch(axis,c);
                    if (side.opening(patch)>0 && (dir%2==0 ? mass : -mass)>0) t=side.inlet(patch);
                }
                const double x=t-side.cp[3],cp=std::fma(std::fma(x,side.cp[2],side.cp[1]),x,side.cp[0]);
                side.capacity[axis][p]=mass*cp;
                side.deferred[axis][p]=mass*std::fma(-cp,t,enthalpy(t+inc,side.cp));
            }
    }
}

struct FluidRow { double diagonal, rhs; };
FluidRow fluid_row(const Mesh& mesh, const Side& side, ArrayView<const double> t,
                   ArrayView<const double> solid, const Coordinate& c) {
    const auto p=mesh.cell(c),dir=static_cast<std::size_t>(side.f.boundary.direction);
    std::array<double,6> a{},neighbor{},capacity{};
    for (std::size_t f=0; f<6; ++f) {
        const auto axis=f/2,nb=mesh.neighbor(c,f);
        auto fc=c; if (f%2) ++fc[axis];
        const double cap=side.capacity[axis][mesh.face(axis,fc)]; capacity[f]=cap;
        a[f]=side.diffusion[p][f]+std::max(f%2 ? -cap : cap,0.0);
        neighbor[f]=t[nb];
        if (nb==p && f==dir) {
            const auto patch=mesh.patch(axis,c); const double opening=side.opening(patch);
            if (opening>0) {
                const auto low=axis==0 ? 1 : 0,high=axis==2 ? 1 : 2;
                const double wl=mesh.widths[low][c[low]],wh=mesh.widths[high][c[high]];
                const double conductivity=side.f.conductivity[p];
                a[f]+=(side.fluid_b ? ((conductivity*wl)*opening)*(wh+wh)
                                   : (conductivity*wh)*((wl+wl)*opening))/mesh.widths[axis][c[axis]];
                neighbor[f]=side.inlet(patch);
            }
        }
    }
    const double volume=mesh.volume(c),hv=side.f.hv[p]*volume;
    const double net=((capacity[1]+capacity[3])+capacity[5])-((capacity[0]+capacity[2])+capacity[4]);
    const double diagonal=((a[3]+hv)+(net+(a[1]+a[0])))+((a[2]+a[5])+a[4]);
    double rhs=a[1]*neighbor[1];
    for (auto f:std::array<std::size_t,5>{0,3,2,5,4}) rhs=std::fma(a[f],neighbor[f],rhs);
    rhs-=mesh.divergence(side.deferred,c);
    rhs=std::fma(hv,solid[p],rhs);
    rhs=std::fma(optional(side.f.source,p,0),volume,rhs);
    return {diagonal,rhs};
}
void update(ArrayView<double> t, std::size_t p, double value, double alpha, double& change) {
    const double increment=alpha*(value-t[p]);
    const double updated=t[p]+increment;
    if (!std::isfinite(updated)) throw std::domain_error("nonfinite 3D model-h row");
    change=std::max(change,std::abs(increment)); t[p]=updated;
}

double sweeps(const Mesh& mesh, Side& a, Side& b, const Rows& ds, ArrayView<const double> source_s,
              TemperatureStateView t, const ModelHControl3D& control, std::size_t count) {
    const double alpha_a=std::min(control.alpha_a,model_coefficients::model_h_relaxation);
    const double alpha_b=std::min(control.alpha_b,model_coefficients::model_h_relaxation);
    double change=0;
    for (std::size_t it=0; it<count; ++it) {
        faces(mesh,a,view(t.a)); faces(mesh,b,view(t.b)); change=0;
        for (std::size_t color=0; color<(control.red_black ? 2U : 1U); ++color)
            for (std::size_t ii=0; ii<mesh.g.nx; ++ii) for (std::size_t jj=0; jj<mesh.g.ny; ++jj)
                for (std::size_t kk=0; kk<mesh.g.nz; ++kk) {
                    const auto i=!control.red_black && a.f.boundary.direction==1 ? mesh.g.nx-1-ii : ii;
                    const auto j=!control.red_black && b.f.boundary.direction==3 ? mesh.g.ny-1-jj : jj;
                    const auto k=!control.red_black && a.f.boundary.direction==5 ? mesh.g.nz-1-kk : kk;
                    if (control.red_black && (i+j+k)%2!=color) continue;
                    const Coordinate c{i,j,k}; const auto p=mesh.cell(c);
                    const auto row_a=fluid_row(mesh,a,view(t.a),view(t.solid),c);
                    update(t.a,p,row_a.rhs/std::max(row_a.diagonal,1e-30),alpha_a,change);
                    const auto& d=ds[p]; const double volume=mesh.volume(c),ha=a.f.hv[p]*volume,hb=b.f.hv[p]*volume;
                    const double diagonal=((hb+ha)+d[1])+(d[0]+d[3])+((d[2]+d[5])+d[4]);
                    double rhs=ha*t.a[p];
                    for (auto f:std::array<std::size_t,6>{5,2,3,0,1,4}) rhs=std::fma(d[f],t.solid[mesh.neighbor(c,f)],rhs);
                    rhs=std::fma(hb,t.b[p],rhs);
                    rhs=std::fma(optional(source_s,p,0),volume,rhs);
                    if (!std::isfinite(diagonal) || diagonal<=0) throw std::domain_error("invalid 3D model-h solid row");
                    update(t.solid,p,rhs/diagonal,control.alpha_solid,change);
                    const auto row_b=fluid_row(mesh,b,view(t.b),view(t.solid),c);
                    update(t.b,p,row_b.rhs/std::max(row_b.diagonal,1e-30),alpha_b,change);
                }
        if (change<1e-10) break;
    }
    return change;
}

ModelHAudit3D audit(const Mesh& mesh, Side& a, Side& b, ArrayView<const double> ks,
                   ArrayView<const double> source_s, TemperatureStateView t) {
    ModelHAudit3D result{};
    result.boundary_complete=true;
    result.solid_residual.resize(mesh.n);
    // No exterior self conductance in the independent physical audit.
    const auto ds=diffusion_rows(mesh,ks,false);
    for (std::size_t p=0; p<mesh.n; ++p) {
        const auto c=mesh.point(p); const auto& d=ds[p]; const double volume=mesh.volume(c);
        const double diagonal=d[1]+d[0]+d[3]+d[2]+d[5]+d[4];
        double residual=diagonal*t.solid[p];
        for (auto f:order) residual-=d[f]*t.solid[mesh.neighbor(c,f)];
        result.solid_residual[p]=residual-optional(source_s,p,0)*volume;
        result.explicit_source+=optional(source_s,p,0)*volume; result.volume+=volume;
    }
    Side* sides[]{&a,&b}; const ArrayView<const double> temperatures[]{view(t.a),view(t.b)};
    for (std::size_t index=0; index<2; ++index) {
        auto& side=*sides[index]; auto& out=result.sides[index]; const auto temp=temperatures[index];
        out.boundary_complete=true; out.cp_coefficients=side.cp;
        out.temperature_min=*std::min_element(temp.data,temp.data+temp.size);
        out.temperature_max=*std::max_element(temp.data,temp.data+temp.size);
        out.residual.resize(mesh.n); faces(mesh,side,temp);
        const auto dir=static_cast<std::size_t>(side.f.boundary.direction),inlet_axis=dir/2;
        out.inlet_diffusion.resize(mesh.n/mesh.counts[inlet_axis]);
        for (std::size_t f=0; f<6; ++f) out.boundaries[f].enthalpy_faces.resize(mesh.n/mesh.counts[f/2]);
        for (std::size_t p=0; p<mesh.n; ++p) {
            const auto c=mesh.point(p); const double volume=mesh.volume(c);
            const auto row=fluid_row(mesh,side,temp,view(t.solid),c);
            const double r=row.diagonal*temp[p]-row.rhs;
            out.residual[p]=r; out.residual_sum+=r; out.residual_max=std::max(out.residual_max,std::abs(r));
            const double exchange=side.f.hv[p]*volume*(t.solid[p]-temp[p]);
            out.exchange+=exchange; result.solid_residual[p]+=exchange;
            out.source+=optional(side.f.source,p,0)*volume;
            if (c[inlet_axis]==(dir%2==0 ? 0 : mesh.counts[inlet_axis]-1)) {
                const auto patch=mesh.patch(inlet_axis,c);
                const double value=2.0*side.f.conductivity[p]*mesh.area(inlet_axis,c)*side.opening(patch)
                    /mesh.widths[inlet_axis][c[inlet_axis]]*(side.inlet(patch)-temp[p]);
                out.inlet_diffusion[patch]=value; out.diffusion_in+=value;
            }
            for (std::size_t f=0; f<6; ++f) {
                const auto axis=f/2;
                if (c[axis]!=(f%2==0 ? 0 : mesh.counts[axis]-1)) continue;
                auto fc=c; if (f%2) ++fc[axis]; const auto fp=mesh.face(axis,fc),patch=mesh.patch(axis,c);
                const double sign=f%2==0 ? -1 : 1,mass=sign*side.mass[axis][fp];
                const bool inlet=f==dir && side.opening(patch)>0;
                const double up=(inlet && mass<0) ? side.inlet(patch) : temp[p];
                const double flux=sign*(side.capacity[axis][fp]*up+side.deferred[axis][fp]);
                auto& boundary=out.boundaries[f];
                boundary.mass_out+=mass; boundary.enthalpy_out+=flux; boundary.enthalpy_faces[patch]=flux;
                if (mass<0 && !inlet) { boundary.unknown_mass_in-=mass; ++boundary.unknown_inflow_count; }
                if (inlet && mass>=0) boundary.inlet_reverse_mass_out+=mass;
            }
        }
        for (const auto& boundary:out.boundaries) {
            out.mass_net+=boundary.mass_out; out.advective_in-=boundary.enthalpy_out;
            out.boundary_complete=out.boundary_complete && boundary.unknown_inflow_count==0;
        }
        out.numerical_external_in=out.advective_in+out.diffusion_in;
        out.normalization=std::max(std::abs(out.exchange),1.0);
        out.global_ratio=std::abs(out.residual_sum)/out.normalization;
        out.cell_ratio=out.residual_max*static_cast<double>(mesh.n)/out.normalization;
        result.numerical_external_in+=out.numerical_external_in; result.explicit_source+=out.source;
        result.boundary_complete=result.boundary_complete && out.boundary_complete;
        for (std::size_t metric=0; metric<2; ++metric) {
            const double value=metric==0 ? out.global_ratio : out.cell_ratio;
            result.gates[2*index+metric]=std::isfinite(value) && value>=0 && value<.01;
        }
    }
    for (std::size_t p=0; p<mesh.n; ++p) {
        const double r=result.solid_residual[p];
        result.solid_sum+=r; result.solid_max=std::max(result.solid_max,std::abs(r));
        result.full_residual_sum+=result.sides[0].residual[p]+result.sides[1].residual[p]+r;
    }
    result.telescoping_error=result.full_residual_sum+result.numerical_external_in+result.explicit_source;
    const double qa=result.sides[0].exchange,qb=result.sides[1].exchange;
    result.ltne_source_ratio=std::abs(qa+qb)/std::max({std::abs(qa),std::abs(qb),1e-30});
    result.gates[4]=std::isfinite(result.ltne_source_ratio) && result.ltne_source_ratio<.01;
    result.gates[5]=result.boundary_complete;
    result.passed=std::all_of(result.gates.begin(),result.gates.end(),[](bool passed) { return passed; });
    return result;
}

void validate(const GridView& g, const ModelHFluid3D& a, const ModelHFluid3D& b,
              ArrayView<const double> ks, ArrayView<const double> source_s,
              TemperatureStateView t, const ModelHControl3D& control) {
    const auto n=product(product(g.nx,g.ny),g.nz);
    if (g.nz<=1 || g.nx==std::numeric_limits<std::size_t>::max()
        || g.ny==std::numeric_limits<std::size_t>::max() || g.nz==std::numeric_limits<std::size_t>::max())
        throw std::invalid_argument("3D model-h requires nz>1 and valid extents");
    const Coordinate extents{product(product(g.nx+1,g.ny),g.nz),product(product(g.nx,g.ny+1),g.nz),
                             product(product(g.nx,g.ny),g.nz+1)};
    if (n>static_cast<std::size_t>(std::numeric_limits<Eigen::Index>::max())/3)
        throw std::invalid_argument("3D model-h state is too large");
    coefficient(g.dx,g.nx,true); coefficient(g.dy,g.ny,true); coefficient(g.dz,g.nz,true); coefficient(ks,n);
    if (source_s.size) check(source_s,n);
    if (!control.chunk_iterations || !std::isfinite(control.q_relative_tolerance) || control.q_relative_tolerance<0)
        throw std::invalid_argument("invalid 3D model-h control");
    for (double alpha:{control.alpha_a,control.alpha_solid,control.alpha_b})
        if (!std::isfinite(alpha) || alpha<=0 || alpha>1) throw std::invalid_argument("invalid model-h relaxation");
    const ArrayView<double> states[]{t.a,t.b,t.solid};
    for (std::size_t i=0; i<3; ++i) {
        check(states[i],n,control.warm_start);
        for (std::size_t j=i+1; j<3; ++j) disjoint(view(states[i]),view(states[j]));
        for (auto input:{g.dx,g.dy,g.dz,ks,source_s}) disjoint(view(states[i]),input);
    }
    if (a.fluid==Fluid::water && b.fluid==Fluid::water)
        throw std::invalid_argument("3D model-h supports symmetric AA/AW/WA");
    for (const auto* f:{&a,&b}) {
        coefficients(f->fluid); coefficient(f->conductivity,n); coefficient(f->hv,n);
        check(f->mass_x,extents[0]); check(f->mass_y,extents[1]); check(f->mass_z,extents[2]);
        if (f->source.size) check(f->source,n);
        const auto& bc=f->boundary;
        if (bc.direction<0 || bc.direction>5 || !std::isfinite(bc.inlet_temperature)
            || bc.inlet_temperature<=0 || bc.capacity_flux.size) throw std::invalid_argument("invalid 3D model-h boundary");
        const std::size_t counts[]{g.nx,g.ny,g.nz}; const auto count=n/counts[bc.direction/2];
        if (bc.profile.size) coefficient(bc.profile,count,true);
        if (bc.opening.size) {
            coefficient(bc.opening,count);
            for (std::size_t p=0; p<count; ++p)
                if (bc.opening[p]>1) throw std::invalid_argument("invalid 3D model-h opening");
        }
        for (auto state:states) for (auto input:{f->conductivity,f->hv,f->mass_x,f->mass_y,f->mass_z,f->source,bc.profile,bc.opening})
            disjoint(view(state),input);
    }
}
}  // namespace

ModelHResult3D solve_model_h_3d(const GridView& grid, const ModelHFluid3D& a,
                              const ModelHFluid3D& b, ArrayView<const double> ks,
                              ArrayView<const double> source_s, TemperatureStateView t,
                              const ModelHControl3D& control) {
    validate(grid,a,b,ks,source_s,t,control);
    ModelHResult3D result{}; result.stop=TemperatureStop::budget_exhausted;
    result.q_b=std::numeric_limits<double>::quiet_NaN();
    const auto cancelled=[&] { return control.cancel && control.cancel(control.context); };
    if (cancelled()) { result.stop=TemperatureStop::cancelled; return result; }
    if (!control.warm_start) {
        std::fill_n(t.a.data,t.a.size,a.boundary.inlet_temperature);
        std::fill_n(t.b.data,t.b.size,b.boundary.inlet_temperature);
        std::fill_n(t.solid.data,t.solid.size,.5*(a.boundary.inlet_temperature+b.boundary.inlet_temperature));
    }
    for (auto source:{a.source,b.source,source_s})
        for (std::size_t p=0; p<source.size; ++p) result.has_sources=result.has_sources || source[p]!=0;
    const Mesh mesh(grid); Side side_a(mesh,a),side_b(mesh,b,true); const auto ds=diffusion_rows(mesh,ks,true);
    auto previous=pack(t); double previous_q=0; bool have_q=false;
    struct Cancelled {};
    const auto step=[&](std::size_t count) {
        if (cancelled()) throw Cancelled{};
        const double change=sweeps(mesh,side_a,side_b,ds,source_s,t,control,count);
        if (cancelled()) throw Cancelled{};
        return change;
    };
    try {
        while (result.iterations<control.max_iterations) {
            if (cancelled()) throw Cancelled{};
            const auto count=std::min(control.chunk_iterations,control.max_iterations-result.iterations);
            if (control.accelerate) {
                Anderson accelerator; std::size_t done=0;
                while (done<count) {
                    auto before=pack(t); const auto n=std::min<std::size_t>(25,count-done);
                    result.residual=step(n); done+=n; auto picard=pack(t);
                    accelerator.push(std::move(before),picard); Eigen::VectorXd candidate;
                    if (!accelerator.candidate(picard,candidate) || count-done<2) continue;
                    const double ordinary=step(1); picard=pack(t); restore(t,candidate);
                    const double trial=step(1); done+=2;
                    if (std::isfinite(trial) && trial<=ordinary) result.residual=trial;
                    else { restore(t,picard); result.residual=ordinary; }
                }
            } else result.residual=step(count);
            result.audit_available=false; result.iterations+=count;
            if (control.progress) control.progress(control.context,result.iterations,control.max_iterations);
            if (cancelled()) throw Cancelled{};
            double q=0;
            for (std::size_t p=0; p<mesh.n; ++p) q+=b.hv[p]*(t.solid[p]-t.b[p])*mesh.volume(mesh.point(p));
            result.q_b=q; const auto current=pack(t);
            if (have_q && std::abs(q-previous_q)/std::max({std::abs(q),std::abs(previous_q),1.0})<control.q_relative_tolerance
                && (current-previous).cwiseAbs().maxCoeff()<.01) {
                if (result.has_sources) { result.stop=TemperatureStop::converged; break; }
                result.audit=audit(mesh,side_a,side_b,ks,source_s,t); result.audit_available=true;
                result.finishing_checks.push_back({result.iterations,result.audit.gates});
                if (result.audit.passed) result.stop=TemperatureStop::converged;
                if (result.audit.passed || !result.audit.boundary_complete) break;
            }
            previous_q=q; have_q=true; previous=current;
        }
    } catch (const Cancelled&) {
        result.stop=TemperatureStop::cancelled; result.audit_available=false;
        result.q_b=std::numeric_limits<double>::quiet_NaN(); return result;
    }
    if (!result.audit_available) {
        result.audit=audit(mesh,side_a,side_b,ks,source_s,t); result.audit_available=true;
    }
    return result;
}
}  // namespace tpmshx
