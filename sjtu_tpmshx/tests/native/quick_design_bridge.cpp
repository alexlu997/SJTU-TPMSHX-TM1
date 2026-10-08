// Qualification-only FFI; production users call the C++ QD driver directly.
#include "tpmshx/quick_design_driver.hpp"
#include "tpmshx/thermal_c_api.h"

#include <cstdio>
#include <exception>

namespace {
struct Callbacks {
    std::size_t cancel_at, inject_side, inject_percent;
    std::size_t cancel_calls = 0, progress_calls = 0, last_progress = 0;
    double* a;
    double* b;
};
bool cancelled(void* pointer) {
    auto& cb = *static_cast<Callbacks*>(pointer);
    ++cb.cancel_calls;
    return cb.cancel_at && cb.cancel_calls >= cb.cancel_at;
}
void progress(void* pointer, unsigned percent) {
    auto& cb = *static_cast<Callbacks*>(pointer);
    ++cb.progress_calls;
    cb.last_progress = percent;
    if (cb.inject_side && percent >= cb.inject_percent)
        (cb.inject_side == 1 ? cb.a : cb.b)[0] = 500.;
}
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_quick_design_driver(
    const std::size_t* shape, double** arrays, const std::size_t* sizes,
    const std::size_t* config, const double* values,
    std::size_t* status, double* metrics, char* error, std::size_t error_size) {
    using namespace tpmshx;
    const auto view = [&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
    const auto out = [&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
    const GridView grid{shape[0],shape[1],shape[2],view(0),view(1),view(2)};
    const QuickDesignGeometry geometry{values[0],values[1],values[2],values[3],values[4],values[5],
                                       view(3),view(4),view(5)};
    const QuickDesignSide a{static_cast<Fluid>(config[3]),values[6],values[7],values[8],values[9]};
    const QuickDesignSide b{static_cast<Fluid>(config[4]),values[10],values[11],values[12],values[13]};
    Callbacks callbacks{config[8],config[9],config[10],0,0,0,arrays[6],arrays[7]};
    const QuickDesignControl control{config[5],config[6],values[14],values[15],config[7] != 0,
                                    cancelled,progress,&callbacks};
    const auto fail = [&](int code, const std::exception& exception) {
        status[2] = callbacks.cancel_calls;
        status[3] = callbacks.progress_calls;
        status[4] = callbacks.last_progress;
        if (error_size) std::snprintf(error,error_size,"%s",exception.what());
        return code;
    };
    try {
        const auto result = solve_quick_design(grid,geometry,static_cast<Topology>(config[0]),
            static_cast<QuickDesignArrangement>(config[1]),static_cast<QuickDesignProperties>(config[2]),
            a,b,{out(6),out(7),out(8)},control);
        status[0] = static_cast<std::size_t>(result.stop);
        status[1] = result.completed_passes;
        status[2] = callbacks.cancel_calls;
        status[3] = callbacks.progress_calls;
        status[4] = callbacks.last_progress;
        for (std::size_t pass = 0; pass < 2; ++pass) {
            const auto& p = result.passes[pass];
            status[5+pass*2] = static_cast<std::size_t>(p.thermal.stop);
            status[6+pass*2] = p.thermal.iterations;
            metrics[40+pass*2] = p.thermal.residual;
            metrics[41+pass*2] = p.thermal.q_b;
            for (std::size_t side = 0; side < 2; ++side) {
                const auto& s = p.sides[side];
                const std::array<double,10> scalars{s.evaluation_temperature,s.properties.rho,s.properties.mu,
                    s.properties.k,s.properties.cp,s.properties.pr,s.reynolds,s.speed,s.hv,s.conductivity};
                for (std::size_t i = 0; i < scalars.size(); ++i) metrics[pass*20+side*10+i] = scalars[i];
            }
        }
        for (std::size_t side = 0; side < 2; ++side) {
            status[9+side] = result.pressure[side].choked;
            metrics[44+side*2] = result.pressure[side].inlet;
            metrics[45+side*2] = result.pressure[side].outlet;
        }
        if (error_size) error[0] = '\0';
        return 0;
    } catch (const QuickDesignWaterFieldError& exception) { return fail(2,exception); }
    catch (const WaterStateError& exception) { return fail(1,exception); }
    catch (const std::invalid_argument& exception) { return fail(3,exception); }
    catch (const std::domain_error& exception) { return fail(4,exception); }
    catch (const std::exception& exception) { return fail(5,exception); }
}
