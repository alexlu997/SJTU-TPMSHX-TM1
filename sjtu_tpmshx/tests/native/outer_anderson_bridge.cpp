// Qualification-only bridge for the original outer property-map accelerator.
#include "tpmshx/outer_anderson.hpp"
#include "tpmshx/thermal_c_api.h"
#include "../../../native/src/model_h_common.hpp"

#include <algorithm>
#include <cstdio>
#include <exception>

namespace {
template<class F> int checked(F operation,char* error,std::size_t capacity) {
    if(capacity) error[0]='\0';
    try { operation(); return 0; }
    catch(const std::exception& e) {
        if(capacity) std::snprintf(error,capacity,"%s",e.what());
        return 1;
    }
}
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_outer_anderson_create(
    int m,double trust,int patience,double condition,void** handle,char* error,std::size_t capacity) {
    *handle=nullptr;
    return checked([&] {*handle=new tpmshx::OuterAnderson(m,trust,patience,condition);},error,capacity);
}
extern "C" TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL test_outer_anderson_destroy(void* handle) {
    delete static_cast<tpmshx::OuterAnderson*>(handle);
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_outer_anderson_step(
    void* handle,std::size_t count,const std::size_t* sizes,const double* const* current,
    const double* const* image,double alpha,double* const* output,std::size_t* statistics,
    double* residual,char* error,std::size_t capacity) {
    return checked([&] {
        std::vector<tpmshx::ArrayView<const double>> x,g;
        for(std::size_t i=0;i<count;++i) {x.push_back({current[i],sizes[i]});g.push_back({image[i],sizes[i]});}
        auto& accelerator=*static_cast<tpmshx::OuterAnderson*>(handle);
        const auto result=accelerator.step(x,g,alpha);
        for(std::size_t i=0;i<count;++i)
            std::copy(result.blocks[i].begin(),result.blocks[i].end(),output[i]);
        const auto& stats=accelerator.stats();
        statistics[0]=result.applied;statistics[1]=stats.applied;statistics[2]=stats.rejected;
        statistics[3]=stats.resets;statistics[4]=stats.residuals.size();
        *residual=stats.residuals.back();
    },error,capacity);
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_anderson_candidate(
    std::size_t rows,std::size_t columns,const double* x,const double* residual,const double* image,
    double condition,double* output,int* applied,char* error,std::size_t capacity) {
    return checked([&] {
        if (!rows || !columns || !x || !residual || !image || !output || !applied)
            throw std::invalid_argument("invalid Anderson history");
        tpmshx::model_h_common::Anderson accelerator(columns,condition);
        for (std::size_t j=0;j<columns;++j) {
            Eigen::VectorXd previous(rows),r(rows);
            for (std::size_t i=0;i<rows;++i) {
                previous[static_cast<Eigen::Index>(i)]=x[i*columns+j];
                r[static_cast<Eigen::Index>(i)]=residual[i*columns+j];
            }
            accelerator.x.push_back(std::move(previous)); accelerator.r.push_back(std::move(r));
        }
        const Eigen::VectorXd g=Eigen::Map<const Eigen::VectorXd>(image,rows);
        Eigen::VectorXd result;
        *applied=accelerator.candidate(g,result);
        if (!*applied) result=g;
        std::copy(result.data(),result.data()+rows,output);
    },error,capacity);
}
