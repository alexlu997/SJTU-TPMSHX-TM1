#include "tpmshx/temperature_staggered.hpp"
#include "tpmshx/thermal_c_api.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>
namespace {
struct Callbacks { std::size_t at,calls=0,progress=0,last=0; };
bool cancel(void* p) { auto& c=*static_cast<Callbacks*>(p); return ++c.calls>=c.at && c.at>0; }
void progress(void* p,std::size_t n,std::size_t) { auto& c=*static_cast<Callbacks*>(p); ++c.progress; c.last=n; }
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_temperature_staggered(
    const std::size_t* shape,double** arrays,const std::size_t* sizes,const std::size_t* config,
    const double* values,std::size_t* status,double* metrics,char* error,std::size_t error_size) {
    using namespace tpmshx;
    try {
        const auto v=[&](std::size_t p) { return ArrayView<const double>{arrays[p],sizes[p]}; };
        const auto out=[&](std::size_t p) { return ArrayView<double>{arrays[p],sizes[p]}; };
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const auto side=[&](std::size_t p,std::size_t s) {
            return StaggeredTemperatureFluid{v(p),v(p+1),v(p+2),v(p+3),{v(p+4),v(p+5),v(p+6)},
                {static_cast<int>(config[5+s]),values[s],v(p+7),v(p+8),v(p+9)},v(p+10)};
        };
        Callbacks cb{config[7]};
        const TemperatureControl control{config[0],config[1],values[2],values[3],values[4],values[5],
            config[2]!=0,true,cancel,progress,&cb};
        StaggeredTemperatureDriver solver;
        const auto result=solver.solve(grid,side(9,0),side(20,1),v(6),{out(3),out(4),out(5)},control,
            config[3]!=0,config[4]!=0,v(8),v(7));
        const std::size_t state[]{static_cast<std::size_t>(result.iteration.stop),result.iteration.iterations,
            cb.calls,cb.progress,cb.last,result.residual[0].available,result.residual[1].available};
        std::copy(std::begin(state),std::end(state),status);
        metrics[0]=result.iteration.residual; metrics[1]=result.iteration.q_b;
        for (std::size_t s=0;s<2;++s) {
            const auto& r=result.residual[s]; const auto& p=result.projection[s];
            status[7+3*s]=p.skipped; status[8+3*s]=p.used_bordered_lu; status[9+3*s]=p.cg_iterations;
            metrics[2+7*s]=r.sum; metrics[3+7*s]=r.maximum; metrics[4+7*s]=r.exchange;
            metrics[5+7*s]=r.global_ratio; metrics[6+7*s]=r.cell_ratio;
            metrics[7+7*s]=p.rhs_mean; metrics[8+7*s]=p.residual_relative;
            if (r.available) {
                if (sizes[31+s]!=r.cells.size()) throw std::invalid_argument("staggered bridge residual extent");
                std::copy(r.cells.begin(),r.cells.end(),arrays[31+s]);
            }
        }
        if (error_size) error[0]='\0'; return 0;
    } catch (const std::invalid_argument& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 1;
    } catch (const std::domain_error& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 2;
    } catch (const std::exception& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 3;
    }
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_mac_projection(
    const std::size_t* shape,double** arrays,const std::size_t* sizes,int direct,
    std::size_t* status,double* metrics,char* error,std::size_t error_size) {
    using namespace tpmshx;
    try {
        const auto v=[&](std::size_t p) { return ArrayView<const double>{arrays[p],sizes[p]}; };
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        if (direct) {
            const auto phi=solve_mac_neumann_bordered(grid,v(3));
            if (sizes[11]!=phi.size()) throw std::invalid_argument("MAC bridge potential extent");
            std::copy(phi.begin(),phi.end(),arrays[11]);
        } else {
            StaggeredTemperatureDriver solver;
            // Two solves in one owner also exercise hierarchy reuse.
            auto result=solver.project_capacity_faces(grid,v(3),v(4),{v(5),v(6),v(7)});
            result=solver.project_capacity_faces(grid,v(3),v(4),{v(5),v(6),v(7)});
            for (std::size_t axis=0;axis<3;++axis) {
                if (sizes[8+axis]!=result.velocity[axis].size()) throw std::invalid_argument("MAC bridge face extent");
                std::copy(result.velocity[axis].begin(),result.velocity[axis].end(),arrays[8+axis]);
            }
            if (sizes[11]!=result.potential.size()) throw std::invalid_argument("MAC bridge potential extent");
            std::copy(result.potential.begin(),result.potential.end(),arrays[11]);
            status[0]=result.info.skipped; status[1]=result.info.used_bordered_lu; status[2]=result.info.cg_iterations;
            metrics[0]=result.info.rhs_mean; metrics[1]=result.info.residual_relative;
        }
        if (error_size) error[0]='\0'; return 0;
    } catch (const std::exception& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 1;
    }
}
