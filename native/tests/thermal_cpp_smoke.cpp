#include "tpmshx/enthalpy_sweeps.hpp"

#include <cmath>
#include <cstdio>
#include <stdexcept>

int main() {
    const double dx[] = {0.01}, dy[] = {0.02}, dz[] = {0.03};
    const double dh[] = {0.0}, cp[] = {1000.0}, hv[] = {0.0}, ks[] = {0.0};
    const double ta[] = {400.0}, tb[] = {300.0};
    const double hs_a[] = {400000.0}, hs_b[] = {300000.0};
    const double mx[] = {0.01, 0.01}, my[] = {0.0, 0.0}, mz[] = {0.0, 0.0};
    double ha[] = {350000.0}, hb[] = {280000.0}, ts[] = {340.0};
    double ra[1], rb[1], rs[1];
    const tpmshx::GridView grid{1, 1, 1, {dx, 1}, {dy, 1}, {dz, 1}};
    const tpmshx::FluidView a{{dh, 1}, {cp, 1}, {ta, 1}, {hs_a, 1}, {hv, 1},
                             {mx, 2}, {my, 2}, {mz, 2}, 400000.0, 0.0, 500000.0};
    const tpmshx::FluidView b{{dh, 1}, {cp, 1}, {tb, 1}, {hs_b, 1}, {hv, 1},
                             {mx, 2}, {my, 2}, {mz, 2}, 300000.0, 0.0, 500000.0};
    const tpmshx::ThermalStateView state{{ha, 1}, {hb, 1}, {ts, 1}};
    const auto clips = tpmshx::enthalpy_sweeps(grid, a, b, {ks, 1}, state, 1, 1.0);
    if (clips.a || clips.b || std::abs(ha[0] - 400000.0) > 1e-8 ||
        std::abs(hb[0] - 300000.0) > 1e-8 || ts[0] != 340.0) return 1;

    const tpmshx::FluidEnergyView ea{{ha, 1}, {ta, 1}, {hv, 1}, {dh, 1},
                                    {mx, 2}, {my, 2}, {mz, 2}, a.h_in};
    const tpmshx::FluidEnergyView eb{{hb, 1}, {tb, 1}, {hv, 1}, {dh, 1},
                                    {mx, 2}, {my, 2}, {mz, 2}, b.h_in};
    const auto audit = tpmshx::thermal_energy_audit(
        grid, ea, eb, {ts, 1}, {ks, 1}, {ra, 1}, {rb, 1}, {rs, 1});
    if (std::abs(ra[0]) > 1e-9 || std::abs(rb[0]) > 1e-9 || rs[0] != 0.0 ||
        std::abs(audit.q_a) > 1e-9 || std::abs(audit.q_b) > 1e-9 ||
        audit.coupled_ratio > 1e-12 || audit.equation_ratio > 1e-12) return 2;
    try {
        tpmshx::enthalpy_sweeps(grid, a, b, {ks, 1}, state, 1, 2.0);
        return 3;
    } catch (const std::invalid_argument&) {
        if (std::abs(ha[0] - 400000.0) > 1e-8 ||
            std::abs(hb[0] - 300000.0) > 1e-8 || ts[0] != 340.0) return 4;
    }
    std::puts("C++ API: transport, energy audit and invalid-input semantics passed");
    return 0;
}
