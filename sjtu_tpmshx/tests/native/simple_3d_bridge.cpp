#include "tpmshx/simple_3d.hpp"
#include "tpmshx/thermal_c_api.h"

#include <algorithm>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <vector>
namespace {
using tpmshx::ArrayView;
struct Handle {
    std::vector<double> dx,dy,dz;
    std::vector<unsigned char> outlet;
    std::unique_ptr<tpmshx::Simple3DSolver> solver;
    std::size_t cancel_after=0,cancel_calls=0;
    tpmshx::GridView grid() const { return {dx.size(),dy.size(),dz.size(),{dx.data(),dx.size()},{dy.data(),dy.size()},{dz.data(),dz.size()}}; }
};
void message(char* out,std::size_t n,const char* text) { if (out&&n) std::snprintf(out,n,"%s",text); }
bool cancel(void* pointer) { auto& h=*static_cast<Handle*>(pointer);++h.cancel_calls;return h.cancel_after&&h.cancel_calls>=h.cancel_after; }
void momentum(const tpmshx::SimpleMomentumResidual& r,double* out) {
    out[6]=r.maximum;
    for (std::size_t i=0;i<3;++i) { out[14+i]=r.numerator[i];out[17+i]=r.denominator[i];out[20+i]=r.component[i]; }
}
}
extern "C" TPMSHX_THERMAL_API void* TPMSHX_THERMAL_CALL tpmshx_simple3d_create(std::size_t nx,std::size_t ny,std::size_t nz,
    const double* dx,const double* dy,const double* dz,const unsigned char* outlet,char* error,std::size_t capacity) noexcept {
    try {
        if (!nx||!ny||!nz||!dx||!dy||!dz||!outlet) throw std::invalid_argument("missing SIMPLE 3D grid");
        auto h=std::make_unique<Handle>();h->dx.assign(dx,dx+nx);h->dy.assign(dy,dy+ny);h->dz.assign(dz,dz+nz);h->outlet.assign(outlet,outlet+nx*nz);
        h->solver=std::make_unique<tpmshx::Simple3DSolver>(h->grid(),ArrayView<const unsigned char>{h->outlet.data(),h->outlet.size()});
        message(error,capacity,"");return h.release();
    } catch (const std::exception& e) { message(error,capacity,e.what());return nullptr; }
    catch (...) { message(error,capacity,"unknown native error");return nullptr; }
}
extern "C" TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_simple3d_destroy(void* pointer) noexcept { delete static_cast<Handle*>(pointer); }
// Qualification bridge, not a production ABI. arrays[18]: eps,mu,mu_eff,K,cF,T,u,v,w,P,Pp,du,dv,dw,rho,vin,out_u,out_w.
// values[12]: alpha_u,p,rho,Pref,R,drift,mom,local,global,bf,vd,stall.
// counts[9]: maxiter,inner,confirm,mom_every,stall_window,flags(ideal/massflux/SOU/adaptive/track),cancel_after,rebuild_every,ordering.
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple3d_call(void* pointer,int operation,double* const* arrays,
    const std::size_t* sizes,const double* values,const std::size_t* counts,double* out,char* error,std::size_t capacity) noexcept {
    try {
        if (!pointer||!arrays||!sizes||!values||!counts||!out) throw std::invalid_argument("missing SIMPLE qualification arrays");
        auto& h=*static_cast<Handle*>(pointer);
        const auto a=[&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
        const auto c=[&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
        const tpmshx::Simple3DMaterialView m{c(0),c(1),c(2),c(3),c(4),c(5)};
        const tpmshx::Simple3DStateView s{a(6),a(7),a(8),a(9),a(10),a(11),a(12),a(13),a(14),a(15)};
        const tpmshx::Simple3DBoundaryView b{c(16),c(17)};
        const auto order=static_cast<tpmshx::Simple3DOrdering>(counts[8]);const bool sou=(counts[5]&4)!=0;
        std::fill(out,out+32,std::numeric_limits<double>::quiet_NaN());
        if (operation==0) {
            tpmshx::simple_3d_predictor(h.grid(),{h.outlet.data(),h.outlet.size()},m,b,s,values[0],counts[1],sou,order);
            momentum(tpmshx::simple_3d_momentum_residual(h.grid(),m,b,s,sou),out);
        } else if (operation==1) momentum(tpmshx::simple_3d_momentum_residual(h.grid(),m,b,s,sou),out);
        else if (operation==2) {
            tpmshx::Simple3DControl control{};
            control.max_iterations=counts[0];control.inner_sweeps=counts[1];control.pressure_rebuild_every=counts[7];
            control.alpha_velocity=values[0];control.alpha_pressure=values[1];control.alpha_density=values[2];
            control.pressure_reference_absolute=values[3];control.gas_constant=values[4];control.pressure_diagonal_drift=values[5];
            control.ideal_gas=(counts[5]&1)!=0;control.massflux_inlet=(counts[5]&2)!=0;control.second_order_upwind=sou;
            control.adaptive_pressure_tolerance=(counts[5]&8)!=0;control.track_momentum=(counts[5]&16)!=0;control.ordering=order;
            control.convergence={values[6],values[7],values[8],values[9],values[10],values[11],counts[2],counts[3],counts[4]};
            h.cancel_after=counts[6];h.cancel_calls=0;control.cancel=cancel;control.context=&h;
            const auto r=h.solver->solve(m,b,s,control);
            out[0]=static_cast<double>(r.stop);out[1]=r.converged;out[2]=static_cast<double>(r.iterations);
            out[3]=r.post_closure_measured;out[4]=r.post_closure_certified;out[5]=r.legacy_residual;momentum(r.momentum,out);
            out[7]=r.mass.local_residual;out[8]=r.mass.global_residual;out[9]=r.mass.backflow_fraction;
            out[10]=r.mass.mass_in;out[11]=r.mass.mass_out;out[12]=static_cast<double>(r.pressure_clip_hits);out[13]=r.legacy_reference;
            out[23]=r.linear.relative_residual;out[24]=r.linear.pin_max_abs;out[25]=static_cast<double>(r.mass.counted_cells);
            out[26]=static_cast<double>(h.cancel_calls);out[27]=static_cast<double>(r.post_closure_rejections);
            out[28]=static_cast<double>(r.linear.rebuild_count);out[29]=r.linear.method=="pyamg_classical_bicgstab";
            out[30]=static_cast<double>(r.linear.iterations);out[31]=static_cast<double>(h.solver->massflux_target().size());
        } else throw std::invalid_argument("unknown SIMPLE qualification operation");
        message(error,capacity,"");return 0;
    } catch (const std::exception& e) { message(error,capacity,e.what());return 1; }
    catch (...) { message(error,capacity,"unknown native error");return 2; }
}
extern "C" TPMSHX_THERMAL_API std::size_t TPMSHX_THERMAL_CALL tpmshx_simple3d_history(void* pointer,int kind,double* out,std::size_t capacity) noexcept {
    if (!pointer) return 0;const auto& h=*static_cast<Handle*>(pointer);const auto& history=h.solver->history();
    const std::vector<double>* values=nullptr;
    if (kind==0) values=&history.legacy;else if(kind==1) values=&history.local_mass;else if(kind==2) values=&history.global_mass;
    else if(kind==4) values=&h.solver->massflux_target();
    if (values) { if(out&&capacity>=values->size())std::copy(values->begin(),values->end(),out);return values->size(); }
    if (kind==3) {
        const auto needed=11*history.momentum.size();
        if (out&&capacity>=needed) for (std::size_t i=0;i<history.momentum.size();++i) {
            const auto& row=history.momentum[i];const auto& r=row.residual;
            const double values[]={static_cast<double>(row.iteration),r.maximum,r.numerator[0],r.numerator[1],r.numerator[2],
                r.denominator[0],r.denominator[1],r.denominator[2],r.component[0],r.component[1],r.component[2]};
            std::copy(values,values+11,out+11*i);
        }
        return needed;
    }
    return 0;
}
