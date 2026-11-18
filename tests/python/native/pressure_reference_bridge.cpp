// Qualification bridge only; production outer drivers call the C++ API.
#include "tpmshx/pressure_reference.hpp"
#include "tpmshx/thermal_c_api.h"

#include <algorithm>
#include <cstdio>
#include <iomanip>
#include <sstream>

namespace {
using namespace tpmshx;
template<class F> int checked(F operation,char* error,std::size_t capacity) {
    if (capacity) error[0]='\0';
    try { operation(); return 0; }
    catch (const ChokedFlowError& e) { if (capacity) std::snprintf(error,capacity,"%s",e.what()); return 4; }
    catch (const std::invalid_argument& e) { if (capacity) std::snprintf(error,capacity,"%s",e.what()); return 1; }
    catch (const std::domain_error& e) { if (capacity) std::snprintf(error,capacity,"%s",e.what()); return 2; }
    catch (const std::exception& e) { if (capacity) std::snprintf(error,capacity,"%s",e.what()); return 3; }
}
std::string history_json(const std::vector<PressureIteration>& history) {
    std::ostringstream out;
    out<<std::setprecision(17)<<'[';
    for (std::size_t i=0;i<history.size();++i) {
        if(i) out<<',';
        const auto& h=history[i];
        out<<"{\"stage\":\""<<h.stage<<"\",\"anchor_Pa\":"<<h.anchor_Pa;
        if(h.estimate_Pa2) out<<",\"estimate_Pa2\":"<<*h.estimate_Pa2;
        if(h.relative_error) out<<",\"relative_error\":"<<*h.relative_error;
        if(h.target_Pa2) out<<",\"target_Pa2\":"<<*h.target_Pa2;
        if(h.step_fraction) out<<",\"step_fraction\":"<<*h.step_fraction;
        if(h.method) out<<",\"method\":\""<<*h.method<<'"';
        out<<'}';
    }
    return out.str()+']';
}
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_pressure_state(
    const std::size_t* shape,const double* const* arrays,double reference,double specified,
    double* result,char* definition,char* error,std::size_t capacity) {
    return checked([&] {
        const GridView g{shape[0],shape[1],shape[2],{arrays[0],shape[0]},
                         {arrays[1],shape[1]},{arrays[2],shape[2]}};
        const auto s=inlet_pressure_state(g,{arrays[3],g.nx*g.ny*g.nz},
             {arrays[4],g.nx*g.nz},{arrays[5],g.nx*g.nz},reference,specified);
        const double values[]={s.specified_Pa,s.realized_Pa,s.outlet_Pa,s.outlet_gauge_Pa,
            s.minimum_Pa,s.relative_error,s.relative_tolerance,static_cast<double>(s.passed)};
        std::copy(std::begin(values),std::end(values),result);
        std::snprintf(definition,capacity,"%s",s.definition.c_str());
    },error,capacity);
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_pressure_step(
    int operation,const double* values,double* result,char* history,char* error,std::size_t capacity) {
    return checked([&] {
        std::vector<PressureIteration> h;
        if(operation==0) result[0]=pressure_initial_reference(values[0],values[1],h);
        else {
            if(operation==2) pressure_initial_reference(values[7],values[0],h);
            const PressurePortState state{values[0],values[1],values[2],values[3],values[4],
                                          values[5],values[6],false,""};
            result[1]=pressure_shooting_target_sq(state);
            result[0]=pressure_shooting_reference(state,h);
        }
        std::snprintf(history,capacity,"%s",history_json(h).c_str());
    },error,capacity);
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_pressure_envelope(
    const double* values,int supplied_ma,const char* mode,const char* dims,
    int* valid,char* reasons,char* error,std::size_t capacity) {
    return checked([&] {
        const auto result=gate_solution(values[0],values[1],values[2],mode,dims,values[3],
            values[4],values[5],supplied_ma ? std::optional<double>(values[6]) : std::nullopt);
        *valid=result.valid;
        std::string text;
        for(std::size_t i=0;i<result.reasons.size();++i) {
            if(i) text+='\n';
            text+=result.reasons[i];
        }
        std::snprintf(reasons,capacity,"%s",text.c_str());
    },error,capacity);
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_pressure_mach(
    int operation,const double* speed,std::size_t ns,const double* temperature,std::size_t nt,
    const double* values,double* result,char* error,std::size_t capacity) {
    return checked([&] {
        if(operation==0) *result=mach_field_max({speed,ns},{temperature,nt},values[0],values[1]);
        else if(operation==1) *result=mach(speed[0],temperature[0],values[0],values[1]);
        else *result=predict_outlet_p_sq(values[2],temperature[0],values[3],values[4],values[0]);
    },error,capacity);
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_port_overlap(
    const double* widths,std::size_t size,double lo,double hi,int staggered,
    double* result,char* error,std::size_t capacity) {
    return checked([&] {
        const auto values=port_overlap_1d({widths,size},lo,hi,staggered!=0);
        std::copy(values.begin(),values.end(),result);
    },error,capacity);
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_port_fractions(
    const double* widths,std::size_t size,double lo,double hi,int uniform,
    double* geometric,double* profile,char* error,std::size_t capacity) {
    return checked([&] {
        const auto values=port_fractions_1d({widths,size},lo,hi,uniform!=0);
        std::copy(values.first.begin(),values.first.end(),geometric);
        std::copy(values.second.begin(),values.second.end(),profile);
    },error,capacity);
}
