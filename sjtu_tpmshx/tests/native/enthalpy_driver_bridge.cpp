// Qualification fixture for the public C++ complete true-h driver.
#include "tpmshx/enthalpy_driver.hpp"
#include "tpmshx/thermal_c_api.h"

#include <cstdio>
#include <exception>

namespace {
struct Callback { std::size_t calls = 0, cancel_at; };
bool cancel(void* pointer) {
    auto& c = *static_cast<Callback*>(pointer);
    return ++c.calls == c.cancel_at;
}
int failure(char* error, std::size_t capacity, const std::exception& exception) {
    if (capacity) std::snprintf(error,capacity,"%s",exception.what());
    return 1;
}
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_enthalpy_driver(
    const std::size_t* shape, double** arrays, const std::size_t* sizes,
    const std::size_t* config, const double* values, const char* table_directory,
    std::size_t* status, double* metrics, char* error, std::size_t capacity) {
    using namespace tpmshx;
    const auto v = [&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
    const auto out = [&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
    Callback callback{0,config[7]};
    try {
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const EnthalpySideView a{static_cast<Fluid>(config[0]),values[0],values[1],
                                v(4),v(5),v(6),v(7),v(8),v(9)};
        const EnthalpySideView b{static_cast<Fluid>(config[1]),values[2],values[3],
                                v(10),v(11),v(12),v(13),v(14),v(15)};
        EnthalpyControl control{config[2],config[3],values[4],values[5],{},{},
                                table_directory ? table_directory : "",cancel,&callback};
        if (config[8]) control.coupled_energy_tolerance = values[6];
        if (config[9]) control.equation_energy_tolerance = values[7];
        const EnthalpyStateView state{out(16),out(17),out(18),out(19),out(20),
                                      config[4] != 0,config[5] != 0,config[6] != 0};
        const auto result = solve_enthalpy(grid,a,b,v(3),state,control);
        status[0] = static_cast<std::size_t>(result.stop);
        status[1] = result.iterations;
        status[2] = callback.calls;
        status[3] = result.last_clips.a; status[4] = result.last_clips.b;
        status[5] = result.total_clips.a; status[6] = result.total_clips.b;
        status[7] = result.used_bicubic[0]; status[8] = result.used_bicubic[1];
        status[9] = result.heos_polish; status[10] = result.final_audit.has_value();
        metrics[0] = result.residual; metrics[1] = result.q_a; metrics[2] = result.q_b;
        metrics[3] = result.energy_imbalance;
        metrics[4] = result.inlet_enthalpy[0]; metrics[5] = result.inlet_enthalpy[1];
        if (result.final_audit) {
            const auto& audit = *result.final_audit;
            status[11] = audit.fluid_equations_computed;
            const double data[] = {audit.q_a,audit.q_b,audit.net,audit.solid_abs_sum,audit.denominator,
                audit.coupled_ratio,audit.fluid_abs_sum[0],audit.fluid_abs_sum[1],
                audit.fluid_cell_max[0],audit.fluid_cell_max[1],audit.equation_ratio};
            for (std::size_t i = 0; i < 11; ++i) metrics[6+i] = data[i];
        }
        if (capacity) error[0] = '\0';
        return 0;
    } catch (const WaterStateError& exception) {
        status[2] = callback.calls; failure(error,capacity,exception); return 2;
    } catch (const std::exception& exception) {
        status[2] = callback.calls; return failure(error,capacity,exception);
    }
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_enthalpy_tables(
    const char* directory, char* error, std::size_t capacity) {
    try { tpmshx::configure_eos_tables_once(directory); return 0; }
    catch (const std::exception& exception) { return failure(error,capacity,exception); }
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_coupled_only_audit(
    double* metrics, double* fluid_residuals, char* error, std::size_t capacity) {
    using namespace tpmshx;
    try {
        const double d = .01, h = 3e5, ta = 350., tb = 300., ts = 325., hv = 1000., ks = 10.;
        const double zero[] = {0.,0.};
        const auto v = [](const double& a) { return ArrayView<const double>{&a,1}; };
        const ArrayView<const double> mass{zero,2};
        // Null conductivity deliberately cannot be read. A coupled-only
        // caller has neither requested nor computed final transport values.
        const FluidEnergyView a{v(h),v(ta),v(hv),{nullptr,17},mass,mass,mass,h};
        const FluidEnergyView b{v(h),v(tb),v(hv),{nullptr,17},mass,mass,mass,h};
        double rs = 0.;
        const auto r = thermal_energy_audit({1,1,1,v(d),v(d),v(d)},a,b,v(ts),v(ks),
            {fluid_residuals,1},{fluid_residuals+1,1},{&rs,1},false);
        const double data[] = {r.coupled_ratio,r.solid_abs_sum,r.equation_ratio,
            r.fluid_abs_sum[0],r.fluid_abs_sum[1],r.fluid_cell_max[0],r.fluid_cell_max[1],
            r.fluid_equations_computed ? 1. : 0.,rs};
        for (std::size_t i = 0; i < 9; ++i) metrics[i] = data[i];
        return 0;
    } catch (const std::exception& exception) { return failure(error,capacity,exception); }
}
