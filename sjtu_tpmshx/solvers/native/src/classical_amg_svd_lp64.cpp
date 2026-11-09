#include "classical_amg_svd_lp64.hpp"

#define ACCELERATE_NEW_LAPACK
#include <Accelerate/Accelerate.h>
#include <stdexcept>
#include <vector>

namespace tpmshx::classical_detail {

void coarse_svd_lp64(Eigen::MatrixXd& dense, Eigen::MatrixXd& u,
                     Eigen::VectorXd& singular, Eigen::MatrixXd& vt) {
    const __LAPACK_int n=static_cast<__LAPACK_int>(dense.rows());
    const char job='S';__LAPACK_int info=0,lwork=-1;
    std::vector<__LAPACK_int> iwork(static_cast<std::size_t>(8*n));
    double query=0.;
    dgesdd_(&job,&n,&n,dense.data(),&n,singular.data(),u.data(),&n,vt.data(),&n,
            &query,&lwork,iwork.data(),&info);
    if(info)throw std::domain_error("AMG DGESDD workspace failure");
    lwork=static_cast<__LAPACK_int>(query);std::vector<double> work(static_cast<std::size_t>(lwork));
    dgesdd_(&job,&n,&n,dense.data(),&n,singular.data(),u.data(),&n,vt.data(),&n,
            work.data(),&lwork,iwork.data(),&info);
    if(info)throw std::domain_error("AMG DGESDD failure");
}

} // namespace tpmshx::classical_detail
