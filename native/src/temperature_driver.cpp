#include "tpmshx/temperature_driver.hpp"
#include "temperature_faces.hpp"
#include "temperature_active_line.hpp"

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

using Mesh = detail::EnergyMesh;

// Prepared unique positive-axis face capacity. Every adjacent pair consumes
// the same face; only this adapter knows cell velocities and inlet overrides.
struct TemperatureEnergyPhase {
    EnergyPhase energy;
    std::array<std::vector<double>,3> capacity,offset;
    TemperatureEnergyPhase(const Mesh& mesh,const TemperatureFluidView& f)
        : energy{f.conductivity,f.hv,{}, {},f.boundary,true} {
        energy.inlet.capacity_flux={}; // consumed once into signed-axis faces
        const auto& g=mesh.g;
        const std::array<std::size_t,3> sizes{(g.nx+1)*g.ny*g.nz,
            g.nx*(g.ny+1)*g.nz,g.nx*g.ny*(g.nz+1)};
        const std::array<ArrayView<const double>,3> velocity{f.u,f.v,f.w};
        for(std::size_t axis=0;axis<3;++axis) {
            offset[axis].assign(sizes[axis],0.);
            if(f.capacity_faces[axis].size) {
                energy.faces.capacity[axis]=f.capacity_faces[axis];
                energy.faces.offset[axis]={offset[axis].data(),offset[axis].size()};
                continue;
            }
            capacity[axis].assign(sizes[axis],0.);
            energy.faces.capacity[axis]={capacity[axis].data(),capacity[axis].size()};
            energy.faces.offset[axis]={offset[axis].data(),offset[axis].size()};
            // A validated nz==1 CC scheme is 2D: optional cell w is inactive.
            if(axis==2&&g.nz==1) continue;
            for(std::size_t p=0;p<mesh.cells();++p) {
                const auto c=mesh.coord(p);
                const auto cell=[&](std::size_t q) {
                    return f.epsilon[q]*f.rho_cp[q]*detail::optional(velocity[axis],q);
                };
                const double area=mesh.face_area(axis,c),local=cell(p);
                const double high=c[axis]+1<mesh.count[axis]
                    ? .5*(local+cell(p+mesh.stride[axis])):local;
                capacity[axis][mesh.face(axis,p,1)]=high*area;
                if(c[axis]==0) capacity[axis][mesh.face(axis,p,-1)]=local*area;
                for(int sign:{-1,1}) {
                    if(mesh.inside(c,axis,sign)||!detail::inlet_face(f.boundary,axis,sign)) continue;
                    const auto patch=mesh.patch(axis,c);
                    auto& C=capacity[axis][mesh.face(axis,p,sign)];
                    if(detail::optional(f.boundary.opening,patch,1.)==0.) C=0.;
                    else if(f.boundary.capacity_flux.size) C=-sign*f.boundary.capacity_flux[patch];
                }
            }
        }
    }
    std::array<ArrayView<double>,3> writable_offsets() {
        return {{{offset[0].data(),offset[0].size()},
                 {offset[1].data(),offset[1].size()},
                 {offset[2].data(),offset[2].size()}}};
    }
};

void update(ArrayView<double> t, std::size_t p, double value, double alpha, double& change) {
    const double next = alpha == 1.0 ? value : t[p]+alpha*(value-t[p]);
    if (!std::isfinite(next)) throw std::domain_error("nonfinite temperature row update");
    change = std::max(change,std::abs(next-t[p]));
    t[p] = next;
}

void apply_row(ArrayView<double> t,std::size_t p,detail::EnergyRow row,
               double alpha,double& change) {
    if(!std::isfinite(row.diagonal)||!std::isfinite(row.rhs)||row.diagonal<=0.)
        throw std::domain_error("invalid temperature energy equation");
    update(t,p,row.rhs/row.diagonal,alpha,change);
}

double point_chunk(const Mesh& mesh,TemperatureEnergyPhase& a,TemperatureEnergyPhase& b,
             ArrayView<const double> ks,TemperatureStateView state,
             const TemperatureControl& control,bool frozen,std::size_t sweeps,
             bool red_black) {
    double change=0.;
    const bool reverse_x=!red_black&&a.energy.inlet.direction==1;
    const bool reverse_y=!red_black&&(b.energy.inlet.direction==3
        ||(mesh.g.nz==1&&a.energy.inlet.direction==3&&b.energy.inlet.direction==0));
    const bool reverse_z=!red_black&&a.energy.inlet.direction==5;
    const auto n=mesh.cells();
    const double alpha_a=std::min(control.alpha_a,.2);
    const double alpha_b=control.second_order_b?std::min(control.alpha_b,.2):control.alpha_b;
    const std::array<ArrayView<double>,3> fields{state.a,state.b,state.solid};
    std::array<std::vector<double>,3> before;
    for(auto& saved:before) saved.resize(n);
    for(std::size_t iteration=0;iteration<sweeps;) {
        for(std::size_t phase=0;phase<3;++phase)
            std::copy_n(fields[phase].data,n,before[phase].data());
        detail::temperature_face_offsets(mesh,a.energy.faces.capacity,
            {state.a.data,n},a.writable_offsets());
        if(control.second_order_b&&!frozen)
            detail::temperature_face_offsets(mesh,b.energy.faces.capacity,
                {state.b.data,n},b.writable_offsets());
        const auto block=std::min(std::size_t{5},sweeps-iteration);
        for(std::size_t inner=0;inner<block;++inner) {
        change=0.;
        for(std::size_t color=0;color<(red_black?2U:1U);++color)
            for(std::size_t ii=0;ii<mesh.g.nx;++ii)
                for(std::size_t jj=0;jj<mesh.g.ny;++jj)
                    for(std::size_t kk=0;kk<mesh.g.nz;++kk) {
                        const std::array<std::size_t,3> c{
                            reverse_x?mesh.g.nx-1-ii:ii,
                            reverse_y?mesh.g.ny-1-jj:jj,
                            reverse_z?mesh.g.nz-1-kk:kk};
                        if(red_black&&(c[0]+c[1])%2!=color) continue;
                        const auto p=(c[0]*mesh.g.ny+c[1])*mesh.g.nz+c[2];
                        apply_row(state.a,p,detail::fluid_energy_row(mesh,a.energy,
                            {state.a.data,n},{state.solid.data,n},p),alpha_a,change);
                        apply_row(state.solid,p,detail::solid_energy_row(mesh,ks,a.energy.hv,b.energy.hv,
                            {state.a.data,n},{state.b.data,n},{state.solid.data,n},{},p),
                            control.alpha_solid,change);
                        if(!frozen) apply_row(state.b,p,detail::fluid_energy_row(mesh,b.energy,
                            {state.b.data,n},{state.solid.data,n},p),alpha_b,change);
                    }
        }
        change=0.;
        for(std::size_t phase=0;phase<3;++phase)
            for(std::size_t p=0;p<n;++p) {
                const double old=before[phase][p];
                fields[phase][p]=old+.6*(fields[phase][p]-old);
                change=std::max(change,std::abs(fields[phase][p]-old));
            }
        iteration+=block;
    }
    return change;
}

bool complete_inflow(const Mesh& mesh,const EnergyPhase& phase) {
    for(std::size_t p=0;p<mesh.cells();++p) {
        const auto c=mesh.coord(p);
        for(std::size_t axis=0;axis<3;++axis) for(int sign:{-1,1})
            if(!mesh.inside(c,axis,sign)
                &&sign*phase.faces.capacity[axis][mesh.face(axis,p,sign)]<0.
                &&!detail::known_inlet(mesh,phase.inlet,c,axis,sign)) return false;
    }
    return true;
}

void refresh_offsets(const Mesh& mesh,TemperatureEnergyPhase& a,TemperatureEnergyPhase& b,
        TemperatureStateView state,bool second_b,ArrayView<const double> prescribed) {
    detail::temperature_face_offsets(mesh,a.energy.faces.capacity,
        {state.a.data,state.a.size},a.writable_offsets());
    if(second_b&&!prescribed.size) detail::temperature_face_offsets(mesh,b.energy.faces.capacity,
        {state.b.data,state.b.size},b.writable_offsets());
}

double actual_error(const Mesh& mesh,TemperatureEnergyPhase& a,TemperatureEnergyPhase& b,
        ArrayView<const double> ks,TemperatureStateView state,bool second_b,
        ArrayView<const double> prescribed) {
    refresh_offsets(mesh,a,b,state,second_b,prescribed);
    const auto ledger=energy_balance_audit(mesh.g,a.energy,b.energy,ks,state,{},prescribed);
    if(!ledger.boundary_complete) throw std::logic_error("active temperature guard lost complete boundary");
    return ledger.error;
}

using PointCache=std::array<std::vector<detail::PointEnergyCoefficients>,3>;

template<bool Cached=false>
void point_sweep(const Mesh& mesh,TemperatureEnergyPhase& a,TemperatureEnergyPhase& b,
        ArrayView<const double> ks,TemperatureStateView state,const TemperatureControl& control,
        bool frozen,int phase_only=-1,const PointCache* cache=nullptr) {
    const bool reverse_x=a.energy.inlet.direction==1;
    const bool reverse_y=b.energy.inlet.direction==3
        ||(mesh.g.nz==1&&a.energy.inlet.direction==3&&b.energy.inlet.direction==0);
    const bool reverse_z=a.energy.inlet.direction==5;
    const auto n=mesh.cells();double change=0.;
    for(std::size_t ii=0;ii<mesh.g.nx;++ii)
        for(std::size_t jj=0;jj<mesh.g.ny;++jj)
            for(std::size_t kk=0;kk<mesh.g.nz;++kk) {
                const std::array<std::size_t,3> c{reverse_x?mesh.g.nx-1-ii:ii,
                    reverse_y?mesh.g.ny-1-jj:jj,reverse_z?mesh.g.nz-1-kk:kk};
                const auto p=(c[0]*mesh.g.ny+c[1])*mesh.g.nz+c[2];
                if(phase_only==-1||phase_only==0)
                    apply_row(state.a,p,Cached ?detail::fluid_energy_row(mesh,a.energy,
                        {state.a.data,n},{state.solid.data,n},p,(*cache)[0][p])
                        :detail::fluid_energy_row(mesh,a.energy,{state.a.data,n},{state.solid.data,n},p),
                        std::min(control.alpha_a,.2),change);
                if(phase_only==-1||phase_only==2)
                    apply_row(state.solid,p,Cached ?detail::solid_energy_row(mesh,ks,a.energy.hv,b.energy.hv,
                        {state.a.data,n},{state.b.data,n},{state.solid.data,n},{},p,(*cache)[2][p])
                        :detail::solid_energy_row(mesh,ks,a.energy.hv,b.energy.hv,
                        {state.a.data,n},{state.b.data,n},{state.solid.data,n},{},p),control.alpha_solid,change);
                if(!frozen&&(phase_only==-1||phase_only==1))
                    apply_row(state.b,p,Cached ?detail::fluid_energy_row(mesh,b.energy,
                        {state.b.data,n},{state.solid.data,n},p,(*cache)[1][p])
                        :detail::fluid_energy_row(mesh,b.energy,{state.b.data,n},{state.solid.data,n},p),
                        control.second_order_b?std::min(control.alpha_b,.2):control.alpha_b,change);
            }
}

void fluid_line_sweep(const Mesh& mesh,TemperatureEnergyPhase& phase,
        ArrayView<double> temperature,ArrayView<const double> solid,double alpha,
        const std::array<bool,3>& reverse,detail::ActiveLineWork& work) {
    const auto axis=static_cast<std::size_t>(phase.energy.inlet.direction/2);
    for(std::size_t ordinal=0;ordinal<mesh.line_count(axis);++ordinal) {
        auto c=mesh.coord(mesh.line_start(axis,ordinal));
        for(std::size_t a=0;a<3;++a) if(a!=axis&&reverse[a]) c[a]=mesh.count[a]-1-c[a];
        const auto p=(c[0]*mesh.g.ny+c[1])*mesh.g.nz+c[2];
        detail::active_temperature_line(mesh,phase,temperature,solid,axis,p,alpha,work);
    }
}

double chunk(const Mesh& mesh,TemperatureEnergyPhase& a,TemperatureEnergyPhase& b,
        ArrayView<const double> ks,TemperatureStateView state,const TemperatureControl& control,
        bool frozen,std::size_t sweeps,bool red_black,bool eligible,
        ArrayView<const double> prescribed,detail::ActiveLineWork& work) {
    if(!eligible)
        return point_chunk(mesh,a,b,ks,state,control,frozen,sweeps,red_black);
    const auto n=mesh.cells();const std::array<ArrayView<double>,3> fields{state.a,state.b,state.solid};
    // Chunk-local cache cannot overlap the full finish ledger. Fallback
    // point blocks have already returned; one-sweep Newton blocks need none.
    PointCache cache;
    if(sweeps>1) for(std::size_t phase=0;phase<3;++phase) {
        if(phase==1&&frozen) continue;
        cache[phase].resize(n);
        for(std::size_t p=0;p<n;++p) {
            const auto row=phase<2 ?detail::fluid_energy_row(mesh,phase==0?a.energy:b.energy,
                {fields[phase].data,n},{state.solid.data,n},p)
                :detail::solid_energy_row(mesh,ks,a.energy.hv,b.energy.hv,
                    {state.a.data,n},{state.b.data,n},{state.solid.data,n},{},p);
            cache[phase][p]={row.diagonal,row.neighbor};
        }
    }
    std::array<std::vector<double>,3> before,saved;
    for(auto* block:{&before,&saved}) for(auto& values:*block) values.resize(n);
    const std::array<bool,3> reverse{a.energy.inlet.direction==1,b.energy.inlet.direction==3
        ||(mesh.g.nz==1&&a.energy.inlet.direction==3&&b.energy.inlet.direction==0),a.energy.inlet.direction==5};
    double change=0.;
    for(std::size_t iteration=0;iteration<sweeps;) {
        const auto block=std::min(std::size_t{5},sweeps-iteration);
        for(std::size_t phase=0;phase<3;++phase) std::copy_n(fields[phase].data,n,before[phase].data());
        detail::temperature_face_offsets(mesh,a.energy.faces.capacity,{state.a.data,n},a.writable_offsets());
        if(control.second_order_b&&!frozen)
            detail::temperature_face_offsets(mesh,b.energy.faces.capacity,{state.b.data,n},b.writable_offsets());
        for(std::size_t inner=0;inner+1<block;++inner)
            point_sweep<true>(mesh,a,b,ks,state,control,frozen,-1,&cache);
        for(std::size_t phase=0;phase<3;++phase) std::copy_n(fields[phase].data,n,saved[phase].data());
        try {
            for(std::size_t phase=0;phase<3;++phase) for(std::size_t p=0;p<n;++p)
                fields[phase][p]=before[phase][p]+.6*(fields[phase][p]-before[phase][p]);
            const double baseline=actual_error(mesh,a,b,ks,state,control.second_order_b,prescribed);
            for(std::size_t phase=0;phase<3;++phase) std::copy_n(saved[phase].data(),n,fields[phase].data);
            fluid_line_sweep(mesh,a,state.a,{state.solid.data,n},control.alpha_a,reverse,work);
            point_sweep(mesh,a,b,ks,state,control,frozen,2);
            if(!frozen) {
                if(control.second_order_b)
                    fluid_line_sweep(mesh,b,state.b,{state.solid.data,n},control.alpha_b,reverse,work);
                else point_sweep(mesh,a,b,ks,state,control,frozen,1);
            }
            for(std::size_t phase=0;phase<3;++phase) for(std::size_t p=0;p<n;++p)
                fields[phase][p]=before[phase][p]+.6*(fields[phase][p]-before[phase][p]);
            const double candidate=actual_error(mesh,a,b,ks,state,control.second_order_b,prescribed);
            if(!(candidate<baseline)) {
                for(std::size_t phase=0;phase<3;++phase) for(std::size_t p=0;p<n;++p)
                    fields[phase][p]=before[phase][p]+.6*(saved[phase][p]-before[phase][p]);
                refresh_offsets(mesh,a,b,state,control.second_order_b,prescribed);
            }
        } catch(...) {
            for(std::size_t phase=0;phase<3;++phase) std::copy_n(saved[phase].data(),n,fields[phase].data);
            refresh_offsets(mesh,a,b,state,control.second_order_b,prescribed);
            throw;
        }
        change=0.;
        for(std::size_t phase=0;phase<3;++phase) for(std::size_t p=0;p<n;++p)
            change=std::max(change,std::abs(fields[phase][p]-before[phase][p]));
        iteration+=block;
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

TemperatureResult solve_temperature(TemperatureScheme scheme, const GridView& grid,
    const TemperatureFluidView& a, const TemperatureFluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    const TemperatureControl& control, ArrayView<const double> prescribed_b, bool red_black,
    PhysicalHeatLedger* returned_audit) {
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
        const bool direct=std::any_of(f->capacity_faces.begin(),f->capacity_faces.end(),
            [](auto face){return face.size!=0;});
        if(direct) {
            const std::array<std::size_t,3> sizes{product(product(grid.nx+1,grid.ny),grid.nz),
                product(product(grid.nx,grid.ny+1),grid.nz),product(product(grid.nx,grid.ny),grid.nz+1)};
            for(std::size_t axis=0;axis<3;++axis) {
                check_array(f->capacity_faces[axis],sizes[axis]);
                for(auto out:outputs) disjoint(out,f->capacity_faces[axis]);
            }
        }
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
    const double unit_depth=1.;
    GridView normalized=grid;
    if(two_d) normalized.dz={&unit_depth,1};
    const Mesh mesh(normalized);
    TemperatureEnergyPhase phase_a(mesh,a),phase_b(mesh,b);
    const bool eligible=!red_black&&(detail::temperature_second_order_active(mesh,phase_a.energy.faces.capacity)
        ||(control.second_order_b&&!prescribed_b.size&&detail::temperature_second_order_active(mesh,phase_b.energy.faces.capacity)))
        &&complete_inflow(mesh,phase_a.energy)&&(prescribed_b.size||complete_inflow(mesh,phase_b.energy));
    detail::ActiveLineWork line_work(eligible ? *std::max_element(mesh.count.begin(),mesh.count.end()):1U);
    const auto audit_state=[&]() {
        detail::temperature_face_offsets(mesh,phase_a.energy.faces.capacity,
            {state.a.data,cells},phase_a.writable_offsets());
        if(control.second_order_b&&!prescribed_b.size)
            detail::temperature_face_offsets(mesh,phase_b.energy.faces.capacity,
                {state.b.data,cells},phase_b.writable_offsets());
        return energy_physical_audit(normalized,phase_a.energy,phase_b.energy,k_ss,state,{},prescribed_b);
    };
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
        result.residual = chunk(mesh,phase_a,phase_b,k_ss,state,control,prescribed_b.size != 0,n,red_black,eligible,prescribed_b,line_work);
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
            // Audit a fresh reconstruction at the returned state, never the
            // offsets frozen at the beginning of the last Picard block.
            auto audit=audit_state();
            double qa=0.;
            for(std::size_t p=0;p<cells;++p)
                qa+=a.hv[p]*(state.a[p]-state.solid[p])*mesh.volume(mesh.coord(p));
            const double denominator=std::max({std::abs(qa),std::abs(result.q_b),1.});
            const bool direct=a.capacity_faces[0].size||b.capacity_faces[0].size;
            if((!direct&&!audit.boundary_complete)
                ||(audit.boundary_complete&&energy_balance_error(audit)/denominator<=1e-7)) {
                result.stop = TemperatureStop::converged;
                if(returned_audit) *returned_audit=std::move(audit);
                return result;
            }
        }
        previous_q = result.q_b;
        have_previous_q = true;
        for (std::size_t phase = 0; phase < outputs.size(); ++phase)
            std::copy_n(outputs[phase].data,cells,previous[phase].data());
    }
    if(returned_audit&&result.iterations>0) *returned_audit=audit_state();
    return result;
}

}  // namespace tpmshx
