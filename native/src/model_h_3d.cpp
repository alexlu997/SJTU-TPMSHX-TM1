#include "tpmshx/model_h_3d.hpp"
#include "model_h_common.hpp"
#include "energy_fv_rows.hpp"

namespace tpmshx {
namespace {
using namespace model_h_common;
using Vector=std::vector<double>;
using Coordinate=std::array<std::size_t,3>;
using Faces=std::array<Vector,3>;
using Diffusion=std::array<std::vector<detail::EnergyDiffusion>,3>;
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
    std::size_t patch(std::size_t axis, const Coordinate& c) const {
        if (axis==0) return c[1]*g.nz+c[2];
        if (axis==1) return c[0]*g.nz+c[2];
        return c[0]*g.ny+c[1];
    }
    double volume(const Coordinate& c) const { return g.dx[c[0]]*g.dy[c[1]]*g.dz[c[2]]; }

};

struct Side {
    const ModelHFluid3D& f;
    const std::array<double,5>* cp;
    bool second_order,strict_boundary;
    std::array<ArrayView<const double>,3> mass;
    Faces capacity,deferred;
    Side(const Mesh&, const ModelHFluid3D& fluid,bool order,bool solved,bool strict)
        :f(fluid),cp(solved ? &coefficients(f.fluid) : nullptr),second_order(order),strict_boundary(strict),
        mass{f.mass_x,f.mass_y,f.mass_z},
        capacity{Vector(f.mass_x.size),Vector(f.mass_y.size),Vector(f.mass_z.size)},
        deferred{Vector(f.mass_x.size),Vector(f.mass_y.size),Vector(f.mass_z.size)} {}
    EnergyPhase energy() const {
        return {f.conductivity,f.hv,f.source,
            {{view(capacity[0]),view(capacity[1]),view(capacity[2])},
             {view(deferred[0]),view(deferred[1]),view(deferred[2])}},f.boundary,true,strict_boundary};
    }
    PhysicalEnergyPhase physical() const {
        return {f.conductivity,f.hv,f.source,
            {view(capacity[0]),view(capacity[1]),view(capacity[2])},
            {view(deferred[0]),view(deferred[1]),view(deferred[2])},f.boundary,true,strict_boundary};
    }
    double inlet(std::size_t patch) const { return optional(f.boundary.profile,patch,f.boundary.inlet_temperature); }
    double opening(std::size_t patch) const { return optional(f.boundary.opening,patch,1); }
};

template<bool physical=false>
void faces(const Mesh& mesh, Side& side, ArrayView<const double> temperature) {
    const auto& coefficients=*side.cp;
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
                if (side.second_order && pos>0 && pos<count && u>0 && u+1<count) {
                    inc=increment(temperature[up_index-mesh.strides[axis]],t,
                        temperature[up_index+mesh.strides[axis]],.5*(widths[u-1]+widths[u]),
                        .5*(widths[u]+widths[u+1]),(mass>=0 ? .5 : -.5)*widths[u]);
                } else if (side.strict_boundary && side.second_order && count>1
                           && !(pos==0 && mass>0) && !(pos==count && mass<0)) {
                    const bool low=u==0;
                    const auto neighbor=low ? u+1 : u-1;
                    auto boundary=c;boundary[axis]=low ? 0 : count;
                    const double boundary_mass=side.mass[axis][mesh.face(axis,boundary)];
                    const auto patch=mesh.patch(axis,c);
                    const bool known=axis==dir/2 && dir%2==(low ? 0U : 1U)
                        && side.opening(patch)>0 && (low ? boundary_mass : -boundary_mass)>0;
                    auto near=c;near[axis]=neighbor;
                    inc=boundary_increment(t,temperature[mesh.cell(near)],.5*(widths[u]+widths[neighbor]),
                        known ? side.inlet(patch) : 0.,.5*widths[u],known,low,
                        (mass>=0 ? .5 : -.5)*widths[u]);
                }
                if (axis==dir/2 && pos==(dir%2==0 ? 0 : count)) {
                    const auto patch=mesh.patch(axis,c);
                    if (side.opening(patch)>0 && (dir%2==0 ? mass : -mass)>0) t=side.inlet(patch);
                }
                const double x=t-coefficients[3],cp=std::fma(std::fma(x,coefficients[2],coefficients[1]),x,coefficients[0]);
                side.capacity[axis][p]=mass*cp;
                if constexpr (physical)
                    side.deferred[axis][p]=mass*enthalpy(t+inc,coefficients);
                else side.deferred[axis][p]=mass*std::fma(-cp,t,enthalpy(t+inc,coefficients));
            }
    }
}

void update(ArrayView<double> t, Vector& carry, std::size_t p, double defect_step, double alpha, double& change) {
    const double increment=alpha*defect_step;
    const double updated=detail::compensated_energy_increment(t[p],increment,carry[p]);
    change=std::max({change,std::abs(increment),std::abs(updated-t[p])}); t[p]=updated;
}

double sweeps(const Mesh& mesh, Side& a, Side& b, ArrayView<const double> ks, ArrayView<const double> source_s,
              TemperatureStateView t, const ModelHControl3D& control, std::size_t count,
              std::size_t line_axis,detail::EnergyLineScratch& line_work,std::array<Vector,3>& carry,
              const Diffusion& diffusion,bool solve_b) {
    const detail::EnergyMesh energy_mesh(mesh.g);
    const auto phase_a=a.energy(),phase_b=b.energy();
    const double alpha_a=std::min(control.alpha_a,model_coefficients::model_h_relaxation);
    const double alpha_b=std::min(control.alpha_b,model_coefficients::model_h_relaxation);
    double change=0;
    for (std::size_t it=0; it<count; ++it) {
        faces(mesh,a,view(t.a));
        if (solve_b) faces(mesh,b,view(t.b));
        change=0;
        if (!control.red_black) {
            for (std::size_t ordinal=0; ordinal<energy_mesh.line_count(line_axis); ++ordinal) {
                const auto start=energy_mesh.line_start(line_axis,ordinal);
                change=std::max(change,detail::fluid_energy_line(energy_mesh,phase_a,t.a,view(t.solid),
                    line_axis,start,alpha_a,line_work,{}, {carry[0].data(),carry[0].size()},diffusion[0].data()));
                change=std::max(change,detail::solid_energy_line(energy_mesh,ks,a.f.hv,b.f.hv,
                    view(t.a),view(t.b),t.solid,source_s,line_axis,start,control.alpha_solid,line_work,
                    {carry[2].data(),carry[2].size()},diffusion[2].data()));
                if (solve_b)
                    change=std::max(change,detail::fluid_energy_line(energy_mesh,phase_b,t.b,view(t.solid),
                        line_axis,start,alpha_b,line_work,{}, {carry[1].data(),carry[1].size()},diffusion[1].data()));
            }
            if (change==0.) break;
            continue;
        }
        for (std::size_t color=0; color<2; ++color)
            for (std::size_t ii=0; ii<mesh.g.nx; ++ii) for (std::size_t jj=0; jj<mesh.g.ny; ++jj)
                for (std::size_t kk=0; kk<mesh.g.nz; ++kk) {
                    const auto i=ii,j=jj,k=kk;
                    if ((i+j+k)%2!=color) continue;
                    const Coordinate c{i,j,k}; const auto p=mesh.cell(c);
                    const auto row_a=detail::fluid_energy_defect_row(energy_mesh,phase_a,view(t.a),view(t.solid),p,0.,&diffusion[0][p]);
                    update(t.a,carry[0],p,row_a.rhs/std::max(row_a.diagonal,1e-30),alpha_a,change);
                    const auto row_s=detail::solid_energy_defect_row(energy_mesh,ks,a.f.hv,b.f.hv,
                        view(t.a),view(t.b),view(t.solid),source_s,p,&diffusion[2][p]);
                    if (!std::isfinite(row_s.diagonal) || row_s.diagonal<=0)
                        throw std::domain_error("invalid 3D model-h solid row");
                    update(t.solid,carry[2],p,row_s.rhs/row_s.diagonal,control.alpha_solid,change);
                    if (solve_b) {
                        const auto row_b=detail::fluid_energy_defect_row(energy_mesh,phase_b,view(t.b),view(t.solid),p,0.,&diffusion[1][p]);
                        update(t.b,carry[1],p,row_b.rhs/std::max(row_b.diagonal,1e-30),alpha_b,change);
                    }
                }
        if (change==0.) break;
    }
    return change;
}

ModelHAudit3D audit(const Mesh& mesh, Side& a, Side& b, ArrayView<const double> ks,
                   ArrayView<const double> source_s, TemperatureStateView t) {
    ModelHAudit3D result{};
    faces(mesh,a,view(t.a)); faces(mesh,b,view(t.b));
    auto ledger=energy_physical_audit(mesh.g,a.energy(),b.energy(),ks,t,source_s);
    result.boundary_complete=ledger.boundary_complete;
    result.solid_residual=std::move(ledger.residual[2]);
    // This public 3D certificate uses D*T-RHS; the common ledger uses RHS-D*T.
    for (double& residual:result.solid_residual) residual=-residual;
    result.explicit_source=ledger.source_integral[2];
    for (std::size_t p=0; p<mesh.n; ++p) result.volume+=mesh.volume(mesh.point(p));
    Side* sides[]{&a,&b}; const ArrayView<const double> temperatures[]{view(t.a),view(t.b)};
    for (std::size_t index=0; index<2; ++index) {
        auto& side=*sides[index]; auto& out=result.sides[index]; const auto temp=temperatures[index];
        out.boundary_complete=true; out.cp_coefficients=*side.cp;
        out.temperature_min=*std::min_element(temp.data,temp.data+temp.size);
        out.temperature_max=*std::max_element(temp.data,temp.data+temp.size);
        out.residual=std::move(ledger.residual[index]);
        for (double& residual:out.residual) residual=-residual;
        const auto dir=static_cast<std::size_t>(side.f.boundary.direction),inlet_axis=dir/2;
        out.inlet_diffusion.resize(mesh.n/mesh.counts[inlet_axis]);
        for (std::size_t f=0; f<6; ++f)
            out.boundaries[f].enthalpy_faces=std::move(ledger.advective_out[index][f]);
        for (std::size_t p=0; p<mesh.n; ++p) {
            const auto c=mesh.point(p); const double volume=mesh.volume(c);
            const double r=out.residual[p]; out.residual_sum+=r; out.residual_max=std::max(out.residual_max,std::abs(r));
            const double exchange=side.f.hv[p]*volume*(t.solid[p]-temp[p]);
            out.exchange+=exchange;
            out.source+=optional(side.f.source,p,0)*volume;
            if (c[inlet_axis]==(dir%2==0 ? 0 : mesh.counts[inlet_axis]-1)) {
                const auto patch=mesh.patch(inlet_axis,c);
                const double value=-ledger.diffusive_out[index][dir][patch];
                out.inlet_diffusion[patch]=value; out.diffusion_in+=value;
            }
            for (std::size_t f=0; f<6; ++f) {
                const auto axis=f/2;
                if (c[axis]!=(f%2==0 ? 0 : mesh.counts[axis]-1)) continue;
                auto fc=c; if (f%2) ++fc[axis]; const auto fp=mesh.face(axis,fc),patch=mesh.patch(axis,c);
                const double sign=f%2==0 ? -1 : 1,mass=sign*side.mass[axis][fp];
                const bool inlet=f==dir && side.opening(patch)>0;
                auto& boundary=out.boundaries[f];
                const double flux=boundary.enthalpy_faces[patch];
                boundary.mass_out+=mass; boundary.enthalpy_out+=flux;
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
              TemperatureStateView t, const ModelHControl3D& control,
              ArrayView<const double> prescribed_b) {
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
    if (prescribed_b.size) {
        if (!control.strict_energy_balance)
            throw std::invalid_argument("prescribed model-h B requires strict energy mode");
        check(prescribed_b,n);
        for (auto state:states) disjoint(view(state),prescribed_b);
    }
    for (std::size_t i=0; i<3; ++i) {
        check(states[i],n,control.warm_start);
        for (std::size_t j=i+1; j<3; ++j) disjoint(view(states[i]),view(states[j]));
        for (auto input:{g.dx,g.dy,g.dz,ks,source_s}) disjoint(view(states[i]),input);
    }
    if (a.fluid==Fluid::water && b.fluid==Fluid::water && !control.strict_energy_balance)
        throw std::invalid_argument("3D model-h supports symmetric AA/AW/WA");
    for (const auto* f:{&a,&b}) {
        const bool solved=f==&a || !prescribed_b.size;
        if (solved) coefficients(f->fluid);
        coefficient(f->conductivity,n); coefficient(f->hv,n);
        check(f->mass_x,extents[0],solved); check(f->mass_y,extents[1],solved); check(f->mass_z,extents[2],solved);
        if (f->source.size) check(f->source,n);
        const auto& bc=f->boundary;
        if (bc.direction<0 || bc.direction>5 || !std::isfinite(bc.inlet_temperature)
            || (solved && bc.inlet_temperature<=0) || bc.capacity_flux.size) throw std::invalid_argument("invalid 3D model-h boundary");
        const std::size_t counts[]{g.nx,g.ny,g.nz}; const auto count=n/counts[bc.direction/2];
        if (bc.profile.size) {
            if (solved) coefficient(bc.profile,count,true);
            else check(bc.profile,count);
        }
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
                              const ModelHControl3D& control,
                              ArrayView<const double> prescribed_b,
                              PhysicalHeatLedger* physical_audit) {
    validate(grid,a,b,ks,source_s,t,control,prescribed_b);
    const bool solve_b=!prescribed_b.size;
    ModelHResult3D result{}; result.stop=TemperatureStop::budget_exhausted;
    result.q_b=std::numeric_limits<double>::quiet_NaN();
    const auto cancelled=[&] { return control.cancel && control.cancel(control.context); };
    if (cancelled()) { result.stop=TemperatureStop::cancelled; return result; }
    if (!control.warm_start) {
        std::fill_n(t.a.data,t.a.size,a.boundary.inlet_temperature);
        if (solve_b) std::fill_n(t.b.data,t.b.size,b.boundary.inlet_temperature);
        std::fill_n(t.solid.data,t.solid.size,.5*(a.boundary.inlet_temperature+b.boundary.inlet_temperature));
    }
    if (!solve_b) std::copy_n(prescribed_b.data,prescribed_b.size,t.b.data);
    for (auto source:{a.source,solve_b ? b.source : ArrayView<const double>{},source_s})
        for (std::size_t p=0; p<source.size; ++p) result.has_sources=result.has_sources || source[p]!=0;
    const Mesh mesh(grid);
    Side side_a(mesh,a,control.second_order_a,true,control.strict_energy_balance),
         side_b(mesh,b,control.second_order_b,solve_b,control.strict_energy_balance);
    const detail::EnergyMesh energy_mesh(grid);
    const auto line_axis=control.red_black ? 0U
        : detail::dominant_diffusion_axis(energy_mesh,side_a.energy(),side_b.energy(),ks);
    detail::EnergyLineScratch line_work(control.red_black ? 0 : energy_mesh.count[line_axis]);
    Diffusion diffusion;
    if(control.max_iterations) {
        diffusion[0].reserve(mesh.n);diffusion[2].reserve(mesh.n);
        if(solve_b) diffusion[1].reserve(mesh.n);
        for(std::size_t p=0;p<mesh.n;++p) {
            diffusion[0].push_back(detail::energy_diffusion(energy_mesh,side_a.energy(),p));
            diffusion[2].push_back(detail::energy_diffusion(energy_mesh,ks,p));
            if(solve_b) diffusion[1].push_back(detail::energy_diffusion(energy_mesh,side_b.energy(),p));
        }
    }
    std::array<Vector,3> carry{Vector(mesh.n),Vector(mesh.n),Vector(mesh.n)};
    const auto reset_carry=[&] { for(auto& field:carry) std::fill(field.begin(),field.end(),0.); };
    auto previous=pack(t,solve_b); double previous_q=0; bool have_q=false;
    bool strict_boundary_complete=true;
    const auto strict_audit=[&] {
        // Reuse the deferred buffers for actual m*h, avoiding C*T+B
        // cancellation. Every subsequent numerical sweep rebuilds C/B first.
        faces<true>(mesh,side_a,view(t.a));
        if (solve_b) faces<true>(mesh,side_b,view(t.b));
        auto ledger=energy_physical_audit(grid,side_a.physical(),side_b.physical(),ks,t,source_s,prescribed_b);
        result.energy_error_ratio=energy_balance_error(ledger)/energy_scale(grid,a.hv,b.hv,t);
        strict_boundary_complete=ledger.boundary_complete;
        result.physical_audit_available=true;
        const bool passed=ledger.boundary_complete && std::isfinite(result.energy_error_ratio)
            && result.energy_error_ratio<=1e-7;
        if (physical_audit) *physical_audit=std::move(ledger);
        return passed;
    };
    struct Cancelled {};
    const auto step=[&](std::size_t count) {
        if (cancelled()) throw Cancelled{};
        const double change=sweeps(mesh,side_a,side_b,ks,source_s,t,control,count,line_axis,line_work,carry,diffusion,solve_b);
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
                    auto before=pack(t,solve_b); const auto n=std::min<std::size_t>(25,count-done);
                    result.residual=step(n); done+=n; auto picard=pack(t,solve_b);
                    accelerator.push(std::move(before),picard); Eigen::VectorXd candidate;
                    if (!accelerator.candidate(picard,candidate) || count-done<2) continue;
                    const double ordinary=step(1); picard=pack(t,solve_b); restore(t,candidate,solve_b); reset_carry();
                    const double trial=step(1); done+=2;
                    if (std::isfinite(trial) && trial<=ordinary) result.residual=trial;
                    else { restore(t,picard,solve_b); result.residual=ordinary; }
                    reset_carry();
                }
            } else result.residual=step(count);
            result.audit_available=false; result.iterations+=count;
            result.physical_audit_available=false;
            if (control.progress) control.progress(control.context,result.iterations,control.max_iterations);
            if (cancelled()) throw Cancelled{};
            double q=0;
            for (std::size_t p=0; p<mesh.n; ++p) q+=b.hv[p]*(t.solid[p]-t.b[p])*mesh.volume(mesh.point(p));
            result.q_b=q; const auto current=pack(t,solve_b);
            if (have_q && std::abs(q-previous_q)/std::max({std::abs(q),std::abs(previous_q),1.0})<control.q_relative_tolerance
                && (current-previous).cwiseAbs().maxCoeff()<.01) {
                if (control.strict_energy_balance) {
                    const bool passed=strict_audit();
                    result.finishing_checks.push_back({result.iterations,{},passed,result.energy_error_ratio});
                    if (passed) result.stop=TemperatureStop::converged;
                    if (passed || !strict_boundary_complete) break;
                } else {
                    if (result.has_sources) { result.stop=TemperatureStop::converged; break; }
                    result.audit=audit(mesh,side_a,side_b,ks,source_s,t); result.audit_available=true;
                    result.finishing_checks.push_back({result.iterations,result.audit.gates});
                    if (result.audit.passed) result.stop=TemperatureStop::converged;
                    if (result.audit.passed || !result.audit.boundary_complete) break;
                }
            }
            previous_q=q; have_q=true; previous=current;
        }
    } catch (const Cancelled&) {
        result.stop=TemperatureStop::cancelled; result.audit_available=false;
        result.physical_audit_available=false;
        result.energy_error_ratio=std::numeric_limits<double>::quiet_NaN();
        result.q_b=std::numeric_limits<double>::quiet_NaN(); return result;
    }
    if (control.strict_energy_balance) {
        if (!result.physical_audit_available && result.iterations) strict_audit();
    } else if (!result.audit_available) {
        result.audit=audit(mesh,side_a,side_b,ks,source_s,t); result.audit_available=true;
    }
    return result;
}
}  // namespace tpmshx
