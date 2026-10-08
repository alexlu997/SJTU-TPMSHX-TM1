#include "tpmshx/simple_2d.hpp"
#include "tpmshx/thermal_c_api.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {
using tpmshx::ArrayView;
struct Handle {
    std::vector<double> dx,dy,progress;
    std::vector<unsigned char> outlet;
    double depth=1.;
    std::unique_ptr<tpmshx::Simple2DSolver> solver;
    std::size_t cancel_after=0,cancel_calls=0;
    tpmshx::GridView grid() const {
        return {dx.size(),dy.size(),1,{dx.data(),dx.size()},{dy.data(),dy.size()},{&depth,1}};
    }
};
void message(char* error, std::size_t capacity, const char* text) {
    if (error && capacity) std::snprintf(error,capacity,"%s",text);
}
bool cancel(void* pointer) {
    auto& h=*static_cast<Handle*>(pointer);
    ++h.cancel_calls;
    return h.cancel_after && h.cancel_calls>=h.cancel_after;
}
void progress(void* pointer,std::size_t iteration,double residual) {
    auto& h=*static_cast<Handle*>(pointer);
    h.progress.push_back(static_cast<double>(iteration)); h.progress.push_back(residual);
}
void momentum(const tpmshx::SimpleMomentumResidual& r,double* out) {
    out[6]=r.maximum;
    out[14]=r.numerator[0]; out[15]=r.numerator[1]; out[16]=r.denominator[0]; out[17]=r.denominator[1];
    out[18]=r.component[0]; out[19]=r.component[1];
}
}

extern "C" TPMSHX_THERMAL_API void* TPMSHX_THERMAL_CALL tpmshx_simple2d_create(
    std::size_t nx,std::size_t ny,const double* dx,const double* dy,const unsigned char* outlet,
    char* error,std::size_t capacity) noexcept {
    try {
        if (!nx || !ny || !dx || !dy || !outlet) throw std::invalid_argument("missing SIMPLE 2D grid");
        auto h=std::make_unique<Handle>();
        h->dx.assign(dx,dx+nx); h->dy.assign(dy,dy+ny); h->outlet.assign(outlet,outlet+nx);
        h->solver=std::make_unique<tpmshx::Simple2DSolver>(h->grid(),ArrayView<const unsigned char>{h->outlet.data(),nx});
        message(error,capacity,""); return h.release();
    } catch (const std::exception& e) { message(error,capacity,e.what()); return nullptr; }
    catch (...) { message(error,capacity,"unknown native error"); return nullptr; }
}
extern "C" TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_simple2d_destroy(void* pointer) noexcept {
    delete static_cast<Handle*>(pointer);
}

// Qualification bridge only. arrays[16]: eps,mu,mu_eff,K,cF,T,u,v,P,Pp,du,dv,rho,vin,in_frac,out_u_frac.
// values[15]: inlet ref speed,taper,rho_ref(NaN=absent),alphau,p,rho,Pref,R,aniso,mom,local,global,bf,vd,stall.
// counts[7]: maxiter,inner,confirm,mom_every,stall_window,flags(ideal/massflux/exitclose),cancel_after.
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple2d_call(
    void* pointer,int operation,double* const* arrays,const std::size_t* sizes,
    const double* values,const std::size_t* counts,double* out,char* error,std::size_t capacity) noexcept {
    try {
        if (!pointer || !arrays || !sizes || !values || !counts || !out)
            throw std::invalid_argument("missing SIMPLE qualification arrays");
        auto& h=*static_cast<Handle*>(pointer);
        const auto a=[&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
        const auto c=[&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
        const tpmshx::Simple2DMaterialView m{c(0),c(1),c(2),c(3),c(4),c(5)};
        const tpmshx::Simple2DStateView s{a(6),a(7),a(8),a(9),a(10),a(11),a(12),a(13)};
        tpmshx::Simple2DBoundaryView b{c(14),c(15),values[0],values[1],{}};
        if (!std::isnan(values[2])) b.inlet_density_reference=values[2];
        std::fill(out,out+25,std::numeric_limits<double>::quiet_NaN());
        if (operation==0) {
            tpmshx::simple_2d_predictor(h.grid(),{h.outlet.data(),h.outlet.size()},m,b,s,values[3],counts[1],values[8]);
            momentum(tpmshx::simple_2d_momentum_residual(h.grid(),m,b,s,values[8]),out);
        } else if (operation==1) {
            momentum(tpmshx::simple_2d_momentum_residual(h.grid(),m,b,s,values[8]),out);
        } else if (operation==2) {
            tpmshx::Simple2DControl control{};
            control.max_iterations=counts[0]; control.inner_sweeps=counts[1];
            control.alpha_velocity=values[3]; control.alpha_pressure=values[4]; control.alpha_density=values[5];
            control.pressure_reference_absolute=values[6]; control.gas_constant=values[7]; control.cf_anisotropy=values[8];
            control.convergence={values[9],values[10],values[11],values[12],values[13],values[14],counts[2],counts[3],counts[4]};
            control.ideal_gas=(counts[5]&1)!=0; control.massflux_inlet=(counts[5]&2)!=0; control.close_outlet_on_exit=(counts[5]&4)!=0;
            h.cancel_after=counts[6]; h.cancel_calls=0; h.progress.clear();
            control.cancel=cancel; control.progress=progress; control.context=&h;
            const auto r=h.solver->solve(m,b,s,control);
            out[0]=static_cast<double>(r.stop); out[1]=r.converged; out[2]=static_cast<double>(r.iterations);
            out[3]=r.post_closure_measured; out[4]=r.post_closure_certified; out[5]=r.legacy_residual;
            momentum(r.momentum,out);
            out[7]=r.mass.local_residual; out[8]=r.mass.global_residual; out[9]=r.mass.backflow_fraction;
            out[10]=r.mass.mass_in; out[11]=r.mass.mass_out; out[12]=static_cast<double>(r.pressure_clip_hits);
            out[13]=h.solver->massflux_target().value_or(std::numeric_limits<double>::quiet_NaN());
            out[20]=r.linear.relative_residual; out[21]=r.linear.pin_max_abs;
            out[22]=static_cast<double>(r.mass.counted_cells); out[23]=static_cast<double>(h.progress.size()/2);
            out[24]=static_cast<double>(h.cancel_calls);
        } else throw std::invalid_argument("unknown SIMPLE qualification operation");
        message(error,capacity,""); return 0;
    } catch (const std::exception& e) { message(error,capacity,e.what()); return 1; }
    catch (...) { message(error,capacity,"unknown native error"); return 2; }
}

extern "C" TPMSHX_THERMAL_API std::size_t TPMSHX_THERMAL_CALL tpmshx_simple2d_history(
    void* pointer,int kind,double* out,std::size_t capacity) noexcept {
    if (!pointer) return 0;
    const auto& h=*static_cast<Handle*>(pointer); const auto& history=h.solver->history();
    const std::vector<double>* values=nullptr;
    if (kind==0) values=&history.legacy;
    else if (kind==1) values=&history.local_mass;
    else if (kind==2) values=&history.global_mass;
    else if (kind==4) values=&h.progress;
    if (values) {
        if (out && capacity>=values->size()) std::copy(values->begin(),values->end(),out);
        return values->size();
    }
    if (kind==3) {
        const std::size_t needed=history.momentum.size()*8;
        if (out && capacity>=needed) for (std::size_t i=0;i<history.momentum.size();++i) {
            const auto& r=history.momentum[i]; const auto& m=r.residual;
            const double row[]={static_cast<double>(r.iteration),m.maximum,m.numerator[0],m.numerator[1],
                m.denominator[0],m.denominator[1],m.component[0],m.component[1]};
            std::copy(row,row+8,out+8*i);
        }
        return needed;
    }
    return 0;
}
