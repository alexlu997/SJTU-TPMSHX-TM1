#include "tpmshx/simple_3d_c_api.h"
#include "tpmshx/simple_3d.hpp"
#include "simple_3d_c_views.hpp"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>

struct tpmshx_simple_3d_handle {
    tpmshx::Simple3DSolver solver;
    std::vector<double> dx,dy,dz;
    tpmshx::GridView grid;
    tpmshx_simple_3d_handle(const tpmshx::GridView& g,tpmshx::ArrayView<const unsigned char> outlet)
        :solver(g,outlet),dx(g.dx.data,g.dx.data+g.dx.size),dy(g.dy.data,g.dy.data+g.dy.size),dz(g.dz.data,g.dz.data+g.dz.size),
         grid{g.nx,g.ny,g.nz,{dx.data(),dx.size()},{dy.data(),dy.size()},{dz.data(),dz.size()}} {}
};
namespace {
void text(char* output,std::size_t capacity,const char* message) noexcept {
    if (!output||!capacity) return;
    const auto n=std::min(capacity-1,std::strlen(message));std::memcpy(output,message,n);output[n]='\0';
}
template<typename F> int guarded(F function,char* error,std::size_t capacity) noexcept {
    if (!error||!capacity) return TPMSHX_SIMPLE_INVALID_ARGUMENT;
    try { function();error[0]='\0';return TPMSHX_SIMPLE_OK; }
    catch(const std::invalid_argument& e) { text(error,capacity,e.what());return TPMSHX_SIMPLE_INVALID_ARGUMENT; }
    catch(const std::domain_error& e) { text(error,capacity,e.what());return TPMSHX_SIMPLE_ARITHMETIC_ERROR; }
    catch(const std::exception& e) { text(error,capacity,e.what());return TPMSHX_SIMPLE_NATIVE_ERROR; }
    catch(...) { text(error,capacity,"unknown native SIMPLE error");return TPMSHX_SIMPLE_NATIVE_ERROR; }
}
bool cancel(void* context) {
    const auto& c=*static_cast<const tpmshx_simple_callbacks_v1*>(context);return c.cancel&&c.cancel(c.context)!=0;
}
void progress(void* context,std::size_t it,double residual) {
    const auto& c=*static_cast<const tpmshx_simple_callbacks_v1*>(context);if(c.progress)c.progress(c.context,it,residual);
}
bool overlap(const double* a,std::size_t na,const double* b,std::size_t nb) {
    const auto x=reinterpret_cast<std::uintptr_t>(a),y=reinterpret_cast<std::uintptr_t>(b);
    return na&&nb&&(x<=y ? y-x<na*sizeof(double) : x-y<nb*sizeof(double));
}
void mass_outputs(const tpmshx::GridView& g,double* const* arrays,const size_t* sizes) {
    const std::size_t expected[]={(g.nx+1)*g.ny*g.nz,g.nx*(g.ny+1)*g.nz,g.nx*g.ny*(g.nz+1)};
    for(std::size_t i=18;i<21;++i) {
        if(!arrays[i]||sizes[i]!=expected[i-18])throw std::invalid_argument("invalid SIMPLE mass-face output extent");
        for(std::size_t j=0;j<i;++j)
            if(overlap(arrays[i],sizes[i],arrays[j],sizes[j]))throw std::invalid_argument("SIMPLE mass-face output overlaps another array");
    }
}
static_assert(static_cast<unsigned>(tpmshx::SimpleStop::post_closure)==TPMSHX_SIMPLE_POST_CLOSURE);
}
extern "C" {
uint32_t TPMSHX_THERMAL_CALL tpmshx_simple_3d_abi_version(void) { return TPMSHX_SIMPLE_3D_ABI_VERSION; }
int TPMSHX_THERMAL_CALL tpmshx_simple_3d_create_v1(size_t nx,size_t ny,size_t nz,
    const double* dx,const double* dy,const double* dz,const uint8_t* open,tpmshx_simple_3d_handle** output,char* error,size_t capacity) {
    return guarded([&] {
        if(!output||!dx||!dy||!dz||!open)throw std::invalid_argument("null SIMPLE create argument");
        const tpmshx::GridView grid{nx,ny,nz,{dx,nx},{dy,ny},{dz,nz}};
        // The core validates dimensions before using the supplied storage.
        auto handle=std::make_unique<tpmshx_simple_3d_handle>(grid,tpmshx::ArrayView<const unsigned char>{open,nx*nz});
        *output=handle.release();
    },error,capacity);
}
void TPMSHX_THERMAL_CALL tpmshx_simple_3d_destroy(tpmshx_simple_3d_handle* handle) { delete handle; }
int TPMSHX_THERMAL_CALL tpmshx_simple_3d_solve_v1(tpmshx_simple_3d_handle* handle,double* const* arrays,const size_t* sizes,
    const tpmshx_simple_3d_config_v1* config,const tpmshx_simple_callbacks_v1* callbacks,
    tpmshx_simple_3d_result_v1* output,char* error,size_t capacity) {
    return guarded([&] {
        if(!handle||!arrays||!sizes||!config||!output)throw std::invalid_argument("null SIMPLE solve argument");
        mass_outputs(handle->grid,arrays,sizes);
        const auto input=[&](std::size_t i){return tpmshx::ArrayView<const double>{arrays[i],sizes[i]};};
        const auto state=[&](std::size_t i){return tpmshx::ArrayView<double>{arrays[i],sizes[i]};};
        const auto& c=*config;
        for(auto flag:{c.ideal_gas,c.massflux_inlet,c.second_order_upwind,c.adaptive_pressure_tolerance,c.track_momentum})
            if(flag>1)throw std::invalid_argument("SIMPLE flags must be 0 or 1");
        const tpmshx::Simple3DMaterialView material{input(0),input(1),input(2),input(3),input(4),input(5)};
        const tpmshx::Simple3DStateView fields{state(6),state(7),state(8),state(9),state(10),state(11),state(12),state(13),state(14),state(15)};
        const tpmshx::Simple3DBoundaryView boundary{input(16),input(17)};
        tpmshx::Simple3DControl control{};
        control.max_iterations=c.max_iterations;control.inner_sweeps=c.inner_sweeps;control.pressure_rebuild_every=c.pressure_rebuild_every;
        control.alpha_velocity=c.alpha_velocity;control.alpha_pressure=c.alpha_pressure;control.alpha_density=c.alpha_density;
        control.pressure_reference_absolute=c.pressure_reference_absolute;control.gas_constant=c.gas_constant;control.pressure_diagonal_drift=c.pressure_diagonal_drift;
        control.ideal_gas=c.ideal_gas!=0;control.massflux_inlet=c.massflux_inlet!=0;control.second_order_upwind=c.second_order_upwind!=0;
        control.adaptive_pressure_tolerance=c.adaptive_pressure_tolerance!=0;control.track_momentum=c.track_momentum!=0;
        control.ordering=static_cast<tpmshx::Simple3DOrdering>(c.ordering);
        const auto& f=c.convergence;
        control.convergence={f.momentum_tolerance,f.local_mass_tolerance,f.global_mass_tolerance,f.backflow_maximum,
            f.velocity_check_tolerance,f.stall_ratio,f.confirmations,f.momentum_interval,f.stall_window};
        tpmshx_simple_callbacks_v1 local{};
        if(callbacks) {
            local=*callbacks;control.cancel=local.cancel?cancel:nullptr;control.progress=local.progress?progress:nullptr;control.context=&local;
        }
        const auto r=handle->solver.solve(material,boundary,fields,control);
        auto result=tpmshx::simple_3d_c_view(r);
        if(r.post_closure_measured&&(r.stop==tpmshx::SimpleStop::tol||r.stop==tpmshx::SimpleStop::stall
            ||r.stop==tpmshx::SimpleStop::max_iterations||r.stop==tpmshx::SimpleStop::post_closure)) {
            std::vector<double> rho_eps(fields.density.size);
            for(std::size_t i=0;i<rho_eps.size();++i)rho_eps[i]=fields.density[i]*material.epsilon[i];
            tpmshx::simple_face_mass_flux(3,handle->grid,{input(6),input(7),input(8)},
                {rho_eps.data(),rho_eps.size()},{state(18),state(19),state(20)});
            result.mass_faces_available=1;
        }
        *output=result;
    },error,capacity);
}
int TPMSHX_THERMAL_CALL tpmshx_simple_3d_history_v1(const tpmshx_simple_3d_handle* handle,uint32_t kind,
    double* values,size_t capacity,size_t* required,char* error,size_t error_capacity) {
    return guarded([&] {
        if(!handle||!required||kind>4||(!values&&capacity))throw std::invalid_argument("invalid SIMPLE history query");
        const auto& h=handle->solver.history();const std::vector<double>* series=nullptr;
        if(kind==0)series=&h.legacy;else if(kind==1)series=&h.local_mass;else if(kind==2)series=&h.global_mass;
        else if(kind==4)series=&handle->solver.massflux_target();
        const auto needed=series?series->size():h.momentum.size()*11;
        if(values&&capacity<needed)throw std::invalid_argument("SIMPLE history buffer is too short");
        if(values) {
            if(series)std::copy(series->begin(),series->end(),values);
            else for(std::size_t i=0;i<h.momentum.size();++i) {
                const auto& entry=h.momentum[i];const auto& r=entry.residual;
                const double row[]={static_cast<double>(entry.iteration),r.maximum,r.numerator[0],r.numerator[1],r.numerator[2],
                    r.denominator[0],r.denominator[1],r.denominator[2],r.component[0],r.component[1],r.component[2]};
                std::copy(row,row+11,values+11*i);
            }
        }
        *required=needed;
    },error,error_capacity);
}
}
