#include "tpmshx/temperature_staggered.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
int main() {
    using namespace tpmshx;
    using V=std::vector<double>;
    V dx(4,.01),dy(3,.01),dz(2,.01),k(24,.2),hv(24,10000),eps(24,.35),cp(24,1200),ks(24,5);
    V ua(30,.1),va(32,0),wa(36,0),ub(30,0),vb(32,.1),wb(36,0),ta(24),tb(24),ts(24);
    const auto v=[](const V& x) { return ArrayView<const double>{x.data(),x.size()}; };
    const auto out=[](V& x) { return ArrayView<double>{x.data(),x.size()}; };
    const GridView grid{4,3,2,v(dx),v(dy),v(dz)};
    const StaggeredTemperatureFluid a{v(k),v(hv),v(eps),v(cp),{v(ua),v(va),v(wa)},{0,350,{},{},{}},{}};
    const StaggeredTemperatureFluid b{v(k),v(hv),v(eps),v(cp),{v(ub),v(vb),v(wb)},{2,300,{},{},{}},{}};
    const TemperatureControl control{5000,100,1e-6,.7,.7,.7,false,true};
    StaggeredTemperatureDriver driver;
    ua[6]+=.01;
    const auto projected=driver.project_capacity_faces(grid,v(eps),v(cp),{v(ua),v(va),v(wa)});
    if (projected.info.skipped || projected.info.residual_relative>1.01e-10
        || projected.velocity[0][0]!=ua[0]) return 3;
    ua[6]-=.01;
    const auto result=driver.solve(grid,a,b,v(ks),{out(ta),out(tb),out(ts)},control,true,false);
    if (result.iteration.stop!=TemperatureStop::converged || !result.residual[0].available
        || !result.residual[1].available || !std::isfinite(result.iteration.q_b)) return 1;
    for (const auto& t:{ta,tb,ts}) for (double value:t) if (value<300 || value>350) return 2;
    std::cout << "staggered_temperature iterations=" << result.iteration.iterations
              << " Q_B_W=" << result.iteration.q_b << '\n';
    return 0;
}
