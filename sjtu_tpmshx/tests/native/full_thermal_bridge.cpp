// Qualification only: strict fullCC uses the existing typed model-h drivers.
// This bridge adds no production ABI and performs no iteration or field repair.
#include "tpmshx/model_h_2d.hpp"
#include "enthalpy_c_views.hpp"
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

// Test the original Python outer with the selected native thermal component.
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_full_thermal_selected(
    const std::size_t* shape,double* const* arrays,const std::size_t* sizes,
    const tpmshx_enthalpy_config_v1* config,const tpmshx_enthalpy_callbacks_v1* callbacks,
    tpmshx_enthalpy_result_v1* result,char* error,std::size_t error_size,
    const double* conductivity_a,const double* conductivity_b) {
    using namespace tpmshx;
    try {
        const auto v=[&](std::size_t i) {return ArrayView<const double>{arrays[i],sizes[i]};};
        const auto out=[&](std::size_t i) {return ArrayView<double>{arrays[i],sizes[i]};};
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const auto side=[&](std::size_t s) {
            const auto offset=4+6*s;
            const auto fluid=static_cast<Fluid>(config->sides[s].fluid);
            const bool eos=uses_co2_eos(fluid);
            return EnthalpySideView{fluid,config->sides[s].inlet_temperature,config->sides[s].inlet_pressure,
                v(offset),v(offset+1),v(offset+2),v(offset+3),v(offset+4),v(offset+5),-1,
                eos?EnergyRelation::eos_h_TP:EnergyRelation::integral_cp_T,
                eos?ConductivitySource::local_eos:ConductivitySource::outer_transport,
                eos?ArrayView<const double>{}:ArrayView<const double>{s?conductivity_b:conductivity_a,sizes[offset]}};
        };
        EnthalpyControl control{config->max_iterations,config->sweeps,config->omega,
            config->update_tolerance,{},{},config->table_directory?config->table_directory:""};
        control.reference_independent_update=true;
        if(config->coupled_gate)control.coupled_energy_tolerance=config->coupled_tolerance;
        if(config->equation_gate)control.equation_energy_tolerance=config->equation_tolerance;
        control.context=const_cast<tpmshx_enthalpy_callbacks_v1*>(callbacks);
        control.cancel=[](void* context) {
            const auto* cb=static_cast<const tpmshx_enthalpy_callbacks_v1*>(context);
            return cb && cb->cancel && cb->cancel(cb->context)!=0;
        };
        const auto native=solve_enthalpy(grid,side(0),side(1),v(3),
            {out(16),out(17),out(18),out(19),out(20),config->warm_a!=0,
             config->warm_b!=0,config->warm_solid!=0},control);
        *result=enthalpy_c_view(native);
        if(error_size)error[0]='\0';
        return 0;
    } catch(const std::exception& e) {
        if(error_size)std::snprintf(error,error_size,"%s",e.what());
        return 1;
    }
}
