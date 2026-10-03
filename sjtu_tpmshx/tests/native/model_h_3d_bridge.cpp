// Test-only bridge for the typed complete 3D model-h driver.
#include "tpmshx/model_h_3d.hpp"
#include "tpmshx/thermal_c_api.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>

namespace {
struct Callbacks { std::size_t cancel_at,calls=0,progress=0,last=0; };
bool cancel(void* context) { auto& c=*static_cast<Callbacks*>(context); return ++c.calls>=c.cancel_at && c.cancel_at>0; }
void progress(void* context,std::size_t done,std::size_t) {
    auto& c=*static_cast<Callbacks*>(context); ++c.progress; c.last=done;
}
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_model_h_3d(
    const std::size_t* shape,double** arrays,const std::size_t* sizes,
    const std::size_t* config,const double* values,std::size_t* status,
    double* metrics,char* error,std::size_t error_size) {
    using namespace tpmshx;
    const auto v=[&](std::size_t p) { return ArrayView<const double>{arrays[p],sizes[p]}; };
    const auto out=[&](std::size_t p) { return ArrayView<double>{arrays[p],sizes[p]}; };
    const auto copy=[&](std::size_t p,const std::vector<double>& data) {
        if (sizes[p]!=data.size()) throw std::invalid_argument("3D bridge output extent mismatch");
        std::copy(data.begin(),data.end(),arrays[p]);
    };
    try {
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const ModelHFluid3D a{static_cast<Fluid>(config[5]),v(8),v(9),v(10),v(11),v(12),
            {static_cast<int>(config[7]),values[0],v(13),v(14),{}},v(15)};
        const ModelHFluid3D b{static_cast<Fluid>(config[6]),v(16),v(17),v(18),v(19),v(20),
            {static_cast<int>(config[8]),values[1],v(21),v(22),{}},v(23)};
        Callbacks cb{config[9]};
        const ModelHControl3D control{config[0],config[1],values[2],values[3],values[4],values[5],
            config[2]!=0,config[3]!=0,config[4]!=0,cancel,progress,&cb};
        const auto result=solve_model_h_3d(grid,a,b,v(6),v(7),{out(3),out(4),out(5)},control);
        const auto& audit=result.audit;
        const std::size_t initial[]{static_cast<std::size_t>(result.stop),result.iterations,cb.calls,cb.progress,cb.last,
            result.audit_available,result.has_sources,audit.boundary_complete,audit.passed};
        std::copy(std::begin(initial),std::end(initial),status);
        for (std::size_t i=0;i<6;++i) status[9+i]=audit.gates[i];
        for (std::size_t i=0;i<2;++i) {
            status[15+i]=audit.sides[i].boundary_complete;
            for (std::size_t f=0;f<6;++f) status[17+6*i+f]=audit.sides[i].boundaries[f].unknown_inflow_count;
        }
        status[29]=result.finishing_checks.size();
        metrics[0]=result.residual; metrics[1]=result.q_b;
        if (result.audit_available) {
            copy(24,audit.sides[0].residual); copy(25,audit.sides[1].residual); copy(26,audit.solid_residual);
            copy(27,audit.sides[0].inlet_diffusion); copy(28,audit.sides[1].inlet_diffusion);
            std::size_t pos=2;
            for (std::size_t i=0;i<2;++i) {
                const auto& s=audit.sides[i];
                const double side[]{s.temperature_min,s.temperature_max,s.mass_net,s.advective_in,s.diffusion_in,
                    s.numerical_external_in,s.exchange,s.source,s.residual_sum,s.residual_max,s.normalization,
                    s.global_ratio,s.cell_ratio};
                for (double value:side) metrics[pos++]=value;
            }
            for (std::size_t i=0;i<2;++i) for (std::size_t f=0;f<6;++f) {
                const auto& bc=audit.sides[i].boundaries[f];
                const double boundary[]{bc.mass_out,bc.enthalpy_out,bc.unknown_mass_in,bc.inlet_reverse_mass_out};
                for (double value:boundary) metrics[pos++]=value;
                copy(29+6*i+f,bc.enthalpy_faces);
            }
            const double total[]{audit.volume,audit.numerical_external_in,audit.explicit_source,audit.solid_sum,
                audit.solid_max,audit.full_residual_sum,audit.telescoping_error,audit.ltne_source_ratio};
            for (double value:total) metrics[pos++]=value;
            if (sizes[41]<7*result.finishing_checks.size()) throw std::invalid_argument("3D bridge trace too small");
            pos=0;
            for (const auto& check:result.finishing_checks) {
                arrays[41][pos++]=static_cast<double>(check.iterations);
                for (bool gate:check.gates) arrays[41][pos++]=gate;
            }
        }
        if (error_size) error[0]='\0';
        return 0;
    } catch (const std::invalid_argument& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 1;
    } catch (const std::domain_error& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 2;
    } catch (const std::exception& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 3;
    }
}
