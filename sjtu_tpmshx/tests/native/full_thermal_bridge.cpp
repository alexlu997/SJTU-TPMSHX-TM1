// Qualification only: strict fullCC uses the existing typed model-h drivers.
// This bridge adds no production ABI and performs no iteration or field repair.
#include "tpmshx/model_h_2d.hpp"
#include "tpmshx/model_h_3d.hpp"
#include "tpmshx/model_h_c_api.h"
#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/thermal_c_api.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>

namespace {
bool cancelled(void* context) {
    const auto& cb=*static_cast<const tpmshx_model_h_callbacks_v1*>(context);
    return cb.cancel && cb.cancel(cb.context);
}
void progressed(void* context,std::size_t done,std::size_t total) {
    const auto& cb=*static_cast<const tpmshx_model_h_callbacks_v1*>(context);
    if(cb.progress) cb.progress(cb.context,done,total);
}
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_full_thermal_strict(
    const std::size_t* shape,double** arrays,const std::size_t* sizes,
    const std::size_t* config,const double* values,const tpmshx_model_h_callbacks_v1* callbacks,std::size_t* status,
    double* metrics,char* error,std::size_t error_size) {
    using namespace tpmshx;
    const auto v=[&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
    const auto out=[&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
    try {
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const TemperatureStateView state{out(3),out(4),out(5)};
        const auto bc=[&](std::size_t s) {
            return TemperatureBoundary{static_cast<int>(config[6+s]),values[s],
                                       v(17+2*s),v(18+2*s),{}};
        };
        PhysicalHeatLedger ledger;
        TemperatureResult iteration;
        bool available=false;
        double ratio=0.;
        if(config[0]==2) {
            const auto phase=[&](std::size_t s) {
                return ModelHFluid2D{static_cast<Fluid>(config[8+s]),v(6+s),v(9+s),
                                    v(11+3*s),v(12+3*s),bc(s)};
            };
            ModelHControl2D control{config[1],config[2],values[2],bool(config[3]),
                                    bool(config[4]),bool(config[5])};
            control.cancel=cancelled;control.progress=progressed;
            control.context=const_cast<tpmshx_model_h_callbacks_v1*>(callbacks);
            control.second_order_b=false;control.strict_energy_balance=true;
            const auto result=solve_model_h_2d(grid,phase(0),phase(1),v(8),state,control,{},&ledger);
            iteration={result.stop,result.iterations,result.residual,result.q_b};
            available=result.physical_audit_available;ratio=result.energy_error_ratio;
        } else if(config[0]==3) {
            const auto phase=[&](std::size_t s) {
                return ModelHFluid3D{static_cast<Fluid>(config[8+s]),v(6+s),v(9+s),
                    v(11+3*s),v(12+3*s),v(13+3*s),bc(s),{}};
            };
            ModelHControl3D control{config[1],config[2],values[2],values[3],values[4],values[5],
                                    bool(config[3]),bool(config[4]),bool(config[5])};
            control.cancel=cancelled;control.progress=progressed;
            control.context=const_cast<tpmshx_model_h_callbacks_v1*>(callbacks);
            control.strict_energy_balance=true;
            const auto result=solve_model_h_3d(grid,phase(0),phase(1),v(8),{},state,control,{},&ledger);
            iteration={result.stop,result.iterations,result.residual,result.q_b};
            available=result.physical_audit_available;ratio=result.energy_error_ratio;
        } else throw std::invalid_argument("full thermal test dimension");
        status[0]=static_cast<std::size_t>(iteration.stop);status[1]=iteration.iterations;
        status[2]=available;status[3]=ledger.boundary_complete;
        metrics[0]=iteration.residual;metrics[1]=iteration.q_b;metrics[2]=ratio;
        for(std::size_t s=0;s<2;++s) {
            metrics[3+s]=0.;
            for(const auto& face:ledger.advective_out[s]) for(double power:face) metrics[3+s]-=power;
        }
        if(error_size) error[0]='\0';
        return 0;
    } catch(const std::exception& e) {
        if(error_size) std::snprintf(error,error_size,"%s",e.what());
        return 1;
    }
}
