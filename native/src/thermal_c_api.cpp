#include "tpmshx/thermal_c_api.h"
#include "tpmshx/enthalpy_sweeps.hpp"

#include <algorithm>
#include <cstring>
#include <exception>
#include <stdexcept>

namespace {

void write_error(char* error, std::size_t capacity, const char* message) noexcept {
    if (!error || capacity == 0) return;
    const auto count = std::min(capacity - 1, std::strlen(message));
    std::memcpy(error, message, count);
    error[count] = '\0';
}

}  // namespace

extern "C" uint32_t tpmshx_thermal_abi_version(void) {
    return TPMSHX_THERMAL_ABI_VERSION;
}

extern "C" int tpmshx_enthalpy_sweeps_v1(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const double* scalars, size_t sweeps, uint64_t* clips,
    char* error, size_t error_capacity) {
    try {
        if (!error || error_capacity == 0)
            throw std::invalid_argument("error buffer must have positive capacity");
        error[0] = '\0';
        if (!shape) throw std::invalid_argument("null shape pointer");
        if (!arrays) throw std::invalid_argument("null array table pointer");
        if (!sizes) throw std::invalid_argument("null size table pointer");
        if (!scalars) throw std::invalid_argument("null scalar table pointer");
        if (!clips) throw std::invalid_argument("null clip output pointer");
        for (std::size_t i = 0; i < 23; ++i)
            if (!arrays[i]) throw std::invalid_argument("null array data pointer");

        using namespace tpmshx;
        const auto view = [&](std::size_t i) {
            return ArrayView<const double>{arrays[i], sizes[i]};
        };
        const auto state_view = [&](std::size_t i) {
            return ArrayView<double>{arrays[i], sizes[i]};
        };
        const GridView grid{shape[0], shape[1], shape[2], view(0), view(1), view(2)};
        const ThermalStateView state{state_view(3), state_view(4), state_view(5)};
        const FluidView a{view(6), view(7), view(8), view(9), view(10),
                          view(11), view(12), view(13), scalars[0], scalars[2], scalars[3]};
        const FluidView b{view(14), view(15), view(16), view(17), view(18),
                          view(19), view(20), view(21), scalars[1], scalars[4], scalars[5]};
        const auto result = enthalpy_sweeps(grid, a, b, view(22), state, sweeps, scalars[6]);
        clips[0] = result.a;
        clips[1] = result.b;
        return 0;
    } catch (const std::invalid_argument& exc) {
        write_error(error, error_capacity, exc.what());
        return 1;
    } catch (const std::domain_error& exc) {
        write_error(error, error_capacity, exc.what());
        return 2;
    } catch (const std::exception& exc) {
        write_error(error, error_capacity, exc.what());
        return 3;
    } catch (...) {
        write_error(error, error_capacity, "unknown native exception");
        return 3;
    }
}
