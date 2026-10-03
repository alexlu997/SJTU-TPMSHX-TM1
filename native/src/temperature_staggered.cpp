#include "tpmshx/temperature_staggered.hpp"
#include "tpmshx/superlu_solve.h"
#include <Eigen/Dense>
#include <amgcl/amg.hpp>
#include <amgcl/backend/builtin.hpp>
#include <amgcl/coarsening/ruge_stuben.hpp>
#include <amgcl/relaxation/gauss_seidel.hpp>
#include <amgcl/adapter/crs_tuple.hpp>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>

namespace tpmshx {
namespace {
using Vector=std::vector<double>;
using Coordinate=std::array<std::size_t,3>;
using Faces=std::array<Vector,3>;
using Rows=std::vector<std::array<double,6>>;
template<class T> ArrayView<const double> view(const T& x) { return {x.data(),x.size()}; }
ArrayView<const double> view(ArrayView<double> x) { return {x.data,x.size}; }
std::size_t product(std::size_t a,std::size_t b) {
    if (!a || !b || a>std::numeric_limits<std::size_t>::max()/b)
        throw std::invalid_argument("invalid staggered grid extent");
    return a*b;
}
template<class T> void check(ArrayView<T> x,std::size_t n,bool finite=true) {
    if (!x.data || x.size!=n) throw std::invalid_argument("staggered array extent mismatch");
    if (finite) for (std::size_t p=0;p<n;++p)
        if (!std::isfinite(x[p])) throw std::invalid_argument("nonfinite staggered input");
}
void coefficient(ArrayView<const double> x,std::size_t n,bool positive=false) {
    check(x,n);
    for (std::size_t p=0;p<n;++p) if (positive ? x[p]<=0 : x[p]<0)
        throw std::invalid_argument("invalid staggered coefficient");
}
void disjoint(ArrayView<const double> a,ArrayView<const double> b) {
    if (!a.size || !b.size) return;
    const auto ap=reinterpret_cast<std::uintptr_t>(a.data),bp=reinterpret_cast<std::uintptr_t>(b.data);
    const auto maximum=std::numeric_limits<std::uintptr_t>::max();
    if (a.size>(maximum-ap)/sizeof(double) || b.size>(maximum-bp)/sizeof(double)
        || (ap<bp+b.size*sizeof(double) && bp<ap+a.size*sizeof(double)))
        throw std::invalid_argument("staggered input/output arrays overlap");
}
double optional(ArrayView<const double> a,std::size_t p,double fallback) { return a.size ? a[p] : fallback; }

struct Mesh {
    const GridView& g;
    std::size_t n;
    Coordinate counts,strides;
    std::array<ArrayView<const double>,3> widths;
    explicit Mesh(const GridView& grid):g(grid),n(product(product(g.nx,g.ny),g.nz)),
        counts{g.nx,g.ny,g.nz},strides{g.ny*g.nz,g.nz,1},widths{g.dx,g.dy,g.dz} {
        for (std::size_t axis=0;axis<3;++axis) coefficient(widths[axis],counts[axis],true);
    }
    std::size_t cell(const Coordinate& c) const { return (c[0]*g.ny+c[1])*g.nz+c[2]; }
    std::size_t face(std::size_t axis,const Coordinate& c) const {
        return (c[0]*(g.ny+(axis==1))+c[1])*(g.nz+(axis==2))+c[2];
    }
    std::size_t face_size(std::size_t axis) const { return product(n/counts[axis],counts[axis]+1); }
    Coordinate point(std::size_t p) const { return {p/(g.ny*g.nz),(p/g.nz)%g.ny,p%g.nz}; }
    std::size_t neighbor(const Coordinate& c,std::size_t f) const {
        const auto p=cell(c),axis=f/2;
        if (f%2==0) return c[axis]>0 ? p-strides[axis] : p;
        return c[axis]+1<counts[axis] ? p+strides[axis] : p;
    }
    std::size_t patch(std::size_t axis,const Coordinate& c) const {
        return axis==0 ? c[1]*g.nz+c[2] : (axis==1 ? c[0]*g.nz+c[2] : c[0]*g.ny+c[1]);
    }
    double volume(const Coordinate& c) const { return g.dx[c[0]]*g.dy[c[1]]*g.dz[c[2]]; }
    double area(std::size_t axis,const Coordinate& c) const {
        return axis==0 ? g.dy[c[1]]*g.dz[c[2]] : (axis==1 ? g.dx[c[0]]*g.dz[c[2]] : g.dx[c[0]]*g.dy[c[1]]);
    }
    double divergence(const Faces& faces,const Coordinate& c) const {
        Coordinate e=c,north=c,t=c; ++e[0]; ++north[1]; ++t[2];
        return (faces[0][face(0,e)]-faces[0][face(0,c)])
            +(faces[1][face(1,north)]-faces[1][face(1,c)])
            +(faces[2][face(2,t)]-faces[2][face(2,c)]);
    }
};

struct Laplacian {
    std::vector<int> rows,columns;
    Vector values;
    explicit Laplacian(const Mesh& mesh) {
        if (mesh.n>static_cast<std::size_t>((std::numeric_limits<int>::max()-1)/9))
            throw std::invalid_argument("MAC grid exceeds native sparse index capacity");
        rows.push_back(0);
        for (std::size_t p=0;p<mesh.n;++p) {
            const auto c=mesh.point(p); std::vector<int> adjacent;
            for (std::size_t f=0;f<6;++f) {
                const auto nb=mesh.neighbor(c,f);
                if (nb!=p) adjacent.push_back(static_cast<int>(nb));
            }
            const auto degree=adjacent.size(); adjacent.push_back(static_cast<int>(p));
            std::sort(adjacent.begin(),adjacent.end());
            for (int column:adjacent) {
                columns.push_back(column); values.push_back(column==static_cast<int>(p) ? static_cast<double>(degree) : -1.0);
            }
            rows.push_back(static_cast<int>(columns.size()));
        }
    }
    void multiply(const Vector& x,Vector& out) const {
        for (std::size_t p=0;p+1<rows.size();++p) {
            double sum=0;
            for (int j=rows[p];j<rows[p+1];++j) sum+=values[static_cast<std::size_t>(j)]*x[static_cast<std::size_t>(columns[static_cast<std::size_t>(j)])];
            out[p]=sum;
        }
    }
};

// PyAMG uses a pseudoinverse on the singular coarsest Neumann operator.
// AMGCL's default skyline LU cannot solve that operator. Only this coarse
// solver changes; the fine L is never pinned or regularized. Ruge-Stuben
// hierarchy details differ between libraries and are qualified numerically.
struct CoarsePseudoInverse {
    Eigen::MatrixXd inverse;
    template<class Matrix> explicit CoarsePseudoInverse(const Matrix& a) {
        const auto n=static_cast<Eigen::Index>(amgcl::backend::rows(a));
        Eigen::MatrixXd dense=Eigen::MatrixXd::Zero(n,n);
        for (Eigen::Index i=0;i<n;++i)
            for (auto it=amgcl::backend::row_begin(a,i);it;++it) dense(i,it.col())=it.value();
        Eigen::JacobiSVD<Eigen::MatrixXd> svd(dense,Eigen::ComputeFullU|Eigen::ComputeFullV);
        if (svd.info()!=Eigen::Success) throw std::runtime_error("MAC coarse pseudoinverse failed");
        svd.setThreshold(std::numeric_limits<double>::epsilon()*static_cast<double>(n));
        inverse=svd.solve(Eigen::MatrixXd::Identity(n,n));
    }
    static unsigned coarse_enough() { return 200; }
    template<class V1,class V2> void operator()(const V1& rhs,V2& x) const {
        for (Eigen::Index i=0;i<inverse.rows();++i) {
            double sum=0;
            for (Eigen::Index j=0;j<inverse.cols();++j) sum+=inverse(i,j)*rhs[static_cast<std::size_t>(j)];
            x[static_cast<std::size_t>(i)]=sum;
        }
    }
    std::size_t bytes() const { return static_cast<std::size_t>(inverse.size())*sizeof(double); }
};
struct NeumannBackend:amgcl::backend::builtin<double,int> {
    using direct_solver=CoarsePseudoInverse;
    static std::shared_ptr<direct_solver> create_solver(std::shared_ptr<matrix> a,const params&) {
        return std::make_shared<direct_solver>(*a);
    }
};
using AMG=amgcl::amg<NeumannBackend,amgcl::coarsening::ruge_stuben,amgcl::relaxation::gauss_seidel>;

Vector bordered(const Laplacian& lap,ArrayView<const double> rhs) {
    const auto n=rhs.size;
    std::vector<int> rows{0},columns,pc(n+1),pr(n+1); Vector values,x(n+1,0);
    for (std::size_t i=0;i<n;++i) {
        for (int j=lap.rows[i];j<lap.rows[i+1];++j) {
            columns.push_back(lap.columns[static_cast<std::size_t>(j)]); values.push_back(lap.values[static_cast<std::size_t>(j)]);
        }
        columns.push_back(static_cast<int>(n)); values.push_back(1); rows.push_back(static_cast<int>(columns.size())); x[i]=rhs[i];
    }
    for (std::size_t i=0;i<n;++i) { columns.push_back(static_cast<int>(i)); values.push_back(1); }
    rows.push_back(static_cast<int>(columns.size()));
    tpmshx_superlu_result result{};
    const int status=tpmshx_superlu_solve_csr(static_cast<int>(n+1),static_cast<int>(values.size()),
        rows.data(),columns.data(),values.data(),x.data(),pc.data(),pr.data(),&result);
    if (status!=TPMSHX_SUPERLU_OK || result.info!=0)
        throw std::runtime_error("MAC bordered SuperLU failed: "+std::to_string(status)+"/"+std::to_string(result.info)+" "+result.message);
    x.resize(n);
    const double mean=std::accumulate(x.begin(),x.end(),0.0)/static_cast<double>(n);
    for (double& value:x) {
        value-=mean;
        if (!std::isfinite(value)) throw std::domain_error("nonfinite MAC bordered potential");
    }
    return x;
}
double dot(const Vector& a,const Vector& b) { return std::inner_product(a.begin(),a.end(),b.begin(),0.0); }

Rows diffusion_rows(const Mesh& mesh,ArrayView<const double> k,bool solid) {
    Rows rows(mesh.n);
    for (std::size_t p=0;p<mesh.n;++p) {
        const auto c=mesh.point(p);
        for (std::size_t f=0;f<6;++f) {
            const auto axis=f/2,nb=mesh.neighbor(c,f),pos=c[axis];
            if (nb!=p) {
                const auto next=f%2==0 ? pos-1 : pos+1;
                rows[p][f]=detail::diffusion_conductance(k[p],k[nb],.5*mesh.widths[axis][pos],
                    .5*mesh.widths[axis][next])*mesh.area(axis,c);
            } else if (solid) rows[p][f]=k[p]*mesh.area(axis,c)/mesh.widths[axis][pos];
        }
    }
    return rows;
}
struct Side {
    const StaggeredTemperatureFluid& f;
    Rows diffusion;
    Faces velocity,capacity;
    Side(const Mesh& mesh,const StaggeredTemperatureFluid& fluid,Faces velocities):
        f(fluid),diffusion(diffusion_rows(mesh,f.conductivity,false)),velocity(std::move(velocities)) {
        const auto direction=static_cast<std::size_t>(f.boundary.direction);
        for (std::size_t axis=0;axis<3;++axis) {
            capacity[axis].resize(mesh.face_size(axis)); auto extent=mesh.counts; ++extent[axis];
            for (std::size_t i=0;i<extent[0];++i) for (std::size_t j=0;j<extent[1];++j)
                for (std::size_t k=0;k<extent[2];++k) {
                    const Coordinate c{i,j,k}; const auto pos=c[axis],count=mesh.counts[axis],p=mesh.face(axis,c);
                    auto lo=c,hi=c; lo[axis]=pos==0 ? 0 : pos-1; hi[axis]=std::min(pos,count-1);
                    const auto l=mesh.cell(lo),r=mesh.cell(hi);
                    const double ef=pos>0 && pos<count ? .5*(f.epsilon[l]+f.epsilon[r]) : f.epsilon[l];
                    const double cp=pos>0 && pos<count ? .5*(f.rho_cp[l]+f.rho_cp[r]) : f.rho_cp[l];
                    capacity[axis][p]=ef*cp*velocity[axis][p]*mesh.area(axis,c);
                    if (f.boundary.capacity_flux.size && axis==direction/2 && pos==(direction%2==0 ? 0 : count)) {
                        const auto patch=mesh.patch(axis,c);
                        if (opening(patch)>0) capacity[axis][p]=(direction%2==0 ? 1 : -1)*f.boundary.capacity_flux[patch];
                    }
                }
        }
    }
    double inlet(std::size_t p) const { return optional(f.boundary.profile,p,f.boundary.inlet_temperature); }
    double opening(std::size_t p) const { return optional(f.boundary.opening,p,1); }
};
double increment(double tm,double t,double tp,double dm,double dp,double offset) {
    const double a=(t-tm)/dm,b=(tp-t)/dp;
    if (a*b<=0) return 0;
    return (a<0 ? -std::min(std::abs(a),std::abs(b)) : std::min(std::abs(a),std::abs(b)))*offset;
}
double sou(const Mesh& mesh,const Side& side,ArrayView<const double> t,const Coordinate& c,bool conservative) {
    double result=0; const auto p=mesh.cell(c);
    for (std::size_t axis=0;axis<3;++axis) {
        auto high=c; ++high[axis];
        const double low=side.velocity[axis][mesh.face(axis,c)],hi=side.velocity[axis][mesh.face(axis,high)];
        const double center=.5*(hi+low),mag=side.f.epsilon[p]*side.f.rho_cp[p]*std::abs(center)*mesh.area(axis,c);
        double axis_result=0;
        for (std::size_t end=0;end<2;++end) {
            auto fc=c; fc[axis]+=end; const auto pos=fc[axis],count=mesh.counts[axis];
            const double flux=conservative ? side.capacity[axis][mesh.face(axis,fc)] : (center>=0 ? mag : -mag);
            if (!pos || pos==count) continue;
            const auto up=flux>=0 ? pos-1 : pos;
            if (!up || up+1==count) continue;
            auto uc=c; uc[axis]=up; const auto u=mesh.cell(uc),stride=mesh.strides[axis];
            const auto width=mesh.widths[axis];
            const double inc=increment(t[u-stride],t[u],t[u+stride],.5*(width[up-1]+width[up]),
                .5*(width[up]+width[up+1]),(flux>=0 ? .5 : -.5)*width[up]);
            axis_result+=(end==0 ? 1 : -1)*flux*inc;
        }
        result+=axis_result;
    }
    return result;
}
struct FluidRow { std::array<double,6> coefficients,neighbors; double diagonal,rhs,source; };
FluidRow fluid_row(const Mesh& mesh,const Side& side,ArrayView<const double> t,
    ArrayView<const double> solid,ArrayView<const double> reconstruction,const Coordinate& c,bool conservative) {
    const auto p=mesh.cell(c),dir=static_cast<std::size_t>(side.f.boundary.direction);
    FluidRow row{}; auto& a=row.coefficients; auto& neighbor=row.neighbors; std::array<double,6> cap{};
    for (std::size_t f=0;f<6;++f) {
        const auto axis=f/2,nb=mesh.neighbor(c,f); auto fc=c; fc[axis]+=f%2;
        cap[f]=side.capacity[axis][mesh.face(axis,fc)];
        a[f]=side.diffusion[p][f]+std::max(f%2 ? -cap[f] : cap[f],0.0); neighbor[f]=t[nb];
        if (nb==p && f==dir) {
            const auto patch=mesh.patch(axis,c); const double opening=side.opening(patch);
            if (opening>0) {
                a[f]+=2.0*side.f.conductivity[p]*mesh.area(axis,c)*opening/mesh.widths[axis][c[axis]];
                neighbor[f]=side.inlet(patch);
            }
        }
    }
    const double volume=mesh.volume(c),hv=side.f.hv[p]*volume;
    const double net=conservative ? (cap[1]-cap[0])+(cap[3]-cap[2])+(cap[5]-cap[4]) : 0;
    row.diagonal=a[1]+a[0]+a[3]+a[2]+a[5]+a[4]+net+hv;
    row.source=sou(mesh,side,reconstruction,c,conservative)+optional(side.f.source,p,0)*volume;
    row.rhs=a[1]*neighbor[1]+a[0]*neighbor[0]+a[3]*neighbor[3]+a[2]*neighbor[2]
        +a[5]*neighbor[5]+a[4]*neighbor[4]+hv*solid[p]+row.source;
    return row;
}
void update(ArrayView<double> t,std::size_t p,double value,double alpha,double& change) {
    const double updated=t[p]+alpha*(value-t[p]);
    if (!std::isfinite(updated)) throw std::domain_error("nonfinite staggered temperature row");
    change=std::max(change,std::abs(updated-t[p])); t[p]=updated;
}
double sweeps(const Mesh& mesh,const Side& a,const Side& b,const Rows& ds,
    ArrayView<const double> source_s,TemperatureStateView t,const TemperatureControl& control,
    bool conservative,bool rb,bool frozen,std::size_t count) {
    double change=0;
    for (std::size_t it=0;it<count;++it) {
        Vector snapshot_a,snapshot_b;
        if (rb) { snapshot_a.assign(t.a.data,t.a.data+t.a.size); snapshot_b.assign(t.b.data,t.b.data+t.b.size); }
        const auto rec_a=rb ? view(snapshot_a) : view(t.a),rec_b=rb ? view(snapshot_b) : view(t.b);
        change=0;
        for (std::size_t color=0;color<(rb ? 2U : 1U);++color)
            for (std::size_t ii=0;ii<mesh.g.nx;++ii) for (std::size_t jj=0;jj<mesh.g.ny;++jj)
                for (std::size_t kk=0;kk<mesh.g.nz;++kk) {
                    const auto i=!rb && a.f.boundary.direction==1 ? mesh.g.nx-1-ii : ii;
                    const auto j=!rb && b.f.boundary.direction==3 ? mesh.g.ny-1-jj : jj;
                    const auto k=!rb && a.f.boundary.direction==5 ? mesh.g.nz-1-kk : kk;
                    if (rb && (i+j+k)%2!=color) continue;
                    const Coordinate c{i,j,k}; const auto p=mesh.cell(c);
                    const auto row_a=fluid_row(mesh,a,view(t.a),view(t.solid),rec_a,c,conservative);
                    update(t.a,p,row_a.rhs/std::max(row_a.diagonal,1e-30),control.alpha_a,change);
                    const auto& d=ds[p]; const double vol=mesh.volume(c),ha=a.f.hv[p]*vol,hb=b.f.hv[p]*vol;
                    const double diagonal=d[1]+d[0]+d[3]+d[2]+d[5]+d[4]+ha+hb;
                    const double rhs=d[1]*t.solid[mesh.neighbor(c,1)]+d[0]*t.solid[mesh.neighbor(c,0)]
                        +d[3]*t.solid[mesh.neighbor(c,3)]+d[2]*t.solid[mesh.neighbor(c,2)]
                        +d[5]*t.solid[mesh.neighbor(c,5)]+d[4]*t.solid[mesh.neighbor(c,4)]
                        +ha*t.a[p]+hb*t.b[p]+optional(source_s,p,0)*vol;
                    if (!std::isfinite(diagonal) || diagonal<=0) throw std::domain_error("invalid staggered solid row");
                    update(t.solid,p,rhs/diagonal,control.alpha_solid,change);
                    if (!frozen) {
                        const auto row_b=fluid_row(mesh,b,view(t.b),view(t.solid),rec_b,c,conservative);
                        update(t.b,p,row_b.rhs/std::max(row_b.diagonal,1e-30),control.alpha_b,change);
                    }
                }
        if (change<1e-10) break;
    }
    return change;
}
StaggeredFluidResidual residual(const Mesh& mesh,const Side& side,ArrayView<const double> t,ArrayView<const double> solid) {
    StaggeredFluidResidual result{}; result.available=true; result.cells.resize(mesh.n);
    for (std::size_t p=0;p<mesh.n;++p) {
        const auto c=mesh.point(p); const auto row=fluid_row(mesh,side,t,solid,t,c,true);
        const auto& a=row.coefficients; const auto& v=row.neighbors;
        // Independent final unrelaxed equation, preserving Python's subtract order.
        const double r=row.diagonal*t[p]-a[1]*v[1]-a[0]*v[0]-a[3]*v[3]-a[2]*v[2]-a[5]*v[5]-a[4]*v[4]
            -side.f.hv[p]*mesh.volume(c)*solid[p]-row.source;
        if (!std::isfinite(r)) throw std::domain_error("nonfinite staggered residual");
        result.cells[p]=r; result.sum+=r; result.maximum=std::max(result.maximum,std::abs(r));
        result.exchange+=side.f.hv[p]*mesh.volume(c)*(solid[p]-t[p]);
    }
    const double scale=std::max(std::abs(result.exchange),1.0);
    result.global_ratio=std::abs(result.sum)/scale; result.cell_ratio=result.maximum*static_cast<double>(mesh.n)/scale;
    return result;
}
}  // namespace

struct StaggeredTemperatureDriver::Impl {
    Coordinate shape{};
    std::unique_ptr<Laplacian> lap;
    std::unique_ptr<AMG> amg;
    void prepare(const Mesh& mesh) {
        if (amg && shape==mesh.counts) return;
        auto candidate=std::make_unique<Laplacian>(mesh);
        AMG::params params; params.coarse_enough=200; params.relax.serial=true;
        params.npre=1; params.npost=1; params.ncycle=1;
        auto hierarchy=std::make_unique<AMG>(std::tie(mesh.n,candidate->rows,candidate->columns,candidate->values),params);
        shape=mesh.counts; lap=std::move(candidate); amg=std::move(hierarchy);
    }
};
StaggeredTemperatureDriver::StaggeredTemperatureDriver():impl_(std::make_unique<Impl>()) {}
StaggeredTemperatureDriver::~StaggeredTemperatureDriver()=default;

Vector solve_mac_neumann_bordered(const GridView& grid,ArrayView<const double> divergence) {
    const Mesh mesh(grid); check(divergence,mesh.n); return bordered(Laplacian(mesh),divergence);
}

MacProjectionResult StaggeredTemperatureDriver::project_capacity_faces(const GridView& grid,
    ArrayView<const double> epsilon,ArrayView<const double> rho_cp,
    const std::array<ArrayView<const double>,3>& velocity) {
    const Mesh mesh(grid); coefficient(epsilon,mesh.n); coefficient(rho_cp,mesh.n,true);
    MacProjectionResult result; Faces capacity,flux;
    for (std::size_t axis=0;axis<3;++axis) {
        check(velocity[axis],mesh.face_size(axis));
        result.velocity[axis].assign(velocity[axis].data,velocity[axis].data+velocity[axis].size);
        capacity[axis].resize(velocity[axis].size); flux[axis].resize(velocity[axis].size);
        auto extent=mesh.counts; ++extent[axis];
        for (std::size_t i=0;i<extent[0];++i) for (std::size_t j=0;j<extent[1];++j)
            for (std::size_t k=0;k<extent[2];++k) {
                const Coordinate c{i,j,k}; const auto pos=c[axis],count=mesh.counts[axis],p=mesh.face(axis,c);
                auto lo=c,hi=c; lo[axis]=pos==0 ? 0 : pos-1; hi[axis]=std::min(pos,count-1);
                const auto l=mesh.cell(lo),r=mesh.cell(hi);
                const double coef=pos>0 && pos<count ? .5*(epsilon[l]*rho_cp[l]+epsilon[r]*rho_cp[r]) : epsilon[l]*rho_cp[l];
                capacity[axis][p]=coef*mesh.area(axis,c); flux[axis][p]=coef*velocity[axis][p]*mesh.area(axis,c);
                if (!std::isfinite(flux[axis][p])) throw std::domain_error("nonfinite MAC input flux");
            }
    }
    Vector rhs(mesh.n); double scale=1e-300,maximum=0;
    for (const auto& axis:flux) for (double f:axis) scale=std::max(scale,std::abs(f));
    for (std::size_t p=0;p<mesh.n;++p) { rhs[p]=mesh.divergence(flux,mesh.point(p)); maximum=std::max(maximum,std::abs(rhs[p])); }
    result.potential.assign(mesh.n,0);
    result.info.rhs_mean=std::accumulate(rhs.begin(),rhs.end(),0.0)/static_cast<double>(mesh.n);
    if (maximum<=1e-9*scale) { result.info.skipped=true; return result; }
    impl_->prepare(mesh);
    Vector b=rhs; for (double& v:b) v-=result.info.rhs_mean;
    Vector r=b,z(mesh.n),p(mesh.n),q(mesh.n); double old_rho=0;
    const double norm=std::sqrt(dot(b,b)),tolerance=1e-10*norm;
    bool converged=norm==0;
    // Same CG relative tolerance and 500-step policy as SciPy. No AMGCL CG
    // small-RHS shortcut: the original absolute tolerance is exactly zero.
    for (std::size_t iteration=0;iteration<500 && !converged;++iteration) {
        if (std::sqrt(dot(r,r))<tolerance) { converged=true; break; }
        impl_->amg->apply(r,z); const double rho=dot(r,z);
        if (iteration==0) p=z;
        else { const double beta=rho/old_rho; for (std::size_t j=0;j<mesh.n;++j) p[j]=z[j]+beta*p[j]; }
        impl_->lap->multiply(p,q); const double alpha=rho/dot(p,q);
        if (!std::isfinite(alpha)) break;
        for (std::size_t j=0;j<mesh.n;++j) { result.potential[j]+=alpha*p[j]; r[j]-=alpha*q[j]; }
        old_rho=rho; result.info.cg_iterations=iteration+1;
    }
    // SciPy reports info=maxiter if the 500th update crosses the tolerance;
    // its convergence check happens at the next loop head, never after it.
    if (!converged) {
        result.info.used_bordered_lu=true; result.potential=bordered(*impl_->lap,view(rhs));
    }
    const double mean=std::accumulate(result.potential.begin(),result.potential.end(),0.0)/static_cast<double>(mesh.n);
    for (double& v:result.potential) v-=mean;
    impl_->lap->multiply(result.potential,q);
    for (std::size_t j=0;j<mesh.n;++j) q[j]-=b[j];
    result.info.residual_relative=norm>0 ? std::sqrt(dot(q,q))/norm : std::sqrt(dot(q,q));
    for (std::size_t axis=0;axis<3;++axis) {
        auto extent=mesh.counts;
        for (std::size_t i=0;i<extent[0];++i) for (std::size_t j=0;j<extent[1];++j)
            for (std::size_t k=0;k<extent[2];++k) {
                const Coordinate c{i,j,k}; if (c[axis]==0) continue;
                const auto pcell=mesh.cell(c),f=mesh.face(axis,c);
                result.velocity[axis][f]+=(result.potential[pcell]-result.potential[pcell-mesh.strides[axis]])/(capacity[axis][f]+1e-30);
                if (!std::isfinite(result.velocity[axis][f])) throw std::domain_error("nonfinite MAC projected velocity");
            }
    }
    return result;
}

StaggeredTemperatureResult StaggeredTemperatureDriver::solve(const GridView& grid,
    const StaggeredTemperatureFluid& a,const StaggeredTemperatureFluid& b,ArrayView<const double> ks,
    TemperatureStateView t,const TemperatureControl& control,bool conservative,bool rb,
    ArrayView<const double> prescribed_b,ArrayView<const double> source_s) {
    const Mesh mesh(grid); coefficient(ks,mesh.n);
    if (grid.nz<=1) throw std::invalid_argument("staggered 3D requires nz>1");
    if (!control.chunk_iterations || !std::isfinite(control.q_relative_tolerance) || control.q_relative_tolerance<=0)
        throw std::invalid_argument("invalid staggered chunk or tolerance");
    if (!control.second_order_b) throw std::invalid_argument("staggered 3D always uses second order B");
    for (double alpha:{control.alpha_a,control.alpha_solid,control.alpha_b})
        if (!std::isfinite(alpha) || alpha<=0 || alpha>1) throw std::invalid_argument("invalid staggered relaxation");
    const std::array<ArrayView<double>,3> output{t.a,t.b,t.solid};
    for (auto out:output) check(out,mesh.n,control.warm_start);
    for (auto input:{prescribed_b,source_s}) if (input.size) check(input,mesh.n);
    for (std::size_t i=0;i<3;++i) {
        for (std::size_t j=0;j<i;++j) disjoint(view(output[i]),view(output[j]));
        for (auto input:{grid.dx,grid.dy,grid.dz,ks,prescribed_b,source_s}) disjoint(view(output[i]),input);
    }
    for (const auto* side:{&a,&b}) {
        coefficient(side->conductivity,mesh.n); coefficient(side->hv,mesh.n);
        coefficient(side->epsilon,mesh.n); coefficient(side->rho_cp,mesh.n,true);
        for (std::size_t axis=0;axis<3;++axis) check(side->velocity[axis],mesh.face_size(axis));
        if (side->source.size) check(side->source,mesh.n);
        const auto& bc=side->boundary;
        if (bc.direction<0 || bc.direction>5 || !std::isfinite(bc.inlet_temperature))
            throw std::invalid_argument("invalid staggered inlet direction or temperature");
        const auto patch_size=mesh.n/mesh.counts[static_cast<std::size_t>(bc.direction)/2];
        for (auto input:{bc.profile,bc.opening,bc.capacity_flux}) if (input.size) check(input,patch_size);
        for (std::size_t p=0;p<bc.opening.size;++p)
            if (bc.opening[p]<0 || bc.opening[p]>1) throw std::invalid_argument("staggered opening outside [0,1]");
        for (auto out:output) {
            for (auto input:{side->conductivity,side->hv,side->epsilon,side->rho_cp,side->source,bc.profile,bc.opening,bc.capacity_flux})
                disjoint(view(out),input);
            for (auto velocity:side->velocity) disjoint(view(out),velocity);
        }
    }
    if (!control.warm_start) for (std::size_t p=0;p<mesh.n;++p) {
        t.a[p]=a.boundary.inlet_temperature; t.b[p]=b.boundary.inlet_temperature;
        t.solid[p]=.5*(a.boundary.inlet_temperature+b.boundary.inlet_temperature);
    }
    if (prescribed_b.size) std::copy(prescribed_b.data,prescribed_b.data+mesh.n,t.b.data);
    StaggeredTemperatureResult result{};
    result.iteration={TemperatureStop::budget_exhausted,0,0,std::numeric_limits<double>::quiet_NaN()};
    std::array<Faces,2> velocities;
    for (std::size_t s=0;s<2;++s) {
        const auto& f=s==0 ? a : b;
        if (conservative) {
            auto projection=project_capacity_faces(grid,f.epsilon,f.rho_cp,f.velocity);
            result.projection[s]=projection.info; velocities[s]=std::move(projection.velocity);
        } else for (std::size_t axis=0;axis<3;++axis)
            velocities[s][axis].assign(f.velocity[axis].data,f.velocity[axis].data+f.velocity[axis].size);
    }
    const Side side_a(mesh,a,std::move(velocities[0])),side_b(mesh,b,std::move(velocities[1]));
    const auto solid_diffusion=diffusion_rows(mesh,ks,true);
    std::array<Vector,3> previous;
    for (std::size_t s=0;s<3;++s) previous[s].assign(output[s].data,output[s].data+mesh.n);
    double old_q=std::numeric_limits<double>::quiet_NaN();
    const auto cancel=[&]() { return control.cancel && control.cancel(control.context); };
    while (result.iteration.iterations<control.max_iterations) {
        if (cancel()) { result.iteration.stop=TemperatureStop::cancelled; return result; }
        const auto count=std::min(control.chunk_iterations,control.max_iterations-result.iteration.iterations);
        result.iteration.residual=sweeps(mesh,side_a,side_b,solid_diffusion,source_s,t,control,conservative,rb,prescribed_b.size>0,count);
        result.iteration.iterations+=count;
        if (control.progress) control.progress(control.context,result.iteration.iterations,control.max_iterations);
        if (cancel()) { result.iteration.stop=TemperatureStop::cancelled; result.iteration.q_b=std::numeric_limits<double>::quiet_NaN(); return result; }
        double q=0,change=0;
        for (std::size_t p=0;p<mesh.n;++p) {
            q+=b.hv[p]*(t.solid[p]-t.b[p])*mesh.volume(mesh.point(p));
            for (std::size_t s=0;s<3;++s) change=std::max(change,std::abs(output[s][p]-previous[s][p]));
        }
        if (!std::isfinite(q)) throw std::domain_error("nonfinite staggered duty");
        result.iteration.q_b=q;
        if (std::isfinite(old_q) && std::abs(q-old_q)/std::max({std::abs(q),std::abs(old_q),1.0})<control.q_relative_tolerance && change<.01) {
            result.iteration.stop=TemperatureStop::converged; break;
        }
        old_q=q; for (std::size_t s=0;s<3;++s) std::copy(output[s].data,output[s].data+mesh.n,previous[s].begin());
    }
    if (conservative) {
        result.residual[0]=residual(mesh,side_a,view(t.a),view(t.solid));
        if (!prescribed_b.size) result.residual[1]=residual(mesh,side_b,view(t.b),view(t.solid));
    }
    return result;
}
}  // namespace tpmshx
