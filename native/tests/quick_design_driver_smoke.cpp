#include "tpmshx/quick_design_driver.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>

int main() {
    using namespace tpmshx;
    try {
        const std::vector<double> dx(8,.004), dy(3,.012), dz(1,.036);
        const std::size_t n = dx.size()*dy.size()*dz.size();
        std::vector<double> eps(n,.6), eps_a(n,.3), ks(n,6.4);
        std::vector<double> ta(n), tb(n), ts(n);
        const auto view = [](const auto& v) { return ArrayView<const double>{v.data(),v.size()}; };
        const GridView grid{dx.size(),dy.size(),dz.size(),view(dx),view(dy),view(dz)};
        const QuickDesignGeometry geometry{.032,.036,.036,.007,1000.,.002,view(eps),view(eps_a),view(ks)};
        const QuickDesignSide a{Fluid::water,355.,2e5,.08,.001};
        const QuickDesignSide b{Fluid::air,300.,2e5,.02,.01};
        const QuickDesignControl control{1000,100,1e-4,.7};
        const auto result = solve_quick_design(grid,geometry,Topology::diamond,QuickDesignArrangement::cross,
            QuickDesignProperties::mean,a,b,{{ta.data(),n},{tb.data(),n},{ts.data(),n}},control);
        if (result.completed_passes != 2 || result.stop == TemperatureStop::cancelled)
            throw std::runtime_error("QD mean pass count/status failed");
        for (const auto& field : {ta,tb,ts})
            for (const auto value : field)
                if (!std::isfinite(value) || value < 299. || value > 356.)
                    throw std::runtime_error("QD smoke temperature range failed");
        if (result.pressure[0].outlet != 199800.)
            throw std::runtime_error("QD pressure/property contract failed");
        std::cout << "quick_design_driver_smoke ok; completed_passes=" << result.completed_passes
                  << "; stop=" << static_cast<int>(result.stop) << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
