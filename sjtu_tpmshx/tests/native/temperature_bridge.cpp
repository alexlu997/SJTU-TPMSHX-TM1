// Test-only FFI: production users call the C++ fixed-coefficient driver.
#include "tpmshx/temperature_driver.hpp"
#include "tpmshx/thermal_c_api.h"

#include <algorithm>
#include <cstdio>
#include <stdexcept>

namespace {
struct Callbacks {
    std::size_t cancel_at, cancel_calls = 0, progress_calls = 0, last_progress = 0;
};
bool cancelled(void* context) {
    auto& cb = *static_cast<Callbacks*>(context);
    ++cb.cancel_calls;
    return cb.cancel_at != 0 && cb.cancel_calls >= cb.cancel_at;
}
void progress(void* context, std::size_t done, std::size_t) {
    auto& cb = *static_cast<Callbacks*>(context);
    ++cb.progress_calls;
    cb.last_progress = done;
}
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_temperature_driver(
    const std::size_t* shape, double** arrays, const std::size_t* sizes,
    const std::size_t* config, const double* values,
    std::size_t* status, double* metrics, char* error, std::size_t error_size) {
    using namespace tpmshx;
    const auto v = [&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
    const auto out = [&](std::size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
    const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
    const TemperatureFluidView a{v(6),v(7),v(8),v(9),v(10),v(11),v(12),
        {static_cast<int>(config[5]),values[0],v(13),v(14),v(15)}};
    const TemperatureFluidView b{v(16),v(17),v(18),v(19),v(20),v(21),v(22),
        {static_cast<int>(config[6]),values[1],v(23),v(24),v(25)}};
    Callbacks callbacks{config[7]};
    TemperatureControl control{config[1],config[2],values[2],values[3],values[4],values[5],
                               config[3] != 0,config[4] != 0,cancelled,progress,&callbacks};
    try {
        const auto result = solve_temperature(static_cast<TemperatureScheme>(config[0]),
            grid,a,b,v(26),{out(3),out(4),out(5)},control,v(27),config[8]!=0);
        status[0] = static_cast<std::size_t>(result.stop);
        status[1] = result.iterations;
        status[2] = callbacks.cancel_calls;
        status[3] = callbacks.progress_calls;
        status[4] = callbacks.last_progress;
        metrics[0] = result.residual;
        metrics[1] = result.q_b;
        if (error_size) error[0] = '\0';
        return 0;
    } catch (const std::invalid_argument& exc) {
        if (error_size) std::snprintf(error,error_size,"%s",exc.what());
        return 1;
    } catch (const std::domain_error& exc) {
        if (error_size) std::snprintf(error,error_size,"%s",exc.what());
        return 2;
    } catch (...) {
        if (error_size) std::snprintf(error,error_size,"unexpected temperature exception");
        return 3;
    }
}
