// Test bridge for thermal Anderson candidates.
#include "tpmshx/thermal_c_api.h"
#include "../../../native/src/anderson.hpp"

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
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_anderson_candidate(
    std::size_t rows,std::size_t columns,const double* x,const double* residual,const double* image,
    double condition,double* output,int* applied,char* error,std::size_t capacity) {
    return checked([&] {
        if (!rows || !columns || !x || !residual || !image || !output || !applied)
            throw std::invalid_argument("invalid Anderson history");
        tpmshx::detail::Anderson accelerator(columns,condition);
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
        tpmshx::detail::Anderson restored;
        restored.restore(accelerator.snapshot());
        Eigen::VectorXd resumed;
        const bool resumed_applied=restored.candidate(g,resumed);
        if (resumed_applied!=static_cast<bool>(*applied)
            || (resumed_applied && (resumed.size()!=result.size() || (resumed-result).cwiseAbs().maxCoeff()!=0.)))
            throw std::runtime_error("restored Anderson candidate differs");
        if (!*applied) result=g;
        std::copy(result.data(),result.data()+rows,output);
    },error,capacity);
}
