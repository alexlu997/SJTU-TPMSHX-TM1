#include "classical_amg.hpp"
#if defined(__APPLE__) && defined(__clang__)
// The locked macOS SciPy/PyAMG wheels contract these original sparse kernels.
// Keep their FMA rounding, then restore strict NumPy-style vector updates.
#pragma clang fp contract(on)
#endif
#include "classical_amg_kernels.hpp"
#if defined(__APPLE__) && defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <Eigen/Dense>
#ifdef __APPLE__
#include "classical_amg_svd_lp64.hpp"
#define ACCELERATE_NEW_LAPACK
#define ACCELERATE_LAPACK_ILP64
#include <Accelerate/Accelerate.h>
#endif
#include <numeric>
#include <optional>
#include <utility>

namespace tpmshx::classical_detail {
namespace {
using Vector=std::vector<double>;
struct Csr {
    int rows=0,cols=0;
    std::vector<int> ptr,col;
    Vector val;
    Csr()=default;
    Csr(int m,int n,std::size_t nnz):rows(m),cols(n),ptr(m+1),col(nnz),val(nnz) {}
    explicit Csr(const PressureSystem& a):rows(static_cast<int>(a.rhs.size())),cols(rows),
        ptr(a.row_offsets),col(a.columns),val(a.values) {}
    void trim() { col.resize(ptr.back());val.resize(ptr.back()); }
    std::size_t bytes() const {return (ptr.size()+col.size())*sizeof(int)+val.size()*sizeof(double);}
};

int index_count(std::size_t n) {
    if(n>static_cast<std::size_t>(std::numeric_limits<int>::max()))
        throw std::length_error("classical AMG CSR index range exceeded");
    return static_cast<int>(n);
}

void finite(const Vector& x) {
    for(double value:x)if(!std::isfinite(value))throw std::domain_error("nonfinite classical AMG arithmetic");
}

Vector multiply(const Csr& a,const Vector& x) {
    Vector result(a.rows,0.);
    for(int i=0;i<a.rows;++i)
        for(int k=a.ptr[i];k<a.ptr[i+1];++k) {
#ifdef __APPLE__
            // Match the locked SciPy CSR matvec's contracted multiply/add.
            result[i]=std::fma(a.val[k],x[a.col[k]],result[i]);
#else
            result[i]+=a.val[k]*x[a.col[k]];
#endif
        }
    finite(result);return result;
}

Csr transpose(const Csr& a) {
    Csr result(a.cols,a.rows,a.val.size());
    original::csr_tocsc(a.rows,a.cols,a.ptr.data(),a.col.data(),a.val.data(),
                       result.ptr.data(),result.col.data(),result.val.data());
    return result;
}

Csr product(const Csr& a,const Csr& b) {
    const auto nnz=original::csr_matmat_maxnnz(a.rows,b.cols,a.ptr.data(),a.col.data(),b.ptr.data(),b.col.data());
    index_count(static_cast<std::size_t>(nnz));
    Csr result(a.rows,b.cols,static_cast<std::size_t>(nnz));
    original::csr_matmat(a.rows,b.cols,a.ptr.data(),a.col.data(),a.val.data(),
        b.ptr.data(),b.col.data(),b.val.data(),result.ptr.data(),result.col.data(),result.val.data());
    result.trim();finite(result.val);return result;
}

Csr without_zeros(const Csr& a,bool diagonal=false,bool sort=false) {
    Csr result(a.rows,a.cols,0);
    std::vector<std::pair<int,double>> row;
    for(int i=0;i<a.rows;++i) {
        row.clear();
        for(int k=a.ptr[i];k<a.ptr[i+1];++k)
            if(a.val[k]!=0. && (!diagonal || a.col[k]!=i))row.emplace_back(a.col[k],a.val[k]);
        if(sort)std::sort(row.begin(),row.end());
        for(const auto& item:row) {result.col.push_back(item.first);result.val.push_back(item.second);}
        result.ptr[i+1]=index_count(result.col.size());
    }
    return result;
}

Csr strength(const Csr& a) {
    Csr s(a.rows,a.cols,a.val.size());
    original::classical_strength_of_connection_abs(a.rows,.25,a.ptr.data(),index_count(a.ptr.size()),
        a.col.data(),index_count(a.col.size()),a.val.data(),index_count(a.val.size()),
        s.ptr.data(),index_count(s.ptr.size()),s.col.data(),index_count(s.col.size()),s.val.data(),index_count(s.val.size()));
    s.trim();
    // pyamg.strength: magnitude, reciprocal maximum row scaling, then eliminate zeros.
    for(int i=0;i<s.rows;++i) {
        double maximum=0.;
        for(int k=s.ptr[i];k<s.ptr[i+1];++k) {s.val[k]=std::abs(s.val[k]);maximum=std::max(maximum,s.val[k]);}
        const double inverse=maximum!=0.?1./maximum:0.;
        for(int k=s.ptr[i];k<s.ptr[i+1];++k)s.val[k]*=inverse;
    }
    return without_zeros(s);
}

std::vector<int> splitting(const Csr& s) {
    // remove_diagonal goes through COO -> CSR, sorting this graph only.
    const Csr graph=without_zeros(s,true,true), back=transpose(graph);
    std::vector<int> influence(s.rows,0),split(s.rows);
    original::rs_cf_splitting(s.rows,graph.ptr.data(),index_count(graph.ptr.size()),
        graph.col.data(),index_count(graph.col.size()),back.ptr.data(),index_count(back.ptr.size()),
        back.col.data(),index_count(back.col.size()),influence.data(),s.rows,split.data(),s.rows);
    return split;
}

Csr interpolation(const Csr& a,Csr s,const std::vector<int>& split,int coarse_count) {
    original::remove_strong_FF_connections(a.rows,s.ptr.data(),index_count(s.ptr.size()),
        s.col.data(),index_count(s.col.size()),s.val.data(),index_count(s.val.size()),split.data(),a.rows);
    s=without_zeros(s);
    std::fill(s.val.begin(),s.val.end(),1.);
    Csr masked(a.rows,a.cols,s.val.size()+a.val.size());
    original::csr_binop_csr(a.rows,a.cols,s.ptr.data(),s.col.data(),s.val.data(),
        a.ptr.data(),a.col.data(),a.val.data(),masked.ptr.data(),masked.col.data(),masked.val.data(),std::multiplies<double>{});
    masked.trim();
    Csr p(a.rows,coarse_count,0);
    original::rs_classical_interpolation_pass1(a.rows,masked.ptr.data(),index_count(masked.ptr.size()),
        masked.col.data(),index_count(masked.col.size()),split.data(),a.rows,p.ptr.data(),index_count(p.ptr.size()));
    p.col.resize(p.ptr.back());p.val.resize(p.ptr.back());
    original::rs_classical_interpolation_pass2(a.rows,a.ptr.data(),index_count(a.ptr.size()),
        a.col.data(),index_count(a.col.size()),a.val.data(),index_count(a.val.size()),
        masked.ptr.data(),index_count(masked.ptr.size()),masked.col.data(),index_count(masked.col.size()),
        masked.val.data(),index_count(masked.val.size()),split.data(),a.rows,p.ptr.data(),index_count(p.ptr.size()),
        p.col.data(),index_count(p.col.size()),p.val.data(),index_count(p.val.size()),true);
    finite(p.val);return p;
}

void symmetric_gauss_seidel(const Csr& a,const Vector& b,Vector& x) {
    const auto sweep=[&](int start,int stop,int step) {
        original::gauss_seidel<int,double,double>(a.ptr.data(),index_count(a.ptr.size()),
            a.col.data(),index_count(a.col.size()),a.val.data(),index_count(a.val.size()),
            x.data(),a.rows,b.data(),a.rows,start,stop,step);
    };
    sweep(0,a.rows,1);sweep(a.rows-1,-1,-1);finite(x);
}

double dot(const Vector& a,const Vector& b) {
#ifdef __APPLE__
    double result=cblas_ddot(static_cast<__LAPACK_int>(a.size()),a.data(),1,b.data(),1);
#else
    double result=0.;for(std::size_t i=0;i<a.size();++i)result+=a[i]*b[i];
#endif
    if(!std::isfinite(result))throw std::domain_error("nonfinite classical BiCGStab dot product");
    return result;
}
double norm(const Vector& a) {return std::sqrt(dot(a,a));}
} // namespace

struct ClassicalAmg::Impl {
    struct Level { Csr a,p,r;Vector x; };
    std::vector<Level> levels;
    std::optional<Eigen::MatrixXd> coarse_inverse;
    explicit Impl(const PressureSystem& system) {
        levels.push_back({Csr(system),{},{},{}});
        // Locked pyamg.ruge_stuben_solver: max_levels=30, max_coarse=200.
        while(levels.size()<30 && levels.back().a.rows>200) {
            auto& level=levels.back();
            Csr s=strength(level.a);const auto cf=splitting(s);
            const int count=std::accumulate(cf.begin(),cf.end(),0);
            if(count==0 || count==level.a.rows)break;
            level.p=interpolation(level.a,std::move(s),cf,count);level.r=transpose(level.p);
            // Original Python expression is (R @ A) @ P. Preserve its unsorted CSR order.
            Csr next=product(product(level.r,level.a),level.p);
            levels.push_back({std::move(next),{},{},{}});
        }
    }
    void cycle(std::size_t index,const Vector& b) {
        auto& level=levels[index];level.x.assign(level.a.rows,0.);
        if(index+1==levels.size()) {
            if(!coarse_inverse) {
                Eigen::MatrixXd dense=Eigen::MatrixXd::Zero(level.a.rows,level.a.cols);
                for(int i=0;i<level.a.rows;++i)
                    for(int k=level.a.ptr[i];k<level.a.ptr[i+1];++k)dense(i,level.a.col[k])=level.a.val[k];
#ifdef __APPLE__
                // SciPy's DGESDD uses LP64; the NumPy BLAS operations use ILP64.
                // Keep the SVD in its own translation unit and preserve pinv's layout.
                const __LAPACK_int n=static_cast<__LAPACK_int>(dense.rows());
                Eigen::MatrixXd u(n,n),vt(n,n);Eigen::VectorXd singular(n);
                coarse_svd_lp64(dense,u,singular,vt);
                const double threshold=static_cast<double>(n)*std::numeric_limits<double>::epsilon()*singular[0];
                __LAPACK_int rank=0;while(rank<n && singular[rank]>threshold)++rank;
                for(__LAPACK_int j=0;j<rank;++j)for(__LAPACK_int i=0;i<n;++i)u(i,j)/=singular[j];
                // NumPy's product is C order; its transpose is the F-order pinv.
                coarse_inverse=Eigen::MatrixXd::Zero(n,n);
                cblas_dgemm(CblasRowMajor,CblasTrans,CblasTrans,n,n,rank,1.,u.data(),n,
                            vt.data(),n,0.,coarse_inverse->data(),n);
#else
                Eigen::JacobiSVD<Eigen::MatrixXd> svd(dense,Eigen::ComputeThinU|Eigen::ComputeThinV);
                const auto singular=svd.singularValues();
                const double threshold=static_cast<double>(std::max(dense.rows(),dense.cols()))*
                    std::numeric_limits<double>::epsilon()*singular[0];
                Eigen::Index rank=0;while(rank<singular.size() && singular[rank]>threshold)++rank;
                // scipy.linalg.pinv: ((U[:,:rank]/s[:rank]) @ Vh[:rank,:]).T.
                Eigen::MatrixXd left=svd.matrixU().leftCols(rank);
                for(Eigen::Index j=0;j<rank;++j)left.col(j)/=singular[j];
                coarse_inverse=(left*svd.matrixV().leftCols(rank).transpose()).transpose().eval();
#endif
                if(!coarse_inverse->allFinite())throw std::domain_error("nonfinite classical AMG coarse pseudo-inverse");
            }
            const Eigen::Map<const Eigen::VectorXd> rhs(b.data(),static_cast<Eigen::Index>(b.size()));
#ifdef __APPLE__
            Eigen::VectorXd solved(rhs.size());
            cblas_dgemv(CblasColMajor,CblasNoTrans,static_cast<__LAPACK_int>(rhs.size()),
                static_cast<__LAPACK_int>(rhs.size()),1.,coarse_inverse->data(),
                static_cast<__LAPACK_int>(rhs.size()),rhs.data(),1,0.,solved.data(),1);
#else
            const Eigen::VectorXd solved=(*coarse_inverse)*rhs;
#endif
            std::copy(solved.data(),solved.data()+solved.size(),level.x.begin());finite(level.x);return;
        }
        symmetric_gauss_seidel(level.a,b,level.x);
        auto residual=multiply(level.a,level.x);
        for(std::size_t i=0;i<residual.size();++i)residual[i]=b[i]-residual[i];
        const auto coarse_b=multiply(level.r,residual);cycle(index+1,coarse_b);
        const auto correction=multiply(level.p,levels[index+1].x);
        for(std::size_t i=0;i<level.x.size();++i)level.x[i]+=correction[i];
        symmetric_gauss_seidel(level.a,b,level.x);
    }
    Vector apply(const Vector& b) {cycle(0,b);return levels.front().x;}
};

ClassicalAmg::ClassicalAmg(const PressureSystem& a):impl_(std::make_unique<Impl>(a)) {}
ClassicalAmg::~ClassicalAmg()=default;
std::size_t ClassicalAmg::bytes() const {
    std::size_t total=0;
    for(const auto& level:impl_->levels)total+=level.a.bytes()+level.p.bytes()+level.r.bytes()+level.x.size()*sizeof(double);
    if(impl_->coarse_inverse)total+=static_cast<std::size_t>(impl_->coarse_inverse->size())*sizeof(double);
    return total;
}

KrylovResult ClassicalAmg::solve(const PressureSystem& system,const Vector& rhs,double tolerance,std::size_t maximum) {
    // Translation of locked SciPy 1.17.1 bicgstab, retaining vector update order,
    // strict residual comparisons, eps^2 breakdown, and the supplied zero start.
    const Csr a(system);KrylovResult result;result.x.assign(rhs.size(),0.);
    const double bnorm=norm(rhs),atol=tolerance*bnorm;
    if(bnorm==0.)return result;
    const double tiny=std::numeric_limits<double>::epsilon()*std::numeric_limits<double>::epsilon();
    Vector r=rhs,shadow=r,p,v;
    double previous=0.,omega=0.,alpha=0.;
    for(std::size_t iteration=0;iteration<maximum;++iteration) {
        result.iterations=iteration;
        if(norm(r)<atol)return result;
        const double rho=dot(shadow,r);
        if(std::abs(rho)<tiny) {result.info=-10;return result;}
        if(iteration>0) {
            if(std::abs(omega)<tiny) {result.info=-11;return result;}
            const double beta=(rho/previous)*(alpha/omega);
            for(std::size_t i=0;i<p.size();++i)p[i]-=omega*v[i];
            for(double& value:p)value*=beta;
            for(std::size_t i=0;i<p.size();++i)p[i]+=r[i];
        } else p=r;
        const auto phat=impl_->apply(p);v=multiply(a,phat);
        const double rv=dot(shadow,v);
        if(rv==0.) {result.info=-11;return result;}
        alpha=rho/rv;
        for(std::size_t i=0;i<r.size();++i)r[i]-=alpha*v[i];
        const Vector s=r;result.iterations=iteration+1;
        if(norm(s)<atol) {
            for(std::size_t i=0;i<result.x.size();++i)result.x[i]+=alpha*phat[i];
            finite(result.x);return result;
        }
        const auto shat=impl_->apply(s),t=multiply(a,shat);
        omega=dot(t,s)/dot(t,t);
        for(std::size_t i=0;i<result.x.size();++i)result.x[i]+=alpha*phat[i];
        for(std::size_t i=0;i<result.x.size();++i)result.x[i]+=omega*shat[i];
        for(std::size_t i=0;i<r.size();++i)r[i]-=omega*t[i];
        previous=rho;finite(result.x);finite(r);
    }
    result.info=static_cast<int>(maximum);return result;
}
} // namespace tpmshx::classical_detail
