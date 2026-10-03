#include "tpmshx/enthalpy_driver.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>

int main() {
    using namespace tpmshx;
    try {
        const std::size_t nx = 8, n = nx;
        std::vector<double> dx(nx,.005), dy(1,.01), dz(1,.01), pressure(n,2e5), eps(n,.3);
        std::vector<double> hv(n,1e5), ks(n,4.), mx_a(nx+1,.001), mx_b(nx+1,-.003);
        std::vector<double> my(n*2,0.), mz(n*2,0.), ha(n), hb(n), ta(n), tb(n), ts(n);
        const auto v = [](const auto& a) { return ArrayView<const double>{a.data(),a.size()}; };
        const auto out = [](auto& a) { return ArrayView<double>{a.data(),a.size()}; };
        const GridView grid{nx,1,1,v(dx),v(dy),v(dz)};
        const EnthalpySideView a{Fluid::air,370.,2e5,v(pressure),v(eps),v(hv),v(mx_a),v(my),v(mz)};
        const EnthalpySideView b{Fluid::water,300.,2e5,v(pressure),v(eps),v(hv),v(mx_b),v(my),v(mz)};
        const EnthalpyControl control{1000,5,.6,2e-5,1e-3,1e-3,""};
        const auto result = solve_enthalpy(grid,a,b,v(ks),{out(ha),out(hb),out(ta),out(tb),out(ts)},control);
        if (result.stop != EnthalpyStop::converged || !result.final_audit
            || !result.final_audit->fluid_equations_computed
            || result.final_audit->equation_ratio > 1e-3)
            throw std::runtime_error("complete true-h convergence/energy qualification failed");
        for (const auto& field : {ta,tb,ts}) for (double value : field)
            if (!std::isfinite(value) || value < 299. || value > 371.)
                throw std::runtime_error("complete true-h temperature range failed");
        std::cout << "enthalpy_driver_smoke ok; iterations=" << result.iterations
                  << "; equation_ratio=" << result.final_audit->equation_ratio << '\n';
        return 0;
    } catch (const std::exception& exception) {
        std::cerr << exception.what() << '\n'; return 1;
    }
}
