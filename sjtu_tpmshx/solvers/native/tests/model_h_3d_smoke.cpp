#include "tpmshx/model_h_3d.hpp"
#include <cmath>
#include <cstdio>
#include <stdexcept>

int main() {
    using namespace tpmshx;
    double dx[]{1},dy[]{1},dz[]{.5,.5},zero[]{0,0},hv[]{2,2};
    double mx[]{0,0,0,0},my[]{0,0,0,0},mz[]{0,0,0};
    double ta[]{350,350},tb[]{300,300},ts[]{325,325};
    const GridView grid{1,1,2,{dx,1},{dy,1},{dz,2}};
    const ModelHFluid3D a{Fluid::air,{zero,2},{hv,2},{mx,4},{my,4},{mz,3},{0,350}};
    const ModelHFluid3D b{Fluid::water,{zero,2},{hv,2},{mx,4},{my,4},{mz,3},{1,300}};
    const ModelHControl3D control{1,1,1e-4,.7,.7,.7,true};
    const auto result=solve_model_h_3d(grid,a,b,{zero,2},{},{{ta,2},{tb,2},{ts,2}},control);
    // Two isolated cells: A uses capped .2, solid explicit .7, then B .2.
    const double expected_a=350+.2*(325-350);
    const double expected_s=325+.7*((expected_a+300)/2-325);
    const double expected_b=300+.2*(expected_s-300);
    for (int p=0;p<2;++p)
        if (std::abs(ta[p]-expected_a)>1e-12 || std::abs(ts[p]-expected_s)>1e-12
            || std::abs(tb[p]-expected_b)>1e-12)
            throw std::runtime_error("3D phase schedule or relaxation differs");
    if (result.stop!=TemperatureStop::budget_exhausted || result.iterations!=1
        || !result.audit_available || !result.audit.boundary_complete || result.audit.passed
        || std::abs(result.q_b-2*(expected_s-expected_b))>1e-12
        || std::abs(result.audit.telescoping_error)>1e-11)
        throw std::runtime_error("3D model-h budget or independent audit differs");
    std::printf("3D model-h independent caller: two-cell phase arithmetic and audit passed\n");
    return 0;
}
