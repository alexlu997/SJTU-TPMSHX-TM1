// Qualification-only bridge. Production callers use the typed C++ interface.
#include "tpmshx/model_h_2d.hpp"
#include "tpmshx/thermal_c_api.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {
thread_local std::vector<std::vector<double>> progress_states;
struct Callbacks { std::size_t cancel_at, calls=0, progress=0, last=0;
    bool capture=false; tpmshx::TemperatureStateView state{}; };
bool cancel(void* context) {
    auto& c=*static_cast<Callbacks*>(context);
    return ++c.calls>=c.cancel_at && c.cancel_at>0;
}
void progress(void* context, std::size_t done, std::size_t) {
    auto& c=*static_cast<Callbacks*>(context); ++c.progress; c.last=done;
    if (c.capture) {
        std::vector<double> row{static_cast<double>(done)};
        for (auto field:{c.state.a,c.state.b,c.state.solid})
            row.insert(row.end(),field.data,field.data+field.size);
        progress_states.push_back(std::move(row));
    }
}
}
// These getters belong only to the qualification bridge.
extern "C" TPMSHX_THERMAL_API std::size_t TPMSHX_THERMAL_CALL test_model_h_progress_size() {
    return progress_states.size();
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_model_h_progress_read(
    std::size_t index,double* values,std::size_t capacity) {
    if (index>=progress_states.size() || capacity!=progress_states[index].size()) return 1;
    const auto& row=progress_states[index];
    std::copy(row.begin(),row.end(),values);
    return 0;
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_model_h_2d(
    const std::size_t* shape, double** arrays, const std::size_t* sizes,
    const std::size_t* config, const double* values, std::size_t* status,
    double* metrics, char* error, std::size_t error_size) {
    using namespace tpmshx;
    const auto v=[&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
    const auto out=[&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
    const auto copy=[&](std::size_t i, const std::vector<double>& data) {
        if (sizes[i]!=data.size()) throw std::invalid_argument("bridge output extent mismatch");
        std::copy(data.begin(),data.end(),arrays[i]);
    };
    progress_states.clear();
    try {
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const ModelHFluid2D a{static_cast<Fluid>(config[5]),v(7),v(8),v(9),v(10),
            {static_cast<int>(config[7]),values[0],v(11),v(12),{}}};
        const ModelHFluid2D b{static_cast<Fluid>(config[6]),v(13),v(14),v(15),v(16),
            {static_cast<int>(config[8]),values[1],v(17),v(18),{}}};
        Callbacks cb{config[9]};
        cb.capture=config[10]!=0; cb.state={out(3),out(4),out(5)};
        ModelHControl2D control{config[0],config[1],values[2],config[2]!=0,
            config[3]!=0,config[4]!=0,cancel,progress,&cb};
        control.strict_energy_balance=config[11]!=0;
        const auto result=solve_model_h_2d(grid,a,b,v(6),{out(3),out(4),out(5)},control);
        const auto& audit=result.audit;
        const std::size_t stats[]{static_cast<std::size_t>(result.stop),result.iterations,cb.calls,cb.progress,cb.last,
            result.audit_available,audit.sides[0].unknown_inflow_faces,audit.sides[1].unknown_inflow_faces,
            audit.boundary_complete,audit.finite,audit.energy_ok,audit.solid_ok,audit.equations_ok,audit.passed,
            result.finishing_checks.size()};
        std::copy(std::begin(stats),std::end(stats),status);
        metrics[0]=result.residual; metrics[1]=result.q_b;
        if (result.physical_audit_available) { copy(19,result.last_a); copy(20,result.last_b); }
        if (result.audit_available) {
            copy(19,result.last_a); copy(20,result.last_b);
            copy(21,audit.sides[0].residual); copy(22,audit.sides[1].residual); copy(23,audit.solid_residual);
            copy(24,audit.sides[0].linearization_defect); copy(25,audit.sides[1].linearization_defect);
            copy(26,audit.sides[0].h_faces[0]); copy(27,audit.sides[0].h_faces[1]);
            copy(28,audit.sides[1].h_faces[0]); copy(29,audit.sides[1].h_faces[1]);
            copy(30,audit.sides[0].inlet_conduction_faces); copy(31,audit.sides[1].inlet_conduction_faces);
            std::size_t pos=2;
            for (const auto& s:audit.sides) {
                const double values_side[]{s.q_advective,s.inlet_conduction,s.exchange,s.residual_sum,s.residual_max,
                    s.linearized_sum,s.linearized_max,s.defect_sum,s.defect_max,s.mass_net,s.mass_local_max,
                    s.mass_in,s.mass_out,s.normalization,s.cell_ratio};
                for (double value:values_side) metrics[pos++]=value;
            }
            const double values_audit[]{audit.solid_sum,audit.solid_max,audit.solid_cell_ratio,audit.residual_sum,
                audit.telescoping_error,audit.net_boundary_in,audit.denominator,audit.energy_imbalance,audit.solid_imbalance};
            for (double value:values_audit) metrics[pos++]=value;
            if (sizes[32]<3*result.finishing_checks.size()) throw std::invalid_argument("bridge trace too small");
            pos=0;
            for (const auto& check:result.finishing_checks) {
                arrays[32][pos++]=static_cast<double>(check.iterations);
                arrays[32][pos++]=check.passed; arrays[32][pos++]=check.equations_ok;
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
