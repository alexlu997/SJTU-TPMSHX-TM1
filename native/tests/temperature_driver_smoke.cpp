#include "tpmshx/temperature_driver.hpp"

#include <cmath>
#include <cstdio>
#include <stdexcept>

int main() {
    using namespace tpmshx;
    const double width[]{1.}, zero[]{0.}, hv[]{2.}, epsilon[]{.5}, rcp[]{2.}, velocity[]{1.};
    double ta[]{400.}, tb[]{300.}, ts[]{350.};
    const GridView grid{1,1,1,{width,1},{width,1},{width,1}};
    const TemperatureFluidView a{{zero,1},{hv,1},{epsilon,1},{rcp,1},
                                 {velocity,1},{zero,1},{},{0,400.}};
    const TemperatureFluidView b{{zero,1},{hv,1},{epsilon,1},{rcp,1},
                                 {zero,1},{velocity,1},{},{2,300.}};
    const TemperatureStateView state{{ta,1},{tb,1},{ts,1}};
    const TemperatureControl control{1,1,1e-4,.7,1.,1.,true,false};
    const auto result = solve_temperature(TemperatureScheme::cell_centered_2d,
                                          grid,a,b,{zero,1},state,control);
    // One CV is both inlet and outlet: A is undamped. Each row has F=1,
    // hv*V=2; the new A is used by solid, then the new solid by B.
    const double expected_a = (400.+2.*350.)/3.;
    const double expected_s = .5*(expected_a+300.);
    const double expected_b = (300.+2.*expected_s)/3.;
    if (result.stop != TemperatureStop::budget_exhausted || result.iterations != 1
        || std::abs(ta[0]-expected_a)>1e-12 || std::abs(ts[0]-expected_s)>1e-12
        || std::abs(tb[0]-expected_b)>1e-12) return 1;
    const auto saved_a = ta[0];
    try {
        solve_temperature(static_cast<TemperatureScheme>(99),grid,a,b,{zero,1},state,control);
        return 2;
    } catch (const std::invalid_argument&) {
        if (ta[0] != saved_a) return 3;
    }
    auto finishing = control;
    finishing.max_iterations = 1000;
    finishing.chunk_iterations = 5;
    finishing.q_relative_tolerance = 1e-10;
    const auto converged = solve_temperature(TemperatureScheme::cell_centered_2d,
                                             grid,a,b,{zero,1},state,finishing);
    // Steady one-CV equations give Ts=350, Ta=1100/3, Tb=1000/3,
    // and equal physical hot/cold duties of 100/3 W per metre of depth.
    if (converged.stop != TemperatureStop::converged || converged.iterations >= 1000
        || std::abs(ts[0]-350.)>1e-7 || std::abs(ta[0]-1100./3.)>1e-7
        || std::abs(tb[0]-1000./3.)>1e-7 || std::abs(converged.q_b-100./3.)>1e-7
        || std::abs((400.-ta[0])-(tb[0]-300.))>1e-7) return 4;
    std::puts("C++ temperature driver: one-CV updates, analytical steady balance and input rejection passed");
    return 0;
}
