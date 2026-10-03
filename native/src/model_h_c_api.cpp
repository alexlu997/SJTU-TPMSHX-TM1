#include "tpmshx/model_h_c_api.h"
#include "tpmshx/model_h_3d.hpp"
#include "model_h_c_views.hpp"
#include "tpmshx/model_coefficients.hpp"
#include <algorithm>
#include <cstdio>
#include <memory>
#include <variant>

namespace {
using namespace tpmshx;
struct Owner {
    std::variant<ModelHResult2D,ModelHResult3D> result;
    std::vector<tpmshx_model_h_check_v1> finishing;
};
bool cancel(void* context) {
    const auto* c=static_cast<const tpmshx_model_h_callbacks_v1*>(context);
    return c && c->cancel && c->cancel(c->context)!=0;
}
void progress(void* context,std::size_t done,std::size_t total) {
    const auto* c=static_cast<const tpmshx_model_h_callbacks_v1*>(context);
    if (c && c->progress) c->progress(c->context,done,total);
}
}  // namespace

extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_model_h_abi_version(void) { return TPMSHX_MODEL_H_ABI_VERSION; }

extern "C" int TPMSHX_THERMAL_CALL tpmshx_solve_model_h_v1(
    const size_t* shape,double* const* arrays,const size_t* sizes,
    const tpmshx_model_h_config_v1* config,const tpmshx_model_h_callbacks_v1* callbacks,
    tpmshx_model_h_result_v1* result,char* error,size_t error_capacity) {
    if (!error || !error_capacity) return 1;
    try {
        if (!shape || !arrays || !sizes || !config || !result) throw std::invalid_argument("null model-h argument");
        const auto& c=*config;
        if ((c.dimension!=2 && c.dimension!=3) || c.fluid_a>1 || c.fluid_b>1 || c.direction_a>=2*c.dimension
            || c.direction_b>=2*c.dimension || c.warm_start>1 || c.accelerate>1 || c.red_black>1)
            throw std::invalid_argument("invalid model-h enum or flag");
        const auto v=[&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
        const auto output=[&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const TemperatureBoundary a_bc{static_cast<int>(c.direction_a),c.inlet_a,v(10),v(11),{}};
        const TemperatureBoundary b_bc{static_cast<int>(c.direction_b),c.inlet_b,v(18),v(19),{}};
        const TemperatureStateView state{output(21),output(22),output(23)};
        auto owner=std::make_unique<Owner>(); tpmshx_model_h_result_v1 local{};
        auto* callback_context=const_cast<tpmshx_model_h_callbacks_v1*>(callbacks);
        if (c.dimension==2) {
            if (sizes[4] || sizes[9] || sizes[12] || sizes[17] || sizes[20])
                throw std::invalid_argument("2D model-h has no z mass faces or explicit sources");
            if (c.alpha_a!=model_coefficients::model_h_relaxation || c.alpha_solid!=1
                || c.alpha_b!=model_coefficients::model_h_relaxation)
                throw std::invalid_argument("2D model-h requires original relaxation");
            const ModelHFluid2D a{static_cast<Fluid>(c.fluid_a),v(5),v(6),v(7),v(8),a_bc};
            const ModelHFluid2D b{static_cast<Fluid>(c.fluid_b),v(13),v(14),v(15),v(16),b_bc};
            const ModelHControl2D control{c.max_iterations,c.chunk_iterations,c.q_relative_tolerance,
                c.warm_start!=0,c.accelerate!=0,c.red_black!=0,cancel,progress,callback_context};
            owner->result=solve_model_h_2d(grid,a,b,v(3),state,control);
            model_h_c_views::plane(local,owner->finishing,std::get<ModelHResult2D>(owner->result));
        } else {
            const ModelHFluid3D a{static_cast<Fluid>(c.fluid_a),v(5),v(6),v(7),v(8),v(9),a_bc,v(12)};
            const ModelHFluid3D b{static_cast<Fluid>(c.fluid_b),v(13),v(14),v(15),v(16),v(17),b_bc,v(20)};
            const ModelHControl3D control{c.max_iterations,c.chunk_iterations,c.q_relative_tolerance,
                c.alpha_a,c.alpha_solid,c.alpha_b,c.warm_start!=0,c.accelerate!=0,c.red_black!=0,cancel,progress,callback_context};
            owner->result=solve_model_h_3d(grid,a,b,v(3),v(4),state,control);
            model_h_c_views::volume(local,owner->finishing,std::get<ModelHResult3D>(owner->result));
        }
        local.finishing_checks=owner->finishing.data(); local.finishing_count=owner->finishing.size();
        local.owner=owner.release(); *result=local; error[0]='\0'; return 0;
    } catch (const std::invalid_argument& e) {
        std::snprintf(error,error_capacity,"%s",e.what()); return 1;
    } catch (const std::domain_error& e) {
        std::snprintf(error,error_capacity,"%s",e.what()); return 2;
    } catch (const std::exception& e) {
        std::snprintf(error,error_capacity,"%s",e.what()); return 3;
    } catch (...) {
        std::snprintf(error,error_capacity,"unexpected native model-h exception"); return 3;
    }
}

extern "C" void TPMSHX_THERMAL_CALL tpmshx_model_h_release_v1(tpmshx_model_h_result_v1* result) {
    if (!result) return;
    delete static_cast<Owner*>(result->owner); *result={};
}
