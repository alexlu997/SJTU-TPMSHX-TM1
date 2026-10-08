#ifndef TPMSHX_ANDERSON_LAPACK_HPP
#define TPMSHX_ANDERSON_LAPACK_HPP
// The locked macOS NumPy wheel uses Accelerate's ILP64 DGESDD/DGELSD.
// Keep the two original calls: the condition check does not compute U/V.
#define ACCELERATE_NEW_LAPACK
#define ACCELERATE_LAPACK_ILP64
#include <Accelerate/Accelerate.h>
#include <Eigen/Dense>
#include <vector>

namespace tpmshx::model_h_common {
inline bool lapack_anderson(const Eigen::MatrixXd& dx,const Eigen::MatrixXd& dr,
                            const Eigen::VectorXd& residual,const Eigen::VectorXd& image,
                            double condition_limit,Eigen::VectorXd& output) {
    const __LAPACK_int m=dr.rows(),n=dr.cols(),one=1,lda=std::max<__LAPACK_int>(1,m),ldb=std::max(m,n);
    const auto count=std::min(m,n);
    Eigen::MatrixXd a=dr;
    std::vector<double> singular(static_cast<std::size_t>(count));
    std::vector<__LAPACK_int> integer_work(static_cast<std::size_t>(8*count));
    __LAPACK_int info=0,lwork=-1;
    double work_query=0.; const char no_vectors='N';
    dgesdd_(&no_vectors,&m,&n,a.data(),&lda,singular.data(),nullptr,&one,nullptr,&one,
            &work_query,&lwork,integer_work.data(),&info);
    if (info!=0) return false;
    lwork=static_cast<__LAPACK_int>(work_query);
    std::vector<double> work(static_cast<std::size_t>(lwork));
    dgesdd_(&no_vectors,&m,&n,a.data(),&lda,singular.data(),nullptr,&one,nullptr,&one,
            work.data(),&lwork,integer_work.data(),&info);
    if (info!=0 || singular.empty() || singular.front()==0.
        || singular.front()/std::max(singular.back(),1e-30)>condition_limit) return false;
    a=dr;
    Eigen::VectorXd rhs=Eigen::VectorXd::Zero(ldb);
    rhs.head(m)=residual;
    const double rcond=std::numeric_limits<double>::epsilon()*static_cast<double>(std::max(m,n));
    __LAPACK_int rank=0,integer_query=0;
    lwork=-1;
    dgelsd_(&m,&n,&one,a.data(),&lda,rhs.data(),&ldb,singular.data(),&rcond,&rank,
            &work_query,&lwork,&integer_query,&info);
    if (info!=0) return false;
    lwork=static_cast<__LAPACK_int>(work_query);
    work.resize(static_cast<std::size_t>(lwork)); integer_work.resize(static_cast<std::size_t>(integer_query));
    dgelsd_(&m,&n,&one,a.data(),&lda,rhs.data(),&ldb,singular.data(),&rcond,&rank,
            work.data(),&lwork,integer_work.data(),&info);
    if (info!=0) return false;
    // np.stack/np.diff keep columns adjacent in C order for the final matvec.
    const Eigen::Matrix<double,Eigen::Dynamic,Eigen::Dynamic,Eigen::RowMajor> difference=dx+dr;
    output.resize(m);
    cblas_dgemv(CblasRowMajor,CblasNoTrans,m,n,1.,difference.data(),n,rhs.data(),1,0.,output.data(),1);
    output=image-output;
    return output.allFinite();
}
} // namespace tpmshx::model_h_common
#endif
