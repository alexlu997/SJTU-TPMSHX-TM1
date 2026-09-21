// Test-only energy-audit bridge; sweep tests use the production C API.
#include "tpmshx/enthalpy_sweeps.hpp"
#include <stdexcept>

extern "C" int test_thermal_energy_audit(const std::size_t* shape, double** arrays,
                                        const std::size_t* sizes, const double* hin,
                                        double* metrics) {
    using namespace tpmshx;
    const auto v = [&](std::size_t i) { return ArrayView<const double>{arrays[i], sizes[i]}; };
    const auto out = [&](std::size_t i) { return ArrayView<double>{arrays[i], sizes[i]}; };
    const GridView grid{shape[0], shape[1], shape[2], v(0), v(1), v(2)};
    const FluidEnergyView a{v(3), v(6), v(10), v(8), v(13), v(14), v(15), hin[0]};
    const FluidEnergyView b{v(4), v(7), v(11), v(9), v(16), v(17), v(18), hin[1]};
    try {
        const auto r = thermal_energy_audit(grid, a, b, v(5), v(12), out(19), out(20), out(21));
        const double values[] = {r.q_a, r.q_b, r.net, r.solid_abs_sum, r.denominator,
            r.coupled_ratio, r.fluid_abs_sum[0], r.fluid_abs_sum[1],
            r.fluid_cell_max[0], r.fluid_cell_max[1], r.equation_ratio};
        for (std::size_t i = 0; i < 11; ++i) metrics[i] = values[i];
        return 0;
    } catch (const std::invalid_argument&) {
        return 1;
    } catch (const std::domain_error&) {
        return 2;
    } catch (...) {
        return 3;
    }
}
