#include "tpmshx/model_h_2d.hpp"
#include <cmath>
#include <cstdio>
#include <stdexcept>

int main() {
    using namespace tpmshx;
    double dx[]{.01}, dy[]{.01}, dz[]{1}, zero[]{0}, hv[]{2000};
    double ma[]{.0001,.0001}, mb[]{-.0001,-.0001}, my[]{0,0};
    double ta[]{350}, tb[]{300}, ts[]{325};
    const GridView grid{1,1,1,{dx,1},{dy,1},{dz,1}};
    const ModelHFluid2D a{Fluid::water,{zero,1},{hv,1},{ma,2},{my,2},{0,350}};
    const ModelHFluid2D b{Fluid::water,{zero,1},{hv,1},{mb,2},{my,2},{1,300}};
    const ModelHControl2D control{1,1,1e-5,true};
    const auto result=solve_model_h_2d(grid,a,b,{zero,1},{{ta,1},{tb,1},{ts,1}},control);
    const double expected_a=350+.2*((.2*325+.4182*350)/.6182-350);
    const double expected_s=.5*(expected_a+300);
    const double expected_b=300+.2*((.2*expected_s+.4182*300)/.6182-300);
    if (result.stop!=TemperatureStop::budget_exhausted || result.iterations!=1 || !result.audit_available
        || std::abs(ta[0]-expected_a)>1e-12 || std::abs(tb[0]-expected_b)>1e-12
        || std::abs(ts[0]-expected_s)>1e-12 || !result.audit.boundary_complete
        || std::abs(result.audit.telescoping_error)>1e-11)
        throw std::runtime_error("single-CV water model-h arithmetic failed");
    bool rejected=false;
    try {
        solve_model_h_2d(grid,a,b,{ta,1},{{ta,1},{tb,1},{ts,1}},control);
    } catch (const std::invalid_argument&) { rejected=true; }
    if (!rejected) throw std::runtime_error("aliased model-h input was accepted");
    std::printf("model-h 2D independent caller: one-CV arithmetic, audit and alias guard passed\n");
    return 0;
}
