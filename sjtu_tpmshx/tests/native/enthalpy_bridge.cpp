// Test-only bridge. This is not an installed API or a promised stable C ABI.
#include "tpmshx/enthalpy_sweeps.hpp"
#include <stdexcept>

extern "C" int test_enthalpy_sweeps(const std::size_t* shape, double** arrays,
                                   const std::size_t* sizes, const double* scalars,
                                   std::size_t sweeps, std::uint64_t* clips) {
    using namespace tpmshx;
    const auto view = [&](std::size_t i) { return ArrayView<const double>{arrays[i], sizes[i]}; };
    const auto state_view = [&](std::size_t i) { return ArrayView<double>{arrays[i], sizes[i]}; };
    const GridView grid{shape[0], shape[1], shape[2], view(0), view(1), view(2)};
    const ThermalStateView state{state_view(3), state_view(4), state_view(5)};
    const FluidView a{view(6), view(7), view(8), view(9), view(10), view(11), view(12), view(13),
                      scalars[0], scalars[2], scalars[3]};
    const FluidView b{view(14), view(15), view(16), view(17), view(18), view(19), view(20), view(21),
                      scalars[1], scalars[4], scalars[5]};
    try {
        const auto result = enthalpy_sweeps(grid, a, b, view(22), state, sweeps, scalars[6]);
        clips[0] = result.a;
        clips[1] = result.b;
        return 0;
    } catch (const std::invalid_argument&) {
        return 1;
    } catch (const std::domain_error&) {
        return 2;
    } catch (...) {
        return 3;
    }
}

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
