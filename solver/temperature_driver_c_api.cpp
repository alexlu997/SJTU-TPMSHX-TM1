#include "tpmshx/temperature_driver_c_api.h"
#include "tpmshx/temperature_staggered.hpp"
#include <cstdio>
#include <exception>
#include <limits>
#include <memory>
#include <stdexcept>

struct tpmshx_temperature_driver_v1 { tpmshx::StaggeredTemperatureDriver staggered; };
namespace {
struct Owner { tpmshx::StaggeredTemperatureResult value; };
int fail(int status,const char* message,char* error,size_t capacity) noexcept {
    if (error && capacity) std::snprintf(error,capacity,"%s",message);
    return status;
}
bool cancelled(void* context) {
    const auto& cb=*static_cast<const tpmshx_temperature_callbacks_v1*>(context);
    return cb.cancel && cb.cancel(cb.context)!=0;
}
void progressed(void* context,size_t done,size_t total) {
    const auto& cb=*static_cast<const tpmshx_temperature_callbacks_v1*>(context);
    if (cb.progress) cb.progress(cb.context,done,total);
}
}
extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_temperature_driver_abi_version(void) {
    return TPMSHX_TEMPERATURE_DRIVER_ABI_VERSION;
}
extern "C" int TPMSHX_THERMAL_CALL tpmshx_temperature_driver_create_v1(
    tpmshx_temperature_driver_v1** driver,char* error,size_t capacity) {
    if (!driver || !error || !capacity) return fail(1,"missing temperature owner or error buffer",error,capacity);
    try {
        auto owner=std::make_unique<tpmshx_temperature_driver_v1>();
        *driver=owner.release(); error[0]='\0'; return 0;
    } catch (const std::exception& e) { return fail(3,e.what(),error,capacity); }
    catch (...) { return fail(3,"unknown temperature owner error",error,capacity); }
}
extern "C" void TPMSHX_THERMAL_CALL tpmshx_temperature_driver_destroy_v1(tpmshx_temperature_driver_v1* driver) {
    delete driver;
}
extern "C" void TPMSHX_THERMAL_CALL tpmshx_temperature_release_v1(tpmshx_temperature_result_v1* result) {
    if (!result) return;
    delete static_cast<Owner*>(result->owner); *result={};
}
extern "C" int TPMSHX_THERMAL_CALL tpmshx_solve_temperature_v1(
    tpmshx_temperature_driver_v1* driver,const size_t* shape,double* const* arrays,
    const size_t* sizes,const tpmshx_temperature_config_v1* config,
    const tpmshx_temperature_callbacks_v1* callbacks,tpmshx_temperature_result_v1* result,
    char* error,size_t capacity) {
    using namespace tpmshx;
    if (!driver || !shape || !arrays || !sizes || !config || !result || !error || !capacity)
        return fail(1,"missing temperature argument or error buffer",error,capacity);
    if (config->scheme>2 || config->direction_a>5 || config->direction_b>5 || config->warm_start>1
        || config->second_order_b>1 || config->conservative>1 || config->red_black>1 || config->accelerate>1)
        return fail(1,"invalid temperature scheme/direction/boolean",error,capacity);
    if (config->accelerate) return fail(1,"non-model-h temperature does not support acceleration",error,capacity);
    if (config->scheme!=2 && config->conservative)
        return fail(1,"conservative projection requires staggered temperature",error,capacity);
    if (config->scheme==1 && config->red_black)
        return fail(1,"CC3D temperature has no RB mode",error,capacity);
    try {
        const auto v=[&](size_t p) { return ArrayView<const double>{arrays[p],sizes[p]}; };
        const auto out=[&](size_t p) { return ArrayView<double>{arrays[p],sizes[p]}; };
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        if (config->scheme==0 && (shape[2]!=1 || sizes[2]!=1 || !arrays[2] || arrays[2][0]!=1 || sizes[12] || sizes[23]))
            throw std::invalid_argument("2D temperature requires unit depth and empty w velocities");
        const auto boundary=[&](size_t offset,size_t s) {
            return TemperatureBoundary{static_cast<int>(s==0 ? config->direction_a : config->direction_b),
                s==0 ? config->inlet_a : config->inlet_b,v(offset+7),v(offset+8),v(offset+9)};
        };
        auto cb=callbacks ? *callbacks : tpmshx_temperature_callbacks_v1{};
        const TemperatureControl control{config->max_iterations,config->chunk_iterations,config->q_relative_tolerance,
            config->alpha_a,config->alpha_solid,config->alpha_b,config->warm_start!=0,config->second_order_b!=0,
            cb.cancel ? cancelled : nullptr,cb.progress ? progressed : nullptr,&cb};
        auto owner=std::make_unique<Owner>();
        if (config->scheme==2) {
            const auto fluid=[&](size_t p,size_t s) { return StaggeredTemperatureFluid{
                v(p),v(p+1),v(p+2),v(p+3),{v(p+4),v(p+5),v(p+6)},boundary(p,s),v(p+10)}; };
            owner->value=driver->staggered.solve(grid,fluid(6,0),fluid(17,1),v(3),
                {out(28),out(29),out(30)},control,config->conservative!=0,config->red_black!=0,v(5),v(4));
        } else {
            if (!shape[0] || !shape[1] || !shape[2] || shape[0]>std::numeric_limits<size_t>::max()/shape[1]
                || shape[0]*shape[1]>std::numeric_limits<size_t>::max()/shape[2])
                throw std::invalid_argument("invalid temperature grid extent");
            const size_t cells=shape[0]*shape[1]*shape[2];
            for (size_t p:{4U,16U,27U}) if (sizes[p]) {
                if (!arrays[p] || sizes[p]!=cells) throw std::invalid_argument("temperature source extent mismatch");
                for (size_t i=0;i<cells;++i) if (arrays[p][i]!=0)
                    throw std::invalid_argument("nonzero MMS sources require staggered temperature");
            }
            const auto fluid=[&](size_t p,size_t s) { return TemperatureFluidView{
                v(p),v(p+1),v(p+2),v(p+3),v(p+4),v(p+5),v(p+6),boundary(p,s)}; };
            owner->value.iteration=solve_temperature(config->scheme==0 ? TemperatureScheme::cell_centered_2d
                : TemperatureScheme::cell_centered_3d,grid,fluid(6,0),fluid(17,1),v(3),
                {out(28),out(29),out(30)},control,v(5),config->red_black!=0);
        }
        tpmshx_temperature_result_v1 output{};
        output.scheme=config->scheme; const auto& value=owner->value;
        output.stop=static_cast<uint32_t>(value.iteration.stop); output.iterations=value.iteration.iterations;
        output.residual=value.iteration.residual; output.q_b=value.iteration.q_b;
        for (size_t s=0;s<2;++s) {
            const auto& r=value.residual[s]; const auto& p=value.projection[s];
            output.fluid[s]={r.available ? 1U : 0U,r.cells.data(),r.cells.size(),r.sum,r.maximum,r.exchange,r.global_ratio,r.cell_ratio};
            output.projection[s]={p.skipped ? 1U : 0U,p.used_bordered_lu ? 1U : 0U,p.cg_iterations,p.rhs_mean,p.residual_relative};
        }
        output.owner=owner.release(); *result=output; error[0]='\0'; return 0;
    } catch (const std::invalid_argument& e) { return fail(1,e.what(),error,capacity); }
    catch (const std::domain_error& e) { return fail(2,e.what(),error,capacity); }
    catch (const std::exception& e) { return fail(3,e.what(),error,capacity); }
    catch (...) { return fail(3,"unknown native temperature exception",error,capacity); }
}
